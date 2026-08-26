import asyncio

from app.core.logging import get_logger
from app.memory.postgres_store import postgres_memory_store
from app.memory.vector_store import vector_store

logger = get_logger("memory_service")


class MemoryService:
    async def remember(
        self,
        text: str,
        category: str = "fact",
        source: str = "explicit",
        importance: float = 0.6,
        conversation_id=None,
    ) -> bool:
        row = await postgres_memory_store.add_fact(
            content=text,
            category=category,
            source=source,
            importance=importance,
            conversation_id=conversation_id,
        )
        loop = asyncio.get_running_loop()
        vector_id = await loop.run_in_executor(
            None, lambda: vector_store.add(text, {"memory_id": str(row.id), "category": category})
        )
        if vector_id is not None:
            await postgres_memory_store.set_vector_id(row.id, vector_id)
        return True

    async def retrieve(self, query: str, k: int = 4) -> list[tuple[str, float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: vector_store.search(query, k=k))

    async def memory_block_for_context(self, query: str, max_items: int = 4) -> str:
        hits = await self.retrieve(query, k=max_items)
        if not hits:
            return ""
        lines = [f"- {text}" for text, _score in hits]
        return "\n".join(lines)

    def store_chunks_sync(self, chunks: list[str], source: str) -> int:
        stored = 0
        for chunk in chunks:
            if vector_store.add(chunk, {"source": source, "category": "document"}):
                stored += 1
        return stored

    async def set_preference(self, key: str, value, source: str = "user") -> None:
        await postgres_memory_store.set_preference(key, value, source)

    async def get_preference(self, key: str, default=None):
        return await postgres_memory_store.get_preference(key, default)

    async def language_preference(self) -> str:
        return await postgres_memory_store.get_preference("reply_language", "auto")

    async def list_fact_texts(self, limit: int = 50) -> list[str]:
        rows = await postgres_memory_store.list_facts(limit=limit)
        return [r.content for r in rows]


memory_service = MemoryService()
