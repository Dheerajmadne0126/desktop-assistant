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
        """Auto-heals by applying pending Alembic migrations.

        Runs on a fresh/switched database (core tables missing) or whenever the
        DB is behind the head revision, so new migrations (e.g. the mobile
        tables) apply automatically on the next boot.
        """
        try:
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy import text

            async with self.engine.connect() as conn:
                has_core = await conn.run_sync(
                    lambda sc: sa_inspect(sc).has_table("preferences")
                )
                has_versions = await conn.run_sync(
                    lambda sc: sa_inspect(sc).has_table("alembic_version")
                )
                current = None
                if has_versions:
                    row = (
                        await conn.execute(
                            text("SELECT version_num FROM alembic_version")
                        )
                    ).first()
                    current = row[0] if row else None

            head = self._head_revision()
            # Skip DBs created via Base.metadata.create_all (no alembic_version
            # table): those are test/scratch databases, not migration-managed.
            needs_migration = (not has_core) or (
                has_versions and head is not None and current != head
            )
            if not needs_migration:
                return

            logger.warning(
                "Applying Alembic migrations (%s -> %s)…", current or "fresh", head
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
    def _head_revision() -> str | None:
        from pathlib import Path

        from alembic.script import ScriptDirectory

        backend_root = Path(__file__).resolve().parents[2]
        script = ScriptDirectory(str(backend_root / "migrations"))
        heads = script.get_heads()
        return heads[0] if heads else None

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
