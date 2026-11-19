import json
import socket
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pi_links.config import Board, Link, Task  # noqa: E402
from pi_links.discovery import Discovery, load_discovery, merge  # noqa: E402
from pi_links.render import render_page  # noqa: E402
from pi_links.scan import (  # noqa: E402
    discover_cron,
    discover_links,
    discover_timers,
    parse_docker_ports,
    parse_listeners,
    probe_address,
    probe_http,
    scan,
    script_from_command,
    write_discovery,
)
from pi_links.schedule import humanize_calendar, humanize_cron  # noqa: E402
from pi_links.server import LinkStore  # noqa: E402

SS_OUTPUT = """\
LISTEN 0 4096 0.0.0.0:8053 0.0.0.0:* users:(("docker-proxy",pid=1,fd=8))
LISTEN 0 1024 0.0.0.0:32400 0.0.0.0:* users:(("Plex Media Serv",pid=2,fd=51))
LISTEN 0 511 127.0.0.1:6380 0.0.0.0:* users:(("redis-server",pid=3,fd=16))
LISTEN 0 4096 0.0.0.0:11470 0.0.0.0:* users:(("docker-proxy",pid=4,fd=8))
LISTEN 0 4096 0.0.0.0:12470 0.0.0.0:* users:(("docker-proxy",pid=5,fd=8))
LISTEN 0 128 0.0.0.0:5000 0.0.0.0:* users:(("python",pid=6,fd=3))
LISTEN 0 2048 10.0.0.5:8090 0.0.0.0:* users:(("gunicorn",pid=7,fd=3),("gunicorn",pid=8,fd=3))
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=9,fd=6))
LISTEN 0 4096 0.0.0.0:80 0.0.0.0:* users:(("python3",pid=10,fd=3))
LISTEN 0 4096 0.0.0.0:2222 0.0.0.0:* users:(("sshd",pid=11,fd=3))
LISTEN 0 4096 [::]:9100 [::]:* users:(("exporter",pid=12,fd=3))
LISTEN 0 4096 [::]:8053 [::]:* users:(("docker-proxy",pid=13,fd=8))
"""
DOCKER_OUTPUT = (
    "pihole\t67/udp, 0.0.0.0:53->53/tcp, 0.0.0.0:8053->80/tcp, [::]:8053->80/tcp\n"
    "stremio-server\t0.0.0.0:11470->11470/tcp, [::]:11470->11470/tcp, 0.0.0.0:12470->12470/tcp\n"
    "db\t\n"
)
PAGES = {
    8053: {"scheme": "http", "status": 404, "title": "Pi-hole abc123"},
    32400: {"scheme": "http", "status": 401, "title": "Unauthorized"},
    11470: {"scheme": "http", "status": 200, "title": "Stremio - Freedom to Stream"},
    12470: {"scheme": "https", "status": 200, "title": "Stremio - Freedom to Stream"},
    5000: {"scheme": "http", "status": 200, "title": "Receipt Upload"},
    8090: {"scheme": "http", "status": 200, "title": "Not Found"},
}


def fake_runner(responses):
    def runner(command):
        for prefix, result in responses.items():
            if " ".join(command).startswith(prefix):
                return result
        return 1, ""
    return runner


def fake_prober(calls):
    def prober(host, port):
        calls.append((host, port))
        return PAGES.get(port)
    return prober


def test_parse_listeners_and_docker_ports():
    listeners = parse_listeners(SS_OUTPUT)
    assert listeners[8053].hosts == {"0.0.0.0", "::"}
    assert listeners[8090].processes == {"gunicorn"}
    assert parse_docker_ports(DOCKER_OUTPUT) == {53: "pihole", 8053: "pihole", 11470: "stremio-server", 12470: "stremio-server"}


@pytest.mark.parametrize(
    "hosts, expected",
    [
        ({"0.0.0.0", "::"}, "127.0.0.1"),
        ({"10.0.0.5"}, "10.0.0.5"),
        ({"127.0.0.1"}, None),
        ({"::1"}, None),
        ({"::"}, "127.0.0.1"),
        ({"fd00::7"}, "[fd00::7]"),
    ],
)
def test_probe_address(hosts, expected):
    assert probe_address(hosts) == expected


def test_discover_links():
    calls = []
    runner = fake_runner({"ss": (0, SS_OUTPUT), "docker ps": (0, DOCKER_OUTPUT)})
    links = discover_links(runner, fake_prober(calls), own_port=80)
    by_port = {link["port"]: link for link in links}

    assert by_port[8053]["name"] == "Pi-hole" and by_port[8053]["path"] == "/admin/"
    assert by_port[8053]["found_as"] == "pihole"
    assert by_port[32400]["name"] == "Plex" and by_port[32400]["path"] == "/web"
    assert by_port[11470]["group"] == "Media"
    assert 12470 not in by_port, "https duplicate of the same app is dropped"
    assert by_port[5000]["name"] == "Receipt Upload" and by_port[5000]["group"] == "Services"
    assert by_port[8090]["name"] == "gunicorn", "generic titles fall back to the process"

    probed_ports = {port for _, port in calls}
    assert not probed_ports & {22, 80, 2222, 6380}
    assert ("10.0.0.5", 8090) in calls


def test_discover_links_without_docker():
    runner = fake_runner({"ss": (0, SS_OUTPUT), "docker ps": (127, "")})
    links = discover_links(runner, fake_prober([]), own_port=80)
    assert {link["port"]: link for link in links}[8053]["name"] == "Pi-hole"


SHOW_OUTPUT = """\
Id=backup.timer
Description=backup-tool: nightly backup at 02:30
FragmentPath=/etc/systemd/system/backup.timer
UnitFileState=enabled
TimersCalendar={ OnCalendar=*-*-* 02:30:00 ; next_elapse=Fri 2026-01-02 02:30:00 UTC }
TimersMonotonic=

Id=mon-speed.timer
Description=mon speed test every 6 hours
FragmentPath=/etc/systemd/system/mon-speed.timer
UnitFileState=enabled
TimersCalendar={ OnCalendar=*-*-* 00/6:07:00 ; next_elapse=x }
TimersMonotonic=

Id=cleanup.timer
Description=Cleanup old files
FragmentPath=/etc/systemd/system/cleanup.timer
UnitFileState=enabled
TimersCalendar=
TimersMonotonic={ OnUnitActiveUSec=1d ; next_elapse=x }

Id=apt-daily.timer
Description=Daily apt download activities
FragmentPath=/usr/lib/systemd/system/apt-daily.timer
UnitFileState=enabled
TimersCalendar={ OnCalendar=*-*-* 06,18:00:00 ; next_elapse=x }
TimersMonotonic=

Id=old.timer
Description=old job
FragmentPath=/etc/systemd/system/old.timer
UnitFileState=disabled
TimersCalendar={ OnCalendar=daily ; next_elapse=x }
TimersMonotonic=

Id=pi-links-scan.timer
Description=Run the pi-links scan on a schedule
FragmentPath=/etc/systemd/system/pi-links-scan.timer
UnitFileState=enabled
TimersCalendar={ OnCalendar=weekly ; next_elapse=x }
TimersMonotonic=
"""


def test_discover_timers_keeps_only_user_installed():
    units = "\n".join(f"{name} loaded active waiting x" for name in
                      ["backup.timer", "mon-speed.timer", "cleanup.timer", "apt-daily.timer", "old.timer", "pi-links-scan.timer"])
    runner = fake_runner({"systemctl list-units": (0, units), "systemctl show": (0, SHOW_OUTPUT)})
    tasks = {task["id"]: task for task in discover_timers(runner)}
    assert set(tasks) == {"backup.timer", "mon-speed.timer", "cleanup.timer"}
    assert tasks["backup.timer"] == {
        "id": "backup.timer", "name": "Nightly backup", "group": "backup-tool",
        "schedule": "Daily 2:30am", "source": "systemd timer",
    }
    assert tasks["mon-speed.timer"]["group"] == "mon"
    assert tasks["mon-speed.timer"]["name"] == "Speed test"
    assert tasks["mon-speed.timer"]["schedule"] == "Every 6 hours"
    assert tasks["cleanup.timer"]["schedule"] == "Every day"


@pytest.mark.parametrize(
    "command, expected",
    [
        ("/srv/jobs/mailer/run.sh", "/srv/jobs/mailer/run.sh"),
        ("/usr/bin/flock -n /tmp/x.lock /srv/backup/backup.sh >> /srv/backup/log 2>&1", "/srv/backup/backup.sh"),
        ("/usr/bin/python3 /opt/tool/report.py --quiet", "/opt/tool/report.py"),
        ("cd /srv && ./go.sh", "/srv"),
        ("echo hello", None),
    ],
)
def test_script_from_command(command, expected):
    assert script_from_command(command) == expected


def test_discover_cron(tmp_path):
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "pat").write_text(
        "# comment\nMAILTO=\"\"\n0 10 * * 1 /home/pat/mailer/run.sh\n"
        "30 6 1 * * /home/pat/music/sync.py >> log 2>&1\n@reboot /home/pat/boot/start.sh\n"
    )
    (spool / "root").write_text("50 17 * * 0 /usr/bin/flock -n /tmp/c.lock /usr/local/sbin/check.py --notify\n")
    owned = tmp_path / "pkg-cron"
    owned.write_text("10 3 * * * root /usr/sbin/pkg-thing\n")
    mine = tmp_path / "my-cron"
    mine.write_text("15 2 * * * root /srv/nightly/clean.sh\n0 * * * * root run-parts /etc/cron.hourly\n")
    runner = fake_runner({f"dpkg -S {owned}": (0, "pkg: " + str(owned))})

    tasks = {task["id"]: task for task in discover_cron(runner, str(spool), [str(owned), str(mine)])}
    assert set(tasks) == {
        "/home/pat/mailer/run.sh", "/home/pat/music/sync.py", "/home/pat/boot/start.sh",
        "/usr/local/sbin/check.py", "/srv/nightly/clean.sh",
    }
    assert tasks["/home/pat/mailer/run.sh"]["name"] == "mailer"
    assert tasks["/home/pat/mailer/run.sh"]["schedule"] == "Mondays 10am"
    assert tasks["/home/pat/music/sync.py"]["group"] == "music"
    assert tasks["/home/pat/boot/start.sh"]["schedule"] == "At startup"
    assert tasks["/usr/local/sbin/check.py"]["group"] == "Other"
    assert tasks["/usr/local/sbin/check.py"]["source"] == "cron (root)"
    assert tasks["/srv/nightly/clean.sh"]["schedule"] == "Daily 2:15am"


def test_scan_and_write_discovery(tmp_path):
    runner = fake_runner({"ss": (0, SS_OUTPUT), "docker ps": (0, DOCKER_OUTPUT)})
    now = datetime.fromisoformat("2026-01-04T18:00:00+10:00")
    data = scan(80, runner=runner, prober=fake_prober([]), now=now)
    path = tmp_path / "state" / "discovered.json"
    write_discovery(path, data)
    assert oct(path.stat().st_mode & 0o777) == "0o644"
    found = load_discovery(path)
    assert found.scanned_at == now
    assert {link.port for link in found.links} == {8053, 32400, 11470, 5000, 8090}


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><head><title> My  App </title></head></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_probe_http_real_server_and_non_http_port():
    server = HTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        result = probe_http("127.0.0.1", server.server_address[1])
        assert result == {"scheme": "http", "status": 200, "title": "My App"}
    finally:
        server.shutdown()

    raw = socket.socket()
    raw.bind(("127.0.0.1", 0))
    raw.listen()

    def answer():
        for _ in range(2):
            try:
                conn, _ = raw.accept()
                conn.sendall(b"SSH-2.0-Fake\r\n")
                conn.close()
            except OSError:
                return
    threading.Thread(target=answer, daemon=True).start()
    assert probe_http("127.0.0.1", raw.getsockname()[1]) is None
    raw.close()


def test_load_discovery_handles_missing_bad_and_unsafe(tmp_path):
    assert load_discovery(tmp_path / "none.json") == Discovery()
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    assert "unreadable scan result" in load_discovery(bad).problem
    odd = tmp_path / "odd.json"
    odd.write_text(json.dumps({
        "scanned_at": "2026-01-04T18:00:00+10:00",
        "links": [{"port": 9000, "path": "//evil.example", "name": "X"}, {"port": "nope"}, "junk"],
        "tasks": [{"id": "a.timer", "name": "A", "schedule": "Daily"}, {"name": "no id"}],
    }))
    found = load_discovery(odd)
    assert [link.path for link in found.links] == ["/"]
    assert [task.match for task in found.tasks] == ["a.timer"]


def test_merge_overrides_hides_and_adds():
    found = Discovery(
        scanned_at=datetime.fromisoformat("2026-01-04T18:00:00+10:00"),
        links=(Link("gunicorn", port=8090), Link("Grafana", "Monitoring", port=3000), Link("Noise", port=9100)),
        tasks=(Task("Fetch", "Hourly", group="tool", match="fetch.timer"),
               Task("mailer", "Mondays 10am", group="mailer", match="/srv/mailer/run.sh")),
    )
    manual = Board(
        links=(
            Link("Library", "Media", "Videos", port=8090, fields=frozenset({"port", "name", "group", "description"})),
            Link("", port=9100, hide=True, fields=frozenset({"port", "hide"})),
            Link("Router", port=8443, scheme="https", fields=frozenset({"port", "name", "scheme"})),
            Link("Docs", "Reference", url="https://example.com"),
        ),
        tasks=(
            Task("", "", group="Video tool", match="fetch.timer", fields=frozenset({"match", "group"})),
            Task("", "", match="/srv/mailer/run.sh", hide=True, fields=frozenset({"match", "hide"})),
            Task("", "", match="gone.timer", fields=frozenset({"match"})),
            Task("Router reboot", "Sundays 4am", group="Network"),
        ),
    )
    merged = merge(manual, found)
    assert [(l.name, l.group, l.port) for l in merged.links] == [
        ("Library", "Media", 8090), ("Grafana", "Monitoring", 3000),
        ("Router", "Services", 8443), ("Docs", "Reference", None),
    ]
    assert merged.links[0].description == "Videos"
    assert [(t.name, t.group) for t in merged.tasks] == [("Fetch", "Video tool"), ("Router reboot", "Network")]
    assert merged.warnings == ("task match 'gone.timer' matches nothing in the last scan",)


def test_no_warnings_before_first_scan():
    manual = Board(tasks=(Task("", "", match="x.timer", fields=frozenset({"match"})),))
    assert merge(manual, Discovery()).warnings == ()


def test_store_picks_up_new_scan_and_page_shows_scan_time(tmp_path):
    links = tmp_path / "links.toml"
    links.write_text('[[link]]\nport = 7000\nname = "Renamed"\n')
    discovery = tmp_path / "discovered.json"
    store = LinkStore(links, discovery)
    merged, problems, found = store.get()
    assert [l.name for l in merged.links] == ["Renamed"] and found.scanned_at is None

    write_discovery(discovery, {
        "version": 1, "scanned_at": "2026-01-04T18:00:00+10:00",
        "links": [{"port": 7000, "name": "Found app", "group": "Apps"}, {"port": 7001, "name": "Other"}],
        "tasks": [{"id": "a.timer", "name": "Job", "group": "Tool", "schedule": "Daily 2am"}],
    })
    merged, problems, found = store.get()
    assert [(l.name, l.group) for l in merged.links] == [("Renamed", "Apps"), ("Other", "Services")]
    page = render_page("T", "h", list(merged.links), str(links), problems, merged.tasks,
                       scanned_at=found.scanned_at)
    assert "Last scan 4 Jan" in page or "Last scan 3 Jan" in page or "Last scan" in page
    assert "Job" in page and "pi-links-scan" in page


def test_page_without_scan_says_so():
    assert "Not scanned yet." in render_page("T", "h", [], "/f")


def test_page_shows_scan_problem():
    page = render_page("T", "h", [], "/f", scan_problem="bad <scan>")
    assert "bad &lt;scan&gt;" in page


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("0 10 * * 1", "Mondays 10am"),
        ("*/15 * * * *", "Every 15 minutes"),
        ("0 */6 * * *", "Every 6 hours"),
        ("0 9 * * 1-5", "Weekdays 9am"),
        ("0 0 * * *", "Daily midnight"),
        ("0 8 * 1 *", "0 8 * 1 *"),
    ],
)
def test_humanize_cron(expression, expected):
    assert humanize_cron(expression) == expected


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("*-*-* *:00/15:00", "Every 15 minutes"),
        ("*-*-* 06,18:00:00", "Daily 6am and 6pm"),
        ("Sun *-*-* 18:00:00 Europe/London", "Sundays 6pm"),
        ("*-*-01 03:00:00", "1st of the month, 3am"),
        ("Sat,Sun 10:00", "Weekends 10am"),
        ("weekly", "Mondays midnight"),
        ("2026-*-* 03:00", "2026-*-* 03:00"),
    ],
)
def test_humanize_calendar(expression, expected):
    assert humanize_calendar(expression) == expected
