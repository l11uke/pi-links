# pi-links

One page that lists the web services and scheduled jobs on a Raspberry Pi. A
weekly scan finds them, so a fresh install shows your Pi with no setup. A small
file lets you rename, regroup or hide what the scan finds, and add anything it
cannot see.

Each link uses the host name or IP you opened the page with, so the page works
however you reach the Pi. It uses the Python standard library and has no
database, JavaScript or external requests.

## Requirements

- Raspberry Pi OS Bookworm or newer, or another Linux system with systemd
- Python 3.11 or newer
- `git`, `ss` (from `iproute2`) and `sudo`
- Docker is optional; when present, the scan names services after their containers

## Install

```bash
sudo git clone https://github.com/OWNER/pi-links.git /opt/pi-links
sudo /opt/pi-links/install.sh
```

The installer asks for the listen address, port, page title and scan schedule,
starts the `pi-links` service, and runs the first scan. Open
`http://<your-pi>:<port>/`.

## What the scan finds

The scan runs as root on the schedule you chose (weekly by default) and writes
its result to `/var/lib/pi-links/discovered.json`. The web page only reads that
file.

| Finds | How | Leaves out |
| --- | --- | --- |
| Web services | Every TCP port other devices can reach that answers HTTP or HTTPS. The name comes from the page title, the Docker container or the process. Common apps such as Plex, Pi-hole and Grafana get their usual name, group and path. | Ports bound to localhost only, SSH, DNS, RPC, and ports that do not serve a web page |
| systemd timers | Timers in `/etc/systemd/system`, which is where you and your installers put them | Timers shipped by OS packages, and disabled timers |
| cron jobs | Every user's crontab, plus files in `/etc/cron.d` that no package owns | Package cron files and `run-parts` lines |

Schedules are written in plain English, such as "Mondays 10am" or "Every 6 hours".

To scan now, for example after installing something new:

```bash
sudo systemctl start pi-links-scan
```

To see what the scan found, with the port or id to use in `links.toml`:

```bash
cd /opt/pi-links && sudo python3 -B -m pi_links scan
```

## Change what the page shows

Edit `/etc/pi-links/links.toml`, save, and reload the page. `links.toml.example`
documents every field.

```toml
# Rename and regroup the service the scan found on port 8090
[[link]]
port = 8090
name = "Video library"
group = "Media"

# Leave a port off the page
[[link]]
port = 9100
hide = true

# Add an address the scan cannot see
[[link]]
name = "Router"
group = "Network"
url = "http://router.lan"

# Rename and regroup a scanned task, matched by the id the scan printed
[[task]]
match = "backup.timer"
name = "Nightly backup"
group = "Backups"

# Add a job that runs somewhere else
[[task]]
name = "Router reboot"
group = "Network"
schedule = "Sundays 4am"
```

If an edit has a mistake, the page keeps the last working version and shows what
to fix. A `match` that no longer matches anything is reported by `check-config`.

### Show when a job last passed

A task can show its latest result. Have the job write a small JSON file after
each run, readable by any user, and point `status_file` at it:

```json
{"checked_at": "2026-01-04T18:00:00+10:00", "ok": true, "summary": "3 of 3 OK"}
```

The page shows "Passed", "Failed", "Overdue" (no pass within
`status_max_age_hours`, default 192) or "No result yet".

## Settings

Settings live in `/etc/pi-links/settings.env`. Run the installer again to change
them. To validate everything without starting anything:

```bash
cd /opt/pi-links && python3 -B -m pi_links check-config
```

| Key | Default | Purpose |
| --- | --- | --- |
| `PI_LINKS_BIND` | `0.0.0.0` | IP address to listen on |
| `PI_LINKS_PORT` | `8090` | Port for the page |
| `PI_LINKS_TITLE` | `Raspberry Pi` | Page heading and tab title |
| `PI_LINKS_LINKS_FILE` | `/etc/pi-links/links.toml` | Your changes and additions |
| `PI_LINKS_DISCOVERY_FILE` | `/var/lib/pi-links/discovered.json` | Scan result |
| `PI_LINKS_SCAN_SCHEDULE` | `weekly` | systemd calendar expression for the scan |

## Upgrade

```bash
sudo git -C /opt/pi-links pull
sudo /opt/pi-links/install.sh
```

## Uninstall

```bash
sudo /opt/pi-links/uninstall.sh          # keeps /etc/pi-links
sudo /opt/pi-links/uninstall.sh --purge  # also deletes /etc/pi-links and the scan result
sudo rm -rf /opt/pi-links
```

## Security

The page has no login and uses plain HTTP. Anyone who can reach the port can see
your service names, ports and job schedules. Keep it on a trusted network and do
not forward the port from the internet.

The scan runs as root so it can see every process and crontab. It records names,
ports, schedules and script paths. It reads no secrets and never prints file
contents.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Page does not load | `systemctl status pi-links` and `journalctl -u pi-links -n 30` |
| Page says "Not scanned yet" | `sudo systemctl start pi-links-scan`, then `journalctl -u pi-links-scan -n 30` |
| A service is missing | It may listen on localhost only. Check with `sudo ss -tlnp`, or add it with a `[[link]]` entry |
| A link opens the wrong page | Set `path` for that port in `links.toml` |
| Installer says the port is in use | `sudo ss -tlnp` shows what holds it; choose another port |

## Development

```bash
python3 -m pytest -q
```

## License

MIT
