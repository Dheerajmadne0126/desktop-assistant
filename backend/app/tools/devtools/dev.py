import os
import re
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.tools.base import ToolResult, tool

logger = get_logger("devtools")

_FORBIDDEN_CHARS = re.compile(r"[&|;`><]")

_ALLOWED_COMMANDS = [
    r"^git status(?: .*)?$",
    r"^git branch(?: -[a-z]+)?(?: .*)?$",
    r"^git log(?: -\d+)?(?: .*)?$",
    r"^git diff(?: .*)?$",
    r"^git show(?: .*)?$",
    r"^git remote -v$",
    r"^git add -A$|^git add \.$",
    r"^git commit -m \"[^\"]+\"$",
    r"^(?:node|npm|python|pip|git) (--version|-v)$",
    r"^npm (list|ls)( .*)?$",
    r"^pip (list|show)( .*)?$",
    r"^dir(?: /b)?$|^ls(?: -la)?$",
]

_SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "dist", "build", ".idea", ".vscode"}
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".exe", ".dll",
    ".mp3", ".mp4", ".wav", ".ttf", ".woff", ".woff2", ".pyc", ".class", ".jar",
}


def _sandbox_roots() -> list[Path]:
    settings = get_settings()
    home = Path.home()
    roots = []
    for raw in settings.file_sandbox_roots.split(","):
        root = (home / raw.strip()).resolve()
        if root.exists():
            roots.append(root)
    if not roots:
        roots.append(home.resolve())
    return roots


def _within_tree(child: Path, root: Path) -> bool:
    try:
        child.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_within_home(path: str) -> Path:
    candidate = Path(os.path.expanduser(path)).resolve()
    home = Path.home().resolve()
    try:
        candidate.relative_to(home)
        return candidate
    except ValueError:
        raise ValueError("Command working directory must be inside your user folder.")


@tool(
    name="run_dev_command",
    description=(
        "Runs a whitelisted read-only/safe development command: git status/branch/log/"
        "diff/show/remote/add/commit, version checks, pip list, npm list, dir. "
        "Anything else is refused. Provide cwd for the project folder."
    ),
)
def run_dev_command(command: str, cwd: str = "") -> ToolResult:
    command = command.strip()
    if not command or len(command) > 300:
        return ToolResult(success=False, message="Empty or oversized command.")

    if _FORBIDDEN_CHARS.search(command):
        return ToolResult(
            success=False,
            message="Refusing: shell operators like ; | & are not allowed.",
        )

    if not any(re.match(pattern, command, re.IGNORECASE) for pattern in _ALLOWED_COMMANDS):
        return ToolResult(
            success=False,
            message=(
                f"'{command}' is not on the safe-command allowlist "
                "(git read ops, versions, pip/npm list, dir)."
            ),
        )

    try:
        workdir = _ensure_within_home(cwd) if cwd else Path.home()
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))
    if not workdir.exists():
        return ToolResult(success=False, message=f"Folder not found: {cwd}")

    argv = ["powershell", "-NoProfile", "-Command", command]
    logger.info("Dev command '%s' in %s", command, workdir)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(workdir),
        )
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, message="Command timed out after 60 seconds.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Execution failed: {exc}")

    parts = [f"Exit code: {result.returncode}"]
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if stdout:
        parts.append("Output:\n" + stdout[:2000])
    if stderr:
        parts.append("Errors:\n" + stderr[:1000])
    return ToolResult(
        success=result.returncode == 0,
        message="\n".join(parts),
        data={"exit_code": result.returncode},
    )


@tool(
    name="search_in_files",
    description=(
        "Searches file CONTENTS (like grep) inside Desktop/Documents/Downloads or a given "
        "subfolder, skipping node_modules/.git etc. Returns matching file:line snippets."
    ),
)
def search_in_files(query: str, dir_path: str = "") -> ToolResult:
    if len(query) < 2:
        return ToolResult(success=False, message="Search text too short.")

    try:
        if dir_path:
            root = _ensure_within_home(dir_path)
            allowed = any(
                _within_tree(root, r) for r in _sandbox_roots()
            )
            if not allowed and root != Path.home():
                return ToolResult(
                    success=False,
                    message="Search folder must be inside Desktop/Documents/Downloads.",
                )
        else:
            roots = _sandbox_roots()
            return _search_roots(roots, query)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not root.exists():
        return ToolResult(success=False, message=f"Folder not found: {dir_path}")
    return _search_roots([root], query)


def _search_roots(roots, query: str) -> ToolResult:
    needle = query.lower()
    matches = []
    files_scanned = 0
    for base in roots:
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                d for d in dirnames
                if d.lower() not in _SKIP_DIRS and not d.startswith((".", "$"))
            ]
            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext in _BINARY_EXTS:
                    continue
                full = os.path.join(dirpath, filename)
                try:
                    if os.path.getsize(full) > 1_500_000:
                        continue
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        for lineno, line in enumerate(f, 1):
                            if needle in line.lower():
                                snippet = line.strip()[:140]
                                display = os.path.relpath(full, str(base))
                                matches.append(f"{display}:{lineno}: {snippet}")
                                if len(matches) >= 40:
                                    break
                        files_scanned += 1
                except Exception:
                    continue
                if len(matches) >= 40:
                    break
            if len(matches) >= 40:
                break
        if len(matches) >= 40:
            break

    if not matches:
        return ToolResult(
            success=True,
            message=f"No occurrences of '{query}' found ({files_scanned} files scanned).",
        )
    more = f"\n...and stopped at 40 matches." if len(matches) >= 40 else ""
    body = "\n".join(matches[:25])
    extra = f"\n(+{len(matches)-25} more)" if len(matches) > 25 else ""
    return ToolResult(success=True, message=f"{len(matches)} matches:\n{body}{extra}{more}")


@tool(
    name="open_project_in_vscode",
    description="Opens a project folder in VS Code. Folder must exist inside your user directory.",
)
def open_project_in_vscode(folder_path: str) -> ToolResult:
    try:
        target = _ensure_within_home(folder_path)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.is_dir():
        return ToolResult(success=False, message=f"Folder not found: {folder_path}")

    try:
        subprocess.Popen(["code", str(target)], shell=False)
        return ToolResult(success=True, message=f"Opened '{target.name}' in VS Code.")
    except FileNotFoundError:
        return ToolResult(success=False, message="VS Code ('code') is not installed or not on PATH.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not open VS Code: {exc}")
