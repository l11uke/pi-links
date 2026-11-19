"""Finds web services and scheduled jobs on this machine.

Runs as root, because listing which process owns a port and reading every
user's crontab both need it. The web service never runs this; it only reads
the file this writes.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import socket
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .schedule import humanize_calendar, humanize_cron, humanize_monotonic

FORMAT_VERSION = 1
SKIP_PORTS = {22, 53, 111}
SKIP_PROCESSES = {
    "sshd", "rpcbind", "systemd-resolve", "dnsmasq", "cupsd", "avahi-daemon",
    "smbd", "nmbd", "exim4", "master", "named", "unbound", "chronyd",
}
GENERIC_TITLES = {
    "unauthorized", "401 unauthorized", "not found", "404 not found", "forbidden",
    "403 forbidden", "error", "index of /", "welcome to nginx!", "apache2 debian default page: it works",
    "redirecting", "loading", "loading...",
}
GENERIC_SCRIPTS = {"run", "main", "start", "cron", "job", "script", "app", "index", "task"}
SYSTEM_BIN_DIRS = {"/usr/local/bin", "/usr/local/sbin", "/usr/bin", "/usr/sbin", "/bin", "/sbin"}
WRAPPERS = {
    "flock", "nice", "ionice", "timeout", "env", "sudo", "bash", "sh", "dash", "zsh",
    "python", "python3", "chronic", "run-one", "nohup", "setsid", "systemd-cat",
}

# Well-known self-hosted apps: keyword, display name, group, path.
HINTS = [
    ("plex", "Plex", "Media", "/web"),
    ("jellyfin", "Jellyfin", "Media", "/"),
    ("emby", "Emby", "Media", "/"),
    ("stremio", "Stremio", "Media", "/"),
    ("strem.io", "Stremio", "Media", "/"),
    ("pi-hole", "Pi-hole", "Network", "/admin/"),
    ("pihole", "Pi-hole", "Network", "/admin/"),
    ("adguard", "AdGuard Home", "Network", "/"),
    ("grafana", "Grafana", "Monitoring", "/"),
    ("ntopng", "ntopng", "Monitoring", "/"),
    ("uptime kuma", "Uptime Kuma", "Monitoring", "/"),
    ("uptime-kuma", "Uptime Kuma", "Monitoring", "/"),
    ("influxdb", "InfluxDB", "Monitoring", "/"),
    ("prometheus", "Prometheus", "Monitoring", "/"),
    ("home assistant", "Home Assistant", "Home", "/"),
    ("homeassistant", "Home Assistant", "Home", "/"),
    ("node-red", "Node-RED", "Home", "/"),
    ("portainer", "Portainer", "Admin", "/"),
    ("cockpit", "Cockpit", "Admin", "/"),
    ("immich", "Immich", "Photos", "/"),
    ("nextcloud", "Nextcloud", "Files", "/"),
    ("syncthing", "Syncthing", "Files", "/"),
    ("transmission", "Transmission", "Downloads", "/"),
    ("qbittorrent", "qBittorrent", "Downloads", "/"),
]

Runner = Callable[[list[str]], "tuple[int, str]"]
Prober = Callable[[str, int], "dict | None"]


def run_command(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return 127, ""
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return result.returncode, result.stdout


@dataclass
class Listener:
    port: int
    hosts: set[str] = field(default_factory=set)
    processes: set[str] = field(default_factory=set)


def parse_listeners(output: str) -> dict[int, Listener]:
    """Parse `ss -H -ltnp` output."""
    listeners: dict[int, Listener] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3] if parts[0] == "LISTEN" else parts[2]
        host, _, port_text = local.rpartition(":")
        if not port_text.isdigit():
            continue
        host = host.strip("[]").split("%")[0]
        port = int(port_text)
        entry = listeners.setdefault(port, Listener(port))
        entry.hosts.add(host)
        entry.processes.update(re.findall(r'\(\("([^"]+)"', line))
        entry.processes.update(re.findall(r'\),\("([^"]+)"', line))
    return listeners


def parse_docker_ports(output: str) -> dict[int, str]:
    """Map published host ports to container names from `docker ps`."""
    mapping: dict[int, str] = {}
    for line in output.splitlines():
        name, _, ports = line.partition("\t")
        for port in re.findall(r"(?:\d{1,3}(?:\.\d{1,3}){3}|\[?::\]?):(\d+)->\d+/tcp", ports):
            mapping.setdefault(int(port), name.strip())
    return mapping


def probe_address(hosts: set[str]) -> str | None:
    """Pick an address to test, or None if only this machine can reach it."""
    if hosts & {"0.0.0.0", "*"}:
        return "127.0.0.1"
    for host in sorted(hosts):
        if host in ("::", "127.0.0.1", "::1") or host.startswith("127.") or host.startswith("fe80"):
            continue
        return f"[{host}]" if ":" in host else host
    if "::" in hosts:
        return "127.0.0.1"
    return None


class _NoRedirectToOtherHosts(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.request.urlparse(newurl).hostname != urllib.request.urlparse(req.full_url).hostname:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe_http(host: str, port: int) -> dict | None:
    """Return scheme, status, title and any redirect if the port answers HTTP or HTTPS.

    A redirect to another host counts: some apps, such as Stremio's server,
    send the browser to a hosted web app.
    """
    for scheme in ("http", "https"):
        handlers = [_NoRedirectToOtherHosts()]
        if scheme == "https":
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(
            f"{scheme}://{host}:{port}/", headers={"User-Agent": "pi-links-scan"}
        )
        try:
            with opener.open(request, timeout=4) as response:
                status, headers, body = response.status, response.headers, response.read(65536)
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, exc.headers, exc.read(65536)
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError,
                socket.timeout, TimeoutError, ssl.SSLError, OSError, ValueError):
            continue
        text = body.decode("utf-8", "replace")
        title = re.search(r"<title[^>]*>([^<]*)", text, re.I)
        content_type = (headers.get("Content-Type") or "").lower()
        location = (headers.get("Location") or "") if 300 <= status < 400 else ""
        if title or "html" in content_type or location:
            return {
                "scheme": scheme,
                "status": status,
                "title": re.sub(r"\s+", " ", title.group(1)).strip() if title else "",
                "location": location,
            }
    return None


def _hint(*texts: str):
    haystack = " ".join(texts).lower()
    for keyword, name, group, path in HINTS:
        if keyword in haystack:
            return name, group, path
    return None


def _clean_title(title: str) -> str:
    title = title.strip()
    if title.lower() in GENERIC_TITLES:
        return ""
    return title[:40].rstrip(" -|:")


def discover_links(runner: Runner, prober: Prober, own_port: int) -> list[dict]:
    _, ss_output = runner(["ss", "-H", "-ltnp"])
    code, docker_output = runner(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"])
    containers = parse_docker_ports(docker_output) if code == 0 else {}

    found = []
    for port, listener in sorted(parse_listeners(ss_output).items()):
        if port in SKIP_PORTS or port == own_port or listener.processes & SKIP_PROCESSES:
            continue
        address = probe_address(listener.hosts)
        if not address:
            continue
        result = prober(address, port)
        if not result:
            continue
        container = containers.get(port, "")
        process = ", ".join(sorted(p for p in listener.processes if p != "docker-proxy"))
        location = result.get("location", "")
        hint = _hint(result["title"], container, process, location)
        if hint:
            name, group, path = hint
        else:
            redirect_host = urllib.request.urlparse(location).hostname or "" if location else ""
            name = (_clean_title(result["title"]) or container or process
                    or redirect_host or f"Port {port}")
            group, path = "Services", "/"
        found.append({
            "port": port,
            "scheme": result["scheme"],
            "path": path,
            "name": name,
            "group": group,
            "found_as": container or process or "unknown process",
        })

    unique: dict[str, dict] = {}
    for link in found:
        key = link["name"].lower()
        kept = unique.get(key)
        if kept is None or (kept["scheme"] == "https" and link["scheme"] == "http"):
            unique[key] = link
    return [link for link in found if unique[link["name"].lower()] is link]


def _parse_show_blocks(output: str) -> list[dict[str, str]]:
    blocks, current = [], {}
    for line in output.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        key, _, value = line.partition("=")
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def _timer_schedule(calendar: str, monotonic: str) -> str:
    phrases = [humanize_calendar(value.strip()) for value in re.findall(r"OnCalendar=([^;}]+)", calendar)]
    if not phrases:
        phrases = [
            humanize_monotonic(key, value.strip())
            for key, value in re.findall(r"(On\w+?)U?Sec=([^;}]+)", monotonic)
        ]
    return " and ".join(dict.fromkeys(phrases)) or "Unknown schedule"


_SCHEDULE_TAIL = re.compile(r"\s*(,|\(|\bat \d|\bevery\b|\bon (mon|tue|wed|thu|fri|sat|sun))", re.I)


def _tidy_name(text: str) -> str:
    text = _SCHEDULE_TAIL.split(text, maxsplit=1)[0].strip(" -:;,")
    if not text:
        return ""
    first = text.split()[0]
    if first.islower() and not any(c.isdigit() for c in first):
        text = text[0].upper() + text[1:]
    return text


def discover_timers(runner: Runner) -> list[dict]:
    _, units = runner(["systemctl", "list-units", "--type=timer", "--all", "--no-legend", "--plain"])
    names = [line.split()[0] for line in units.splitlines() if line.split() and line.split()[0].endswith(".timer")]
    if not names:
        return []
    _, shown = runner(
        ["systemctl", "show", *names, "-p", "Id", "-p", "Description", "-p", "FragmentPath",
         "-p", "UnitFileState", "-p", "TimersCalendar", "-p", "TimersMonotonic"]
    )
    tasks = []
    for block in _parse_show_blocks(shown):
        unit = block.get("Id", "")
        if (
            not unit.endswith(".timer")
            or unit.startswith("pi-links")
            or not block.get("FragmentPath", "").startswith("/etc/systemd/system/")
            or block.get("UnitFileState") in ("disabled", "masked")
        ):
            continue
        stem = unit[: -len(".timer")]
        prefix = stem.split("-")[0]
        description = block.get("Description", "").strip()
        labelled = re.match(r"^([\w.+-]+):\s+(.+)$", description)
        if labelled:
            group, name = labelled.group(1), labelled.group(2)
        elif description.lower().startswith(prefix.lower() + " "):
            group, name = prefix, description[len(prefix) + 1 :]
        else:
            group, name = prefix, description
        tasks.append({
            "id": unit,
            "name": _tidy_name(name) or stem,
            "group": group,
            "schedule": _timer_schedule(block.get("TimersCalendar", ""), block.get("TimersMonotonic", "")),
            "source": "systemd timer",
        })
    return tasks


def script_from_command(command: str) -> str | None:
    """Find the script a cron command runs, skipping wrappers and lock files."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        if token in ("&&", ";", "||") or token.startswith((">", "|", "2>", "1>", "&>")):
            break
        if token.startswith("-") or not token.startswith("/"):
            continue
        if os.path.basename(token) in WRAPPERS:
            continue
        if token.endswith(".lock") or token.startswith(("/tmp/", "/run/", "/var/lock/", "/dev/")):
            continue
        return token
    return None


def _cron_task(user: str, schedule: str, command: str) -> dict:
    script = script_from_command(command)
    if script:
        path = Path(script)
        folder, stem = path.parent.name, path.stem
        if stem in GENERIC_SCRIPTS:
            name = group = folder
        elif str(path.parent) in SYSTEM_BIN_DIRS:
            name, group = stem, "Other"
        else:
            name, group = stem, folder
        task_id = script
    else:
        name, group = command.split()[0].rsplit("/", 1)[-1], "Other"
        task_id = f"cron:{user}:{command[:80]}"
    return {
        "id": task_id,
        "name": name,
        "group": group,
        "schedule": humanize_cron(schedule),
        "source": f"cron ({user})",
    }


def _cron_lines(text: str, user: str | None):
    """Yield (user, schedule, command). user=None means the line has a user field."""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", line):
            continue
        parts = line.split()
        if parts[0].startswith("@"):
            schedule, rest = parts[0], parts[1:]
        else:
            if len(parts) < 6:
                continue
            schedule, rest = " ".join(parts[:5]), parts[5:]
        if user is None:
            if len(rest) < 2:
                continue
            yield rest[0], schedule, " ".join(rest[1:])
        elif rest:
            yield user, schedule, " ".join(rest)


def discover_cron(runner: Runner, spool: str = "/var/spool/cron/crontabs",
                  system_files: list[str] | None = None) -> list[dict]:
    tasks = []
    try:
        users = sorted(os.listdir(spool))
    except OSError:
        users = []
    for user in users:
        try:
            text = Path(spool, user).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tasks += [_cron_task(u, s, c) for u, s, c in _cron_lines(text, user)]

    if system_files is None:
        system_files = ["/etc/crontab", *sorted(str(p) for p in Path("/etc/cron.d").glob("*"))]
    for path in system_files:
        code, _ = runner(["dpkg", "-S", path])
        if code == 0:
            continue  # installed by a package
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for user, schedule, command in _cron_lines(text, None):
            if "run-parts" in command:
                continue
            tasks.append(_cron_task(user, schedule, command))
    return tasks


def scan(own_port: int, runner: Runner = run_command, prober: Prober = probe_http,
         now: datetime | None = None) -> dict:
    return {
        "version": FORMAT_VERSION,
        "scanned_at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "links": discover_links(runner, prober, own_port),
        "tasks": discover_timers(runner) + discover_cron(runner),
    }


def write_discovery(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=".discovered.")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(data, out, indent=1)
    os.chmod(temp, 0o644)
    os.replace(temp, path)
