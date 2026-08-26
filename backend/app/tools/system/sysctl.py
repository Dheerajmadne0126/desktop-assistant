import datetime
import os
import platform

import psutil

from app.tools.base import ToolResult, tool


@tool(
    name="get_system_time",
    description="Returns the current date and time on this computer.",
)
def get_system_time() -> ToolResult:
    now = datetime.datetime.now()
    return ToolResult(success=True, message=now.strftime("%A, %d %B %Y, %I:%M %p"))


@tool(
    name="system_info",
    description="Returns CPU, RAM, disk and battery-style health info for this PC.",
)
def system_info() -> ToolResult:
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.expanduser("~")[:3] or "/")
    msg = (
        f"CPU {cpu:.0f}%, RAM {ram.percent:.0f}% "
        f"({ram.used / 1024**3:.1f}/{ram.total / 1024**3:.1f} GB), "
        f"Disk {disk.percent:.0f}% used ({disk.free / 1024**3:.0f} GB free). "
        f"System: {platform.system()} {platform.release()}."
    )
    return ToolResult(success=True, message=msg, data={"cpu": cpu, "ram": ram.percent})


@tool(
    name="take_screenshot",
    description="Captures the screen and saves it to a file. Returns the file path.",
)
def take_screenshot() -> ToolResult:
    import tempfile

    import pyautogui

    path = os.path.join(tempfile.gettempdir(), f"jarvis_screen_{int(datetime.datetime.now().timestamp())}.png")
    pyautogui.screenshot(path)
    return ToolResult(success=True, message=f"Screenshot saved to {path}", data={"path": path})


@tool(
    name="lock_workstation",
    description="Locks the Windows workstation immediately.",
)
def lock_workstation() -> ToolResult:
    import ctypes

    ctypes.windll.user32.LockWorkStation()
    return ToolResult(success=True, message="Workstation locked.")
