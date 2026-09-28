import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from collections import deque

from app.core.logging import get_logger
from app.memory.postgres_store import postgres_memory_store
from app.memory.vector_store import vector_store

logger = get_logger("memory_service")


@dataclass
class ConversationContext:
    """Short-term conversation context for a single session."""
    conversation_id: str
    recent_turns: List[Dict[str, Any]] = field(default_factory=list)
    active_topics: List[str] = field(default_factory=list)
    pending_tool_results: Dict[str, Any] = field(default_factory=dict)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def add_turn(self, role: str, content: str, language: str = "English", tool_used: str = None):
        self.recent_turns.append({
            "role": role,
            "content": content,
            "language": language,
            "tool_used": tool_used,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only last 10 turns
        if len(self.recent_turns) > 10:
            self.recent_turns = self.recent_turns[-10:]
        self.last_updated = datetime.now(timezone.utc)
    
    def add_tool_result(self, tool_name: str, result: Any):
        self.pending_tool_results[tool_name] = {
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    
    def get_recent_context(self, max_turns: int = 5) -> str:
        """Get formatted recent conversation for LLM context."""
        if not self.recent_turns:
            return ""
        recent = self.recent_turns[-max_turns:]
        lines = []
        for turn in recent:
            prefix = "User" if turn["role"] == "user" else "Assistant"
            tool_info = f" [used {turn['tool_used']}]" if turn.get("tool_used") else ""
            lines.append(f"{prefix}{tool_info}: {turn['content'][:200]}")
        return "\n".join(lines)


class ContextManager:
    """Manages conversation contexts with TTL-based cleanup."""
    
    def __init__(self, ttl_minutes: int = 60):
        self._contexts: Dict[str, ConversationContext] = {}
        self._access_times: Dict[str, datetime] = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self._lock = asyncio.Lock()
    
    async def get_or_create(self, conversation_id: str) -> ConversationContext:
        async with self._lock:
            self._cleanup_expired()
            if conversation_id not in self._contexts:
                self._contexts[conversation_id] = ConversationContext(conversation_id=conversation_id)
            self._access_times[conversation_id] = datetime.now(timezone.utc)
            return self._contexts[conversation_id]
    
    async def get(self, conversation_id: str) -> Optional[ConversationContext]:
        async with self._lock:
            self._cleanup_expired()
            if conversation_id in self._contexts:
                self._access_times[conversation_id] = datetime.now(timezone.utc)
                return self._contexts[conversation_id]
            return None
    
    def _cleanup_expired(self):
        now = datetime.now(timezone.utc)
        expired = [
            cid for cid, last_access in self._access_times.items()
            if now - last_access > self.ttl
        ]
        for cid in expired:
            self._contexts.pop(cid, None)
            self._access_times.pop(cid, None)
        if expired:
            logger.debug("Cleaned up %d expired conversation contexts", len(expired))
    
    async def clear(self, conversation_id: str):
        async with self._lock:
            self._contexts.pop(conversation_id, None)
            self._access_times.pop(conversation_id, None)


class EnhancedMemoryService:
    def __init__(self):
        self.context_manager = ContextManager(ttl_minutes=60)
        self._topic_extractor_cache: Dict[str, List[str]] = {}
    
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
        
        # Update conversation context with new fact
        if conversation_id:
            context = await self.context_manager.get_or_create(str(conversation_id))
            if category not in context.active_topics:
                context.active_topics.append(category)
                if len(context.active_topics) > 5:
                    context.active_topics = context.active_topics[-5:]
        
        logger.info("Remembered %s fact: %s...", category, text[:50])
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

    async def get_contextual_memory(
        self, 
        query: str, 
        conversation_id: str, 
        max_items: int = 4,
        include_context: bool = True
    ) -> str:
        """Get memory block enhanced with conversation context."""
        parts = []
        
        # Get vector memory
        memory_block = await self.memory_block_for_context(query, max_items)
        if memory_block:
            parts.append(f"[LONG-TERM MEMORY]\n{memory_block}")
        
        # Get conversation context
        if include_context and conversation_id:
            context = await self.context_manager.get(conversation_id)
            if context:
                ctx_str = context.get_recent_context(5)
                if ctx_str:
                    parts.append(f"[RECENT CONTEXT]\n{ctx_str}")
                
                if context.active_topics:
                    parts.append(f"[ACTIVE TOPICS] {', '.join(context.active_topics)}")
                
                if context.pending_tool_results:
                    tool_results = "\n".join(
                        f"- {tool}: {res['result'][:100]}..." 
                        for tool, res in context.pending_tool_results.items()
                    )
                    parts.append(f"[RECENT TOOL RESULTS]\n{tool_results}")
        
        return "\n\n".join(parts) if parts else ""

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

    async def extract_topics(self, text: str) -> List[str]:
        """Extract key topics from text for context tracking."""
        cache_key = hash(text)
        if cache_key in self._topic_extractor_cache:
            return self._topic_extractor_cache[cache_key]
        
        # Simple topic extraction - in production could use LLM
        topics = []
        text_lower = text.lower()
        topic_keywords = {
            "project": ["project", "code", "repo", "github", "git"],
            "meeting": ["meeting", "call", "schedule", "calendar"],
            "email": ["email", "mail", "send", "inbox"],
            "file": ["file", "document", "folder", "directory"],
            "browser": ["browser", "web", "search", "url", "website"],
            "system": ["system", "cpu", "memory", "disk", "performance"],
            "reminder": ["remind", "alarm", "timer", "schedule"],
        }
        
        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                topics.append(topic)
        
        self._topic_extractor_cache[cache_key] = topics
        return topics

    async def clear_conversation_context(self, conversation_id: str):
        await self.context_manager.clear(conversation_id)


enhanced_memory_service = EnhancedMemoryService()