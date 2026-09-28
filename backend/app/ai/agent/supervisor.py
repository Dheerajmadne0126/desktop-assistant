import json
import re
import time
from dataclasses import dataclass

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.agent.fastpath import fast_path, run_fast_match
from app.ai.agent.planner import execute_agentic_goal
from app.ai.language import detect_language
from app.ai.llm.provider import get_fast_llm, get_llm
from app.ai.personality.prompts import (
    build_system_prompt,
)
from app.ai.text_utils import clean_llm_text
from app.conversation.clarifier import clarification_manager
from app.conversation.manager import conversation_manager
from app.core.logging import get_logger
from app.memory.service import memory_service
from app.tools.base import ToolResult
from app.tools.registry import registry

logger = get_logger("supervisor")

_GREETING_RE = re.compile(
    r"^\s*(?:hey|hi|hello|yo|he|hoy|हे|हेय)?\s*"
    r"(?:jarvis|जर्विस|जार्विस)\s*[!,.?]*\s*$",
    re.IGNORECASE,
)
_GREETINGS = {
    "English": [
        "Yes sir? I'm listening.",
        "Sir. Go ahead.",
        "Right here, sir — what do you need?",
    ],
    "Marathi": [
        "हो सर, ऐकतोय.",
        "सर, बोला — काय करू?",
        "मी जर्विस सर, सांगा.",
    ],
    "Hindi": [
        "जी सर, सुन रहा हूँ.",
        "सर, बताइए — क्या करना है?",
        "हाँ सर, मैं तैयार हूँ.",
    ],
}

_LANG_SWITCH_RE = re.compile(
    r"\b(?:talk|speak|reply|answer|respond|chat|बोल|बोलू|बोला|बताओ|बताइए|"
    r"उत्तर|जवाब|सुन|पाहिजे|हवं|हवी|हवा|चाहिए)\b[^.!?]{0,60}?"
    r"(english|hindi|marathi|इंग्लिश|इंग्रजी|हिंदी|मराठी)"
    r"|\b(?:english|hindi|marathi|इंग्लिश|इंग्रजी|हिंदी|मराठी)(?:मध्ये(?:च)?|में)?"
    r"[^.!?]{0,40}?(?:उत्तर|जवाब|reply|answer|respond|बोल|बोलू|बात)",
    re.IGNORECASE,
)

_LANG_WORD_MAP = [
    ("english", "English"),
    ("इंग्लिश", "English"),
    ("इंग्रजी", "English"),
    ("hindi", "Hindi"),
    ("हिंदी", "Hindi"),
    ("marathi", "Marathi"),
    ("मराठी", "Marathi"),
]

_COMMAND_INTENT_RE = re.compile(
    r"^(open|close|play|stop|pause|set a timer|set an alarm|what time|restart|shutdown|lock|take a screenshot|search for|volume)\b",
    re.IGNORECASE
)

# Short conversational questions must NOT be treated as ambiguous input:
# "काय करतोय?", "क्या कर रहे हो?", "what's up?" etc. are valid questions
# that should reach the LLM, not trigger the clarify fast-path.
_QUESTION_RE = re.compile(
    r"\b(?:what|which|who|whom|whose|where|when|why|how|doing|happening|going on|whats|what's)\b"
    r"|काय|कोण|कुणी|कुणाला|कुठे|कधी|कसे|कसा|कशी|किती|काया"
    r"|क्या|कौन|कहाँ|कब|कैसे|कैसा|कितना|कितनी|क्यों|क्यूँ"
    r"|\bkya\b|\bkay\b|\bkasa\b|\bkase\b|\bkuthe\b|\bkadhi\b|\bkon\b|\bkiti\b|\bkyu\b|\bkaise\b|\bkahan\b|\bkab\b|\bkaun\b",
    re.IGNORECASE,
)


def _voice_brevity_hint(source: str) -> str:
    """Stronger brevity for voice turns: long essay replies get read aloud
    for minutes, which is exactly what the user is complaining about."""
    if source != "voice":
        return ""
    return (
        "\nThis reply will be SPOKEN ALOUD: keep it to 1-3 short spoken "
        "sentences. No essays, no numbered lists, no markdown."
    )


def _detect_switch_target(text: str) -> str | None:
    lowered = text.lower()
    for word, target in _LANG_WORD_MAP:
        if word in lowered:
            return target
    return None

_SWITCH_ACKS = {
    "English": ["Sure sir — English from now on.", "Okay sir, switching to English."],
    "Marathi": ["नक्की सर, आता आपण मराठीत बोलूया.", "ठीक आहे सर, मराठीतच उत्तर देतो."],
    "Hindi": ["जी सर, अब हिंदी में बात करते हैं.", "ठीक है सर, हिंदी में जवाब दूँगा."],
}


@dataclass
class SupervisorResult:
    reply: str
    language: str
    mode: str = "chat"
    tool_used: str | None = None


_STRUCTURED_MARKERS = (
    "<tool_call>", "<tool_code>", "</tool", '"tool_use"', '"tool_name"',
    '"mode":',
)


def _looks_structured(reply: str) -> bool:
    stripped = reply.lstrip()
    if stripped.startswith(("{", "[")):
        return True
    lowered = reply.lower()
    return any(marker in lowered for marker in _STRUCTURED_MARKERS)


def _strip_leading_bullets(text: str) -> str:
    lines = [ln.lstrip("â€¢-â€“* ").strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines).strip()


class Supervisor:
    _specs: list[dict] | None = None

    def __init__(self) -> None:
        self._lang_streak = 0
        self._streak_language = "English"
        # Language of the most recent reply, read by the voice pipeline so TTS
        # picks the right voice (Marathi/Hindi/English) for streamed turns.
        self._last_language = "English"

    async def process_user_input(self, text: str, source: str = "voice", request_id: str = "-") -> SupervisorResult:
        started = time.perf_counter()
        text = (text or "").strip()
        if not text:
            return SupervisorResult(reply=self._natural_fallback("English", "unheard"), language="English", mode="error")

        conversation = await conversation_manager.get_or_create_active()
        conv_id = conversation.id
        
        t0 = time.perf_counter()
        language = detect_language(text)
        self._last_language = language
        await self._track_language_persistence(language)
        t1 = time.perf_counter()
        
        logger.info("[%s] [TURN] src=%s lang=%s text=%s", request_id, source, language, text[:60])

        await conversation_manager.add_message(conv_id, "user", text, language=language)
        history = (await conversation_manager.get_recent_messages(conv_id, limit=9))[:-1]
        t2 = time.perf_counter()
        
        try:
            # We will pass t2 to route to trace memory timing
            result = await self._route(text, conv_id, language, history, source, t2)
        except Exception as exc:
            logger.error("Supervisor error: %s", exc, exc_info=True)
            result = SupervisorResult(
                reply="Something went wrong on my side. Please try again.",
                language=language,
                mode="error",
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        await conversation_manager.add_message(
            conv_id,
            "assistant",
            result.reply,
            language=result.language,
            latency_ms=latency_ms,
        )
        logger.info(
            "Turn complete mode=%s lang=%s latency=%dms",
            result.mode,
            result.language,
            latency_ms,
        )
        return result

    async def _route(self, text, conv_id, language, history, source, t2=None) -> SupervisorResult:
        pending_clar = clarification_manager.get(conv_id)
        if pending_clar is not None:
            escape = fast_path.match(text)
            done = await clarification_manager.feed_user_reply(pending_clar, text)
            if done == "filled":
                return await self._execute_tool_and_phrase(
                    pending_clar.tool_name,
                    dict(pending_clar.collected),
                    conv_id,
                    language,
                )
            if (
                done == "no_progress"
                and pending_clar.rounds <= 1
            ) or (escape is not None and done != "filled"):
                clarification_manager.clear(conv_id)
            elif done == "asked_more" or done == "no_progress":
                question = clarification_manager.question_for(pending_clar)
                return SupervisorResult(reply=question, language=language, mode="clarify")

        from app.services.confirmation import confirmation_service

        confirmation_result = await confirmation_service.handle_user_response(text, conv_id)
        if confirmation_result is not None:
            phrased = self._template_outcome(confirmation_result)
            return SupervisorResult(reply=phrased, language=language, mode="confirmation")

        if _GREETING_RE.match(text):
            import random

            pool = _GREETINGS.get(language, _GREETINGS["English"])
            greeting = random.choice(pool)
            logger.info("Greeting fast-path (no LLM): %s", greeting[:40])
            return SupervisorResult(reply=greeting, language=language, mode="greeting")

        switch_match = _LANG_SWITCH_RE.search(text)
        if switch_match:
            lowered = text.lower()
            # Prevent false positives like "why are you speaking in hindi"
            if not any(w in lowered for w in ["why", "का ", "का?", "क्यों", "kyu"]):
                target = _detect_switch_target(text)
                if target:
                    await memory_service.set_preference("reply_language", target, source="user")
                    self._lang_streak = 0
                    self._streak_language = target if target != "English" else "English"
                    self._last_language = target
                    import random
    
                    ack = random.choice(_SWITCH_ACKS.get(target, _SWITCH_ACKS["English"]))
                    logger.info("Language switched via explicit request -> %s", target)
                    return SupervisorResult(reply=ack, language=target, mode="language_switch")

        fast_match = fast_path.match(text)
        if fast_match is not None:
            outcome = await run_fast_match(fast_match, conv_id)
            reply = (
                outcome.message
                if fast_match.tool_name == "__set_language__"
                else self._template_outcome(outcome)
            )
            return SupervisorResult(
                reply=reply,
                language=language,
                mode="fastpath",
                tool_used=None if fast_match.tool_name == "__set_language__" else fast_match.tool_name,
            )

        # Handle short/ambiguous inputs that might cause hallucination
        # Check for very short inputs that aren't known commands
        words = text.strip().split()
        is_short_ambiguous = (
            len(words) <= 2 
            and len(text.strip()) <= 10
            and not _COMMAND_INTENT_RE.search(text)
            and not _GREETING_RE.match(text)
            and not _LANG_SWITCH_RE.search(text)
            and not _QUESTION_RE.search(text)
        )
        
        if is_short_ambiguous:
            # For very short ambiguous inputs, ask for clarification instead of hallucinating
            clarification = {
                "English": "I didn't catch that clearly, sir. Could you please elaborate?",
                "Marathi": "माफ करा सर, ते नीट समजलं नाही. थोडं स्पष्ट सांगाल का?",
                "Hindi": "माफ़ कीजिए सर, समझ नहीं आया। थोड़ा विस्तार से बताइए।",
            }
            lang_key = language if language in ("Marathi", "Hindi") else "English"
            return SupervisorResult(
                reply=clarification[lang_key],
                language=language,
                mode="clarify",
            )

        if _COMMAND_INTENT_RE.search(text):
            logger.debug("Bypassing memory retrieval for clear command intent.")
            memory_block = ""
        else:
            memory_block = await memory_service.memory_block_for_context(text)
            
        language_pref = await memory_service.language_preference()
        
        import time
        if t2:
            t3 = time.perf_counter()
            logger.info("[PERF] Pre-LLM setup took %dms (Memory: %dms)", int((t3 - t2)*1000), int((t3 - t2)*1000))

        response, tool_calls = await self._decide_and_answer(
            text, conv_id, language, history, memory_block, language_pref, source=source
        )

        if len(tool_calls) >= 2:
            # Try agentic planner first for complex multi-step tasks
            try:
                plan_result = await execute_agentic_goal(text, conv_id, history)
                if plan_result and plan_result.get("reply"):
                    return SupervisorResult(
                        reply=plan_result["reply"],
                        language=language,
                        mode="plan",
                    )
                # Planner returned no actionable plan -> fall back to conversational response
                logger.info("Planner returned no plan; falling back to chat")
                reply = await self._plain_chat(text, conv_id, language, source=source)
                return SupervisorResult(reply=reply, language=language, mode="chat")
            except Exception as exc:
                logger.warning("Planner failed, falling back to chat: %s", exc)
                reply = await self._plain_chat(text, conv_id, language, source=source)
                return SupervisorResult(reply=reply, language=language, mode="chat")

        if len(tool_calls) == 1:
            call = tool_calls[0]
            return await self._handle_single_tool_call(call, text, conv_id, language)

        reply = clean_llm_text(response.get("content") or "")
        if not reply or _looks_structured(reply):
            reply = await self._plain_chat(text, conv_id, language)
        if not reply or _looks_structured(reply):
            reply = self._natural_fallback(language)
        return SupervisorResult(reply=reply, language=language, mode="chat")

    def _natural_fallback(self, language: str, kind: str = "unheard") -> str:
        """Contextual etiquette when the system genuinely can't process — never dead air."""
        import random

        listening = {
            "English": ["Yes sir, I'm listening.", "Go ahead, sir.", "Sir? I'm all ears."],
            "Marathi": ["हो सर, ऐकतोय.", "हो सर, सांगा.", "सर, बोला — ऐकतोय."],
            "Hindi": ["हाँ सर, सुन रहा हूँ.", "जी सर, बताइए.", "सर, मैं हूँ — बोलिए."],
        }
        unheard = {
            "English": [
                "Sorry sir, that didn't come through clearly — say it again?",
                "Hmm, I missed that one sir. Once more?",
            ],
            "Marathi": [
                "माफ करा सर, ते नीट समजलं नाही. पुन्हा सांगाल का?",
                "सर, ते पक्कं कळलं नाही — थोडं स्पष्ट सांगा.",
            ],
            "Hindi": [
                "माफ़ कीजिए सर, समझ नहीं आया। दोबारा बताइए?",
                "सर, वो ठीक से पकड़ में नहीं आया — फिर बोलिए।",
            ],
        }
        pool_map = listening if kind == "listening" else unheard
        lang = language if language in ("Marathi", "Hindi") else "English"
        return random.choice(pool_map.get(lang, pool_map["English"]))

    async def _track_language_persistence(self, language: str) -> None:
        """Symmetric drift tracking: 2 consecutive non-English turns adopt that
        language; 2 consecutive English turns release a stale non-auto lock."""
        try:
            if language in ("Marathi", "Hindi"):
                if self._streak_language == language:
                    self._lang_streak += 1
                else:
                    self._streak_language = language
                    self._lang_streak = 1
                if self._lang_streak >= 2:
                    current = await memory_service.language_preference()
                    if current != language:
                        await memory_service.set_preference("reply_language", language, source="auto")
                        logger.info("Auto-persisted conversation language: %s", language)
            elif language == "English":
                if self._streak_language == "English":
                    self._lang_streak += 1
                else:
                    self._streak_language = "English"
                    self._lang_streak = 1
                if self._lang_streak >= 2:
                    current = await memory_service.language_preference()
                    if current not in (None, "auto", "English"):
                        await memory_service.set_preference(
                            "reply_language", "auto", source="auto"
                        )
                        logger.info(
                            "Released stale '%s' preference after consecutive English turns.",
                            current,
                        )
        except Exception as exc:
            logger.debug("Language persistence skipped: %s", exc)

    async def _decide_and_answer(
        self, text, conv_id, language, history, memory_block, language_pref="auto", source="api"
    ):
        """ONE LLM call: the model chats OR emits tool_calls. Replaces classify+answer."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        system_prompt = build_system_prompt(
            memory_block=memory_block,
            mode_hint=(
                "Decide in this single turn: either reply conversationally, or call exactly "
                "one tool when an action/lookup is clearly needed. Emit multiple tool calls "
                "ONLY for a complex multi-step request. Never invent results. "
                "If the user is merely greeting or summoning you, reply conversationally — "
                "never call web_search or any tool for greetings.\n"
                "Multi-action sentences ('open notepad and type 100') -> emit ONE tool call "
                "per action, in order: open_application first, then keyboard_type with the "
                "spoken text. Only use write_file when the user explicitly says file/save/"
                "document; typing into an app is keyboard_type, never a file."
            )
            + _voice_brevity_hint(source),
            language_preference=language_pref,
        )
        messages = [SystemMessage(content=system_prompt)]
        for turn in history[-8:]:
            if turn["role"] == "user":
                messages.append(HumanMessage(content=turn["content"]))
            elif turn["role"] == "assistant":
                messages.append(AIMessage(content=turn["content"]))
        messages.append(HumanMessage(content=text))

        llm = get_llm(temperature=0)
        specs = self._tool_specs_cache()
        import time
        llm_t0 = time.perf_counter()
        try:
            if specs:
                bound = llm.bind_tools(specs, max_tokens=600)
                response = await bound.ainvoke(messages)
            else:
                response = await llm.ainvoke(messages)
            logger.info("LLM Inference completed in %dms", int((time.perf_counter() - llm_t0) * 1000))
        except Exception as exc:
            logger.error("Router LLM failed: %s", exc)
            raise

        raw_calls = getattr(response, "tool_calls", None) or []
        tool_calls = [
            {"name": tc.get("name"), "args": tc.get("args") or {}}
            for tc in raw_calls
            if isinstance(tc, dict) and tc.get("name")
        ]
        content = response.content if isinstance(response.content, str) else ""
        return {"content": content}, tool_calls

    @classmethod
    def _tool_specs_cache(cls):
        if cls._specs is None:
            cls._specs = registry.openai_tool_specs()
        return cls._specs

    async def _handle_single_tool_call(self, call, text, conv_id, language) -> SupervisorResult:
        tool_name = call.get("name")
        tool = registry.get(tool_name or "")
        if tool is None or tool.permission.value == "BLOCKED":
            reply = await self._plain_chat(text, conv_id, language)
            return SupervisorResult(reply=reply, language=language, mode="chat")

        args = call.get("args") or {}
        missing_required = [
            name for name in tool.parameters_schema.get("required", [])
            if not args.get(name)
        ]
        if missing_required:
            from app.conversation.clarifier import clarification_manager

            collected = {k: v for k, v in args.items() if v}
            clarification_manager.start(conv_id, tool_name, missing_required, collected)
            question = clarification_manager.question_for(
                clarification_manager.get(conv_id)
            )
            return SupervisorResult(reply=question, language=language, mode="clarify")

        return await self._execute_tool_and_phrase(tool_name, args, conv_id, language)

    async def _execute_tool_and_phrase(self, tool_name, args, conv_id, language):
        result = await registry.execute(
            tool_name, args, triggered_by="agent", conversation_id=conv_id
        )
        if "CONFIRMATION_REQUIRED:" in result.message:
            code = result.message.split(":")[1]
            desc = result.message.split(":", 2)[2]
            return SupervisorResult(
                reply=f"I need your approval first. I want to {desc}. Say yes, or give me code {code}.",
                language=language,
                mode="confirm",
                tool_used=tool_name,
            )

        reply = self._template_outcome(result)
        return SupervisorResult(reply=reply, language=language, mode="tool", tool_used=tool_name)

    async def _handle_multiple_tool_calls(self, tool_calls: list[dict], text: str, conv_id: str, language: str) -> SupervisorResult:
        observations = []
        for call in tool_calls:
            tool_name = call.get("name")
            tool = registry.get(tool_name or "")
            if tool is None or tool.permission.value == "BLOCKED":
                observations.append(f"Tool {tool_name} not found or blocked.")
                continue

            args = call.get("args") or {}
            result = await registry.execute(tool_name, args, triggered_by="agent", conversation_id=conv_id)
            observations.append(f"{tool_name}: {result.message}")
            if not result.success and "CONFIRMATION_REQUIRED:" in result.message:
                code = result.message.split(":")[1]
                desc = result.message.split(":", 2)[2]
                return SupervisorResult(
                    reply=f"I need your approval first. I want to {desc}. Say yes, or give me code {code}.",
                    language=language,
                    mode="confirm",
                    tool_used=tool_name,
                )

        from langchain_core.messages import HumanMessage, SystemMessage
        summary_prompt_messages = [
            SystemMessage(
                content="Summarize for the user what was accomplished in one or two short spoken sentences based on the tool execution results. Be honest about any failure. No markdown."
            ),
            HumanMessage(content=f"Goal: {text}\nResults:\n" + "\n".join(observations)),
        ]
        try:
            summary = clean_llm_text((await get_fast_llm().ainvoke(summary_prompt_messages)).content)
        except Exception:
            summary = "I have completed the tasks."
            
        return SupervisorResult(reply=summary, language=language, mode="multi-tool")

    def _template_outcome(self, result: ToolResult) -> str:
        """Zero-latency honest phrasing straight from the validated tool result."""
        message = clean_llm_text(result.message or "")
        raw_lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
        if not raw_lines:
            return "Done." if result.success else "That didn't work."

        lines = raw_lines[1:] if len(raw_lines) > 1 and raw_lines[0].endswith((":")) else raw_lines
        cleaned = [_strip_leading_bullets(ln).strip() for ln in lines]
        cleaned = [ln.rstrip(":").strip() for ln in cleaned if ln]
        text = "; ".join(cleaned) if cleaned else raw_lines[0]

        first_line = next((ln for ln in raw_lines if ln), "")
        if not result.success:
            lowered = text.lower()
            prefix = ""
            if not any(k in lowered for k in ("could not", "couldn't", "failed", "not found", "refus", "no ", "don't know", "invalid", "unable")):
                prefix = "That didn't work. "
            return f"{prefix}{text}"[:400]

        if len(text) > 340:
            cut = text.rfind(";", 0, 340)
            text = (text[:cut] + "; …") if cut > 80 else text[:337] + "..."
        return text

    async def _plain_chat(self, text, conv_id, language, source="api") -> str:
        memory_block = await memory_service.memory_block_for_context(text)
        language_pref = await memory_service.language_preference()
        system_prompt = build_system_prompt(
            memory_block=memory_block,
            mode_hint=(
                "Reply conversationally in plain spoken sentences."
                + _voice_brevity_hint(source)
            ),
            language_preference=language_pref,
        )
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=text)]
        try:
            response = await get_llm().ainvoke(messages)
            return clean_llm_text(response.content)
        except Exception as exc:
            logger.error("Plain chat LLM failed: %s", exc)
            return ""


supervisor = Supervisor()


async def process_text(text: str, source: str = "api", request_id: str = "-") -> SupervisorResult:
    from app.tools import register_all_tools

    register_all_tools()
    return await supervisor.process_user_input(text, source=source, request_id=request_id)


async def process_text_stream(text: str, source: str = "api", request_id: str = "-"):
    """Stream version of process_text that yields tokens."""
    from app.tools import register_all_tools
    register_all_tools()
    
    text = (text or "").strip()
    if not text:
        yield ""
        return
    
    conversation = await conversation_manager.get_or_create_active()
    conv_id = conversation.id
    
    language = detect_language(text)
    supervisor._last_language = language
    await supervisor._track_language_persistence(language)
    
    await conversation_manager.add_message(conv_id, "user", text, language=language)
    history = (await conversation_manager.get_recent_messages(conv_id, limit=9))[:-1]
    
    # Fast paths - no streaming
    if _GREETING_RE.match(text):
        import random
        pool = _GREETINGS.get(language, _GREETINGS["English"])
        yield random.choice(pool)
        return
    
    switch_match = _LANG_SWITCH_RE.search(text)
    if switch_match:
        lowered = text.lower()
        if not any(w in lowered for w in ["why", "का ", "का?", "क्यों", "kyu"]):
            target = _detect_switch_target(text)
            if target:
                await memory_service.set_preference("reply_language", target, source="user")
                supervisor._lang_streak = 0
                supervisor._streak_language = target if target != "English" else "English"
                supervisor._last_language = target
                import random
                ack = random.choice(_SWITCH_ACKS.get(target, _SWITCH_ACKS["English"]))
                yield ack
                return
    
    fast_match = fast_path.match(text)
    if fast_match is not None:
        outcome = await run_fast_match(fast_match, conv_id)
        reply = outcome.message if fast_match.tool_name == "__set_language__" else supervisor._template_outcome(outcome)
        yield reply
        return
    
    # Streaming path for chat
    if _COMMAND_INTENT_RE.search(text):
        logger.debug("Bypassing memory retrieval for clear command intent.")
        memory_block = ""
    else:
        memory_block = await memory_service.memory_block_for_context(text)
    
    language_pref = await memory_service.language_preference()
    
    system_prompt = build_system_prompt(
        memory_block=memory_block,
        mode_hint=(
            "Decide in this single turn: either reply conversationally, or call exactly "
            "one tool when an action/lookup is clearly needed. Emit multiple tool calls "
            "ONLY for a complex multi-step request. Never invent results. "
            "If the user is merely greeting or summoning you, reply conversationally — "
            "never call web_search or any tool for greetings.\n"
            "Multi-action sentences ('open notepad and type 100') -> emit ONE tool call "
            "per action, in order: open_application first, then keyboard_type with the "
            "spoken text. Only use write_file when the user explicitly says file/save/"
            "document; typing into an app is keyboard_type, never a file."
        )
        + _voice_brevity_hint(source),
        language_preference=language_pref,
    )
    messages = [SystemMessage(content=system_prompt)]
    for turn in history[-8:]:
        if turn["role"] == "user":
            messages.append(HumanMessage(content=turn["content"]))
        elif turn["role"] == "assistant":
            messages.append(AIMessage(content=turn["content"]))
    messages.append(HumanMessage(content=text))
    
    llm = get_llm(temperature=0)
    specs = supervisor._tool_specs_cache()
    
    # Stream LLM response
    full_content = ""
    tool_calls = []
    
    if specs:
        bound = llm.bind_tools(specs, max_tokens=600)
        async for chunk in bound.astream(messages):
            if chunk.content:
                full_content += chunk.content
                yield chunk.content
            if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)
    else:
        async for chunk in llm.astream(messages):
            if chunk.content:
                full_content += chunk.content
                yield chunk.content
    
    # Handle tool calls if any
    raw_calls = tool_calls
    tool_calls = [
        {"name": tc.get("name"), "args": tc.get("args") or {}}
        for tc in raw_calls
        if isinstance(tc, dict) and tc.get("name")
    ]
    
    content = full_content
    
    if len(tool_calls) >= 2:
        # For multi-tool, we need to execute and summarize
        result = await supervisor._handle_multiple_tool_calls(tool_calls, text, conv_id, language)
        yield result.reply
        return
    
    if len(tool_calls) == 1:
        call = tool_calls[0]
        result = await supervisor._handle_single_tool_call(call, text, conv_id, language)
        yield result.reply
        return
    
    reply = clean_llm_text(content or "")
    if not reply or _looks_structured(reply):
        reply = await supervisor._plain_chat(text, conv_id, language, source=source)
    if not reply or _looks_structured(reply):
        reply = supervisor._natural_fallback(language)
    
    # For a plain chat the reply was already streamed chunk by chunk above;
    # yielding it again makes TTS speak it twice. Only yield when the final
    # reply actually differs from what was streamed (tool results/fallbacks).
    if reply != clean_llm_text(full_content):
        yield reply


__all__ = ["SupervisorResult", "process_text", "process_text_stream"]
