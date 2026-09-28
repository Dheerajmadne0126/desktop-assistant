import asyncio
import os

import pytest
from sqlalchemy.engine import make_url

from app.core.config import get_settings

TEST_DB = "jarvis_test"

# Never hardcode credentials in this file: the test database reuses the exact
# user/password/host from the project's real DATABASE_URL (backend/.env) and
# only swaps the database name to a dedicated test database.


def _base_url() -> str:
    get_settings.cache_clear()
    return get_settings().database_url


def _ensure_test_database() -> bool:
    try:
        import asyncpg

        base = make_url(_base_url())
        test_url = base.set(database=TEST_DB).render_as_string(hide_password=False)

        os.environ["DATABASE_URL"] = test_url
        os.environ["ENVIRONMENT"] = "test"
        os.environ["VOICE_ENABLED"] = "false"
        os.environ.pop("AI_API_KEY", None)
        os.environ["LOG_DIR"] = os.path.join(
            os.path.dirname(__file__), "..", ".test_logs"
        )

        async def _create():
            conn = await asyncpg.connect(
                host=base.host or "localhost",
                port=base.port or 5432,
                user=base.username,
                password=base.password,
                database="postgres",
            )
            try:
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB
                )
                if not exists:
                    await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
            finally:
                await conn.close()

        asyncio.run(_create())
        return True
    except Exception:
        return False


DB_AVAILABLE = _ensure_test_database()

if DB_AVAILABLE:
    get_settings.cache_clear()

    from app.db.base import Base
    from app.db.session import database
    import app.models  # noqa: F401

    database.init()

    async def _create_all():
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())


@pytest.fixture(autouse=True)
def _require_db(request):
    if request.node.get_closest_marker("needs_db") and not DB_AVAILABLE:
        pytest.skip("Postgres test DB not available")


@pytest.fixture(autouse=True)
async def _clean_tables():
    if not DB_AVAILABLE:
        yield
        return
    from sqlalchemy import text

    from app.db.session import database

    async with database.engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE conversations, messages, memories, preferences, "
                "scheduled_tasks, pending_confirmations, tool_executions, task_runs "
                "CASCADE"
            )
        )
    yield


@pytest.fixture
def fake_llm_factory():
    from types import SimpleNamespace

    class FakeResponse:
        def __init__(self, content):
            self.content = content

    class FakeLLM:
        def __init__(self, items):
            self._items = list(items)
            self.calls = []

        def bind_tools(self, specs, **kwargs):
            return self

        async def ainvoke(self, prompt, *args, **kwargs):
            self.calls.append(prompt if isinstance(prompt, str) else str(prompt))
            if not self._items:
                return FakeResponse("{}")
            item = self._items.pop(0)
            if isinstance(item, str):
                return FakeResponse(item)
            if isinstance(item, dict):
                return SimpleNamespace(
                    content=item.get("content", ""),
                    tool_calls=item.get("tool_calls", []),
                )
            return item

        def invoke(self, prompt, *args, **kwargs):
            import asyncio

            return asyncio.get_event_loop().run_until_complete(self.ainvoke(prompt))

        async def astream(self, prompt, *args, **kwargs):
            self.calls.append(prompt if isinstance(prompt, str) else str(prompt))
            if not self._items:
                return
            item = self._items.pop(0)
            if isinstance(item, str):
                yield SimpleNamespace(content=item, tool_calls=[])
            elif isinstance(item, dict):
                yield SimpleNamespace(
                    content=item.get("content", ""),
                    tool_calls=item.get("tool_calls", []),
                )
            else:
                yield item

    def factory(*items):
        return FakeLLM(list(items))

    return factory
