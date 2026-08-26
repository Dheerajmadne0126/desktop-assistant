import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.schedules import router as schedules_router
from app.api.routes.voice import router as voice_router
from app.api.routes.ws_events import router as ws_events_router
from app.core.config import get_settings
from app.core.events import event_bus
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    event_bus.set_main_loop(asyncio.get_running_loop())

    from app.db.session import database

    database.init()
    db_ok = await database.check()
    if not db_ok:
        logger.warning(
            "Database unreachable at startup. Start it with: docker compose up -d"
        )
    else:
        await database.ensure_schema()

    try:
        from app.tools import register_all_tools

        register_all_tools()
    except Exception as exc:
        logger.error("Tool registration failed: %s", exc)

    try:
        from app.voice.pipeline import voice_pipeline

        voice_pipeline.start()
    except Exception as exc:
        logger.error("Voice pipeline failed to start: %s", exc)

    try:
        from app.scheduler.service import scheduler_service

        await scheduler_service.start()
    except Exception as exc:
        logger.error("Scheduler failed to start: %s", exc)

    async def _warm_vector_memory():
        try:
            from app.memory.vector_store import vector_store

            await asyncio.to_thread(vector_store.warmup)
            logger.info("Vector memory warmed up.")
        except Exception as exc:
            logger.warning("Vector warmup skipped: %s", exc)

    asyncio.create_task(_warm_vector_memory())

    logger.info("%s backend started (env=%s).", settings.app_name, settings.environment)
    yield

    from app.conversation.manager import conversation_manager

    try:
        from app.scheduler.service import scheduler_service

        scheduler_service.shutdown()
    except Exception:
        pass
    try:
        from app.voice.pipeline import voice_pipeline

        voice_pipeline.stop()
    except Exception:
        pass
    await conversation_manager.close_all()
    await database.dispose()
    logger.info("Backend shutdown complete.")


settings = get_settings()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(ws_events_router)
app.include_router(chat_router)
app.include_router(schedules_router)
app.include_router(voice_router)
