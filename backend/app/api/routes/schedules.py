import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.scheduler.service import scheduler_service

router = APIRouter(prefix="/schedules", tags=["schedules"])


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(pattern="^(reminder|alarm|timer|routine|briefing)$")
    payload: dict[str, Any] = {}
    run_at: Optional[datetime] = None
    cron: Optional[str] = None
    interval_seconds: Optional[int] = None


class SchedulePatch(BaseModel):
    enabled: Optional[bool] = None


def _serialize(task) -> dict:
    return {
        "id": str(task.id),
        "name": task.name,
        "kind": task.kind,
        "enabled": task.enabled,
        "run_at": task.run_at.isoformat() if task.run_at else None,
        "cron": task.cron,
        "interval_seconds": task.interval_seconds,
        "payload": task.payload,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "last_status": task.last_status,
        "last_error": task.last_error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


@router.get("")
async def list_schedules() -> dict:
    tasks = await scheduler_service.list_tasks()
    return {"tasks": [_serialize(t) for t in tasks], "scheduler_running": scheduler_service.is_started}


@router.post("")
async def create_schedule(payload: ScheduleCreate) -> dict:
    if payload.run_at is None and payload.cron is None and not payload.interval_seconds:
        raise HTTPException(400, "Provide run_at, cron or interval_seconds")
    try:
        task = await scheduler_service.create_task(
            name=payload.name,
            kind=payload.kind,
            payload=payload.payload,
            run_at=payload.run_at,
            cron=payload.cron,
            interval_seconds=payload.interval_seconds,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if task is None:
        raise HTTPException(503, "Scheduler is not running")
    return _serialize(task)


@router.patch("/{task_id}")
async def patch_schedule(task_id: uuid.UUID, patch: SchedulePatch) -> dict:
    if patch.enabled is None:
        raise HTTPException(400, "Nothing to update; provide 'enabled'")
    ok = await scheduler_service.set_enabled(task_id, patch.enabled)
    if not ok:
        raise HTTPException(404, "Task not found")
    task = await scheduler_service.get_task(task_id)
    return _serialize(task)


@router.delete("/{task_id}")
async def delete_schedule(task_id: uuid.UUID) -> dict:
    ok = await scheduler_service.delete_task(task_id)
    if not ok:
        raise HTTPException(404, "Task not found")
    return {"deleted": True}
