import time

from fastapi import APIRouter

from app.core.config import get_settings
from app.db.session import database

router = APIRouter(tags=["health"])

_started_at = time.time()


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    db_ok = await database.check()

    voice_status = "disabled"
    if settings.voice_enabled:
        try:
            from app.voice.pipeline import voice_pipeline

            voice_status = voice_pipeline.status
        except Exception:
            voice_status = "down"

    components = {
        "database": "up" if db_ok else "down",
        "voice_pipeline": voice_status,
        "scheduler": _scheduler_status(),
    }
    degraded = "down" in components.values()
    return {
        "status": "degraded" if degraded else "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - _started_at, 1),
        "components": components,
    }


def _scheduler_status() -> str:
    try:
        from app.scheduler.service import scheduler_service

        return "up" if scheduler_service.is_started else "down"
    except Exception:
        return "down"
