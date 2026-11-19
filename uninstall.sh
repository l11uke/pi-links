#!/usr/bin/env bash
# Removes the pi-links service. Add --purge to delete settings and links too.
set -euo pipefail

CONFIG_DIR="${PI_LINKS_CONFIG_DIR:-/etc/pi-links}"
UNIT_DIR="${PI_LINKS_UNIT_DIR:-/etc/systemd/system}"
UNIT_FILE="$UNIT_DIR/pi-links.service"
SCAN_SERVICE_FILE="$UNIT_DIR/pi-links-scan.service"
SCAN_TIMER_FILE="$UNIT_DIR/pi-links-scan.timer"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: run this with sudo" >&2
    exit 1
fi

systemctl disable --now pi-links-scan.timer 2>/dev/null || true
systemctl disable --now pi-links.service 2>/dev/null || true
rm -f "$UNIT_FILE" "$SCAN_SERVICE_FILE" "$SCAN_TIMER_FILE"
systemctl daemon-reload

if [[ "${1:-}" == "--purge" ]]; then
    discovery_file=""
    if [[ -f "$CONFIG_DIR/settings.env" ]]; then
        discovery_file="$(sed -n 's/^PI_LINKS_DISCOVERY_FILE=//p' "$CONFIG_DIR/settings.env" | tail -n 1)"
        discovery_file="${discovery_file%\"}"
        discovery_file="${discovery_file#\"}"
    fi
    if [[ -n "$discovery_file" ]]; then
        rm -f "$discovery_file"
        rmdir "$(dirname "$discovery_file")" 2>/dev/null || true
    fi
    rm -rf "$CONFIG_DIR"
    echo "Removed the services, the scan result and $CONFIG_DIR."
else
    echo "Removed the services. Your settings and links remain in $CONFIG_DIR."
fi
