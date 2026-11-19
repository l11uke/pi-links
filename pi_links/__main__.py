"""Command line: python3 -m pi_links {serve,check-config,scan}."""

from __future__ import annotations

import argparse
import os
import signal
import sys

from . import __version__
from .config import DEFAULT_SETTINGS_FILE, ConfigError, load_board, load_settings
from .discovery import load_discovery, merge
from .scan import scan as run_scan, write_discovery
from .status import format_time
from .server import LinkStore, LinksServer


def _stop(_signum, _frame) -> None:
    raise KeyboardInterrupt


def serve(settings_file: str) -> int:
    settings = load_settings(settings_file)
    store = LinkStore(settings.links_file, settings.discovery_file)
    try:
        server = LinksServer(settings, store)
    except OSError as exc:
        print(
            f"Cannot listen on {settings.bind}:{settings.port}: {exc.strerror}. "
            "Change PI_LINKS_PORT or PI_LINKS_BIND.",
            file=sys.stderr,
        )
        return 1

    signal.signal(signal.SIGTERM, _stop)
    print(f"pi-links {__version__} listening on {settings.bind}:{settings.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def check_config(settings_file: str) -> int:
    settings = load_settings(settings_file)
    board = load_board(settings.links_file)
    discovery = load_discovery(settings.discovery_file)
    merged = merge(board, discovery)
    print("Configuration is valid.")
    print(f"PI_LINKS_BIND={settings.bind}")
    print(f"PI_LINKS_PORT={settings.port}")
    print(f"PI_LINKS_TITLE={settings.title}")
    print(f"PI_LINKS_LINKS_FILE={settings.links_file}")
    print(f"PI_LINKS_DISCOVERY_FILE={settings.discovery_file}")
    print(f"PI_LINKS_SCAN_SCHEDULE={settings.scan_schedule}")
    if discovery.problem:
        print(f"Scan result: {discovery.problem}")
    elif discovery.scanned_at:
        print(f"Last scan: {format_time(discovery.scanned_at)}")
    else:
        print("Last scan: none yet")
    print(f"Links: {len(merged.links)}")
    for link in merged.links:
        target = link.url or f"port {link.port}{link.path}"
        print(f"  {link.group}: {link.name} ({target})")
    print(f"Scheduled tasks: {len(merged.tasks)}")
    for task in merged.tasks:
        extra = f", result file {task.status_file}" if task.status_file else ""
        print(f"  {task.group}: {task.name} ({task.schedule}{extra})")
    for warning in merged.warnings:
        print(f"Warning: {warning}")
    return 0


def scan(settings_file: str) -> int:
    settings = load_settings(settings_file)
    if os.geteuid() != 0:
        print("The scan needs root to see every process and crontab. Run it with sudo.", file=sys.stderr)
        return 1
    data = run_scan(settings.port)
    write_discovery(settings.discovery_file, data)
    print(f"Wrote {settings.discovery_file}")
    print(f"Web services: {len(data['links'])}  (match in links.toml by port)")
    for link in data["links"]:
        print(f"  port {link['port']}: {link['name']} [{link['group']}] found as {link['found_as']}")
    print(f"Scheduled tasks: {len(data['tasks'])}  (match in links.toml by id)")
    for task in data["tasks"]:
        print(f"  id {task['id']}: {task['name']} [{task['group']}] {task['schedule']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi_links")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--settings", default=DEFAULT_SETTINGS_FILE, help="path to settings.env")
    parser.add_argument("command", choices=["serve", "check-config", "scan"])
    args = parser.parse_args(argv)

    action = {"serve": serve, "check-config": check_config, "scan": scan}[args.command]
    try:
        return action(args.settings)
    except ConfigError as exc:
        print("Configuration problems:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
