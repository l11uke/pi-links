"""Turns cron and systemd timer schedules into plain English.

Anything outside the common patterns is returned as written.
"""

from __future__ import annotations

import re

DAY_NAMES = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]
DAY_INDEX = {name: i for i, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}


def clock(hour: int, minute: int) -> str:
    if hour == 0 and minute == 0:
        return "midnight"
    if hour == 12 and minute == 0:
        return "noon"
    suffix = "am" if hour < 12 else "pm"
    twelve = hour % 12 or 12
    return f"{twelve}{suffix}" if minute == 0 else f"{twelve}:{minute:02d}{suffix}"


def ordinal(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return f"{day}th"
    return f"{day}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th') }"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _days(spec: str) -> list[int] | None:
    """Parse a day-of-week field: names or numbers, lists and ranges."""
    result: list[int] = []
    for part in spec.split(","):
        bounds = part.split("-") if "-" in part else part.split("..")
        values = []
        for bound in bounds:
            bound = bound.strip().lower()[:3]
            if bound.isdigit():
                values.append(int(bound) % 7)
            elif bound in DAY_INDEX:
                values.append(DAY_INDEX[bound])
            else:
                return None
        if len(values) == 1:
            result.append(values[0])
        elif len(values) == 2:
            start, end = values
            span = range(start, end + 1) if start <= end else [*range(start, 7), *range(0, end + 1)]
            result.extend(span)
        else:
            return None
    return sorted(set(result))


def _day_phrase(days: list[int]) -> str:
    if days == [1, 2, 3, 4, 5]:
        return "Weekdays"
    if days == [0, 6]:
        return "Weekends"
    return _join([DAY_NAMES[d] for d in days])


def _numbers(spec: str) -> list[int] | None:
    if not re.fullmatch(r"\d+(,\d+)*", spec):
        return None
    return [int(v) for v in spec.split(",")]


def _times(hours: list[int], minute: int) -> str:
    return _join([clock(h, minute) for h in hours])


def _describe(minute: str, hour: str, dom: str, dow: str) -> str | None:
    """Shared logic for cron fields and the time part of OnCalendar."""
    step_min = re.fullmatch(r"(?:\*|0)/(\d+)", minute)
    if step_min and hour == "*" and dom == "*" and dow == "*":
        return f"Every {step_min.group(1)} minutes"
    if re.fullmatch(r"\d+", minute) and hour == "*" and dom == "*" and dow == "*":
        return "Hourly"
    step_hour = re.fullmatch(r"(?:\*|0)/(\d+)", hour)
    if step_hour and re.fullmatch(r"\d+", minute) and dom == "*" and dow == "*":
        return f"Every {step_hour.group(1)} hours"

    hours = _numbers(hour)
    minutes = _numbers(minute)
    if not hours or not minutes or len(minutes) != 1:
        return None
    at = _times(hours, minutes[0])

    if dom == "*" and dow == "*":
        return f"Daily {at}"
    if dom == "*":
        days = _days(dow)
        return f"{_day_phrase(days)} {at}" if days else None
    if dow == "*":
        dates = _numbers(dom)
        if dates:
            return f"{_join([ordinal(d) for d in dates])} of the month, {at}"
    return None


CRON_MACROS = {
    "@reboot": "At startup",
    "@hourly": "Hourly",
    "@daily": "Daily midnight",
    "@midnight": "Daily midnight",
    "@weekly": "Sundays midnight",
    "@monthly": "1st of the month, midnight",
    "@yearly": "1 January, midnight",
    "@annually": "1 January, midnight",
}


def humanize_cron(expression: str) -> str:
    expression = expression.strip()
    if expression.startswith("@"):
        return CRON_MACROS.get(expression.lower(), expression)
    fields = expression.split()
    if len(fields) != 5 or fields[3] != "*":
        return expression
    minute, hour, dom, _, dow = fields
    return _describe(minute, hour, dom, dow) or expression


CALENDAR_SHORTHANDS = {
    "minutely": "Every minute",
    "hourly": "Hourly",
    "daily": "Daily midnight",
    "weekly": "Mondays midnight",
    "monthly": "1st of the month, midnight",
    "yearly": "1 January, midnight",
    "annually": "1 January, midnight",
}


def humanize_calendar(expression: str) -> str:
    """Translate a systemd OnCalendar expression."""
    original = expression.strip()
    parts = original.split()
    if parts and "/" in parts[-1] and not parts[-1][0].isdigit() and parts[-1][0] != "*":
        parts = parts[:-1]  # trailing time zone, such as Australia/Brisbane
    if parts and parts[-1].upper() == "UTC":
        parts = parts[:-1]
    if len(parts) == 1 and parts[0].lower() in CALENDAR_SHORTHANDS:
        return CALENDAR_SHORTHANDS[parts[0].lower()]

    dow = "*"
    if parts and re.fullmatch(r"[A-Za-z][A-Za-z,.\-]*", parts[0]):
        dow = parts.pop(0).replace("..", "-")
    if len(parts) == 1 and ":" in parts[0]:
        parts = ["*-*-*", parts[0]]
    if len(parts) != 2:
        return original

    date, time = parts
    date_match = re.fullmatch(r"\*-\*-(\*|\d+(?:,\d+)*)", date)
    time_match = re.fullmatch(r"([^:]+):([^:]+)(?::[^:]+)?", time)
    if not date_match or not time_match:
        return original
    dom = date_match.group(1)
    if dom != "*":
        dom = ",".join(str(int(d)) for d in dom.split(","))
    hour = _strip_zeros(time_match.group(1))
    minute = _strip_zeros(time_match.group(2))
    return _describe(minute, hour, dom, dow) or original


def _strip_zeros(field: str) -> str:
    return re.sub(r"\b0+(\d)", r"\1", field)


def humanize_monotonic(field: str, value: str) -> str:
    """Translate OnUnitActiveSec style settings, values like 1d or 15min."""
    match = re.fullmatch(r"(\d+)\s*(us|ms|s|sec|min|m|h|hr|d|w)?(?:\s*\d+\w*)*", value)
    if not match:
        return f"{field}={value}"
    amount = int(match.group(1))
    unit = {"s": "second", "sec": "second", "min": "minute", "m": "minute", "h": "hour",
            "hr": "hour", "d": "day", "w": "week"}.get(match.group(2) or "s", "second")
    every = f"{amount} {unit}{'s' if amount != 1 else ''}"
    if field.startswith("OnBoot") or field.startswith("OnStartup"):
        return f"{every} after startup"
    return f"Every {every}" if amount != 1 else f"Every {unit}"
