"""Reads the scan result and combines it with links.toml.

Everything the scan found is shown. Entries in links.toml change what was
found (matched by port for links and by `match` for tasks), hide it, or add
things the scan cannot see.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .config import Board, Link, Task

LINK_OVERRIDES = ("name", "group", "description", "path", "scheme")
TASK_OVERRIDES = ("name", "group", "schedule", "description", "status_file", "status_max_age_hours")
MAX_FILE_BYTES = 2_000_000


@dataclass(frozen=True)
class Discovery:
    scanned_at: datetime | None = None
    links: tuple[Link, ...] = ()
    tasks: tuple[Task, ...] = ()
    problem: str = ""


@dataclass(frozen=True)
class Merged:
    links: tuple[Link, ...]
    tasks: tuple[Task, ...]
    warnings: tuple[str, ...] = ()


def _text(value, limit=120) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def load_discovery(path: str | Path) -> Discovery:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return Discovery()
    except OSError as exc:
        return Discovery(problem=f"{path}: cannot read file: {exc.strerror}")
    try:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("file too large")
        data = json.loads(raw)
        scanned_at = datetime.fromisoformat(data["scanned_at"])
        if scanned_at.tzinfo is None:
            raise ValueError("scanned_at has no time zone")
    except (ValueError, KeyError, TypeError) as exc:
        return Discovery(problem=f"{path}: unreadable scan result ({exc}). Run the scan again.")

    links = []
    for item in data.get("links", []):
        if not isinstance(item, dict):
            continue
        port = item.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            continue
        path_value = _text(item.get("path")) or "/"
        if not path_value.startswith("/") or path_value.startswith("//") or " " in path_value:
            path_value = "/"
        links.append(Link(
            name=_text(item.get("name"), 60) or f"Port {port}",
            group=_text(item.get("group"), 60) or "Services",
            port=port,
            path=path_value,
            scheme="https" if item.get("scheme") == "https" else "http",
        ))

    tasks = []
    for item in data.get("tasks", []):
        if not isinstance(item, dict) or not _text(item.get("id"), 300):
            continue
        tasks.append(Task(
            name=_text(item.get("name"), 80) or _text(item.get("id"), 80),
            schedule=_text(item.get("schedule"), 80) or "Unknown schedule",
            group=_text(item.get("group"), 60) or "Other",
            match=_text(item.get("id"), 300),
        ))
    return Discovery(scanned_at=scanned_at, links=tuple(links), tasks=tuple(tasks))


def _apply(found, override, fields):
    changes = {name: getattr(override, name) for name in fields if name in override.fields}
    return replace(found, **changes)


def merge(manual: Board, found: Discovery) -> Merged:
    warnings = []

    link_overrides = {link.port: link for link in manual.links if link.port is not None}
    matched_ports = set()
    links = []
    for link in found.links:
        override = link_overrides.get(link.port)
        if override:
            matched_ports.add(link.port)
            if override.hide:
                continue
            link = _apply(link, override, LINK_OVERRIDES)
        links.append(link)
    for link in manual.links:
        if link.url:
            links.append(link)
        elif link.port not in matched_ports and not link.hide:
            links.append(link if link.name else replace(link, name=f"Port {link.port}"))

    task_overrides = {task.match: task for task in manual.tasks if task.match}
    matched_ids = set()
    tasks = []
    for task in found.tasks:
        override = task_overrides.get(task.match)
        if override:
            matched_ids.add(task.match)
            if override.hide:
                continue
            task = _apply(task, override, TASK_OVERRIDES)
        tasks.append(task)
    for task in manual.tasks:
        if task.match is None:
            tasks.append(task)
        elif task.match not in matched_ids and found.scanned_at is not None:
            warnings.append(f"task match {task.match!r} matches nothing in the last scan")

    return Merged(links=tuple(links), tasks=tuple(tasks), warnings=tuple(warnings))
