import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger("events")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._max_queue_size = 200

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Event subscriber queue full; dropping event.")

    def publish_threadsafe(self, event: dict[str, Any]) -> None:
        if self._main_loop is None or self._main_loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.publish(event), self._main_loop)


event_bus = EventBus()
