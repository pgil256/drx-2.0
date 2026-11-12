#!/usr/bin/env bash
set -euo pipefail

# Run on the Pi with sudo: sudo bash install.sh [--uninstall]
#
# Installs the touchscreen watchdog as a root systemd service. The script is
# copied to /usr/local/sbin so the service does not depend on which KneeSpa
# tree is on the unit or which version the chooser starts; run this installer
# again after updating touch_watchdog.py.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/touch_watchdog.py"
TARGET="/usr/local/sbin/kneespa-touch-watchdog"
SERVICE="kneespa-touch-watchdog.service"
UNIT="/etc/systemd/system/$SERVICE"

if [[ "$EUID" -ne 0 ]]; then
    echo "Run this installer with sudo: sudo bash install.sh" >&2
    exit 1
fi
command -v systemctl >/dev/null 2>&1 || { echo "systemd is required." >&2; exit 1; }

case "${1:-}" in
    --uninstall)
        systemctl disable --now "$SERVICE" >/dev/null 2>&1 || true
        rm -f -- "$UNIT" "$TARGET"
        systemctl daemon-reload
        echo "Removed $SERVICE and $TARGET."
        exit 0 ;;
    "") ;;
    *) echo "Usage: sudo bash install.sh [--uninstall]" >&2; exit 2 ;;
esac

[[ -f "$SOURCE" ]] || { echo "Cannot find $SOURCE" >&2; exit 1; }
PYTHON="$(command -v python3)" || { echo "Python 3 is required." >&2; exit 1; }
"$PYTHON" -m py_compile "$SOURCE"

install -o root -g root -m 0755 "$SOURCE" "$TARGET"
cat > "$UNIT" <<EOF
[Unit]
Description=KneeSpa touchscreen USB watchdog
Documentation=file://$SCRIPT_DIR/README.md

[Service]
ExecStart=$PYTHON -u $TARGET run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 "$UNIT"

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
systemctl restart "$SERVICE"

echo "Installed and started $SERVICE."
echo "Current state:"
"$PYTHON" "$TARGET" status || true
echo
echo "What it has done:  journalctl -u $SERVICE"
echo "Remove it:         sudo bash $SCRIPT_DIR/install.sh --uninstall"
