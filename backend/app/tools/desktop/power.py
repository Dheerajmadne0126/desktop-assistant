import subprocess

from app.core.logging import get_logger
from app.tools.base import ToolResult, tool

logger = get_logger("power")


@tool(
    name="shutdown_pc",
    description=(
        "Shuts down the entire computer after a short delay. Requires explicit user "
        "confirmation."
    ),
    permission="CONFIRM",
    confirm_verb="shut down the whole computer",
)
def shutdown_pc(delay_seconds: int = 15) -> ToolResult:
    delay = max(5, min(int(delay_seconds), 300))
    try:
        result = subprocess.run(
            ["shutdown", "/s", "/t", str(delay)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ToolResult(success=False, message="Windows refused the shutdown command.")
        logger.warning("Shutdown scheduled in %ds", delay)
        return ToolResult(
            success=True,
            message=f"Shutting down in {delay} seconds. Run 'shutdown /a' to abort.",
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Shutdown failed: {exc}")


@tool(
    name="restart_pc",
    description="Restarts the entire computer. Requires explicit user confirmation.",
    permission="CONFIRM",
    confirm_verb="restart the whole computer",
)
def restart_pc(delay_seconds: int = 15) -> ToolResult:
    delay = max(5, min(int(delay_seconds), 300))
    try:
        result = subprocess.run(
            ["shutdown", "/r", "/t", str(delay)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ToolResult(success=False, message="Windows refused the restart command.")
        logger.warning("Restart scheduled in %ds", delay)
        return ToolResult(success=True, message=f"Restarting in {delay} seconds.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Restart failed: {exc}")


@tool(
    name="abort_shutdown",
    description="Cancels a scheduled shutdown or restart of the computer.",
)
def abort_shutdown() -> ToolResult:
    try:
        result = subprocess.run(["shutdown", "/a"], capture_output=True, timeout=10)
        if result.returncode != 0:
            return ToolResult(success=False, message="No pending shutdown to cancel.")
        return ToolResult(success=True, message="Scheduled shutdown cancelled.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not abort: {exc}")


@tool(
    name="control_volume",
    description=(
        "Controls speaker volume using media keys. Actions: 'up', 'down', 'mute'. "
        "Steps controls how many notches (1-20)."
    ),
)
def control_volume(action: str, steps: int = 3) -> ToolResult:
    action = action.lower().strip()
    if action not in ("up", "down", "mute"):
        return ToolResult(success=False, message=f"Unsupported volume action '{action}'.")
    steps = max(1, min(int(steps), 20))

    import pyautogui

    key_map = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}
    key = key_map[action]

    count = 1 if action == "mute" else steps
    for _ in range(count):
        pyautogui.press(key)
        pyautogui.sleep(0.03)

    label = {"up": f"Volume up {count} notch(es)", "down": f"Volume down {count} notch(es)", "mute": "Toggled mute"}[action]
    return ToolResult(success=True, message=f"{label}.")


@tool(
    name="set_brightness",
    description=(
        "Sets screen brightness percentage (0-100). Only works on laptops with a "
        "supported display driver."
    ),
)
def set_brightness(percent: int) -> ToolResult:
    percent = max(0, min(int(percent), 100))
    script = (
        "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
        f".WmiSetBrightness(1,{percent})"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0 or result.stderr.strip():
            return ToolResult(
                success=False,
                message="Brightness control is not supported on this display.",
            )
        return ToolResult(success=True, message=f"Brightness set to {percent}%.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Brightness change failed: {exc}")
