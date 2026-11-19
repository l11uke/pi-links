#!/usr/bin/env bash
# Removes the pi-links service. Add --purge to delete settings and links too.
set -euo pipefail

CONFIG_DIR="${PI_LINKS_CONFIG_DIR:-/etc/pi-links}"
UNIT_DIR="${PI_LINKS_UNIT_DIR:-/etc/systemd/system}"
UNIT_FILE="$UNIT_DIR/pi-links.service"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Error: run this with sudo" >&2
    exit 1
fi

systemctl disable --now pi-links.service 2>/dev/null || true
rm -f "$UNIT_FILE"
systemctl daemon-reload

if [[ "${1:-}" == "--purge" ]]; then
    rm -rf "$CONFIG_DIR"
    echo "Removed the service and $CONFIG_DIR."
else
    echo "Removed the service. Your settings and links remain in $CONFIG_DIR."
fi
