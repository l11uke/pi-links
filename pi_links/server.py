"""HTTP server for the links page."""

from __future__ import annotations

import ipaddress
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ConfigError, Link, Settings, load_links
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
    """Reloads the links file when it changes and keeps the last good copy."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._links = load_links(path)
        self._problems: list[str] = []
        self._stamp = self._current_stamp()

    def _current_stamp(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def get(self) -> tuple[list[Link], list[str]]:
        with self._lock:
            stamp = self._current_stamp()
            if stamp != self._stamp:
                self._stamp = stamp
                try:
                    self._links = load_links(self.path)
                    self._problems = []
                except ConfigError as exc:
                    self._problems = exc.problems
            return list(self._links), list(self._problems)


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
        links, problems = self.server.store.get()
        page = render_page(
            self.server.settings.title,
            host,
            links,
            str(self.server.store.path),
            problems,
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
