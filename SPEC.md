# pi-links specification

Status: draft v3

## Purpose

Serve one page of links to the web services on a Raspberry Pi, plus a list of
its scheduled jobs.

## Scope

- Links are defined in a TOML file outside the repo.
- A port link uses the host from the browser's request, so no IP or host name is
  stored for services on the Pi.
- A URL link holds a full http or https address.
- Links are grouped by `group`, in first-seen order.
- Edits apply on the next page load. An invalid edit leaves the last good list in
  place and shows the problems on the page.
- Scheduled jobs are listed from `[[task]]` entries, with schedule text written
  by the owner, grouped by `group` in first-seen order. They are not clickable.
- `/healthz` returns `ok`.

Service status checks, job run history, logins and browser-based editing are out
of scope for v2.

## Runtime

Python 3.11+ standard library, run by systemd with `DynamicUser=yes`.

## Configuration

`settings.env` keys: `PI_LINKS_BIND`, `PI_LINKS_PORT`, `PI_LINKS_TITLE`,
`PI_LINKS_LINKS_FILE`. The project has no secrets, so it has no `secrets.env`.

`links.toml` fields: `name`, `group`, `description`, `port`, `path`, `scheme`,
`url`. Each link sets exactly one of `port` or `url`.

`[[task]]` fields: `name`, `group`, `schedule`, `description`. `name` and `schedule` are
required.

## Commands

- `python3 -m pi_links serve`
- `python3 -m pi_links check-config`
- `install.sh`, `uninstall.sh [--purge]`
