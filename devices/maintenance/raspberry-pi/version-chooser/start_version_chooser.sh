#!/usr/bin/env bash
set -euo pipefail
umask 077

# Started at desktop login by install.sh's autostart entry, and by its shortcut.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${KNEESPA_APP_DIR:-/home/pi/drx}"

fail() {
    printf 'KneeSpa version chooser: %s\n' "$1" >&2
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --no-markup --title="KneeSpa" --text="$1" 2>/dev/null || true
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center -title "KneeSpa" "$1" 2>/dev/null || true
    fi
    exit 1
}

[[ -d "$APP_DIR" ]] || fail "Cannot find $APP_DIR. Check KNEESPA_APP_DIR or reinstall."
APP_DIR="$(cd -- "$APP_DIR" && pwd)"
export KNEESPA_APP_DIR="$APP_DIR"

# The chooser needs only PyQt5; use the same interpreter order as the app launcher.
PYTHON="${KNEESPA_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    for candidate in "$APP_DIR/kneespa_env/bin/python" \
        "$APP_DIR/.venv/bin/python" "$HOME/kneespa_env/bin/python"; do
        if [[ -x "$candidate" && ! -d "$candidate" ]]; then
            PYTHON="$candidate"
            break
        fi
    done
    PYTHON="${PYTHON:-$(command -v python3 || true)}"
fi
[[ -n "$PYTHON" && -x "$PYTHON" ]] || fail "Python 3 was not found. Set KNEESPA_PYTHON."

LOG_DIR="${KNEESPA_DEVICE_DIR:-$APP_DIR/devices/local}/raspberry-pi/logs"
mkdir -p -- "$LOG_DIR" || fail "Cannot create the log directory: $LOG_DIR"
LOG_FILE="$LOG_DIR/version-chooser.log"
if [[ -f "$LOG_FILE" ]]; then
    mv -f -- "$LOG_FILE" "$LOG_FILE.previous" || fail "Cannot rotate $LOG_FILE."
fi
exec >"$LOG_FILE" 2>&1 || fail "Cannot write $LOG_FILE."
printf 'KneeSpa version chooser: %s\nPython: %s\n' "$(date --iso-8601=seconds)" "$PYTHON"

# The chooser shows its own errors, then replaces itself with the chosen app.
exec "$PYTHON" -u "$SCRIPT_DIR/version_chooser.py" "$@"
