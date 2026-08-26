import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.core.logging import get_logger
from app.db.session import database
from app.models.memory import Conversation, Message

logger = get_logger("conversation")

class ConversationManager:
    async def get_or_create_active(self) -> Conversation:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        async with database.session() as session:
            stmt = (
                select(Conversation)
                .where(Conversation.is_active == True)  # noqa: E712
                .order_by(Conversation.created_at.desc())
                .limit(1)
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing is not None and existing.updated_at > cutoff:
                return existing

            fresh = Conversation(id=uuid.uuid4())
            session.add(fresh)
            await session.commit()
            logger.info("Started new conversation %s", fresh.id)
            return fresh

    async def add_message(
        self,
        conversation_id,
        role: str,
        content: str,
        language: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content[:8000],
            language=language,
            latency_ms=latency_ms,
        )
        async with database.session() as session:
            session.add(msg)
            await session.commit()
        if role != "tool":
            logger.debug("Message[%s/%s] %s...", str(conversation_id)[:8], role, content[:60])

    async def get_recent_messages(self, conversation_id, limit: int = 8) -> list[dict]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.role.in_(("user", "assistant")))
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        async with database.session() as session:
            rows = list((await session.execute(stmt)).scalars())
        rows.reverse()
        return [{"role": r.role, "content": r.content, "language": r.language} for r in rows]

    async def close_all(self) -> None:
        async with database.session() as session:
            await session.execute(
                update(Conversation).where(Conversation.is_active == True).values(is_active=False)  # noqa: E712
            )
            await session.commit()

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


conversation_manager = ConversationManager()
