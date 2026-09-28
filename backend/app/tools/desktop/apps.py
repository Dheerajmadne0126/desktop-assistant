import os
import subprocess
import time

import psutil

from app.tools.base import ToolResult, tool
from app.tools.desktop.app_discovery import (
    find_processes,
    get_window_fragment,
    invalidate_cache,
    resolve_executable,
)


@tool(
    name="open_application",
    description=(
        "Opens a desktop application by name (e.g. chrome, notepad, calculator, vscode, "
        "explorer, terminal, spotify, discord, steam, slack). Desktop apps only - not websites. "
        "Discovers applications dynamically from Start Menu, PATH, and common install locations."
    ),
)
def open_application(app_name: str) -> ToolResult:
    target = resolve_executable(app_name)
    if target is None:
        return ToolResult(success=False, message=f"I don't know an application called '{app_name}'.")

    try:
        if target.endswith(".exe"):
            os.startfile(target)
        else:
            subprocess.Popen([target], shell=False)
        return ToolResult(success=True, message=f"Opened {app_name}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not open {app_name}: {exc}")


@tool(
    name="close_application",
    description="Closes a running desktop application by name (e.g. chrome, notepad).",
)
def close_application(app_name: str) -> ToolResult:
    procs = find_processes(app_name)
    closed = 0
    for proc in procs:
        try:
            proc.terminate()
            closed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if closed:
        return ToolResult(
            success=True,
            message=f"Closed {app_name} ({closed} process{'es' if closed > 1 else ''}).",
        )
    return ToolResult(success=False, message=f"No running process found for {app_name}.")


@tool(
    name="focus_application",
    description=(
        "Brings an already-running application's window to the front (e.g. focus chrome). "
        "Fails honestly if the app is not running."
    ),
)
def focus_application(app_name: str) -> ToolResult:
    key = app_name.lower().strip()
    fragment = get_window_fragment(key)

    try:
        import pygetwindow as gw

        windows = [
            w
            for w in gw.getAllWindows()
            if fragment.lower() in (w.title or "").lower() and not (w.isMinimized and False)
        ]
        if not windows:
            return ToolResult(
                success=False,
                message=f"No visible window matching '{app_name}' is running right now.",
            )
        window = windows[0]
        try:
            if window.isMinimized:
                window.restore()
        except Exception:
            pass
        window.activate()
        return ToolResult(success=True, message=f"Brought {app_name} to the front.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not focus {app_name}: {exc}")


@tool(
    name="restart_application",
    description="Closes and reopens a desktop application (e.g. restart chrome to fix it).",
)
def restart_application(app_name: str) -> ToolResult:
    close_result = close_application.func(app_name)
    if not close_result.success:
        return ToolResult(
            success=False,
            message=f"Cannot restart {app_name}: it does not appear to be running.",
        )

    time.sleep(1.0)
    open_result = open_application.func(app_name)
    if open_result.success:
        return ToolResult(success=True, message=f"Restarted {app_name}.")
    return ToolResult(
        success=False,
        message=f"Closed {app_name} but failed to reopen it: {open_result.message}",
    )


@tool(
    name="list_applications",
    description="Lists all discoverable applications on the system.",
)
def list_applications() -> ToolResult:
    from app.tools.desktop.app_discovery import get_app_cache

    cache = get_app_cache()
    apps = sorted(set(cache.keys()))
    return ToolResult(
        success=True,
        message=f"Found {len(apps)} applications:\n" + "\n".join(f"- {a}" for a in apps),
        data={"applications": apps},
    )


@tool(
    name="refresh_application_cache",
    description="Forces a refresh of the application discovery cache.",
)
def refresh_application_cache() -> ToolResult:
    invalidate_cache()
    from app.tools.desktop.app_discovery import get_app_cache

    cache = get_app_cache()
    return ToolResult(
        success=True,
        message=f"Application cache refreshed. {len(cache)} applications discovered.",
        data={"count": len(cache)},
    )