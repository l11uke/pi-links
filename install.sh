#!/usr/bin/env bash
# Installs or reconfigures pi-links. Safe to run again.
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${PI_LINKS_CONFIG_DIR:-/etc/pi-links}"
UNIT_DIR="${PI_LINKS_UNIT_DIR:-/etc/systemd/system}"
SETTINGS_FILE="$CONFIG_DIR/settings.env"
LINKS_FILE="$CONFIG_DIR/links.toml"
UNIT_FILE="$UNIT_DIR/pi-links.service"

die() {
    echo "Error: $*" >&2
    exit 1
}

existing() {
    local key="$1" fallback="$2" value=""
    if [[ -f "$SETTINGS_FILE" ]]; then
        value="$(sed -n "s/^${key}=//p" "$SETTINGS_FILE" | tail -n 1)"
        value="${value%\"}"
        value="${value#\"}"
    fi
    printf '%s' "${value:-$fallback}"
}

ask() {
    local label="$1" default="$2" answer
    read -r -p "$label [$default]: " answer || die "input ended before setup finished"
    printf '%s' "${answer:-$default}"
}

valid_bind() {
    python3 -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$1" 2>/dev/null
}

port_available() {
    local port="$1" current_port="$2"
    if [[ -z "$(ss -H -ltn "sport = :$port")" ]]; then
        return 0
    fi
    [[ "$port" == "$current_port" ]] && systemctl is-active --quiet pi-links.service
}

[[ "$(id -u)" -eq 0 ]] || die "run this with sudo"
[[ "$(uname -s)" == "Linux" ]] || die "pi-links needs Linux"
for tool in python3 systemctl ss sed; do
    command -v "$tool" >/dev/null || die "$tool is required"
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || die "Python 3.11 or newer is required"
[[ -f "$INSTALL_DIR/pi_links/__main__.py" ]] || die "run this from a complete pi-links clone"

current_port="$(existing PI_LINKS_PORT "")"

while true; do
    bind="$(ask "IP address to listen on" "$(existing PI_LINKS_BIND 0.0.0.0)")"
    valid_bind "$bind" && break
    echo "Enter an IP address, such as 0.0.0.0." >&2
done

while true; do
    port="$(ask "Port for the page" "$(existing PI_LINKS_PORT 8090)")"
    if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
        echo "Enter a port from 1 to 65535." >&2
    elif ! port_available "$port" "$current_port"; then
        echo "Port $port is in use. Choose another." >&2
    else
        break
    fi
done

while true; do
    title="$(ask "Page title" "$(existing PI_LINKS_TITLE "Raspberry Pi")")"
    if ((${#title} > 60)) || [[ "$title" == *[\"\$\`\\]* ]]; then
        echo "Use up to 60 characters, without quotes, dollar signs, backticks or backslashes." >&2
    else
        break
    fi
done

install -d -m 755 "$CONFIG_DIR" "$UNIT_DIR"

settings_tmp="$(mktemp "$CONFIG_DIR/.settings.XXXXXX")"
cat >"$settings_tmp" <<EOF
# Written by pi-links install.sh. Re-run the installer to change these.
PI_LINKS_BIND="$bind"
PI_LINKS_PORT="$port"
PI_LINKS_TITLE="$title"
PI_LINKS_LINKS_FILE="$LINKS_FILE"
EOF
chmod 644 "$settings_tmp"
mv "$settings_tmp" "$SETTINGS_FILE"

if [[ ! -f "$LINKS_FILE" ]]; then
    install -m 644 "$INSTALL_DIR/links.toml.example" "$LINKS_FILE"
fi
chmod 644 "$LINKS_FILE"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    chown "$SUDO_USER" "$LINKS_FILE"
fi

(cd "$INSTALL_DIR" && python3 -B -m pi_links --settings "$SETTINGS_FILE" check-config >/dev/null)

python_path="$(command -v python3)"
sed -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
    -e "s|@PYTHON@|$python_path|g" \
    "$INSTALL_DIR/systemd/pi-links.service.template" >"$UNIT_FILE"
chmod 644 "$UNIT_FILE"

systemctl daemon-reload
systemctl enable pi-links.service >/dev/null
systemctl restart pi-links.service

if [[ "${PI_LINKS_SKIP_HEALTHCHECK:-}" != "1" ]]; then
    case "$bind" in
        0.0.0.0) health_host="127.0.0.1" ;;
        ::) health_host="[::1]" ;;
        *:*) health_host="[$bind]" ;;
        *) health_host="$bind" ;;
    esac
    healthy=no
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2)' \
            "http://$health_host:$port/healthz" 2>/dev/null; then
            healthy=yes
            break
        fi
        sleep 1
    done
    [[ "$healthy" == "yes" ]] || die "service did not respond. Run: journalctl -u pi-links -n 30"
fi

echo "pi-links is running on port $port."
echo "Edit your links in $LINKS_FILE, then reload the page."
