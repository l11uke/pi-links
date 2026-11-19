import http.client
import os
import re
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pi_links.config import (  # noqa: E402
    DEFAULTS,
    ConfigError,
    Link,
    Settings,
    Task,
    load_board,
    load_links,
    load_settings,
)
from pi_links.render import link_href, link_target, render_page  # noqa: E402
from pi_links.server import LinksServer, LinkStore, host_from_header  # noqa: E402
from pi_links.status import format_time, read_status  # noqa: E402


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def problems_for(path):
    with pytest.raises(ConfigError) as caught:
        load_links(path)
    return "\n".join(caught.value.problems)


@pytest.fixture
def running(tmp_path):
    links = write(tmp_path / "links.toml", '[[link]]\nname = "Alpha"\nport = 9000\n')
    settings = Settings("127.0.0.1", 0, "Test board", links)
    server = LinksServer(settings, LinkStore(links))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, links
    server.shutdown()
    server.server_close()


def request(server, path="/", method="GET", host=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Host": host} if host else {}
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    body = response.read().decode()
    connection.close()
    return response, body


def test_defaults_apply_without_a_settings_file(tmp_path):
    settings = load_settings(tmp_path / "missing.env", environ={})
    assert settings.port == 8090
    assert settings.bind == "0.0.0.0"


def test_settings_file_then_environment_precedence(tmp_path):
    path = write(tmp_path / "s.env", 'PI_LINKS_PORT="9100"\nPI_LINKS_TITLE="Lab Pi"\n')
    settings = load_settings(path, environ={"PI_LINKS_PORT": "9200"})
    assert settings.port == 9200
    assert settings.title == "Lab Pi"


def test_all_settings_problems_reported_together(tmp_path):
    path = write(
        tmp_path / "s.env",
        "PI_LINKS_BIND=nope\nPI_LINKS_PORT=70000\nPI_LINKS_TITLE=\n"
        "PI_LINKS_LINKS_FILE=relative.toml\nPI_LINKS_TYPO=1\n",
    )
    with pytest.raises(ConfigError) as caught:
        load_settings(path, environ={})
    text = "\n".join(caught.value.problems)
    for key in ("PI_LINKS_BIND", "PI_LINKS_PORT", "PI_LINKS_TITLE", "PI_LINKS_LINKS_FILE", "PI_LINKS_TYPO"):
        assert key in text


def test_links_parse_with_defaults_and_order(tmp_path):
    path = write(
        tmp_path / "l.toml",
        '[[link]]\nname = "B"\nport = 1234\n\n'
        '[[link]]\nname = "A"\ngroup = "Docs"\nurl = "https://example.com/a"\n',
    )
    links = load_links(path)
    assert [link.name for link in links] == ["B", "A"]
    assert links[0].group == "Services"
    assert links[0].path == "/"


@pytest.mark.parametrize(
    "body, expected",
    [
        ('url = "https://example.com"', "name is required for a url link"),
        ('name = "A"\nurl = "https://example.com"\nhide = true', "hide only applies to port links"),
        ('port = 80\nhide = "yes"', "hide must be true or false"),
        ('name = "A"', "exactly one of port or url"),
        ('name = "A"\nport = 80\nurl = "https://example.com"', "exactly one of port or url"),
        ('name = "A"\nport = 0', "port must be"),
        ('name = "A"\nport = true', "port must be"),
        ('name = "A"\nport = 80\npath = "admin"', "path must"),
        ('name = "A"\nport = 80\npath = "//evil.example"', "path must"),
        ('name = "A"\nport = 80\nscheme = "ftp"', "scheme must"),
        ('name = "A"\nurl = "javascript:alert(1)"', "url must"),
        ('name = "A"\nurl = "https://example.com"\npath = "/x"', "only applies"),
        ('name = "A"\nport = 80\nprot = 1', "unknown key prot"),
    ],
)
def test_invalid_links_are_rejected(tmp_path, body, expected):
    assert expected in problems_for(write(tmp_path / "l.toml", f"[[link]]\n{body}\n"))


def test_invalid_toml_and_missing_file(tmp_path):
    assert "invalid TOML" in problems_for(write(tmp_path / "l.toml", "[[link]\n"))
    assert "file not found" in problems_for(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    "header, expected",
    [
        ("pi.lan:8090", "pi.lan"),
        ("10.20.30.40:8090", "10.20.30.40"),
        ("[fd00::5]:8090", "[fd00::5]"),
        ("[fd00::5]", "[fd00::5]"),
        ('evil"><script>', "fallback"),
        ("[not-ip]:80", "fallback"),
        ("", "fallback"),
        (None, "fallback"),
    ],
)
def test_host_header_handling(header, expected):
    assert host_from_header(header, "fallback") == expected


def test_link_addresses():
    assert link_href(Link("A", port=3000, path="/x"), "pi.lan") == "http://pi.lan:3000/x"
    assert link_href(Link("A", port=80), "pi.lan") == "http://pi.lan/"
    assert link_href(Link("A", port=443, scheme="https"), "pi.lan") == "https://pi.lan/"
    assert link_target(Link("A", url="https://www.example.com/x")) == "example.com"


def test_page_escapes_every_value():
    link = Link("<b>n</b>", group="<i>g</i>", description="<u>d</u>", port=1000)
    page = render_page("<t>", "pi.lan", [link], "/x<y", ["<bad>"])
    for raw in ("<b>n", "<i>g", "<u>d", "<t>", "<bad>"):
        assert raw not in page
    assert "<script" not in page


def test_groups_sort_alphabetically_with_catch_all_last():
    links = [Link("A", group="Two", port=1), Link("B", group="One", port=2),
             Link("C", group="Two", port=3), Link("D", port=4)]
    page = render_page("T", "h", links, "/f")
    assert page.index(">One<") < page.index(">Two<") < page.index(">Services<")
    assert page.index(">A<") < page.index(">C<")
    assert page.count("<section>") == 3


def test_server_builds_links_from_host_header(running):
    server, _ = running
    response, body = request(server, host="board.example:8090")
    assert response.status == 200
    assert 'href="http://board.example:9000/"' in body
    assert "default-src 'none'" in response.getheader("Content-Security-Policy")


def test_server_routes(running):
    server, _ = running
    assert request(server, "/healthz")[1] == "ok\n"
    assert request(server, "/other")[0].status == 404
    response, body = request(server, method="HEAD")
    assert response.status == 200 and body == ""
    assert request(server, method="POST")[0].status == 501


def test_edit_applies_on_reload_and_bad_edit_keeps_last_good(running):
    server, links = running
    write(links, '[[link]]\nname = "Beta service"\nport = 9001\n')
    assert "Beta service" in request(server)[1]

    write(links, "[[link]\nbroken")
    body = request(server)[1]
    assert "Beta service" in body
    assert "last working version" in body

    write(links, '[[link]]\nname = "Gamma"\nport = 9002\n')
    body = request(server)[1]
    assert "Gamma" in body and "last working version" not in body


def test_empty_links_show_next_step(tmp_path):
    page = render_page("T", "h", [], "/etc/example/links.toml")
    assert "No links yet" in page and "/etc/example/links.toml" in page


def test_tasks_parse_in_order(tmp_path):
    path = write(
        tmp_path / "l.toml",
        '[[task]]\nname = "B"\nschedule = "Daily"\n\n'
        '[[task]]\nname = "A"\nschedule = "Weekly"\ndescription = "Email"\n',
    )
    board = load_board(path)
    assert [task.name for task in board.tasks] == ["B", "A"]
    assert board.tasks[0].group == "Other"
    assert board.links == ()


def test_tasks_render_under_sorted_project_headings():
    tasks = [Task("A", "Daily", group="Two"), Task("B", "Daily", group="One"),
             Task("C", "Daily", group="Two"), Task("D", "Daily")]
    page = render_page("T", "h", [], "/f", tasks=tasks)
    assert page.count('class="task-group"') == 3
    assert page.index("<h3>One</h3>") < page.index("<h3>Two</h3>") < page.index("<h3>Other</h3>")
    assert page.index(">B<") < page.index(">A<") < page.index(">C<")


@pytest.mark.parametrize(
    "body, expected",
    [
        ('schedule = "Daily"', "name is required"),
        ('name = "A"', "schedule is required"),
        ('name = "A"\nschedule = 5', "schedule must be text"),
        ('name = "A"\nschedule = "Daily"\nport = 80', "unknown key port"),
    ],
)
def test_invalid_tasks_are_rejected(tmp_path, body, expected):
    assert expected in problems_for(write(tmp_path / "l.toml", f"[[task]]\n{body}\n"))


def test_tasks_render_escaped_and_without_links():
    page = render_page("T", "h", [], "/f", tasks=[Task("<n>", "<s>", "<d>", "<g>")])
    assert "Scheduled tasks" in page
    assert "No links yet" not in page
    assert "<a " not in page
    for raw in ("<n>", "<s>", "<d>", "<g>"):
        assert raw not in page


def test_server_shows_tasks_after_edit(running):
    server, links = running
    write(links, '[[task]]\nname = "Nightly job"\nschedule = "Daily 2am"\n')
    body = request(server)[1]
    assert "Nightly job" in body and "Daily 2am" in body


NOW = __import__("datetime").datetime.fromisoformat("2026-01-10T12:00:00+10:00")


def status_file(tmp_path, body):
    return str(write(tmp_path / "status.json", body))


@pytest.mark.parametrize(
    "body, state",
    [
        ('{"checked_at": "2026-01-10T09:00:00+10:00", "ok": true, "summary": "7 of 7"}', "passed"),
        ('{"checked_at": "2026-01-10T09:00:00+10:00", "ok": false, "summary": "1 failed"}', "failed"),
        ('{"checked_at": "2026-01-01T09:00:00+10:00", "ok": true}', "overdue"),
        ('{"checked_at": "2026-01-10T09:00:00", "ok": true}', "unreadable"),
        ('{"checked_at": "2026-01-10T09:00:00+10:00", "ok": "yes"}', "unreadable"),
        ('{"ok": true}', "unreadable"),
        ("not json", "unreadable"),
    ],
)
def test_status_states(tmp_path, body, state):
    assert read_status(status_file(tmp_path, body), 192, now=NOW).state == state


def test_missing_status_file_is_never(tmp_path):
    assert read_status(tmp_path / "none.json", 192, now=NOW).state == "never"


def test_failed_result_stays_failed_when_old(tmp_path):
    path = status_file(tmp_path, '{"checked_at": "2025-01-01T09:00:00+10:00", "ok": false}')
    assert read_status(path, 1, now=NOW).state == "failed"


def test_format_time():
    moment = __import__("datetime").datetime.fromisoformat("2026-01-04T18:00:00+00:00")
    assert format_time(moment.astimezone()) == format_time(moment)
    assert "Jan" in format_time(moment)


@pytest.mark.parametrize(
    "body, expected",
    [
        ('status_file = "relative.json"', "status_file must be an absolute path"),
        ('status_file = "/x.json"\nstatus_max_age_hours = 0', "whole number of hours"),
        ("status_max_age_hours = 24", "needs status_file"),
    ],
)
def test_invalid_status_keys(tmp_path, body, expected):
    text = f'[[task]]\nname = "A"\nschedule = "Daily"\n{body}\n'
    assert expected in problems_for(write(tmp_path / "l.toml", text))


def test_task_status_renders_and_escapes(tmp_path):
    ok = status_file(tmp_path, '{"checked_at": "2099-01-01T09:00:00+10:00", "ok": true, "summary": "<all> good"}')
    page = render_page("T", "h", [], "/f", tasks=[Task("A", "Daily", status_file=ok)])
    assert "Passed" in page and "marker-passed" in page
    assert "<all>" not in page and "&lt;all&gt; good" in page
    page = render_page("T", "h", [], "/f", tasks=[Task("B", "Daily", status_file=str(tmp_path / "x.json"))])
    assert "No result yet" in page and "marker-attention" in page
    page = render_page("T", "h", [], "/f", tasks=[Task("C", "Daily")])
    assert "status" not in page.split("<body>")[1]


def test_settings_example_matches_code():
    text = (ROOT / "settings.env.example").read_text()
    assert set(re.findall(r"^(PI_LINKS_[A-Z_]+)=", text, re.M)) == set(DEFAULTS)
    settings = load_settings(ROOT / "settings.env.example", environ={})
    assert settings.port == int(DEFAULTS["PI_LINKS_PORT"])


def test_links_example_is_empty_and_its_samples_are_valid(tmp_path):
    example = ROOT / "links.toml.example"
    assert load_links(example) == []
    sample = re.sub(
        r"^# (\[\[(?:link|task)\]\]|[a-z_]+ = .*)$", r"\1", example.read_text(), flags=re.M
    )
    board = load_board(write(tmp_path / "l.toml", sample))
    assert len(board.links) == 3
    assert board.links[1].hide
    assert len(board.tasks) == 2
    assert board.tasks[0].match and board.tasks[0].status_file
    assert board.tasks[1].match is None


def test_no_site_values_in_tracked_text():
    private = re.compile(r"192\.168\.|/home/admin|l11uke|@gmail\.")
    for path in ROOT.rglob("*"):
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
            if path.suffix != ".pyc" and path.name != "test_pi_links.py":
                assert not private.search(path.read_text(encoding="utf-8")), path


@pytest.fixture
def installer_env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "id": "echo 0",
        "ss": 'case "$*" in *":5555"*) echo LISTEN ;; esac',
        "systemctl": 'echo "$*" >> "$STUB_LOG"; case "$1" in is-active) exit 1 ;; esac',
        "chown": 'echo "chown $*" >> "$STUB_LOG"',
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        PI_LINKS_CONFIG_DIR=str(tmp_path / "etc"),
        PI_LINKS_UNIT_DIR=str(tmp_path / "units"),
        PI_LINKS_SKIP_HEALTHCHECK="1",
        STUB_LOG=str(tmp_path / "log"),
        SUDO_USER="tester",
    )
    return tmp_path, env


def run_script(name, env, stdin="", *args):
    return subprocess.run(
        ["bash", str(ROOT / name), *args], input=stdin, env=env, text=True, capture_output=True
    )


def test_installer_writes_config_and_prefills_on_rerun(installer_env):
    tmp, env = installer_env
    result = run_script("install.sh", env, "127.0.0.1\n5555\n8123\nLab board\nnot a schedule\nSun 03:40\n")
    assert result.returncode == 0, result.stderr
    assert "Port 5555 is in use" in result.stderr
    assert "systemd does not understand" in result.stderr

    settings = tmp / "etc/settings.env"
    assert 'PI_LINKS_PORT="8123"' in settings.read_text()
    assert stat.S_IMODE(settings.stat().st_mode) == 0o644
    assert "chown tester" in (tmp / "log").read_text()

    unit = (tmp / "units/pi-links.service").read_text()
    assert "@" not in unit and f"WorkingDirectory={ROOT}" in unit
    assert "OnCalendar=Sun 03:40" in (tmp / "units/pi-links-scan.timer").read_text()
    assert "scan" in (tmp / "units/pi-links-scan.service").read_text()
    log = (tmp / "log").read_text()
    assert "enable --now pi-links-scan.timer" in log and "start pi-links-scan.service" in log

    links = tmp / "etc/links.toml"
    links.write_text('[[link]]\nname = "Keep"\nport = 1000\n')
    result = run_script("install.sh", env, "\n\n\n\n")
    assert result.returncode == 0, result.stderr
    assert 'PI_LINKS_TITLE="Lab board"' in settings.read_text()
    assert 'PI_LINKS_SCAN_SCHEDULE="Sun 03:40"' in settings.read_text()
    assert "Keep" in links.read_text()


def test_installer_rejects_unsafe_title(installer_env):
    tmp, env = installer_env
    result = run_script("install.sh", env, '0.0.0.0\n8123\nbad"$(x)\nGood\nweekly\n')
    assert result.returncode == 0, result.stderr
    assert 'PI_LINKS_TITLE="Good"' in (tmp / "etc/settings.env").read_text()


def test_uninstaller_keeps_config_until_purge_and_repeats_safely(installer_env):
    tmp, env = installer_env
    assert run_script("install.sh", env, "0.0.0.0\n8123\nBoard\nweekly\n").returncode == 0
    settings = tmp / "etc/settings.env"
    settings.write_text(settings.read_text().replace(
        "/var/lib/pi-links/discovered.json", str(tmp / "state/discovered.json")))
    (tmp / "state").mkdir()
    (tmp / "state/discovered.json").write_text("{}")
    assert run_script("uninstall.sh", env).returncode == 0
    assert not (tmp / "units/pi-links.service").exists()
    assert not (tmp / "units/pi-links-scan.timer").exists()
    assert (tmp / "state/discovered.json").exists()
    assert (tmp / "etc/links.toml").exists()
    assert run_script("uninstall.sh", env, "", "--purge").returncode == 0
    assert not (tmp / "etc").exists()
    assert not (tmp / "state").exists()
    assert run_script("uninstall.sh", env, "", "--purge").returncode == 0
