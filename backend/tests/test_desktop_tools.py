import shutil
from pathlib import Path

import pytest

from app.tools.desktop.power import control_volume
from app.tools.filesystem.files import (
    move_file,
    read_file,
    rename_file,
    write_file,
)
from app.tools.registry import registry


@pytest.fixture(autouse=True)
def _ensure_registry():
    from app.tools import register_all_tools

    register_all_tools()


@pytest.fixture(scope="module")
def sandbox_tmp():
    base = Path.home() / "Documents" / "_jarvis_t5"
    src = base / "src"
    dst = base / "dst"
    src.mkdir(parents=True, exist_ok=True)
    dst.mkdir(parents=True, exist_ok=True)

    report = base / "report.txt"
    report.write_text("quarterly numbers", encoding="utf-8")

    yield {"base": base, "src": src, "dst": dst, "report": report}

    shutil.rmtree(base, ignore_errors=True)


def test_write_outside_sandbox_rejected(sandbox_tmp):
    result = write_file.func("C:\\Windows\\evil.txt", content="nope")
    assert not result.success
    assert "outside the allowed folders" in result.message


def test_write_and_read_inside_sandbox(sandbox_tmp):
    target = sandbox_tmp["base"] / "notes" / "hello.txt"
    written = write_file.func(str(target), content="hello world")
    assert written.success
    read = read_file.func(str(target))
    assert read.success and "hello world" in read.message


def test_rename_rejects_invalid_characters(sandbox_tmp):
    result = rename_file.func(str(sandbox_tmp["report"]), new_name="bad|name.txt")
    assert not result.success
    assert "invalid characters" in result.message


def test_rename_refuses_overwrite(sandbox_tmp):
    clash = sandbox_tmp["base"] / "clash.txt"
    clash.write_text("existing", encoding="utf-8")
    result = rename_file.func(str(clash), new_name="report.txt")
    assert not result.success
    assert "already exists" in result.message


def test_rename_success(sandbox_tmp):
    original = sandbox_tmp["base"] / "rename_me.txt"
    original.write_text("x", encoding="utf-8")
    result = rename_file.func(str(original), new_name="renamed_ok.txt")
    assert result.success
    assert (sandbox_tmp["base"] / "renamed_ok.txt").exists()
    assert not original.exists()


@pytest.mark.needs_db
async def test_move_file_requires_confirmation(sandbox_tmp):
    victim = sandbox_tmp["src"] / "move_me.txt"
    victim.write_text("data", encoding="utf-8")

    result = await registry.execute(
        "move_file",
        {
            "filepath": str(victim),
            "destination_dir": str(sandbox_tmp["dst"]),
        },
        triggered_by="test",
    )
    assert not result.success
    assert "CONFIRMATION_REQUIRED:" in result.message
    assert victim.exists()


def test_control_volume_rejects_bad_action():
    result = control_volume.func(action="explode", steps=2)
    assert not result.success
    assert "Unsupported volume action" in result.message


def test_power_tools_are_confirmation_gated():
    from app.tools.base import Permission

    for name in ("shutdown_pc", "restart_pc"):
        tool = registry.get(name) or next(
            (t for t in __import__("app.tools", fromlist=["_ALL"])._ALL if t.name == name),
            None,
        )
        assert tool is not None, f"{name} missing"
        assert tool.permission == Permission.CONFIRM


def test_abort_shutdown_is_safe_action():
    from app.tools.base import Permission

    tool = registry.get("abort_shutdown")
    assert tool is not None
    assert tool.permission == Permission.SAFE
