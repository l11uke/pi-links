"""The only module that reads configuration.

Settings come from code defaults, then settings.env, then the process
environment. Links come from a TOML file. Every problem found is reported at
once, naming the key and the file it belongs in.
"""

from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

DEFAULT_SETTINGS_FILE = "/etc/pi-links/settings.env"

DEFAULTS = {
    "PI_LINKS_BIND": "0.0.0.0",
    "PI_LINKS_PORT": "8090",
    "PI_LINKS_TITLE": "Raspberry Pi",
    "PI_LINKS_LINKS_FILE": "/etc/pi-links/links.toml",
}

MAX_TITLE_LENGTH = 60
LINK_KEYS = {"name", "group", "description", "port", "path", "scheme", "url"}
TASK_KEYS = {"name", "group", "schedule", "description"}
DEFAULT_TASK_GROUP = "Other"
DEFAULT_GROUP = "Services"
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


class ConfigError(Exception):
    """One or more configuration problems."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Settings:
    bind: str
    port: int
    title: str
    links_file: Path


@dataclass(frozen=True)
class Link:
    name: str
    group: str = DEFAULT_GROUP
    description: str = ""
    port: int | None = None
    path: str = "/"
    scheme: str = "http"
    url: str | None = None


@dataclass(frozen=True)
class Task:
    name: str
    schedule: str
    description: str = ""
    group: str = DEFAULT_TASK_GROUP


@dataclass(frozen=True)
class Board:
    links: tuple[Link, ...] = ()
    tasks: tuple[Task, ...] = ()


def _parse_env_file(path: Path, problems: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    except OSError as exc:
        problems.append(f"{path}: cannot read file: {exc.strerror}")
        return values

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not key:
            problems.append(f"{path}:{number}: expected KEY=value")
            continue
        if key not in DEFAULTS:
            problems.append(f"{path}:{number}: unknown key {key}")
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_settings(
    settings_file: str | Path = DEFAULT_SETTINGS_FILE,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    environ = os.environ if environ is None else environ
    path = Path(settings_file)
    problems: list[str] = []

    merged = dict(DEFAULTS)
    merged.update(_parse_env_file(path, problems))
    merged.update({key: environ[key] for key in DEFAULTS if key in environ})

    bind = merged["PI_LINKS_BIND"]
    try:
        ipaddress.ip_address(bind)
    except ValueError:
        problems.append(f"PI_LINKS_BIND in {path}: {bind!r} is not an IP address")

    port = 0
    try:
        port = int(merged["PI_LINKS_PORT"])
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError:
        problems.append(
            f"PI_LINKS_PORT in {path}: {merged['PI_LINKS_PORT']!r} "
            "is not a port from 1 to 65535"
        )

    title = merged["PI_LINKS_TITLE"].strip()
    if not title or len(title) > MAX_TITLE_LENGTH:
        problems.append(
            f"PI_LINKS_TITLE in {path}: must be 1 to {MAX_TITLE_LENGTH} characters"
        )

    links_file = merged["PI_LINKS_LINKS_FILE"]
    if not Path(links_file).is_absolute():
        problems.append(f"PI_LINKS_LINKS_FILE in {path}: must be an absolute path")

    if problems:
        raise ConfigError(problems)
    return Settings(bind=bind, port=port, title=title, links_file=Path(links_file))


def _text(entry: dict, key: str, label: str, problems: list[str]) -> str:
    value = entry.get(key, "")
    if not isinstance(value, str):
        problems.append(f"{label}: {key} must be text")
        return ""
    return value.strip()


def _parse_link(entry: object, label: str, problems: list[str]) -> Link | None:
    if not isinstance(entry, dict):
        problems.append(f"{label}: must be a [[link]] table")
        return None

    start = len(problems)
    for key in sorted(set(entry) - LINK_KEYS):
        problems.append(f"{label}: unknown key {key}")

    name = _text(entry, "name", label, problems)
    if not name:
        problems.append(f"{label}: name is required")
    group = _text(entry, "group", label, problems) or DEFAULT_GROUP
    description = _text(entry, "description", label, problems)

    has_port = "port" in entry
    has_url = "url" in entry
    if has_port == has_url:
        problems.append(f"{label}: set exactly one of port or url")

    port = None
    path = "/"
    scheme = "http"
    url = None

    if has_port:
        port = entry["port"]
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            problems.append(f"{label}: port must be a number from 1 to 65535")
        path = entry.get("path", "/")
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or _UNSAFE_URL_CHARS.search(path)
        ):
            problems.append(f"{label}: path must start with a single / and hold no spaces")
        scheme = entry.get("scheme", "http")
        if scheme not in ("http", "https"):
            problems.append(f"{label}: scheme must be http or https")

    if has_url:
        for key in ("path", "scheme"):
            if key in entry:
                problems.append(f"{label}: {key} only applies to port links")
        url = entry["url"]
        valid = isinstance(url, str) and not _UNSAFE_URL_CHARS.search(url)
        if valid:
            try:
                parts = urlsplit(url)
                valid = parts.scheme in ("http", "https") and bool(parts.hostname)
            except ValueError:
                valid = False
        if not valid:
            problems.append(f"{label}: url must be a full http or https address")

    if len(problems) > start:
        return None
    return Link(
        name=name,
        group=group,
        description=description,
        port=port,
        path=path,
        scheme=scheme,
        url=url,
    )


def _parse_task(entry: object, label: str, problems: list[str]) -> Task | None:
    if not isinstance(entry, dict):
        problems.append(f"{label}: must be a [[task]] table")
        return None

    start = len(problems)
    for key in sorted(set(entry) - TASK_KEYS):
        problems.append(f"{label}: unknown key {key}")

    name = _text(entry, "name", label, problems)
    if not name:
        problems.append(f"{label}: name is required")
    schedule = _text(entry, "schedule", label, problems)
    if not schedule:
        problems.append(f"{label}: schedule is required")
    description = _text(entry, "description", label, problems)
    group = _text(entry, "group", label, problems) or DEFAULT_TASK_GROUP

    if len(problems) > start:
        return None
    return Task(name=name, schedule=schedule, description=description, group=group)


def load_board(links_file: str | Path) -> Board:
    path = Path(links_file)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError:
        raise ConfigError([f"{path}: file not found"]) from None
    except OSError as exc:
        raise ConfigError([f"{path}: cannot read file: {exc.strerror}"]) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError([f"{path}: invalid TOML: {exc}"]) from None

    problems = [
        f"{path}: unknown top-level key {key}" for key in sorted(set(data) - {"link", "task"})
    ]
    entries = data.get("link", [])
    task_entries = data.get("task", [])
    if not isinstance(entries, list):
        raise ConfigError(problems + [f"{path}: link must be written as [[link]]"])
    if not isinstance(task_entries, list):
        raise ConfigError(problems + [f"{path}: task must be written as [[task]]"])

    links = []
    for number, entry in enumerate(entries, start=1):
        link = _parse_link(entry, f"{path}: link {number}", problems)
        if link:
            links.append(link)

    tasks = []
    for number, entry in enumerate(task_entries, start=1):
        task = _parse_task(entry, f"{path}: task {number}", problems)
        if task:
            tasks.append(task)

    if problems:
        raise ConfigError(problems)
    return Board(links=tuple(links), tasks=tuple(tasks))


def load_links(links_file: str | Path) -> list[Link]:
    return list(load_board(links_file).links)
