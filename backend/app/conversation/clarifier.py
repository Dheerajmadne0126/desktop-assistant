import json
import time
from dataclasses import dataclass, field

from app.ai.llm.provider import get_fast_llm
from app.ai.text_utils import clean_llm_text
from app.core.logging import get_logger
from app.tools.registry import registry

logger = get_logger("clarifier")

_MAX_ROUNDS = 4
_TTL_SECONDS = 600

_SLOT_QUESTIONS = {
    "app_name": {"en": "Which application should I open?", "auto": "Which one?"},
    "when": {"en": "At what time?", "auto": "What time?"},
    "time": {"en": "At what time?", "auto": "What time?"},
    "duration": {"en": "For how long?", "auto": "How long?"},
    "duration_str": {"en": "For how long?", "auto": "How long?"},
    "time_hhmm": {"en": "At what time? Use 24-hour format like 08:30.", "auto": "What time?"},
    "message": {"en": "What should it say?", "auto": "What text?"},
    "filepath": {"en": "Which file?", "auto": "Which file?"},
    "dir_path": {"en": "Which folder?", "auto": "Which folder?"},
    "url": {"en": "Which website?", "auto": "Where to?"},
    "query": {"en": "What should I look for?", "auto": "Search for what?"},
    "to_address": {"en": "Send it to which email address?", "auto": "To whom?"},
    "subject": {"en": "What subject line?", "auto": "Subject?"},
    "body": {"en": "What should the email say?", "auto": "What content?"},
    "content": {"en": "What should I write in it?", "auto": "Write what?"},
    "name_fragment": {"en": "Which one should I cancel? Say part of its name.", "auto": "Which one?"},
}


@dataclass
class PendingClarification:
    conversation_id: object
    tool_name: str
    collected: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    rounds: int = 0
    started_at: float = field(default_factory=time.time)


class ClarificationManager:
    def __init__(self) -> None:
        self._pending: dict[object, PendingClarification] = {}

    def start(self, conversation_id, tool_name: str, missing: list[str], collected: dict | None = None):
        state = PendingClarification(
            conversation_id=conversation_id,
            tool_name=tool_name,
            collected=dict(collected or {}),
            missing=list(missing),
        )
        self._pending[conversation_id] = state
        return state

    def get(self, conversation_id) -> PendingClarification | None:
        state = self._pending.get(conversation_id)
        if state is None:
            return None
        expired = (
            time.time() - state.started_at > _TTL_SECONDS
            or state.rounds >= _MAX_ROUNDS
        )
        if expired:
            self.clear(conversation_id)
            return None
        return state

    def clear(self, conversation_id) -> None:
        self._pending.pop(conversation_id, None)

    def question_for(self, state: PendingClarification) -> str:
        slot = state.missing[0]
        template = _SLOT_QUESTIONS.get(slot, {}).get("en", f"What is the {slot.replace('_', ' ')}?")
        return template

    async def feed_user_reply(self, state: PendingClarification, user_text: str) -> str:
        """Returns 'filled', 'asked_more', or 'no_progress'."""
        tool = registry.get(state.tool_name)
        properties = tool.parameters_schema.get("properties", {}) if tool else {}
        previously_collected = set(state.collected.keys())

        prompt = (
            "You are a slot-filling extractor for an assistant.\n"
            f"The assistant needs values for the action '{state.tool_name}'.\n"
            f"Slot definitions (JSON schema): {json.dumps(properties)}\n"
            f"Already collected: {json.dumps(state.collected)}\n"
            f"Missing: {json.dumps(state.missing)}\n"
            f"The user just said: \"{user_text}\"\n\n"
            "Extract any of the missing slot values from what the user said. "
            "The user may answer casually or in Hindi/Marathi/Hinglish; interpret meaning, "
            "normalize times like 'tomorrow 9 am' into a clear string. "
            "Reply with ONLY JSON: {\"extracted\": {slot: value}, \"still_missing\": [slots]}"
        )
        try:
            response = await get_fast_llm().ainvoke(prompt)
            content = clean_llm_text(response.content)
            if content.startswith("```"):
                content = content.strip("`").strip()
                if content.lower().startswith("json"):
                    content = content[4:].strip()
            data = json.loads(content)
            extracted = data.get("extracted", {}) or {}
            still_missing = data.get("still_missing")
        except Exception as exc:
            logger.warning("Slot extraction failed (%s); falling back.", exc)
            extracted = {state.missing[0]: user_text.strip()} if state.missing else {}
            still_missing = None

        for key, value in extracted.items():
            if key in properties and value not in (None, ""):
                state.collected[key] = str(value)

        required = [
            name for name, spec in properties.items()
            if name in tool.parameters_schema.get("required", [])
        ]
        state.missing = [
            name for name in required if not state.collected.get(name)
        ]
        if still_missing is not None and isinstance(still_missing, list):
            state.missing = [m for m in state.missing if m in still_missing] or state.missing

        state.rounds += 1
        if not state.missing:
            self.clear(state.conversation_id)
            return "filled"
        new_values = set(state.collected.keys()) - previously_collected
        if not new_values:
            return "no_progress"
        return "asked_more"


clarification_manager = ClarificationManager()
