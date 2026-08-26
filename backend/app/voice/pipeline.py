import asyncio
import re
import time
import uuid

from app.conversation.manager import conversation_manager
from app.core.config import get_settings
from app.core.events import event_bus
from app.core.logging import get_logger
from app.core.state import AgentState, state_machine
from app.voice.mic import MicrophoneHub
from app.voice.stt import transcribe_with_fallback
from app.voice.stt.quality_gate import _JARVIS_VARIANT, stt_quality_gate
from app.voice.tts import speak_text, stop_speaking
from app.voice.vad import PhraseRecorder
from app.voice.wakeword.provider import WakeWordListener

logger = get_logger("pipeline")

_TRIGGER_MIN_INTERVAL = 1.5
_DUPLICATE_TEXT_WINDOW = 4.0
_ECHO_SETTLE_SECONDS = 0.25

_SLEEP_RE = re.compile(
    r"^(?:stop|bas|band)[.!]?$"
    r"|stop listening|go to sleep|sleep (?:jarvis|now|mode)|jarvis (?:go to )?sleep"
    r"|deactivate(?: jarvis)?"
    r"|\u0938\u094b \u091c\u093e|\u092c\u0902\u0926 \u0915\u0930(?:\u094b)?|\u0938\u094d\u0932\u0940\u092a",
    re.IGNORECASE,
)


def is_sleep_command(text: str) -> bool:
    lowered = text.lower().strip()
    if len(lowered.split()) <= 4 and _SLEEP_RE.match(lowered):
        return True
    return bool(_SLEEP_RE.search(lowered))

def _normalize_for_dedupe(text: str) -> str:
    return re.sub(r"[^\w\u0900-\u097F]+", "", text).lower()


class VoicePipeline:
    def __init__(self) -> None:
        self.is_running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._session_task: asyncio.Task | None = None
        self._session_lock = asyncio.Lock()
        self._last_trigger_at = 0.0
        self._last_text = ""
        self._last_text_at = 0.0
        self._last_reply_words: set[str] = set()
        self._last_reply_at = 0.0
        self._stt_offline_notified = False

        settings = get_settings()
        self.hub = MicrophoneHub(settings.sample_rate)
        self.wake_listener = WakeWordListener(self.hub)
        self.recorder = PhraseRecorder(self.hub)

    @property
    def status(self) -> str:
        if not get_settings().voice_enabled:
            return "disabled"
        if not self.is_running:
            return "down"
        return "up"

    def start(self) -> None:
        settings = get_settings()
        if not settings.voice_enabled:
            logger.info("Voice pipeline disabled by configuration.")
            return
        if self.is_running:
            return

        self.is_running = True
        self._loop = asyncio.get_running_loop()

        mic_live = self.hub.start()
        if not mic_live:
            logger.error("Microphone unavailable; wake word + capture disabled.")
            self.is_running = False
            return

        try:
            from app.voice.tts.base import prepare_output_mixer

            prepare_output_mixer(get_settings().tts_sample_rate)
        except Exception as exc:
            logger.warning("Output mixer pre-init skipped: %s", exc)

        self.recorder.start_worker()

        def _wake():
            if self._loop is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._on_wake_word(), self._loop)

        wake_started = self.wake_listener.start(_wake)
        if not wake_started:
            logger.warning("Wake word unavailable; activation via dashboard button only.")
        logger.info("Voice pipeline live on single shared microphone stream.")

    def stop(self) -> None:
        self.is_running = False
        stop_speaking()
        self.wake_listener.stop()
        self.recorder.stop_worker()
        self.hub.suppress_wake(False)
        self.hub.set_capture(False)
        self.hub.stop()
        if self._session_task is not None and self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._session_task.cancel)
            except Exception:
                pass

    async def _on_wake_word(self) -> None:
        now = time.monotonic()
        if now - self._last_trigger_at < _TRIGGER_MIN_INTERVAL:
            return
        self._last_trigger_at = now

        current = state_machine.state
        if current == AgentState.SPEAKING:
            logger.info("Wake during speech ignored (half-duplex; use barge-in).")
            return

        if current in (AgentState.IDLE, AgentState.LISTENING_FOR_WAKE_WORD):
            async with self._session_lock:
                if self._session_task is not None and not self._session_task.done():
                    return
                if state_machine.state not in (
                    AgentState.IDLE,
                    AgentState.LISTENING_FOR_WAKE_WORD,
                ):
                    return
                t0 = time.perf_counter()
                self._session_task = asyncio.create_task(self.command_session())
                await state_machine.set_state(
                    AgentState.LISTENING_FOR_COMMAND, "Yes? I'm listening."
                )
                logger.info(
                    "[WAKE] activated in %.0fms", (time.perf_counter() - t0) * 1000
                )

    async def command_session(self) -> None:
        settings = get_settings()
        empty_retries = 0
        turns = 0
        started = time.perf_counter()
        stats = {"stt": [], "llm": [], "tts": [], "turn": []}

        try:
            while turns <= settings.max_followup_turns and self.is_running:
                self._stt_offline_notified = False
                await state_machine.set_state(
                    AgentState.LISTENING_FOR_COMMAND, "Listening..."
                )
                record_start = time.perf_counter()
                wav_bytes = await asyncio.to_thread(self.recorder.record_phrase)
                turns += 1

                if not wav_bytes:
                    empty_retries += 1
                    logger.info(
                        "No speech captured (%d/%d).",
                        empty_retries,
                        settings.empty_listen_retries,
                    )
                    if empty_retries >= settings.empty_listen_retries:
                        break
                    continue
                empty_retries = 0

                stt_t0 = time.perf_counter()
                stt_result = await transcribe_with_fallback(wav_bytes)
                stt_ms = int((time.perf_counter() - stt_t0) * 1000)
                text = (stt_result.text or "").strip() if stt_result else ""

                if stt_result is None:
                    from app.voice import stt as stt_module

                    await self._handle_stt_failure(
                        stt_module.last_failure_kind, language
                    )

                if not text:
                    empty_retries += 1
                    if empty_retries >= settings.empty_listen_retries:
                        break
                    continue

                request_id = uuid.uuid4().hex[:8]
                accepted, reason = stt_quality_gate(stt_result)

                if accepted:
                    from app.voice.stt.quality_gate import _JARVIS_VARIANT

                    residue = _JARVIS_VARIANT.sub("", text).strip(" .!?।")
                    if len(residue) < 2 and _JARVIS_VARIANT.search(text):
                        logger.info("[%s] Wake-only utterance; listening again.", request_id)
                        continue

                normalized = _normalize_for_dedupe(text)
                duplicate = (
                    bool(normalized)
                    and normalized == self._last_text
                    and time.monotonic() - self._last_text_at < _DUPLICATE_TEXT_WINDOW
                )
                if not accepted:
                    logger.info("[%s] STT rejected (%s): %r", request_id, reason, text[:50])
                    empty_retries += 1
                    if empty_retries >= settings.empty_listen_retries:
                        break
                    continue
                if duplicate:
                    logger.info("[%s] Duplicate transcript skipped.", request_id)
                    continue

                if self._is_self_echo(text):
                    logger.warning(
                        "[%s] SELF-ECHO rejected (matched previous TTS): %r",
                        request_id,
                        text[:60],
                    )
                    continue

                self._last_text = normalized
                self._last_text_at = time.monotonic()

                logger.info(
                    "[%s] [STT] %dms %s",
                    request_id,
                    stt_ms,
                    text[:70],
                )
                await event_bus.publish({"type": "transcription", "text": f"USER: {text}"})

                await state_machine.set_state(AgentState.THINKING, "Thinking...")
                self.wake_listener.suppress(True)
                llm_t0 = time.perf_counter()
                result = await self._process(text, request_id)
                llm_ms = int((time.perf_counter() - llm_t0) * 1000)
                logger.info("[%s] [RESPONSE] %dms %s", request_id, llm_ms, result.reply[:70])
                self._remember_reply(result.reply)

                await event_bus.publish(
                    {"type": "transcription", "text": f"JARVIS: {result.reply}"}
                )
                await state_machine.set_state(AgentState.SPEAKING, "Responding...")

                # Half-duplex guard: capture stays OFF while speaking so the
                # collector can NEVER record JARVIS's own voice as a user phrase.
                # Voice barge-in works via RMS monitoring on the raw feed instead.
                self.wake_listener.suppress(True)

                if get_settings().barge_in_enabled:
                    self.recorder.set_barge_monitor(
                        lambda: stop_speaking(), armed=True
                    )

                tts_t0 = time.perf_counter()
                completed = await speak_text(result.reply, language=result.language)
                tts_ms = int((time.perf_counter() - tts_t0) * 1000)

                self.recorder.set_barge_monitor(None, armed=False)
                self.hub.set_capture(False)
                total_ms = int((time.perf_counter() - record_start) * 1000)
                stats["stt"].append(stt_ms)
                stats["llm"].append(llm_ms)
                stats["tts"].append(tts_ms)
                stats["turn"].append(total_ms)
                logger.info(
                    "[%s] [TIMING] stt=%dms llm=%dms tts=%dms turn=%dms",
                    request_id,
                    stt_ms,
                    llm_ms,
                    tts_ms,
                    total_ms,
                )

                if not completed:
                    logger.info("[%s] Speech interrupted; listening immediately.", request_id)
                    continue

                await asyncio.sleep(_ECHO_SETTLE_SECONDS)

                if is_sleep_command(text):
                    ack = random_ack_sleep(result.language)
                    await state_machine.set_state(AgentState.SPEAKING, "Sleeping")
                    self.wake_listener.suppress(True)
                    try:
                        await speak_text(ack, language=result.language)
                    finally:
                        self.wake_listener.suppress(False)
                    logger.info(
                        "[SLEEP] Session closed by user; wake word re-armed "
                        "(threshold=%.2f).",
                        settings.wake_word_threshold,
                    )
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Voice session error: %s", exc, exc_info=True)
        finally:
            self.recorder.set_barge_monitor(None, armed=False)
            self.hub.set_capture(False)
            self.wake_listener.suppress(False)
            self._session_task = None
            if self.is_running:
                await state_machine.set_state(
                    AgentState.LISTENING_FOR_WAKE_WORD,
                    f"Say 'Hey Jarvis' ({int(time.perf_counter() - started)}s session)",
                )

            def avg(key):
                vals = stats[key]
                return int(sum(vals) / len(vals)) if vals else 0

            logger.info(
                "[SESSION] turns=%d | avg stt=%dms llm=%dms tts=%dms turn=%dms "
                "| wake_fires=%d",
                turns,
                avg("stt"),
                avg("llm"),
                avg("tts"),
                avg("turn"),
                self.wake_listener.fire_count,
            )
            logger.info("Voice session ended after %d turn(s).", turns)

    async def _handle_stt_failure(self, kind: str, language: str) -> None:
        """Speaks ONE context-appropriate notice per session:
        network outage vs 'didn't catch that'."""
        if self._stt_offline_notified:
            return
        self._stt_offline_notified = True

        from app.memory.service import memory_service

        pref = await memory_service.language_preference()
        spoken_lang = pref if pref in ("Marathi", "Hindi") else "English"

        await state_machine.set_state(AgentState.SPEAKING, "Speech service issue")

        if kind == "network":
            logger.warning("[STT] Network outage; informing user once.")
            notice = {
                "Marathi": "सर, नेटवर्क तुटलंय — म्हणून मला ऐकता येत नाहीये. नेट आलं की बरोबर चालू होईन.",
                "Hindi": "सर, नेटवर्क डाउन है — इसलिए मैं सुन नहीं पा रहा। नेट आते ही ठीक हो जाऊँगा।",
            }.get(spoken_lang, "Sir, my network link is down so I can't reach the speech servers. I'll work again the moment it returns.")
        else:
            logger.info("[STT] Audio not understandable; informing user once.")
            notice = {
                "Marathi": "माफ करा सर, ते नीट समजलं नाही — पुन्हा सांगाल का?",
                "Hindi": "माफ़ कीजिए सर, समझ नहीं आया — दोबारा बोलिए।",
            }.get(spoken_lang, "Sorry sir, I couldn't catch that clearly — say it again?")

        await speak_text(notice, language=spoken_lang)

    async def _process(self, text: str, request_id: str = "-"):
        from app.ai.agent.supervisor import process_text

        return await process_text(text, source="voice", request_id=request_id)

    def _remember_reply(self, reply: str) -> None:
        self._last_reply_words = {
            w.lower()
            for w in re.findall(r"[\w\u0900-\u097F]{4,}", reply)
        }
        self._last_reply_at = time.monotonic()

    def _is_self_echo(self, text: str) -> bool:
        """Rejects transcripts that heavily overlap JARVIS's most recent spoken
        reply — the signature of speaker-to-mic echo slipping through."""
        if not self._last_reply_words:
            return False
        if time.monotonic() - self._last_reply_at > 15:
            return False
        words = {
            w.lower() for w in re.findall(r"[\w\u0900-\u097F]{4,}", text)
        }
        if not words:
            return False
        overlap = len(words & self._last_reply_words) / len(words)
        shared = len(words & self._last_reply_words)
        return (shared >= 2 and overlap >= 0.4) or (shared >= 1 and overlap >= 0.8)

    def trigger_manual_listen(self) -> bool:
        if not self.is_running or self._loop is None:
            return False
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is self._loop:
            if state_machine.state == AgentState.SPEAKING:
                stop_speaking()
                return True
            if self._session_task is None or self._session_task.done():
                self._session_task = asyncio.create_task(self.command_session())
                asyncio.create_task(
                    state_machine.set_state(AgentState.LISTENING_FOR_COMMAND, "Yes? I'm listening.")
                )
            return True
        asyncio.run_coroutine_threadsafe(self._on_wake_word(), self._loop)
        return True


def random_ack_sleep(language: str) -> str:
    return {
        "Marathi": "ठीक आहे सर, मी झोपतो. पुन्हा 'Hey Jarvis' म्हणा.",
        "Hindi": "ठीक है सर, मैं स्लीप मोड में जा रहा हूँ।",
    }.get(language, "Going to sleep, sir. Say 'Hey Jarvis' when you need me.")

voice_pipeline = VoicePipeline()

