import inspect
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ValidationError, create_model

from app.core.logging import get_logger

logger = get_logger("tools")


class Permission(str, Enum):
    SAFE = "SAFE"
    CONFIRM = "CONFIRM"
    BLOCKED = "BLOCKED"


@dataclass
class ToolResult:
    success: bool
    message: str
    data: Any = None


class ConfirmationRequired(Exception):
    def __init__(self, description: str, spoken_code: str):
        self.description = description
        self.spoken_code = spoken_code
        super().__init__(f"CONFIRMATION_REQUIRED: {description}")


def build_model_from_signature(func: Callable, name: str) -> type[BaseModel]:
    sig = inspect.signature(func)
    fields = {}
    for param_name, param in sig.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        annotation = param.annotation if param.annotation is not inspect.Parameter.empty else str
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (annotation, default)
    return create_model(f"{name}Args", **fields)


@dataclass
class Tool:
    name: str
    description: str
    func: Callable
    permission: Permission = Permission.SAFE
    confirm_verb: str = ""
    args_model: type[BaseModel] | None = field(default=None, init=False)

    def __post_init__(self):
        self.args_model = build_model_from_signature(self.func, self.name)

    @property
    def parameters_schema(self) -> dict:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def validate_args(self, args: dict) -> dict:
        try:
            validated = self.args_model(**(args or {}))
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
            )
            raise ValueError(f"Invalid arguments for '{self.name}' -> {errors}") from exc
        return validated.model_dump(exclude_none=True)

    async def run_validated(self, args: dict) -> ToolResult:
        started = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(self.func):
                raw = self.func(**args)
                import asyncio

                raw = await asyncio.wait_for(raw, timeout=120)
            else:
                import asyncio

                raw = await asyncio.to_thread(self.func, **args)
            result = _coerce_result(raw)
        except ConfirmationRequired:
            raise
        except Exception as exc:
            logger.warning("Tool '%s' failed: %s", self.name, exc)
            return ToolResult(success=False, message=f"Tool failed: {exc}")
        result.message = str(result.message)[:4000]
        logger.info(
            "Tool '%s' executed in %.0fms success=%s",
            self.name,
            (time.perf_counter() - started) * 1000,
            result.success,
        )
        return result


def tool(
    name: str,
    description: str,
    permission: Permission = Permission.SAFE,
    confirm_verb: str = "",
) -> Callable[[Callable], Tool]:
    def decorator(func: Callable) -> Tool:
        return Tool(
            name=name,
            description=description,
            func=func,
            permission=Permission(permission),
            confirm_verb=confirm_verb or description[:60],
        )

    return decorator


def _coerce_result(raw: Any) -> ToolResult:
    if isinstance(raw, ToolResult):
        return raw
    if isinstance(raw, tuple) and len(raw) == 2 and isinstance(raw[1], bool):
        return ToolResult(success=raw[1], message=str(raw[0]))
    if isinstance(raw, bool):
        return ToolResult(success=raw, message="Done." if raw else "Failed.")
    if isinstance(raw, dict):
        ok = bool(raw.get("success", True))
        msg = raw.get("message") or raw.get("error") or "Done."
        return ToolResult(success=ok, message=str(msg), data=raw)
    return ToolResult(success=True, message=str(raw))
