# pi-links

A single page of links to the web services running on a Raspberry Pi. You list
your services in one file. The page builds each address from the host name or
IP you used to open it, so the same list works however you reach the Pi.

It uses the Python standard library and has no database, JavaScript or external
requests.

## Requirements

- Raspberry Pi OS Bookworm or newer, or another Linux system with systemd
- Python 3.11 or newer
- `git`, `ss` (from `iproute2`) and `sudo`

## Install

```bash
sudo git clone https://github.com/OWNER/pi-links.git /opt/pi-links
sudo /opt/pi-links/install.sh
```

The installer asks for the listen address, port and page title, then starts the
`pi-links` service. Open `http://<your-pi>:<port>/`.

## Configure

Links live in `/etc/pi-links/links.toml`. Save the file and reload the page.

```toml
[[link]]
name = "Grafana"
group = "Monitoring"
description = "Dashboards"
port = 3000

[[link]]
name = "Project source"
group = "Reference"
url = "https://example.com/my-project"
```

Jobs with no web page go in the same file and appear under "Scheduled tasks".
The page shows the schedule you write; it does not read cron or systemd.

```toml
[[task]]
name = "Weekly report"
schedule = "Mondays 8am"
description = "Emails a summary"
```

`links.toml.example` documents every field. If an edit has a mistake, the page
keeps the last working list and shows what to fix.

Settings live in `/etc/pi-links/settings.env`. Run the installer again to change
them. To validate everything without starting the service:

```bash
cd /opt/pi-links && python3 -B -m pi_links check-config
```

| Key | Default | Purpose |
| --- | --- | --- |
| `PI_LINKS_BIND` | `0.0.0.0` | IP address to listen on |
| `PI_LINKS_PORT` | `8090` | Port for the page |
| `PI_LINKS_TITLE` | `Raspberry Pi` | Page heading and tab title |
| `PI_LINKS_LINKS_FILE` | `/etc/pi-links/links.toml` | Links file |

## Upgrade

```bash
sudo git -C /opt/pi-links pull
sudo /opt/pi-links/install.sh
```

## Uninstall

```bash
sudo /opt/pi-links/uninstall.sh          # keeps /etc/pi-links
sudo /opt/pi-links/uninstall.sh --purge  # deletes /etc/pi-links too
sudo rm -rf /opt/pi-links
```

## Security

The page has no login and uses plain HTTP. Anyone who can reach the port can see
your service names and ports. Keep it on a trusted network and do not forward the
port from the internet.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Page does not load | `systemctl status pi-links` and `journalctl -u pi-links -n 30` |
| Installer says the port is in use | `sudo ss -tlnp` shows what holds it; choose another port |
| A link fails | Confirm the service port with `sudo ss -tlnp`, then correct `links.toml` |

## Development

```bash
python3 -m pytest -q
```

## License

MIT
