import time

from app.core.config import get_settings
from app.core.logging import get_logger
from app.memory.postgres_store import postgres_memory_store

logger = get_logger("proactive")


class ProactiveService:
    """Two notification lanes:

    - announce_user_scheduled: fires for things the USER explicitly asked for
      (reminders, alarms, timers). Always attempts delivery.
    - notify_proactive: assistant-initiated nudges. Gated behind PROACTIVE_ENABLED,
      quiet hours, category preferences, and a minimum interval.
    """

    def __init__(self) -> None:
        self.last_proactive_at = 0.0
        self.min_interval_s = 300

    async def _speak_if_possible(self, message: str) -> bool:
        from app.core.state import AgentState, state_machine
        from app.voice.tts import speak_text

        if not self._is_quiet_hours_ok():
            logger.info("Suppressed announcement during quiet hours.")
            return False

        if state_machine.state == AgentState.SPEAKING:
            logger.info("Skipped announcement; currently speaking.")
            return False

        language = "English"
        try:
            lang_pref = await postgres_memory_store.get_preference("reply_language")
            if isinstance(lang_pref, str) and lang_pref:
                language = {"marathi": "Marathi", "hindi": "Hindi"}.get(
                    lang_pref.lower(), "English"
                )
        except Exception:
            pass

        delivered = await speak_text(message, language=language)
        return delivered

    def _is_quiet_hours_ok(self) -> bool:
        settings = get_settings()
        try:
            current_hour = time.localtime().tm_hour
            start = int(settings.quiet_hours_start.split(":")[0])
            end = int(settings.quiet_hours_end.split(":")[0])
            if start <= end:
                in_quiet = start <= current_hour < end
            else:
                in_quiet = current_hour >= start or current_hour < end
            return not in_quiet
        except Exception:
            return True

    async def announce_user_scheduled(self, message: str) -> bool:
        """Reminders/alarms/timers the user explicitly created. Quiet hours still apply."""
        logger.info("Scheduled announcement: %s", message[:80])
        return await self._speak_if_possible(message)

    async def notify_proactive(self, message: str, category: str = "general") -> bool:
        settings = get_settings()
        if not settings.proactive_enabled:
            return False

        if time.time() - self.last_proactive_at < self.min_interval_s:
            logger.debug("Proactive suppressed by min-interval.")
            return False

        enabled_categories = await postgres_memory_store.get_preference(
            "proactive_categories",
            ["routine", "briefing"],
        )
        if isinstance(enabled_categories, list) and category not in enabled_categories:
            logger.debug("Proactive suppressed; category '%s' disabled.", category)
            return False

        delivered = await self.notify_proactive_inner(message)
        if delivered:
            self.last_proactive_at = time.time()
        return delivered

    async def notify_proactive_inner(self, message: str) -> bool:
        return await self._speak_if_possible(message)


proactive_service = ProactiveService()
