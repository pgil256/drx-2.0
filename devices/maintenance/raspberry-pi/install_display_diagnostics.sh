#!/usr/bin/env bash
set -euo pipefail

# Install two double-clickable Raspberry Pi desktop launchers for the read-only
# display diagnostic collector.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/collect_display_diagnostics.sh"
INSTALL_DIR="$HOME/.local/bin"
TARGET="$INSTALL_DIR/kneespa-display-diagnostics"

if [[ ! -f "$SOURCE" ]]; then
    echo "Cannot find $SOURCE" >&2
    exit 1
fi

if command -v xdg-user-dir >/dev/null 2>&1; then
    DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
fi
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"

mkdir -p "$INSTALL_DIR" "$DESKTOP_DIR"
install -m 0755 "$SOURCE" "$TARGET"

BASELINE_LAUNCHER="$DESKTOP_DIR/KneeSpa Collect Display Baseline.desktop"
FAILURE_LAUNCHER="$DESKTOP_DIR/KneeSpa Capture Display Failure.desktop"

cat > "$BASELINE_LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=KneeSpa - Collect Display Baseline
Comment=Save a complete healthy display, touchscreen, USB, and power report
Exec="$TARGET" --baseline
Icon=utilities-system-monitor
Terminal=true
StartupNotify=false
Categories=System;
EOF

cat > "$FAILURE_LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=KneeSpa - Capture Display Failure
Comment=Capture display and touchscreen evidence before unplugging cables
Exec="$TARGET" --failure
Icon=dialog-warning
Terminal=true
StartupNotify=false
Categories=System;
EOF

chmod 0755 "$BASELINE_LAUNCHER" "$FAILURE_LAUNCHER"

# GNOME-derived desktops may require launchers to be marked as trusted.
if command -v gio >/dev/null 2>&1; then
    gio set "$BASELINE_LAUNCHER" metadata::trusted true >/dev/null 2>&1 || true
    gio set "$FAILURE_LAUNCHER" metadata::trusted true >/dev/null 2>&1 || true
fi

echo "Installed desktop launchers:"
echo "  $BASELINE_LAUNCHER"
echo "  $FAILURE_LAUNCHER"
echo
echo "Reports will be saved under:"
echo "  $HOME/KneeSpa-display-diagnostics"
echo
echo "Run the baseline launcher while everything is working."
echo "Run the failure launcher before unplugging any cables when possible."
echo "Your desktop may ask you to trust or allow each launcher the first time."

if [[ -t 0 ]]; then
    read -r -p "Press Enter to close this window..." _
fi
