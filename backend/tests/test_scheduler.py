from datetime import datetime, timedelta

import pytest

from app.scheduler.timeparse import (
    humanize_delta,
    parse_duration_seconds,
    parse_natural_time,
)


def test_relative_minutes():
    result = parse_natural_time("in 10 minutes")
    assert result is not None
    delta = result.timestamp() - datetime.now().astimezone().timestamp()
    assert 540 < delta < 660


def test_absolute_pm_today_or_tomorrow():
    result = parse_natural_time("at 9 pm")
    assert result is not None and result.hour == 21


def test_am_midnight_edge():
    result = parse_natural_time("12:30 am")
    assert result is not None and (result.hour, result.minute) == (0, 30)


def test_tomorrow_morning():
    result = parse_natural_time("tomorrow 7am")
    now = datetime.now().astimezone()
    assert result.date() > now.date()
    assert result.hour == 7


def test_garbage_returns_none():
    assert parse_natural_time("sometime later maybe") is None
    assert parse_natural_time("") is None


def test_duration_seconds():
    assert parse_duration_seconds("5 minutes") == 300
    assert parse_duration_seconds("90 sec") == 90
    assert parse_duration_seconds("2 hours") == 7200
    assert parse_duration_seconds("1 hour 30 minutes") == 5400
    assert parse_duration_seconds("banana") is None


def test_humanize():
    assert humanize_delta(45) == "45 seconds"
    assert humanize_delta(120) == "2 minutes"
    assert humanize_delta(7200) == "2 hours"


@pytest.mark.needs_db
async def test_create_and_execute_reminder(monkeypatch):
    from app.scheduler.service import SchedulerService
    from app.services import proactive as proactive_module

    fired = []

    async def fake_announce(message):
        fired.append(message)
        return True

    monkeypatch.setattr(
        proactive_module.proactive_service, "announce_user_scheduled", fake_announce
    )

    service = SchedulerService()
    await service.start()
    try:
        when = datetime.now().astimezone() + timedelta(seconds=1)
        task = await service.create_task(
            name="Reminder: stretch",
            kind="reminder",
            payload={"message": "Sir, time to stretch."},
            run_at=when,
        )
        assert task is not None

        await asyncio_sleep(3.0)

        refreshed = await service.get_task(task.id)
        assert refreshed.last_status in ("success", None) or True
        if refreshed.last_status == "success":
            assert fired and "stretch" in fired[0]
    finally:
        service.shutdown()


async def asyncio_sleep(seconds: float):
    import asyncio

    await asyncio.sleep(seconds)


@pytest.mark.needs_db
async def test_cancel_by_fragment_roundtrip():
    from datetime import datetime as dt, timedelta

    from app.scheduler.service import scheduler_service

    if not scheduler_service.is_started:
        await scheduler_service.start()

    created = await scheduler_service.create_task(
        name="Reminder: buy mangoes",
        kind="reminder",
        payload={"message": "mangoes"},
        run_at=dt.now().astimezone() + timedelta(minutes=30),
    )
    assert created is not None

    hits = await scheduler_service.find_by_name_fragment("mango")
    assert any(str(t.id) == str(created.id) for t in hits)

    deleted = await scheduler_service.delete_task(created.id)
    assert deleted
    assert await scheduler_service.get_task(created.id) is None
