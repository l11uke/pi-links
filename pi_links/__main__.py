"""Command line: python3 -m pi_links {serve,check-config}."""

from __future__ import annotations

import argparse
import signal
import sys

from . import __version__
from .config import DEFAULT_SETTINGS_FILE, ConfigError, load_board, load_settings
from .server import LinkStore, LinksServer


def _stop(_signum, _frame) -> None:
    raise KeyboardInterrupt


def serve(settings_file: str) -> int:
    settings = load_settings(settings_file)
    store = LinkStore(settings.links_file)
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
    print("Configuration is valid.")
    print(f"PI_LINKS_BIND={settings.bind}")
    print(f"PI_LINKS_PORT={settings.port}")
    print(f"PI_LINKS_TITLE={settings.title}")
    print(f"PI_LINKS_LINKS_FILE={settings.links_file}")
    print(f"Links: {len(board.links)}")
    for link in board.links:
        target = link.url or f"port {link.port}{link.path}"
        print(f"  {link.group}: {link.name} ({target})")
    print(f"Scheduled tasks: {len(board.tasks)}")
    for task in board.tasks:
        extra = f", result file {task.status_file}" if task.status_file else ""
        print(f"  {task.group}: {task.name} ({task.schedule}{extra})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pi_links")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--settings", default=DEFAULT_SETTINGS_FILE, help="path to settings.env")
    parser.add_argument("command", choices=["serve", "check-config"])
    args = parser.parse_args(argv)

    action = serve if args.command == "serve" else check_config
    try:
        return action(args.settings)
    except ConfigError as exc:
        print("Configuration problems:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  {problem}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
