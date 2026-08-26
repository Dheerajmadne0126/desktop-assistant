import uuid
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select, update

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import database
from app.models.schedule import ScheduledTask

logger = get_logger("scheduler")

_VALID_KINDS = {"reminder", "alarm", "timer", "routine", "briefing"}


class SchedulerService:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None
        self.is_started = False

    async def start(self) -> None:
        if self.is_started:
            return

        await self._recover_missed_tasks()

        self._scheduler = AsyncIOScheduler()
        self._scheduler.start()
        self.is_started = True

        tasks = await self.list_tasks(enabled_only=True)
        registered = 0
        for task in tasks:
            if await self.register_job(task):
                registered += 1
        logger.info("Scheduler started; %d/%d jobs registered.", registered, len(tasks))

    def shutdown(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
        self.is_started = False
        logger.info("Scheduler stopped.")

    async def _recover_missed_tasks(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 86400
        try:
            async with database.session() as session:
                rows = (
                    (
                        await session.execute(
                            select(ScheduledTask).where(
                                ScheduledTask.enabled == True,  # noqa: E712
                                ScheduledTask.kind.in_(["reminder", "alarm", "timer"]),
                                ScheduledTask.run_at != None,  # noqa: E711
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                missed = []
                for row in rows:
                    run_at_utc = row.run_at
                    if run_at_utc.tzinfo is None:
                        continue
                    ts = run_at_utc.timestamp()
                    if ts < now.timestamp():
                        if ts >= cutoff:
                            missed.append(row)
                        else:
                            row.enabled = False
                            row.last_status = "expired"
                for row in missed:
                    row.run_at = datetime.now(timezone.utc)
                    row.last_status = "missed_offline"
                await session.commit()
            if missed:
                logger.warning("Recovered %d task(s) missed while offline.", len(missed))
        except Exception as exc:
            logger.error("Task recovery failed: %s", exc)

    def _build_trigger(self, task: ScheduledTask):
        if task.run_at is not None:
            return DateTrigger(run_date=task.run_at)
        if task.cron:
            return CronTrigger.from_crontab(task.cron)
        if task.interval_seconds:
            return IntervalTrigger(seconds=task.interval_seconds)
        return None

    async def register_job(self, task: ScheduledTask) -> bool:
        if self._scheduler is None:
            return False
        trigger = self._build_trigger(task)
        if trigger is None:
            logger.warning("Task %s has no valid schedule; skipping.", task.id)
            return False
        self._scheduler.add_job(
            self._execute,
            trigger=trigger,
            id=str(task.id),
            args=[str(task.id)],
            replace_existing=True,
            name=task.name,
        )
        return True

    async def create_task(
        self,
        name: str,
        kind: str,
        payload: dict[str, Any],
        run_at=None,
        cron: str | None = None,
        interval_seconds: int | None = None,
    ) -> ScheduledTask | None:
        kind = kind.lower().strip()
        if kind not in _VALID_KINDS:
            raise ValueError(f"Unknown task kind '{kind}'")
        if run_at is None and not cron and not interval_seconds:
            raise ValueError("Provide one of run_at / cron / interval_seconds")

        if cron:
            try:
                CronTrigger.from_crontab(cron)
            except ValueError as exc:
                raise ValueError(f"Invalid cron expression: {exc}") from exc

        task_id = uuid.uuid4()
        row = ScheduledTask(
            id=task_id,
            name=name[:255],
            kind=kind,
            run_at=run_at,
            cron=cron,
            interval_seconds=interval_seconds,
            payload=payload or {},
            enabled=True,
        )
        async with database.session() as session:
            session.add(row)
            await session.commit()

        await self.register_job(row)
        logger.info("Created %s '%s' (%s)", kind, name, task_id)
        return row

    async def list_tasks(self, enabled_only: bool = False) -> list[ScheduledTask]:
        stmt = select(ScheduledTask).order_by(ScheduledTask.created_at.desc()).limit(100)
        if enabled_only:
            from sqlalchemy import Boolean as _B

            stmt = select(ScheduledTask).where(ScheduledTask.enabled == True).order_by(  # noqa: E712
                ScheduledTask.created_at.desc()
            ).limit(100)
        async with database.session() as session:
            return list((await session.execute(stmt)).scalars())

    async def get_task(self, task_id) -> ScheduledTask | None:
        async with database.session() as session:
            return await session.get(ScheduledTask, task_id)

    async def set_enabled(self, task_id, enabled: bool) -> bool:
        task = await self.get_task(task_id)
        if task is None:
            return False
        async with database.session() as session:
            await session.execute(
                update(ScheduledTask).where(ScheduledTask.id == task_id).values(enabled=enabled)
            )
            await session.commit()

        if enabled:
            await self.register_job(task)
        elif self._scheduler:
            try:
                self._scheduler.remove_job(str(task_id))
            except Exception:
                pass
        return True

    async def delete_task(self, task_id) -> bool:
        task = await self.get_task(task_id)
        if task is None:
            return False
        async with database.session() as session:
            await session.execute(delete(ScheduledTask).where(ScheduledTask.id == task_id))
            await session.commit()
        if self._scheduler:
            try:
                self._scheduler.remove_job(str(task_id))
            except Exception:
                pass
        logger.info("Deleted task %s", task_id)
        return True

    async def find_by_name_fragment(self, fragment: str) -> list[ScheduledTask]:
        fragment = fragment.strip().lower()
        tasks = await self.list_tasks()
        hits = [t for t in tasks if fragment in t.name.lower()]
        return hits

    async def _execute(self, task_id: str) -> None:
        from app.services.proactive import proactive_service

        started = datetime.now(timezone.utc)
        status = "success"
        error_text = None
        try:
            task = await self.get_task(uuid.UUID(task_id))
            if task is None or not task.enabled:
                return

            message = str(task.payload.get("message") or task.name)
            command = task.payload.get("command")

            if task.kind == "routine" and command:
                from app.ai.agent.supervisor import process_text

                await process_text(str(command), source="scheduled")
                if task.payload.get("speak_result", True):
                    await proactive_service.announce_user_scheduled(
                        f"That routine is done: {message}"
                    )
            else:
                await proactive_service.announce_user_scheduled(message)

            if task.kind in ("reminder", "alarm", "timer"):
                await self.set_enabled(task.id, False)
        except Exception as exc:
            status = "failed"
            error_text = str(exc)[:900]
            logger.error("Scheduled task %s failed: %s", task_id, exc)
        finally:
            try:
                async with database.session() as session:
                    await session.execute(
                        update(ScheduledTask)
                        .where(ScheduledTask.id == uuid.UUID(task_id))
                        .values(last_run_at=started, last_status=status, last_error=error_text)
                    )
                    await session.commit()
            except Exception as exc:
                logger.warning("Could not record execution log: %s", exc)


scheduler_service = SchedulerService()
