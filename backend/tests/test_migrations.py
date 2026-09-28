"""End-to-end proof that the Alembic migrations apply cleanly on a brand-new
database — including the mobile tables (mobile_devices, pairing_sessions,
mobile_sessions) that historically shipped without a migration.

Runs `upgrade head` against a fresh scratch database created for this test,
verifies the schema (version stamp, tables, mobile unique indexes), downgrades
back to base, re-upgrades (idempotency), and drops the scratch database.
"""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings

pytestmark = pytest.mark.needs_db

_SCRATCH_DB = "jarvis_migration_test"

_EXPECTED_TABLES = [
    # 0001: core schema
    "conversations",
    "messages",
    "memories",
    "preferences",
    "scheduled_tasks",
    "pending_confirmations",
    "tool_executions",
    "task_runs",
    # 0002: mobile companion tables
    "mobile_devices",
    "pairing_sessions",
    "mobile_sessions",
]


def _connect_kwargs(database: str) -> dict:
    """Same user/host/password as the real DATABASE_URL, never hardcoded."""
    base = make_url(get_settings().database_url)
    return {
        "host": base.host or "localhost",
        "port": base.port or 5432,
        "user": base.username,
        "password": base.password,
        "database": database,
    }


def _scratch_url() -> str:
    base = make_url(get_settings().database_url)
    return base.set(database=_SCRATCH_DB).render_as_string(hide_password=False)


async def _admin_exec(sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(**_connect_kwargs("postgres"))
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _create_scratch_db() -> None:
    import asyncpg

    conn = await asyncpg.connect(**_connect_kwargs("postgres"))
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _SCRATCH_DB
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_SCRATCH_DB}"')
    finally:
        await conn.close()


async def _drop_scratch_db() -> None:
    await _admin_exec(f'DROP DATABASE IF EXISTS "{_SCRATCH_DB}"')


async def _run_alembic(method: str, target: str) -> None:
    """Run an alembic command in a worker thread (env.py uses asyncio.run)."""
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", _scratch_url().replace("%", "%%"))

    fn = getattr(command, method)
    await asyncio.to_thread(fn, cfg, target)


async def _query(sql: str, *args) -> list:
    import asyncpg

    conn = await asyncpg.connect(**_connect_kwargs(_SCRATCH_DB))
    try:
        return list(await conn.fetch(sql, *args))
    finally:
        await conn.close()


async def _version() -> str | None:
    rows = await _query("SELECT version_num FROM alembic_version")
    return rows[0]["version_num"] if rows else None


async def _table_names() -> set[str]:
    rows = await _query(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    return {r["tablename"] for r in rows}


async def _index_names(table: str) -> set[str]:
    rows = await _query(
        "SELECT indexname FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = $1",
        table,
    )
    return {r["indexname"] for r in rows}


async def test_migrations_apply_cleanly_on_scratch_db():
    await _create_scratch_db()
    try:
        # Fresh DB -> upgrade head
        await _run_alembic("upgrade", "head")
        assert await _version() == "0002"

        tables = await _table_names()
        missing = set(_EXPECTED_TABLES) - tables
        assert not missing, f"missing tables after upgrade: {missing}"

        # Unique indexes the mobile auth models rely on
        assert "ix_mobile_devices_device_id" in await _index_names("mobile_devices")
        assert "ix_pairing_sessions_session_token" in await _index_names(
            "pairing_sessions"
        )
        assert "ix_mobile_sessions_session_token" in await _index_names(
            "mobile_sessions"
        )

        # Downgrade removes every app table again
        await _run_alembic("downgrade", "base")
        remaining = set(_EXPECTED_TABLES) & await _table_names()
        assert not remaining, f"tables left after downgrade base: {remaining}"

        # Re-upgrade from a clean slate works (idempotent fresh apply)
        await _run_alembic("upgrade", "head")
        assert await _version() == "0002"
        tables = await _table_names()
        missing = set(_EXPECTED_TABLES) - tables
        assert not missing, f"missing tables after re-upgrade: {missing}"
    finally:
        await _drop_scratch_db()
