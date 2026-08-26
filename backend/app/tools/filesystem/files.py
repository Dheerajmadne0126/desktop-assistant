import fnmatch
import os
from pathlib import Path

from app.core.config import get_settings
from app.tools.base import ToolResult, tool

MAX_READ_CHARS = 15000


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


def _ensure_within_sandbox(path: str) -> Path:
    raw = os.path.expanduser(path)
    expanded = Path(raw)

    if expanded.is_absolute():
        candidates = [expanded.resolve()]
    else:
        # Bare relatives are spoken-intent ("Desktop\\x") -> always resolve
        # against the user's HOME first, never the server's working directory.
        candidates = [
            (Path.home() / raw).resolve(),
            (Path.home() / "Documents" / raw).resolve(),
        ]

    def within(child: Path, root: Path) -> bool:
        try:
            child.relative_to(root)
            return True
        except ValueError:
            return False

    for candidate in candidates:
        for root in _sandbox_roots():
            if within(candidate, root):
                return candidate

    raise ValueError(
        f"Path '{path}' is outside the allowed folders "
        f"({', '.join(r.name for r in _sandbox_roots())})."
    )


@tool(
    name="list_directory",
    description="Lists files and folders in a directory. Empty path lists the Downloads folder.",
)
def list_directory(dir_path: str = "") -> ToolResult:
    try:
        target = (
            _ensure_within_sandbox(str(Path.home() / "Downloads"))
            if not dir_path
            else _ensure_within_sandbox(dir_path)
        )
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.exists():
        return ToolResult(success=False, message=f"Directory not found: {dir_path}")

    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())[:200]
        dirs = [e.name + "/" for e in entries if e.is_dir()]
        files = [e.name for e in entries if not e.is_dir()]
        body = "\n".join(dirs + files) or "(empty)"
        return ToolResult(success=True, message=f"{target}:\n{body}")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not list directory: {exc}")


@tool(
    name="read_file",
    description="Reads a text file's content. Use for .txt, .py, .json, code, notes, etc.",
)
def read_file(filepath: str) -> ToolResult:
    try:
        target = _ensure_within_sandbox(filepath)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.is_file():
        return ToolResult(success=False, message=f"File not found: {filepath}")

    try:
        content = target.read_text(encoding="utf-8", errors="ignore")
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS] + "\n...[truncated]"
        return ToolResult(success=True, message=content or "(empty file)")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not read file: {exc}")


@tool(
    name="search_files",
    description=(
        "Searches your Desktop, Documents and Downloads for files whose names match a "
        "pattern. Supports wildcards like *.pdf or report*."
    ),
)
def search_files(pattern: str) -> ToolResult:
    matches = []
    for root in _sandbox_roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))]
            for filename in filenames:
                if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    matches.append(os.path.join(dirpath, filename))
                    if len(matches) >= 40:
                        break
            if len(matches) >= 40:
                break
        if len(matches) >= 40:
            break

    if not matches:
        return ToolResult(success=True, message=f"No files matching '{pattern}' found.")
    listing = "\n".join(matches[:20])
    more = f"\n...and {len(matches) - 20} more" if len(matches) > 20 else ""
    return ToolResult(success=True, message=f"Found {len(matches)}:\n{listing}{more}", data={"matches": matches})


@tool(
    name="write_file",
    description=(
        "Creates or overwrites a text file with given content inside Desktop/Documents/"
        "Downloads. Requires user confirmation."
    ),
    permission="CONFIRM",
    confirm_verb="create or modify a file",
)
def write_file(filepath: str, content: str) -> ToolResult:
    try:
        target = _ensure_within_sandbox(filepath)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult(success=True, message=f"Wrote {len(content)} characters to {target}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not write file: {exc}")


@tool(
    name="delete_file",
    description=(
        "Permanently deletes one file inside Desktop/Documents/Downloads after user "
        "confirmation. Refuses directories."
    ),
    permission="CONFIRM",
    confirm_verb="permanently delete a file",
)
def delete_file(filepath: str) -> ToolResult:
    try:
        target = _ensure_within_sandbox(filepath)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.exists():
        return ToolResult(success=False, message=f"File not found: {filepath}")
    if target.is_dir():
        return ToolResult(success=False, message="Refusing to delete a directory.")

    try:
        os.remove(target)
        return ToolResult(success=True, message=f"Deleted {target.name}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Delete failed: {exc}")


@tool(
    name="open_file",
    description=(
        "Opens a file with its default Windows application (e.g. a PDF in your PDF "
        "reader). Path must be inside Desktop/Documents/Downloads."
    ),
)
def open_file(filepath: str) -> ToolResult:
    try:
        target = _ensure_within_sandbox(filepath)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.exists():
        return ToolResult(success=False, message=f"File not found: {filepath}")

    try:
        os.startfile(str(target))
        return ToolResult(success=True, message=f"Opened {target.name}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Could not open {target.name}: {exc}")


@tool(
    name="rename_file",
    description=(
        "Renames a file inside Desktop/Documents/Downloads. Refuses to overwrite an "
        "existing file."
    ),
)
def rename_file(filepath: str, new_name: str) -> ToolResult:
    try:
        target = _ensure_within_sandbox(filepath)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not target.exists():
        return ToolResult(success=False, message=f"File not found: {filepath}")
    if any(ch in new_name for ch in '\\/:*?"<>|'):
        return ToolResult(success=False, message=f"'{new_name}' contains invalid characters.")

    destination = target.with_name(new_name)
    if destination.exists():
        return ToolResult(success=False, message=f"'{new_name}' already exists there.")

    try:
        target.rename(destination)
        return ToolResult(success=True, message=f"Renamed to {new_name}.")
    except Exception as exc:
        return ToolResult(success=False, message=f"Rename failed: {exc}")


@tool(
    name="move_file",
    description=(
        "Moves a file to another folder inside Desktop/Documents/Downloads. Requires "
        "user confirmation. Set overwrite=false to refuse overwriting."
    ),
    permission="CONFIRM",
    confirm_verb="move a file to a different folder",
)
def move_file(filepath: str, destination_dir: str, overwrite: bool = False) -> ToolResult:
    try:
        source = _ensure_within_sandbox(filepath)
        dest_dir = _ensure_within_sandbox(destination_dir)
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if not source.exists():
        return ToolResult(success=False, message=f"File not found: {filepath}")
    if not dest_dir.is_dir():
        return ToolResult(success=False, message=f"Destination folder not found: {destination_dir}")

    destination = dest_dir / source.name
    if destination.exists() and not overwrite:
        return ToolResult(
            success=False,
            message=f"'{source.name}' already exists in the destination folder.",
        )

    try:
        import shutil

        shutil.move(str(source), str(destination))
        return ToolResult(
            success=True, message=f"Moved {source.name} to {dest_dir.name}."
        )
    except Exception as exc:
        return ToolResult(success=False, message=f"Move failed: {exc}")
