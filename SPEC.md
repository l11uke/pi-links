# pi-links specification

Status: draft v1

## Purpose

Serve one page of links to the web services on a Raspberry Pi.

## Scope

- Links are defined in a TOML file outside the repo.
- A port link uses the host from the browser's request, so no IP or host name is
  stored for services on the Pi.
- A URL link holds a full http or https address.
- Links are grouped by `group`, in first-seen order.
- Edits apply on the next page load. An invalid edit leaves the last good list in
  place and shows the problems on the page.
- `/healthz` returns `ok`.

Service status checks, logins and browser-based editing are out of scope for v1.

## Runtime

Python 3.11+ standard library, run by systemd with `DynamicUser=yes`.

## Configuration

`settings.env` keys: `PI_LINKS_BIND`, `PI_LINKS_PORT`, `PI_LINKS_TITLE`,
`PI_LINKS_LINKS_FILE`. The project has no secrets, so it has no `secrets.env`.

`links.toml` fields: `name`, `group`, `description`, `port`, `path`, `scheme`,
`url`. Each link sets exactly one of `port` or `url`.

## Commands

- `python3 -m pi_links serve`
- `python3 -m pi_links check-config`
- `install.sh`, `uninstall.sh [--purge]`
