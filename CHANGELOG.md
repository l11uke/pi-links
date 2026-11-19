# Changelog

## 2026-11-19 — 0.5.0

- Added a scan that finds web services, systemd timers and cron jobs on its own,
  run by `pi-links-scan.timer` (weekly by default) and once at install.
- `links.toml` now changes what the scan finds: match links by `port` and tasks
  by `match`, hide either with `hide = true`, or add items the scan cannot see.
  A port link no longer needs `name`.
- New settings: `PI_LINKS_DISCOVERY_FILE`, `PI_LINKS_SCAN_SCHEDULE`. The
  installer asks for the scan schedule.
- New command: `python3 -m pi_links scan`.
- The footer shows when the last scan ran.
- Smaller text across the page.

## 2026-11-19 — 0.4.0

- Added `status_file` and `status_max_age_hours` to `[[task]]`. A task shows when
  it last passed, or that it failed, is overdue or has no result yet.

## 2026-11-19 — 0.3.1

- Smaller text and spacing in the Scheduled tasks section.

## 2026-11-19 — 0.3.0

- Added a `group` field to `[[task]]`. Scheduled tasks are shown under a heading
  for each project.

## 2026-11-19 — 0.2.0

- Added `[[task]]` entries and a "Scheduled tasks" section for jobs with no web page.

## 2026-11-19 — 0.1.0

- First release: links page, TOML link list with live reload, `check-config`,
  installer, uninstaller and systemd service.
