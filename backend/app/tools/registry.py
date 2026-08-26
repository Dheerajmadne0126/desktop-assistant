import json
import time
from typing import Any

from app.core.logging import get_logger
from app.db.session import database
from app.tools.base import ConfirmationRequired, Permission, Tool, ToolResult

logger = get_logger("registry")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug("Registered tool '%s' (%s)", tool.name, tool.permission.value)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def callable_names(self) -> list[str]:
        return [
            t.name for t in self._tools.values() if t.permission != Permission.BLOCKED
        ]

    def catalog_for_llm(self) -> str:
        lines = []
        for t in self._tools.values():
            if t.permission == Permission.BLOCKED:
                continue
            params = json.dumps(t.parameters_schema.get("properties", {}))
            confirm = " [needs user confirmation]" if t.permission == Permission.CONFIRM else ""
            lines.append(f"- {t.name}{confirm}: {t.description} | args: {params}")
        return "\n".join(lines)

    def openai_tool_specs(self) -> list[dict]:
        specs = []
        for t in self._tools.values():
            if t.permission == Permission.BLOCKED:
                continue
            schema = t.parameters_schema
            props = {
                k: {kk: vv for kk, vv in v.items() if kk != "title"}
                for k, v in schema.get("properties", {}).items()
            }
            slim = {"type": "object", "properties": props}
            if schema.get("required"):
                slim["required"] = schema["required"]
            short_desc = t.description.split(". ")[0].strip()
            if len(short_desc) > 110:
                short_desc = short_desc[:107] + "..."
            confirm_note = " Needs user confirmation." if t.permission == Permission.CONFIRM else ""
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": short_desc + confirm_note,
                        "parameters": slim,
                    },
                }
            )
        return specs

    async def execute(
        self,
        name: str,
        args: dict | None,
        triggered_by: str = "agent",
        conversation_id=None,
        skip_permission: bool = False,
    ) -> ToolResult:
        tool = self._tools.get(name)
        started = time.perf_counter()
        if tool is None or tool.permission == Permission.BLOCKED:
            result = ToolResult(success=False, message=f"Unknown or blocked tool: {name}")
            await self._log(tool_name=name, args=args or {}, result=result, duration=0,
                            triggered_by=triggered_by, conversation_id=conversation_id)
            return result

        try:
            validated = tool.validate_args(args or {})
        except ValueError as exc:
            result = ToolResult(success=False, message=str(exc))
            await self._log(
                tool_name=name,
                args=args or {},
                result=result,
                duration=0,
                triggered_by=triggered_by,
                conversation_id=conversation_id,
            )
            return result

        if tool.permission == Permission.CONFIRM and not skip_permission:
            from app.services.confirmation import confirmation_service

            pending = await confirmation_service.create_pending(
                tool=tool,
                args=validated,
                conversation_id=conversation_id,
            )
            result = ToolResult(
                success=False,
                message=(
                    f"CONFIRMATION_REQUIRED:{pending.spoken_code}:{pending.description}"
                ),
            )
            await self._log(
                tool_name=name,
                args=validated,
                result=result,
                duration=0,
                triggered_by=triggered_by,
                conversation_id=conversation_id,
            )
            return result

        result = await tool.run_validated(validated)
        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._log(name, validated, result, duration_ms, triggered_by, conversation_id)
        return result

    async def _log(
        self,
        tool_name: str,
        args: dict,
        result: ToolResult,
        duration: int,
        triggered_by: str,
        conversation_id,
        validated_args: dict | None = None,
    ) -> None:
        try:
            import uuid
            from datetime import datetime, timezone

            from sqlalchemy import insert

            from app.models.core import ToolExecution

            payload = validated_args if validated_args is not None else args
            safe_args = {k: v for k, v in (payload or {}).items()}
            values = {
                "id": uuid.uuid4(),
                "tool_name": tool_name,
                "args": safe_args,
                "result": result.message[:3900],
                "success": result.success,
                "error": None if result.success else result.message[:900],
                "duration_ms": duration,
                "triggered_by": triggered_by,
                "conversation_id": conversation_id,
                "created_at": datetime.now(timezone.utc),
            }
            async with database.session() as session:
                await session.execute(insert(ToolExecution).values(**values))
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to persist tool execution log: %s", exc)


registry = ToolRegistry()
