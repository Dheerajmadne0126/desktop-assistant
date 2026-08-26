import re
from dataclasses import dataclass

from app.core.logging import get_logger
from app.tools.base import ToolResult
from app.tools.registry import registry

logger = get_logger("fastpath")


@dataclass
class FastMatch:
    tool_name: str
    args: dict
    ack: str


_OPEN_VERB = r"(?:open|start|launch|khol|kholo|kholna|chaloo|chalu|chala|chalao|ugad|ugade|suru)"
_CLOSE_VERB = r"(?:close|exit|quit|band|thamb|kill)"


class FastPath:
    def _patterns(self) -> list[tuple[re.Pattern, str, callable]]:
        return [
            (
                re.compile(rf"^(?:{_OPEN_VERB})\s+(.+?)(?:\s+(?:kar|karo|kara|kra))?$", re.I),
                "open_application",
                lambda m: {"app_name": m.group(1).strip()},
            ),
            (
                re.compile(rf"^(.+?)\s+(?:{_OPEN_VERB})(?:\s+(?:kar|karo|kara|kra))?$", re.I),
                "open_application",
                lambda m: {"app_name": m.group(1).strip()},
            ),
            (
                re.compile(rf"^(?:{_CLOSE_VERB})\s+(.+?)(?:\s+(?:kar|karo|kara))?$", re.I),
                "close_application",
                lambda m: {"app_name": m.group(1).strip()},
            ),
            (
                re.compile(r"^(.+?)\s+(?:band kar|band karo|band)$", re.I),
                "close_application",
                lambda m: {"app_name": m.group(1).strip()},
            ),
            (
                re.compile(
                    r"^(?:what(?:'?s| is)?(?: the)? time\b[^.?]*\??|time\?)$"
                    r"|^kitne baje h[aeie]*$|^time (?:sang|bata|kay|kya)",
                    re.I,
                ),
                "get_system_time",
                lambda m: {},
            ),
            (
                re.compile(r"^screenshot$|^take (?:a )?screenshot$|^screen capture$", re.I),
                "take_screenshot",
                lambda m: {},
            ),
            (
                re.compile(
                    r"^lock (?:my |the )?(?:pc|computer|workstation|screen|system)$|^pc lock kar",
                    re.I,
                ),
                "lock_workstation",
                lambda m: {},
            ),
        ]

    def match(self, text: str) -> FastMatch | None:
        cleaned = text.strip().strip("?!.।")
        if len(cleaned.split()) > 12:
            return self._language_preference(cleaned)

        remember = re.match(
            r"^(?:remember|note)(?: that| this)?(?: ki)? (.+)$", cleaned, re.I
        )
        if remember:
            return FastMatch(
                tool_name="remember_fact",
                args={"text": remember.group(1).strip()},
                ack="",
            )
        yaad = re.match(r"^(.+?),?\s+yaad rakho$", cleaned, re.I)
        if yaad:
            return FastMatch(
                tool_name="remember_fact",
                args={"text": yaad.group(1).strip()},
                ack="",
            )

        recall_patterns = [
            r"^do you remember\b.*$",
            r"^(?:what|who|which|when|where)('?s| is| are) my .+$",
            r"^mer[ai] .+ (?:kya|kay) tha?$",
        ]
        for rp in recall_patterns:
            if re.match(rp, cleaned, re.I):
                return FastMatch(
                    tool_name="recall_information",
                    args={"query": cleaned},
                    ack="",
                )

        if len(cleaned.split()) > 8:
            return None

        for pattern, tool_name, arg_extractor in self._patterns():
            match = pattern.search(cleaned)
            if not match:
                continue
            args = arg_extractor(match)
            if tool_name in ("open_application", "close_application"):
                args["app_name"] = args["app_name"].lower().strip()
                if args["app_name"] in ("it", "this", "that", "the door"):
                    continue
            return FastMatch(tool_name=tool_name, args=args, ack="")

        return self._language_preference(cleaned)

    def _language_preference(self, text: str) -> FastMatch | None:
        patterns = [
            (re.compile(r"speak in (marathi|hindi|english)", re.I), None),
            (re.compile(r"(marathi|hindi|english) madhe bola?", re.I), None),
            (re.compile(r"(marathi|hindi|english) me bolo", re.I), None),
            (re.compile(r"(marathi|hindi|english) bol", re.I), None),
        ]
        for pattern, _ in patterns:
            match = pattern.search(text)
            if match:
                lang = match.group(1).capitalize()
                return FastMatch(
                    tool_name="__set_language__",
                    args={"language": lang},
                    ack=f"Noted. I will reply in {lang}.",
                )
        return None


fast_path = FastPath()


async def run_fast_match(fast_match: FastMatch, conversation_id=None) -> ToolResult:
    from app.memory.service import memory_service

    if fast_match.tool_name == "__set_language__":
        await memory_service.set_preference("reply_language", fast_match.args["language"])
        return ToolResult(success=True, message=fast_match.ack)

    result = await registry.execute(
        fast_match.tool_name,
        fast_match.args,
        triggered_by="fastpath",
        conversation_id=conversation_id,
    )
    return result
