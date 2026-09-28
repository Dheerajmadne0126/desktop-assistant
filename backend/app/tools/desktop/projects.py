import os
import subprocess
import asyncio

from app.tools.base import ToolResult, tool
from app.tools.desktop.project_discovery import (
    find_project,
    list_projects,
    invalidate_cache,
    get_project_summary,
)
from app.tools.desktop.app_discovery import resolve_executable


@tool(
    name="find_project",
    description=(
        "Finds a project by name. Searches configured directories for projects "
        "with markers like package.json, pyproject.toml, Cargo.toml, .git, etc. "
        "Returns the project path and type."
    ),
)
def find_project_tool(name: str) -> ToolResult:
    project = find_project(name)
    if project is None:
        return ToolResult(
            success=False,
            message=f"Project '{name}' not found. Try 'list_projects' to see available projects.",
        )
    return ToolResult(
        success=True,
        message=f"Found {project.type} project '{project.name}' at {project.path}",
        data=project.to_dict(),
    )


@tool(
    name="list_projects",
    description="Lists all discovered projects with their types and paths.",
)
def list_projects_tool() -> ToolResult:
    projects = list_projects()
    if not projects:
        return ToolResult(
            success=True,
            message="No projects found. Check your configured sandbox directories.",
        )
    
    lines = []
    for p in projects:
        lines.append(f"- {p.name} ({p.type}): {p.path}")
    
    return ToolResult(
        success=True,
        message=f"Found {len(projects)} projects:\n" + "\n".join(lines),
        data={"projects": [p.to_dict() for p in projects]},
    )


@tool(
    name="open_project",
    description=(
        "Opens a project in the specified IDE or editor. "
        "Supported IDEs: vscode, vscodium, cursor, windsurf, intellij, pycharm, "
        "webstorm, rider, clion, goland, datagrip, phpstorm, rubymine, "
        "android-studio, sublime, vim, neovim, vscode-insiders."
        "If no IDE specified, uses VS Code by default."
    ),
)
def open_project(project_name: str, ide: str = "vscode") -> ToolResult:
    project = find_project(project_name)
    if project is None:
        return ToolResult(
            success=False,
            message=f"Project '{project_name}' not found. Use 'list_projects' to see available projects.",
        )
    
    ide_lower = ide.lower().strip()
    ide_commands = {
        "vscode": "code",
        "vscodium": "codium",
        "cursor": "cursor",
        "windsurf": "windsurf",
        "intellij": "idea",
        "pycharm": "pycharm",
        "webstorm": "webstorm",
        "rider": "rider",
        "clion": "clion",
        "goland": "goland",
        "datagrip": "datagrip",
        "phpstorm": "phpstorm",
        "rubymine": "rubymine",
        "android-studio": "studio",
        "sublime": "subl",
        "vim": "vim",
        "neovim": "nvim",
        "vscode-insiders": "code-insiders",
    }
    
    cmd = ide_commands.get(ide_lower, ide_lower)
    target = resolve_executable(cmd)
    
    if target is None:
        return ToolResult(
            success=False,
            message=f"IDE '{ide}' not found. Available: {', '.join(sorted(ide_commands.keys()))}",
        )
    
    try:
        if target.endswith(".exe"):
            os.startfile(target, "", project.path)
        else:
            subprocess.Popen([target, project.path], shell=False, cwd=project.path)
        return ToolResult(
            success=True,
            message=f"Opened project '{project.name}' in {ide} at {project.path}",
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            message=f"Could not open project in {ide}: {exc}",
        )


@tool(
    name="open_project_terminal",
    description=(
        "Opens a terminal (Windows Terminal, cmd, or PowerShell) at the project directory. "
        "Useful for running commands in the project context."
    ),
)
def open_project_terminal(project_name: str, terminal: str = "wt") -> ToolResult:
    project = find_project(project_name)
    if project is None:
        return ToolResult(
            success=False,
            message=f"Project '{project_name}' not found.",
        )
    
    terminal_lower = terminal.lower().strip()
    terminal_commands = {
        "wt": "wt.exe",
        "terminal": "wt.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "pwsh": "pwsh.exe",
    }
    
    cmd = terminal_commands.get(terminal_lower, terminal_lower)
    target = resolve_executable(cmd)
    
    # If not found via known commands, try the original input
    if target is None:
        target = resolve_executable(terminal)
    
    if target is None:
        return ToolResult(
            success=False,
            message=f"Terminal '{terminal}' not found or not in PATH. Tried: {cmd}. Available shortcuts: {', '.join(sorted(terminal_commands.keys()))}",
        )
    
    try:
        if "wt.exe" in target or "wt" in cmd:
            subprocess.Popen([target, "-d", project.path], shell=False)
        elif "cmd.exe" in target:
            subprocess.Popen([target, "/k", "cd", project.path], shell=False)
        elif "powershell" in target or "pwsh" in target:
            subprocess.Popen([target, "-NoExit", "-Command", f"cd '{project.path}'"], shell=False)
        else:
            subprocess.Popen([target], shell=False, cwd=project.path)
        return ToolResult(
            success=True,
            message=f"Opened {terminal} at {project.path}",
        )
    except Exception as exc:
        return ToolResult(
            success=False,
            message=f"Could not open terminal: {exc}",
        )


@tool(
    name="run_project_command",
    description=(
        "Runs a command in the project directory. Only allows safe, pre-approved commands "
        "like: npm run, npm start, npm test, npm build, python -m, python manage.py, "
        "cargo run, cargo build, cargo test, go run, go build, go test, make, "
        "docker compose, docker-compose, ./gradlew, ./mvnw, dotnet run, dotnet build."
        "Use for starting dev servers, running tests, building, etc."
    ),
)
def run_project_command(project_name: str, command: str) -> ToolResult:
    project = find_project(project_name)
    if project is None:
        return ToolResult(
            success=False,
            message=f"Project '{project_name}' not found.",
        )
    
    allowed_prefixes = [
        "npm run", "npm start", "npm test", "npm build", "npm install", "npm ci",
        "yarn run", "yarn start", "yarn test", "yarn build",
        "pnpm run", "pnpm start", "pnpm test", "pnpm build",
        "python -m", "python -c", "python manage.py", "python -m pytest",
        "python -m unittest", "pip install", "pipenv run", "poetry run",
        "cargo run", "cargo build", "cargo test", "cargo check", "cargo clippy",
        "go run", "go build", "go test", "go vet", "go mod tidy",
        "make", "make test", "make build",
        "docker compose", "docker-compose",
        "./gradlew", "./gradlew test", "./gradlew build",
        "./mvnw", "./mvnw test", "./mvnw package",
        "dotnet run", "dotnet build", "dotnet test", "dotnet restore",
        "flutter run", "flutter build", "flutter test",
        "swift build", "swift test",
        "bun run", "bun test", "bun build",
        "deno run", "deno test", "deno task",
    ]
    
    cmd_lower = command.lower().strip()
    if not any(cmd_lower.startswith(prefix.lower()) for prefix in allowed_prefixes):
        return ToolResult(
            success=False,
            message=f"Command not in allowed list. Allowed prefixes: {', '.join(sorted(set(p.split()[0] for p in allowed_prefixes)))}",
        )
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=project.path,
        )
        
        output = result.stdout[:5000] if result.stdout else ""
        error = result.stderr[:2000] if result.stderr else ""
        
        if result.returncode == 0:
            msg = f"Command succeeded in {project.name}"
            if output:
                msg += f":\n{output}"
        else:
            msg = f"Command failed in {project.name} (exit {result.returncode})"
            if error:
                msg += f":\n{error}"
            elif output:
                msg += f":\n{output}"
        
        return ToolResult(
            success=result.returncode == 0,
            message=msg,
            data={"exit_code": result.returncode, "stdout": output, "stderr": error},
        )
    except subprocess.TimeoutExpired:
        return ToolResult(success=False, message="Command timed out after 120 seconds")
    except Exception as exc:
        return ToolResult(success=False, message=f"Execution failed: {exc}")


@tool(
    name="get_project_summary",
    description="Returns a summary of all discovered projects grouped by type.",
)
def get_project_summary_tool() -> ToolResult:
    summary = get_project_summary()
    lines = [f"Total projects: {summary['total']}"]
    for ptype, count in sorted(summary['by_type'].items()):
        lines.append(f"  {ptype}: {count}")
    return ToolResult(
        success=True,
        message="\n".join(lines),
        data=summary,
    )


@tool(
    name="refresh_project_cache",
    description="Forces a refresh of the project discovery cache.",
)
def refresh_project_cache() -> ToolResult:
    invalidate_cache()
    summary = get_project_summary()
    return ToolResult(
        success=True,
        message=f"Project cache refreshed. {summary['total']} projects discovered.",
        data=summary,
    )