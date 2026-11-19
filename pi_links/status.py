"""Reads the result file a scheduled job writes after each run.

Format, JSON: {"checked_at": "<ISO 8601 time with offset>", "ok": true,
"summary": "optional short text"}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

MAX_FILE_BYTES = 16_384


@dataclass(frozen=True)
class Status:
    state: str  # passed, failed, overdue, never, unreadable
    checked_at: datetime | None = None
    summary: str = ""


def read_status(path: str | Path, max_age_hours: int, now: datetime | None = None) -> Status:
    now = now or datetime.now().astimezone()
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return Status("never")
    except OSError:
        return Status("unreadable")
    if len(raw) > MAX_FILE_BYTES:
        return Status("unreadable")

    try:
        data = json.loads(raw)
        checked_at = datetime.fromisoformat(data["checked_at"])
        ok = data["ok"]
        summary = data.get("summary", "")
        if checked_at.tzinfo is None or not isinstance(ok, bool) or not isinstance(summary, str):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        return Status("unreadable")

    summary = summary.strip()[:200]
    if not ok:
        return Status("failed", checked_at, summary)
    if now - checked_at > timedelta(hours=max_age_hours):
        return Status("overdue", checked_at, summary)
    return Status("passed", checked_at, summary)


def format_time(moment: datetime) -> str:
    local = moment.astimezone()
    hour = local.strftime("%I").lstrip("0")
    minute = local.strftime("%M")
    clock = f"{hour}{local.strftime('%p').lower()}" if minute == "00" else f"{hour}:{minute}{local.strftime('%p').lower()}"
    return f"{local.day} {local.strftime('%b')}, {clock}"
