import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("db")


class Database:
    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def init(self) -> None:
        settings = get_settings()
        kwargs = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5, "echo": False}
        if settings.environment == "test":
            from sqlalchemy.pool import NullPool

            kwargs.pop("pool_size")
            kwargs.pop("max_overflow")
            kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {
            "timeout": 8,
            "command_timeout": 10,
            "server_settings": {"application_name": "jarvis"},
        }
        self._engine = create_async_engine(settings.database_url, **kwargs)
        self._session_factory = async_sessionmaker(
            bind=self._engine, expire_on_commit=False
        )
        logger.info("Database engine initialized.")

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not initialized; call init() first.")
        return self._engine

    def session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized; call init() first.")
        return self._session_factory()

    async def check(self) -> bool:
        try:
            from sqlalchemy import text

            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("Database health check failed: %s", exc)
            return False

    async def ensure_schema(self) -> None:
        """Auto-heals fresh/switched databases by applying pending migrations.

        Runs only when the core schema is missing, so normal boots cost nothing.
        """
        try:
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy import text

            async with self.engine.connect() as conn:
                has_core = await conn.run_sync(
                    lambda sc: sa_inspect(sc).has_table("preferences")
                )
            if has_core:
                return

            logger.warning(
                "Core tables missing (fresh or switched database). "
                "Applying migrations automatically…"
            )
            await asyncio.to_thread(self._run_alembic_upgrade)
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1 FROM preferences LIMIT 1"))
            logger.info("Database schema is now up to date.")
        except Exception as exc:
            logger.error(
                "Auto-migration failed. Run manually: alembic upgrade head (%s)", exc
            )

    @staticmethod
    def _run_alembic_upgrade() -> None:
        from pathlib import Path

        from alembic import command
        from alembic.config import Config

        backend_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(backend_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_root / "migrations"))
        cfg.set_main_option(
            "sqlalchemy.url",
            get_settings().database_url.replace("%", "%%"),
        )
        command.upgrade(cfg, "head")

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            logger.info("Database engine disposed.")


database = Database()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with database.session() as session:
        yield session
