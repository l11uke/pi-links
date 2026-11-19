# pi-links specification

Status: draft v5

## Purpose

Show one page of the web services and scheduled jobs on a Raspberry Pi, found
automatically, with owner changes on top.

## Scan

- Runs as root from `pi-links-scan.service`, started by `pi-links-scan.timer` on
  `PI_LINKS_SCAN_SCHEDULE`, and once by the installer.
- Web services: each TCP listener reachable from other devices (bound to a
  wildcard or a non-loopback address) is requested over HTTP, then HTTPS with
  certificate checks off. A response with HTML or a title counts. Ports 22, 53,
  111, the page's own port and well-known non-web daemons are skipped.
- Names come from a built-in list of common apps, then the page title (generic
  titles such as "Unauthorized" ignored), then the Docker container, then the
  process. Two finds with the same name keep the HTTP one.
- Timers: units whose file is in `/etc/systemd/system`, not disabled or masked,
  excluding pi-links' own. Group comes from a `project:` prefix in the
  description or the unit name prefix.
- Cron: every crontab in `/var/spool/cron/crontabs`, plus `/etc/crontab` and
  `/etc/cron.d/*` files no dpkg package owns. The task id is the script path,
  found by skipping wrappers such as flock and interpreters.
- Schedules are translated to plain English; anything unusual is shown as written.
- Writes JSON (`version`, `scanned_at`, `links`, `tasks`) atomically, mode 644.

## Page

- Shows scanned links and tasks merged with `links.toml`:
  - `[[link]]` with `port` changes the scanned link on that port (only the keys
    set), hides it with `hide = true`, or adds it if the scan did not find it.
  - `[[link]]` with `url` adds an external link.
  - `[[task]]` with `match` changes or hides the scanned task with that id.
  - `[[task]]` without `match` adds a task; `name` and `schedule` are required.
- Port links use the host from the browser's request.
- Links and tasks are grouped by `group`, groups in alphabetical order with
  "Services" and "Other" last, items in scan order within a group.
- A task with `status_file` shows its latest result: passed, failed, overdue,
  no result yet, or unreadable.
- Edits and new scans apply on the next page load. An invalid links file leaves
  the last good version in place and shows the problems.
- The footer shows the last scan time.
- `/healthz` returns `ok`.

Service health checks, run history beyond the latest result, logins and
browser-based editing are out of scope.

## Runtime

Python 3.11+ standard library. The page runs with `DynamicUser=yes`; only the
scan runs as root.

## Configuration

`settings.env` keys: `PI_LINKS_BIND`, `PI_LINKS_PORT`, `PI_LINKS_TITLE`,
`PI_LINKS_LINKS_FILE`, `PI_LINKS_DISCOVERY_FILE`, `PI_LINKS_SCAN_SCHEDULE`. The
project has no secrets, so it has no `secrets.env`.

`[[link]]` fields: `port` or `url`, `name`, `group`, `description`, `path`,
`scheme`, `hide`.

`[[task]]` fields: `match`, `hide`, `name`, `group`, `schedule`, `description`,
`status_file`, `status_max_age_hours`.

## Commands

- `python3 -m pi_links serve`
- `python3 -m pi_links check-config`
- `python3 -m pi_links scan` (root)
- `install.sh`, `uninstall.sh [--purge]`
