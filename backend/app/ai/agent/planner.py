import json
import uuid

from sqlalchemy import update as sa_update

from app.ai.llm.provider import get_llm
from app.ai.text_utils import clean_llm_text
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import database
from app.models.core import TaskRun
from app.tools.base import ToolResult
from app.tools.registry import registry

logger = get_logger("planner")


def _extract_json(content: str):
    content = clean_llm_text(content).strip()
    if content.startswith("```"):
        content = content.strip("`").strip()
        if content.lower().startswith("json"):
            content = content[4:].strip()
    return json.loads(content)


class Planner:
    async def create_plan(self, goal: str, catalog: str, history: list[dict]) -> list[dict]:
        settings = get_settings()
        prompt = (
            "You are the planning module of JARVIS, a desktop assistant.\n"
            f"Goal: {goal}\n\n"
            f"Available tools:\n{catalog}\n\n"
            "Break the goal into a SHORT sequence of concrete tool calls "
            f"(max {settings.agent_max_steps}). Use a tool only when needed. If no tool is "
            "needed at all, return an empty steps array.\n"
            "Respond with ONLY JSON: "
            '{"steps": [{"description": "...", "tool": "tool_name", "args": {...}}]}'
        )
        response = await get_llm(temperature=0).ainvoke(prompt)
        try:
            data = _extract_json(response.content)
            steps = data.get("steps", [])
        except Exception as exc:
            logger.warning("Plan parse failed: %s", exc)
            return []

        valid = []
        for step in steps[: settings.agent_max_steps]:
            tool_name = step.get("tool")
            tool = registry.get(tool_name)
            if tool is None or tool.permission.value == "BLOCKED":
                continue
            valid.append(
                {
                    "description": step.get("description", ""),
                    "tool": tool_name,
                    "args": step.get("args", {}),
                }
            )
        return valid


planner = Planner()


async def _adjust_next_step_args(goal: str, observations: list[str], next_step: dict) -> dict:
    """Lets step N+1 use results from steps 1..N. One cheap LLM call between steps."""
    if not observations:
        return next_step.get("args", {})
    prompt = (
        "You are coordinating a task for JARVIS.\n"
        f"Overall goal: {goal}\n"
        "Results so far:\n" + "\n".join(observations[-3:]) + "\n\n"
        f"Next planned step: {json.dumps(next_step)}\n\n"
        "Adjust ONLY the 'args' of this next step using the real results above "
        "(e.g. use an actual URL/name found in the results). Keep it valid JSON.\n"
        'Reply ONLY JSON: {"args": {...}}'
    )
    try:
        response = await get_fast_llm().ainvoke(prompt)
        content = clean_llm_text(response.content)
        if content.startswith("```"):
            content = content.strip("`").strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
        data = json.loads(content)
        adjusted = data.get("args")
        if isinstance(adjusted, dict):
            return adjusted
    except Exception as exc:
        logger.debug("Arg adjustment skipped: %s", exc)
    return next_step.get("args", {})


async def execute_agentic_goal(goal: str, conversation_id=None, history=None) -> dict:
    """Plan -> execute -> observe loop with hard limits. Returns {'reply', 'status'}."""
    from langchain_core.messages import HumanMessage, SystemMessage

    settings = get_settings()
    catalog = registry.catalog_for_llm()

    run_id = uuid.uuid4()
    async with database.session() as session:
        session.add(
            TaskRun(id=run_id, goal=goal, max_steps=settings.agent_max_steps, status="running")
        )
        await session.commit()

    try:
        steps = await planner.create_plan(goal, catalog, history or [])
    except Exception:
        await _finish_run(run_id, status="failed", error="Planning failed.")
        return {"reply": "I couldn't work out a plan for that.", "status": "failed"}

    if not steps:
        await _finish_run(run_id, status="completed", result="no tools required")
        return None  # caller falls back to conversational answer

    observations = []
    for index, step in enumerate(steps):
        args = step.get("args", {})
        if index > 0:
            args = await _adjust_next_step_args(goal, observations, step)
        result: ToolResult = await registry.execute(
            step["tool"],
            args,
            triggered_by="agent",
            conversation_id=conversation_id,
        )
        observations.append(f"{index + 1}. {step['description']}: {result.message}")
        if not result.success:
            if "CONFIRMATION_REQUIRED:" in result.message:
                code = result.message.split(":")[1]
                desc = result.message.split(":", 2)[2]
                await _finish_run(run_id, status="awaiting_confirmation", plan={"steps": steps})
                return {
                    "reply": (
                        f"I need your approval before I continue: {desc} "
                        f"Say yes or give me code {code}."
                    ),
                    "status": "awaiting_confirmation",
                }
            await _finish_run(run_id, status="failed", error=result.message, done=index + 1)
            break

    await _update_progress(run_id, len(observations))

    summary_prompt_messages = [
        SystemMessage(
            content=(
                "Summarize for the user what was accomplished in one or two short spoken "
                "sentences. Be honest about any failure. No markdown."
            )
        ),
        HumanMessage(content=f"Goal: {goal}\nResults:\n" + "\n".join(observations)),
    ]
    try:
        summary = clean_llm_text(
            (await get_llm().ainvoke(summary_prompt_messages)).content
        )
        status = "completed"
    except Exception:
        summary = "; ".join(o.split(": ", 1)[-1] for o in observations)[:400]
        status = "completed"

    await _finish_run(run_id, status=status, result=summary, plan={"steps": steps})
    return {"reply": summary, "status": status}


async def _update_progress(run_id, steps_done: int) -> None:
    try:
        async with database.session() as session:
            await session.execute(
                sa_update(TaskRun).where(TaskRun.id == run_id).values(steps_done=steps_done)
            )
            await session.commit()
    except Exception as exc:
        logger.warning("TaskRun progress update failed: %s", exc)


async def _finish_run(run_id, status: str, result: str | None = None,
                      error: str | None = None, plan=None, done: int | None = None) -> None:
    values = {"status": status}
    if result is not None:
        values["result"] = result[:3900]
    if error is not None:
        values["error"] = error[:900]
    if plan is not None:
        values["plan"] = plan
    if done is not None:
        values["steps_done"] = done
    try:
        async with database.session() as session:
            await session.execute(sa_update(TaskRun).where(TaskRun.id == run_id).values(**values))
            await session.commit()
    except Exception as exc:
        logger.warning("TaskRun finish failed: %s", exc)
