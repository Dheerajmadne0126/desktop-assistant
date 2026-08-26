import re
from datetime import datetime, timedelta

from app.scheduler.timeparse import humanize_delta, parse_duration_seconds, parse_natural_time
from app.tools.base import ToolResult, tool


def _fmt_when(when: datetime) -> str:
    return when.strftime("%I:%M %p").lstrip("0")


@tool(
    name="set_reminder",
    description=(
        "Sets a one-shot reminder. time examples: 'in 10 minutes', 'at 9 pm', "
        "'tomorrow 7:30 am'. Fails with a hint if the time can't be parsed."
    ),
)
async def set_reminder(when: str, message: str) -> ToolResult:
    from app.scheduler.service import scheduler_service

    parsed = parse_natural_time(when)
    if parsed is None:
        return ToolResult(
            success=False,
            message=(
                "I couldn't understand that time. Try 'in 15 minutes', 'at 5 pm', "
                "or 'tomorrow 8 am'."
            ),
        )

    delta = int(parsed.timestamp() - datetime.now().astimezone().timestamp())
    try:
        task = await scheduler_service.create_task(
            name=f"Reminder: {message[:60]}",
            kind="reminder",
            payload={"message": message},
            run_at=parsed,
        )
    except ValueError as exc:
        return ToolResult(success=False, message=str(exc))

    if task is None:
        return ToolResult(success=False, message="The scheduler isn't running right now.")
    return ToolResult(
        success=True,
        message=(
            f"Reminder set for {_fmt_when(parsed)} "
            f"({humanize_delta(max(delta, 0))} from now): {message}"
        ),
        data={"task_id": str(task.id)},
    )


@tool(
    name="set_alarm",
    description=(
        "Sets an alarm spoken at the given time. Same formats as reminders "
        "('at 6 am', 'tomorrow 06:30'). Optional label."
    ),
)
async def set_alarm(when: str, label: str = "Alarm! Time to wake up.") -> ToolResult:
    from app.scheduler.service import scheduler_service

    parsed = parse_natural_time(when)
    if parsed is None:
        return ToolResult(
            success=False,
            message="Couldn't parse that alarm time. Try 'at 6 am' or 'tomorrow 06:30'.",
        )
    task = await scheduler_service.create_task(
        name=f"Alarm: {label[:50]}",
        kind="alarm",
        payload={"message": label},
        run_at=parsed,
    )
    if task is None:
        return ToolResult(success=False, message="The scheduler isn't running right now.")
    return ToolResult(success=True, message=f"Alarm set for {_fmt_when(parsed)}.", data={"task_id": str(task.id)})


@tool(
    name="set_timer",
    description=(
        "Starts a countdown timer. duration examples: '5 minutes', '90 sec', '2 hours'. "
        "Optional label for what it's for."
    ),
)
async def set_timer(duration_str: str, message: str = "Time's up!") -> ToolResult:
    from app.scheduler.service import scheduler_service

    seconds = parse_duration_seconds(duration_str)
    if seconds is None:
        return ToolResult(
            success=False,
            message="Couldn't parse the duration. Try '5 minutes' or '45 sec'.",
        )

    when = datetime.now().astimezone() + timedelta(seconds=seconds)
    task = await scheduler_service.create_task(
        name=f"Timer {duration_str}",
        kind="timer",
        payload={"message": message},
        run_at=when,
    )
    if task is None:
        return ToolResult(success=False, message="The scheduler isn't running right now.")
    return ToolResult(
        success=True,
        message=f"Timer running for {humanize_delta(seconds)}. I'll say: {message}",
        data={"task_id": str(task.id)},
    )


@tool(
    name="create_daily_routine",
    description=(
        "Creates a routine that runs EVERY DAY at a fixed 24-hour time (e.g. '08:30') "
        "and executes a prompt through JARVIS, like a morning briefing."
    ),
)
async def create_daily_routine(time_hhmm: str, prompt: str, speak_result: bool = True) -> ToolResult:
    from app.scheduler.service import scheduler_service

    m = re.match(r"^(\d{1,2}):(\d{2})$", time_hhmm.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ToolResult(success=False, message="Use 24-hour format like '08:30'.")
    cron = f"{int(m.group(2))} {int(m.group(1))} * * *"

    task = await scheduler_service.create_task(
        name=f"Daily {time_hhmm}: {prompt[:40]}",
        kind="routine",
        payload={"command": prompt, "message": prompt[:80], "speak_result": speak_result},
        cron=cron,
    )
    if task is None:
        return ToolResult(success=False, message="The scheduler isn't running right now.")
    return ToolResult(
        success=True,
        message=f"Daily routine created for {time_hhmm}: {prompt}",
        data={"task_id": str(task.id)},
    )


@tool(
    name="list_schedules",
    description="Lists all active reminders, alarms, timers and routines.",
)
async def list_schedules() -> ToolResult:
    from app.scheduler.service import scheduler_service

    tasks = await scheduler_service.list_tasks(enabled_only=True)
    if not tasks:
        return ToolResult(success=True, message="You have no active reminders or routines.")

    lines = []
    for t in tasks[:10]:
        if t.kind in ("reminder", "alarm", "timer") and t.run_at:
            local = t.run_at.astimezone() if t.run_at.tzinfo else t.run_at
            when = local.strftime("%a %I:%M %p").lstrip("0")
        elif t.cron:
            parts = t.cron.split()
            when = f"daily at {parts[1].zfill(2)}:{parts[0].zfill(2)}"
        elif t.interval_seconds:
            when = f"every {humanize_delta(t.interval_seconds)}"
        else:
            when = "?"
        lines.append(f"- {t.name} ({t.kind}) -> {when}")

    return ToolResult(success=True, message="Active schedules:\n" + "\n".join(lines))


@tool(
    name="cancel_schedule",
    description=(
        "Cancels a reminder/alarm/timer/routine by matching part of its name "
        "(e.g. name_fragment='stretch')."
    ),
)
async def cancel_schedule(name_fragment: str) -> ToolResult:
    from app.scheduler.service import scheduler_service

    hits = await scheduler_service.find_by_name_fragment(name_fragment)
    cancelled = 0
    for t in hits:
        if await scheduler_service.delete_task(t.id):
            cancelled += 1

    if cancelled:
        return ToolResult(success=True, message=f"Cancelled {cancelled} schedule(s).")
    return ToolResult(success=False, message=f"No schedule found matching '{name_fragment}'.")


