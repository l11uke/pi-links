"""HTTP server for the links page."""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Board, ConfigError, Settings, load_board
from .discovery import Discovery, Merged, load_discovery, merge
from .render import render_page

_HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


def _format_ip(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    return f"[{address}]" if address.version == 6 else str(address)


def host_from_header(header: str | None, fallback: str) -> str:
    """Return the host the browser used, or the fallback if it is not valid."""
    value = (header or "").strip()
    if value.startswith("["):
        end = value.find("]")
        remainder = value[end + 1 :] if end != -1 else "x"
        if end != -1 and (not remainder or re.fullmatch(r":\d{1,5}", remainder)):
            formatted = _format_ip(value[1:end])
            if formatted and formatted.startswith("["):
                return formatted
        return fallback
    name, _, port = value.partition(":")
    if _HOSTNAME.fullmatch(name) and (not port or re.fullmatch(r"\d{1,5}", port)):
        return name
    return fallback


class LinkStore:
    """Reloads the links file and scan result when either changes.

    An invalid links file leaves the last good copy in place.
    """

    def __init__(self, path: Path, discovery_path: Path | None = None):
        self.path = path
        self.discovery_path = discovery_path
        self._lock = threading.Lock()
        self._board = load_board(path)
        self._problems: list[str] = []
        self._discovery = self._load_discovery()
        self._stamps = self._current_stamps()

    def _load_discovery(self) -> Discovery:
        return load_discovery(self.discovery_path) if self.discovery_path else Discovery()

    @staticmethod
    def _stamp(path: Path | None) -> tuple[int, int] | None:
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _current_stamps(self):
        return (self._stamp(self.path), self._stamp(self.discovery_path))

    def get(self) -> tuple[Merged, list[str], Discovery]:
        with self._lock:
            stamps = self._current_stamps()
            if stamps[0] != self._stamps[0]:
                try:
                    self._board = load_board(self.path)
                    self._problems = []
                except ConfigError as exc:
                    self._problems = exc.problems
            if stamps[1] != self._stamps[1]:
                self._discovery = self._load_discovery()
            self._stamps = stamps
            return merge(self._board, self._discovery), list(self._problems), self._discovery


class Handler(BaseHTTPRequestHandler):
    server_version = "pi-links"
    sys_version = ""
    timeout = 10

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _respond(self) -> None:
        route = self.path.partition("?")[0]
        if route == "/healthz":
            self._send(200, "text/plain; charset=utf-8", b"ok\n")
            return
        if route != "/":
            self._send(404, "text/plain; charset=utf-8", b"Not found\n")
            return

        local_ip = self.connection.getsockname()[0]
        host = host_from_header(self.headers.get("Host"), _format_ip(local_ip) or local_ip)
        merged, problems, discovery = self.server.store.get()
        page = render_page(
            self.server.settings.title,
            host,
            list(merged.links),
            str(self.server.store.path),
            problems,
            merged.tasks,
            scanned_at=discovery.scanned_at,
            scan_problem=discovery.problem,
        )
        self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))

    do_GET = _respond
    do_HEAD = _respond

    def log_request(self, code="-", size="-") -> None:
        """Access logging is off: this page gets no traffic worth recording."""


class LinksServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, settings: Settings, store: LinkStore):
        self.address_family = socket.AF_INET6 if ":" in settings.bind else socket.AF_INET
        self.settings = settings
        self.store = store
        super().__init__((settings.bind, settings.port), Handler)
