from fastapi import APIRouter

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/listen")
async def manual_listen() -> dict:
    from app.voice.pipeline import voice_pipeline

    started = voice_pipeline.trigger_manual_listen()
    if not started:
        return {
            "started": False,
            "detail": "Voice pipeline is not running. Check /health and restart the backend.",
        }
    return {"started": True, "detail": "Listening now. Speak your command."}


@router.get("/wake-stats")
async def wake_stats() -> dict:
    from app.core.config import get_settings
    from app.voice.pipeline import voice_pipeline

    listener = voice_pipeline.wake_listener
    scores = [s["score"] for s in listener.recent_scores]
    return {
        "threshold": get_settings().wake_word_threshold,
        "fire_count": listener.fire_count,
        "samples": len(scores),
        "max_recent": max(scores) if scores else 0.0,
        "avg_recent": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "recent": listener.recent_scores[-20:],
        "hint": (
            "If your spoken 'Hey Jarvis' peaks below threshold, lower "
            "WAKE_WORD_THRESHOLD in .env to just under that peak."
        ),
    }
