import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import database
from app.models.core import PendingConfirmation
from app.tools.base import Tool, ToolResult

logger = get_logger("confirmation")

_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead",
    "confirm", "confirmed", "proceed", "haan", "ha", "ji", "theek", "thik",
    "chal", "kardo", "kar", "ho", "hoya", "bara", "net",
}
_NEGATIVE = {
    "no", "nope", "cancel", "stop", "don't", "dont", "nahi", "nahin", "nako",
    "nko", "ruk", "ruko", "mat", "thamb", "band",
}


class ConfirmationService:
    async def create_pending(self, tool: Tool, args: dict, conversation_id=None):
        settings = get_settings()
        code = f"{secrets.randbelow(9000) + 1000}"
        row = PendingConfirmation(
            id=uuid.uuid4(),
            tool_name=tool.name,
            args=args,
            description=tool.confirm_verb or tool.description[:120],
            spoken_code=code,
            status="pending",
            conversation_id=conversation_id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        async with database.session() as session:
            session.add(row)
            await session.commit()
        logger.info("Pending confirmation %s for tool '%s'", code, tool.name)
        return row

    async def get_latest_pending(self, conversation_id=None) -> PendingConfirmation | None:
        stmt = (
            select(PendingConfirmation)
            .where(PendingConfirmation.status == "pending")
            .order_by(PendingConfirmation.expires_at.desc())
            .limit(5)
        )
        async with database.session() as session:
            rows = (await session.execute(stmt)).scalars().all()
        now = datetime.now(timezone.utc)
        valid = [
            r
            for r in rows
            if r.expires_at > now
            and (conversation_id is None or r.conversation_id in (None, conversation_id))
        ]
        return valid[0] if valid else None

    async def resolve(
        self,
        pending_id: uuid.UUID,
        confirmed: bool,
    ) -> None:
        async with database.session() as session:
            await session.execute(
                update(PendingConfirmation)
                .where(PendingConfirmation.id == pending_id)
                .values(
                    status="confirmed" if confirmed else "denied",
                    resolved_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    def parse_user_response(self, text: str, pending_code: str) -> str:
        lowered = text.lower().strip()
        digits = "".join(ch for ch in lowered if ch.isdigit())
        if pending_code in digits:
            return "confirmed"
        words = set(lowered.split())
        has_affirm = bool(words & _AFFIRMATIVE)
        has_deny = bool(words & _NEGATIVE)
        if has_deny and not has_affirm:
            return "denied"
        if has_affirm and not has_deny:
            return "confirmed"
        return "unclear"

    async def handle_user_response(self, text: str, conversation_id=None):
        pending = await self.get_latest_pending(conversation_id)
        if pending is None:
            return None
        verdict = self.parse_user_response(text, pending.spoken_code)
        if verdict == "unclear":
            return None
        await self.resolve(pending.id, verdict == "confirmed")
        if verdict == "denied":
            return ToolResult(success=True, message="Cancelled. I did not do it.")
        from app.tools.registry import registry

        result = await registry.execute(
            pending.tool_name,
            pending.args,
            triggered_by="confirmation",
            conversation_id=pending.conversation_id,
            skip_permission=True,
        )
        return result


confirmation_service = ConfirmationService()
