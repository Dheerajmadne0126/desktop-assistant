import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, update

from app.core.logging import get_logger
from app.db.session import database
from app.models.memory import Memory, UserPreference

logger = get_logger("memory")


class PostgresMemoryStore:
    async def add_fact(
        self,
        content: str,
        category: str,
        source: str,
        importance: float = 0.5,
        conversation_id=None,
    ) -> Memory:
        memory_id = uuid.uuid4()
        async with database.session() as session:
            row = Memory(
                id=memory_id,
                content=content,
                category=category,
                source=source,
                importance=importance,
                conversation_id=conversation_id,
            )
            session.add(row)
            await session.commit()
        logger.info("Stored %s memory #%s", category, memory_id)
        return row

    async def set_vector_id(self, memory_id: uuid.UUID, vector_id: uuid.UUID) -> None:
        async with database.session() as session:
            await session.execute(
                update(Memory).where(Memory.id == memory_id).values(vector_id=vector_id)
            )
            await session.commit()

    async def deactivate(self, memory_id: uuid.UUID) -> None:
        async with database.session() as session:
            await session.execute(
                update(Memory).where(Memory.id == memory_id).values(is_active=False)
            )
            await session.commit()

    async def list_facts(self, limit: int = 100) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.is_active == True)  # noqa: E712
            .order_by(Memory.importance.desc(), Memory.created_at.desc())
            .limit(limit)
        )
        async with database.session() as session:
            return list((await session.execute(stmt)).scalars())

    async def set_preference(self, key: str, value, source: str = "user") -> None:
        payload = {"value": value} if not isinstance(value, (dict, list)) else value
        async with database.session() as session:
            existing = await session.get(UserPreference, key)
            if existing:
                existing.value = payload
                existing.source = source
                existing.updated_at = datetime.now(timezone.utc)
            else:
                session.add(UserPreference(key=key, value=payload, source=source))
            await session.commit()

    async def get_preference(self, key: str, default=None):
        async with database.session() as session:
            row = await session.get(UserPreference, key)
        if row is None:
            return default
        if isinstance(row.value, dict) and set(row.value.keys()) == {"value"}:
            return row.value["value"]
        return row.value

    async def get_all_preferences(self) -> dict:
        async with database.session() as session:
            rows = list((await session.execute(select(UserPreference))).scalars())
        result = {}
        for r in rows:
            v = r.value
            if isinstance(v, dict) and set(v.keys()) == {"value"}:
                v = v["value"]
            result[r.key] = v
        return result


postgres_memory_store = PostgresMemoryStore()
