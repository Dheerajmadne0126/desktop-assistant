import pytest

from app.tools.base import Permission, Tool, ToolResult
from app.tools.registry import ToolRegistry


def make_tool(name="dummy", permission=Permission.SAFE, func=None):
    if func is None:
        async def func(city: str, units: str = "metric") -> str:
            return f"Weather in {city} ({units})"
    return Tool(
        name=name,
        description="A dummy tool",
        func=func,
        permission=permission,
        confirm_verb="do a dummy thing",
    )


async def test_validates_and_runs():
    reg = ToolRegistry()
    reg.register(make_tool())
    result = await reg.execute("dummy", {"city": "Pune"}, skip_permission=True)
    assert result.success
    assert "Pune" in result.message


async def test_invalid_args_reported():
    reg = ToolRegistry()
    reg.register(make_tool())
    result = await reg.execute("dummy", {"wrong_arg": 1})
    assert not result.success
    assert "Invalid arguments" in result.message


async def test_unknown_tool():
    reg = ToolRegistry()
    result = await reg.execute("nope", {})
    assert not result.success


def test_duplicate_registration_rejected():
    reg = ToolRegistry()
    reg.register(make_tool(name="same"))
    with pytest.raises(ValueError):
        reg.register(make_tool(name="same"))


def test_schema_generated():
    tool = make_tool()
    schema = tool.parameters_schema
    assert "city" in schema["properties"]
    assert set(schema["required"]) == {"city"}


def test_blocked_excluded_from_catalog():
    reg = ToolRegistry()
    reg.register(make_tool(name="secret", permission=Permission.BLOCKED))
    assert "secret" not in reg.catalog_for_llm()


async def test_sync_tool_supported():
    def sync_tool(x: int) -> str:
        return f"value {x}"

    reg = ToolRegistry()
    reg.register(Tool(name="syncy", description="", func=sync_tool, confirm_verb="x"))
    result = await reg.execute("syncy", {"x": 7}, skip_permission=True)
    assert result.success and "7" in result.message
