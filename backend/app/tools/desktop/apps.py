import os
import subprocess

import psutil

from app.tools.base import ToolResult, tool

APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "files": "explorer.exe",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "powershell.exe",
    "paint": "mspaint.exe",
    "spotify": "spotify.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
}

PROCESS_NAME_OVERRIDES = {
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "code": "Code.exe",
}

WINDOW_TITLE_FRAGMENTS = {
    "notepad": "Notepad",
    "calculator": "Calculator",
    "chrome": "Chrome",
    "edge": "Edge",
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "spotify": "Spotify",
    "word": "Word",
    "excel": "Excel",
    "powerpoint": "PowerPoint",
    "terminal": "Terminal",
    "cmd": "Command Prompt",
    "powershell": "PowerShell",
}


def resolve_executable(app_name: str) -> str | None:
    key = app_name.lower().strip()
    target = APP_MAP.get(key)
    if target:
        return target
    candidate = f"{key}.exe"
    try:
        subprocess.run(
            ["where", candidate], capture_output=True, check=True, timeout=5
        )
        return candidate
    except Exception:
        return None


def _find_processes(app_name: str):
    key = app_name.lower().strip()
    exe = PROCESS_NAME_OVERRIDES.get(key, APP_MAP.get(key, key))
    if not exe.endswith(".exe"):
        exe = f"{exe}.exe"
    matches = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name == exe.lower():
                matches.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return matches


@tool(
    name="open_application",
    description=(
        "Opens a desktop application by name (e.g. chrome, notepad, calculator, vscode, "
        "explorer, terminal, spotify). Desktop apps only - not websites."
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
    procs = _find_processes(app_name)
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
    fragment = WINDOW_TITLE_FRAGMENTS.get(key, app_name)

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

    import time

    time.sleep(1.0)
    open_result = open_application.func(app_name)
    if open_result.success:
        return ToolResult(success=True, message=f"Restarted {app_name}.")
    return ToolResult(
        success=False,
        message=f"Closed {app_name} but failed to reopen it: {open_result.message}",
    )
