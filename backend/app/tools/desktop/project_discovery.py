import os
import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("project_discovery")


@dataclass
class Project:
    name: str
    path: str
    type: str
    markers: List[str]
    last_modified: float
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


PROJECT_MARKERS = {
    "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "poetry.lock"],
    "node": ["package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": [".sln", ".csproj", ".fsproj", ".vbproj"],
    "ruby": ["Gemfile", "Rakefile"],
    "php": ["composer.json"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
    "terraform": [".tf"],
    "kubernetes": ["kustomization.yaml"],
}

COMMON_DEV_ROOTS = [
    "Projects", "Code", "Dev", "Development", "Source", "Repos",
    "Repositories", "github", "gitlab", "bitbucket", "workspace",
    "work", "src",
]

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", "bin", "obj", ".idea", ".vscode",
    ".DS_Store", "Thumbs.db", "*.egg-info", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".coverage", "htmlcov",
    "site-packages", "packages", "vendor", "bower_components",
}

_MAX_DEPTH = 3
_MAX_DIRS_PER_ROOT = 200

_PROJECT_CACHE: Dict[str, Project] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TIMESTAMP = 0.0
_CACHE_TTL = 300


def _get_search_roots() -> List[Path]:
    settings = get_settings()
    roots = []
    home = Path.home()
    
    for raw in settings.file_sandbox_roots.split(","):
        root = (home / raw.strip()).resolve()
        if root.exists():
            roots.append(root)
    
    if not roots:
        roots.append(home.resolve())
    
    return roots


def _is_excluded(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_DIRS or part.startswith('.'):
            return True
    return False


def _detect_project_type(project_path: Path) -> tuple[str, List[str]]:
    found_markers = []
    project_type = "unknown"
    
    for ptype, markers in PROJECT_MARKERS.items():
        for marker in markers:
            if (project_path / marker).exists():
                found_markers.append(marker)
                if project_type == "unknown":
                    project_type = ptype
    
    if (project_path / ".git").exists():
        found_markers.append(".git")
        if project_type == "unknown":
            project_type = "git"
    
    return project_type, found_markers


def _extract_project_name(path: Path) -> str:
    name = path.name
    if name in COMMON_DEV_ROOTS or name.lower() in EXCLUDE_DIRS:
        try:
            parent = path.parent
            if parent.name not in COMMON_DEV_ROOTS:
                name = parent.name
        except Exception:
            pass
    return name


def _scan_for_projects(root: Path) -> List[Project]:
    """Fast scan - only checks immediate children of root, no deep recursion."""
    projects = []
    dirs_scanned = 0
    
    try:
        items = list(root.iterdir())
    except (PermissionError, OSError):
        return projects
    
    for item in items:
        if dirs_scanned >= _MAX_DIRS_PER_ROOT:
            break
        if not item.is_dir() or _is_excluded(item):
            continue
        
        dirs_scanned += 1
        
        # Check if this directory itself is a project
        ptype, markers = _detect_project_type(item)
        if markers:
            name = _extract_project_name(item)
            try:
                stat = item.stat()
                projects.append(Project(
                    name=name,
                    path=str(item),
                    type=ptype,
                    markers=markers,
                    last_modified=stat.st_mtime,
                    description=f"{ptype.title()} project with {', '.join(markers[:3])}"
                ))
            except OSError:
                pass
            continue
        
        # Check immediate subdirectories (depth 2)
        try:
            for subitem in item.iterdir():
                if dirs_scanned >= _MAX_DIRS_PER_ROOT:
                    break
                if not subitem.is_dir() or _is_excluded(subitem):
                    continue
                
                dirs_scanned += 1
                ptype, markers = _detect_project_type(subitem)
                if markers:
                    name = _extract_project_name(subitem)
                    try:
                        stat = subitem.stat()
                        projects.append(Project(
                            name=name,
                            path=str(subitem),
                            type=ptype,
                            markers=markers,
                            last_modified=stat.st_mtime,
                            description=f"{ptype.title()} project with {', '.join(markers[:3])}"
                        ))
                    except OSError:
                        pass
        except (PermissionError, OSError):
            continue
    
    return projects


def discover_projects(force_refresh: bool = False) -> Dict[str, Project]:
    global _CACHE_TIMESTAMP, _PROJECT_CACHE
    with _CACHE_LOCK:
        if not force_refresh and _PROJECT_CACHE and (time.time() - _CACHE_TIMESTAMP) < _CACHE_TTL:
            return _PROJECT_CACHE
        
        logger.info("Discovering projects...")
        all_projects = {}
        
        for root in _get_search_roots():
            try:
                projects = _scan_for_projects(root)
                for proj in projects:
                    key = proj.name.lower()
                    if key not in all_projects or proj.last_modified > all_projects[key].last_modified:
                        all_projects[key] = proj
            except Exception as exc:
                logger.warning("Error scanning root %s: %s", root, exc)
        
        _PROJECT_CACHE = all_projects
        _CACHE_TIMESTAMP = time.time()
        logger.info("Discovered %d projects", len(all_projects))
        return all_projects


def find_project(query: str) -> Optional[Project]:
    projects = discover_projects()
    query_lower = query.lower().strip()
    
    # Exact match
    for name, project in projects.items():
        if query_lower == name:
            return project
    
    # Partial match
    for name, project in projects.items():
        if query_lower in name or name in query_lower:
            return project
    
    # Match by marker
    for name, project in projects.items():
        if any(query_lower in marker.lower() for marker in project.markers):
            return project
    
    return None


def list_projects() -> List[Project]:
    projects = discover_projects()
    return sorted(projects.values(), key=lambda p: p.last_modified, reverse=True)


def invalidate_cache() -> None:
    global _CACHE_TIMESTAMP, _PROJECT_CACHE
    with _CACHE_LOCK:
        _PROJECT_CACHE = {}
        _CACHE_TIMESTAMP = 0.0


def get_project_summary() -> dict:
    projects = list_projects()
    by_type = {}
    for p in projects:
        by_type[p.type] = by_type.get(p.type, 0) + 1
    return {
        "total": len(projects),
        "by_type": by_type,
        "projects": [p.to_dict() for p in projects[:50]]
    }