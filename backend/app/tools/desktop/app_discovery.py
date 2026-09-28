import os
import subprocess
import threading
import time
import winreg
from pathlib import Path
from typing import Dict, List, Optional, Set
from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger("app_discovery")

KNOWN_SYSTEM_APPS = {
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

_DISCOVERY_CACHE: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TIMESTAMP = 0.0
_CACHE_TTL = 300

COMMON_INSTALL_ROOTS = [
    Path(os.environ.get("ProgramFiles", "C:/Program Files")),
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")),
    Path(os.environ.get("LocalAppData", "")) / "Programs",
    Path(os.environ.get("AppData", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path(os.environ.get("ProgramData", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
]

PATH_DIRS = [
    Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p
]


def _scan_start_menu() -> Dict[str, str]:
    apps = {}
    try:
        ps_script = """
        $shell = New-Object -ComObject Shell.Application
        $folder = $shell.Namespace('shell:AppsFolder')
        $items = $folder.Items()
        foreach ($item in $items) {
            $name = $item.Name
            $path = $item.Path
            if ($path -and $path.EndsWith('.exe')) {
                Write-Output "$name|$path"
            }
        }
        """
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=15
        )
        for line in result.stdout.strip().splitlines():
            if "|" in line:
                name, path = line.split("|", 1)
                key = name.lower().strip()
                if key not in apps:
                    apps[key] = path
    except Exception as exc:
        logger.debug("Start Menu scan failed: %s", exc)
    return apps


def _scan_path_dirs() -> Dict[str, str]:
    apps = {}
    for path_dir in PATH_DIRS:
        try:
            if not path_dir.exists():
                continue
            for exe in path_dir.glob("*.exe"):
                key = exe.stem.lower()
                if key not in apps:
                    apps[key] = str(exe)
        except Exception:
            continue
    return apps


def _scan_common_roots() -> Dict[str, str]:
    apps = {}
    for root in COMMON_INSTALL_ROOTS:
        try:
            if not root.exists():
                continue
            for exe in root.rglob("*.exe"):
                try:
                    rel = exe.relative_to(root)
                    name_parts = rel.parts[:-1]
                    if name_parts:
                        key = name_parts[0].lower()
                    else:
                        key = exe.stem.lower()
                    if key not in apps:
                        apps[key] = str(exe)
                except Exception:
                    key = exe.stem.lower()
                    if key not in apps:
                        apps[key] = str(exe)
        except Exception:
            continue
    return apps


def _scan_registry_uninstall() -> Dict[str, str]:
    apps = {}
    try:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ):
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as sk:
                                    try:
                                        display_name = winreg.QueryValueEx(sk, "DisplayName")[0]
                                        install_location = winreg.QueryValueEx(sk, "InstallLocation")[0] if True else ""
                                    except OSError:
                                        continue
                                    if install_location:
                                        install_path = Path(install_location)
                                        for exe in install_path.glob("*.exe"):
                                            key_name = display_name.lower()
                                            if key_name not in apps:
                                                apps[key_name] = str(exe)
                                    try:
                                        uninstall_string = winreg.QueryValueEx(sk, "UninstallString")[0]
                                        if uninstall_string and ".exe" in uninstall_string.lower():
                                            exe_path = uninstall_string.strip('"')
                                            if Path(exe_path).exists():
                                                key_name = display_name.lower()
                                                if key_name not in apps:
                                                    apps[key_name] = exe_path
                                    except OSError:
                                        pass
                            except OSError:
                                continue
                except OSError:
                    continue
    except Exception as exc:
        logger.debug("Registry scan failed: %s", exc)
    return apps


def _discover_all_apps() -> Dict[str, str]:
    all_apps = {}
    all_apps.update(KNOWN_SYSTEM_APPS)
    all_apps.update(_scan_start_menu())
    all_apps.update(_scan_path_dirs())
    all_apps.update(_scan_common_roots())
    all_apps.update(_scan_registry_uninstall())
    return all_apps


def get_app_cache() -> Dict[str, str]:
    global _CACHE_TIMESTAMP, _DISCOVERY_CACHE
    with _CACHE_LOCK:
        if time.time() - _CACHE_TIMESTAMP > _CACHE_TTL or not _DISCOVERY_CACHE:
            logger.info("Discovering applications...")
            _DISCOVERY_CACHE = _discover_all_apps()
            _CACHE_TIMESTAMP = time.time()
            logger.info("Discovered %d applications", len(_DISCOVERY_CACHE))
        return _DISCOVERY_CACHE


def invalidate_cache() -> None:
    global _CACHE_TIMESTAMP, _DISCOVERY_CACHE
    with _CACHE_LOCK:
        _DISCOVERY_CACHE = {}
        _CACHE_TIMESTAMP = 0.0


def resolve_executable(app_name: str) -> Optional[str]:
    key = app_name.lower().strip()
    cache = get_app_cache()
    target = cache.get(key)
    if target:
        return target
    candidate = f"{key}.exe"
    try:
        subprocess.run(["where", candidate], capture_output=True, check=True, timeout=5)
        return candidate
    except Exception:
        return None


def find_processes(app_name: str) -> List:
    import psutil
    key = app_name.lower().strip()
    exe = PROCESS_NAME_OVERRIDES.get(key, KNOWN_SYSTEM_APPS.get(key, key))
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


def get_window_fragment(app_name: str) -> str:
    key = app_name.lower().strip()
    return WINDOW_TITLE_FRAGMENTS.get(key, app_name)