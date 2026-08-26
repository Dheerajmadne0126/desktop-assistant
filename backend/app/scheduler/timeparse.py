import re
from datetime import datetime, timedelta

_TIME_12H = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", re.I)
_TIME_24H = re.compile(r"^(\d{1,2}):(\d{2})$")
_RELATIVE = re.compile(
    r"^in\s+(\d+)\s*(second|seconds|sec|minute|minutes|min|mins|hour|hours|hr|hrs)s?$", re.I
)


def _combine(day: datetime, hour: int, minute: int) -> datetime:
    candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate


def parse_natural_time(text: str) -> datetime | None:
    """Parses common spoken times into a timezone-aware datetime (local time).

    Supports: 'in 5 minutes', 'at 9 pm', '9:25 am', 'tomorrow 7am',
    'tomorrow at 19:45', '23:10'. Returns None when unparseable.
    """
    cleaned = text.strip().lower()
    now = datetime.now().astimezone()

    relative = _RELATIVE.match(cleaned)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2).lower()
        seconds = {"sec": 1, "second": 1, "seconds": 1, "min": 60, "mins": 60,
                   "minute": 60, "minutes": 60, "hr": 3600, "hour": 3600,
                   "hours": 3600}.get(unit, 0)
        if not seconds or amount <= 0 or amount > 100000:
            return None
        return now + timedelta(seconds=amount * seconds)

    day_offset = 0
    remainder = cleaned
    tomorrow = re.match(r"^tomorrow,?\s*(?:at)?\s*(.*)$", remainder)
    if tomorrow:
        day_offset = 1
        remainder = tomorrow.group(1).strip()

    remainder = remainder.removeprefix("at ").strip()

    m12 = _TIME_12H.match(remainder)
    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2) or 0)
        meridiem = m12.group(3).lower()
        if hour < 1 or hour > 12:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        target_day = now + timedelta(days=day_offset)
        candidate = _combine(target_day, hour, minute)
        if day_offset == 0 and candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    m24 = _TIME_24H.match(remainder)
    if m24:
        hour, minute = int(m24.group(1)), int(m24.group(2))
        if hour > 23 or minute > 59:
            return None
        target_day = now + timedelta(days=day_offset)
        candidate = _combine(target_day, hour, minute)
        if day_offset == 0 and candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    bare_hour = re.match(r"^(\d{1,2})\s?(?:o'?clock)?$", remainder)
    if bare_hour:
        hour = int(bare_hour.group(1))
        if 1 <= hour <= 12:
            meridiem = "pm" if hour < 8 else "am"
            full_hour = hour + 12 if (meridiem == "pm" and hour != 12) else hour
            target_day = now + timedelta(days=day_offset)
            candidate = _combine(target_day, full_hour % 24, 0)
            if day_offset == 0 and candidate <= now:
                candidate += timedelta(days=1)
            return candidate

    return None


_UNIT_SECONDS = {
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": 60, "minutes": 60, "min": 60, "mins": 60,
    "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
}


def parse_duration_seconds(text: str) -> int | None:
    """Parses '5 minutes', '90 sec', '2 hours' into total seconds."""
    total = 0
    found = False
    for amount, unit in re.findall(r"(\d+)\s*([a-z]+)", text.lower()):
        factor = _UNIT_SECONDS.get(unit)
        if factor:
            total += int(amount) * factor
            found = True
    return total if found and total > 0 else None


def humanize_delta(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    if seconds < 3600:
        minutes = round(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = seconds / 3600
    if hours < 24:
        h = round(hours)
        return f"{h} hour{'s' if h != 1 else ''}"
    days = round(hours / 24)
    return f"{days} day{'s' if days != 1 else ''}"
