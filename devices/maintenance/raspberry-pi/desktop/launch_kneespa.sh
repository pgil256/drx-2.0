#!/usr/bin/env bash
set -euo pipefail
umask 077

# install.sh creates the desktop shortcut for this deployed Pi repository.
APP_DIR="${KNEESPA_APP_DIR:-/home/pi/drx}"

fail() {
    printf 'KneeSpa: %s\n' "$1" >&2
    if command -v zenity >/dev/null 2>&1; then
        zenity --error --no-markup --title="KneeSpa" --text="$1" 2>/dev/null || true
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center -title "KneeSpa" "$1" 2>/dev/null || true
    elif command -v notify-send >/dev/null 2>&1; then
        notify-send --urgency=critical "KneeSpa" "$1" 2>/dev/null || true
    fi
    exit 1
}

[[ -f "$APP_DIR/runtime/raspberry-pi/main/kneespa.py" ]] ||
    fail "Cannot find KneeSpa in $APP_DIR. Check KNEESPA_APP_DIR or reinstall the shortcut."
APP_DIR="$(cd -- "$APP_DIR" && pwd)"

# A service started outside this launcher does not share its desktop lock.
if command -v systemctl >/dev/null 2>&1 &&
    systemctl is-active --quiet kneespa.service 2>/dev/null; then
    fail "KneeSpa is already running through kneespa.service. Use the existing app window."
fi

# Use an explicit interpreter; virtual-environment activation is unnecessary.
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
[[ -n "$PYTHON" && -x "$PYTHON" && ! -d "$PYTHON" ]] ||
    fail "Python was not found. Install Python 3 or set KNEESPA_PYTHON to its full path."

# Resolve relative state paths from the same working directory used by the app.
cd -- "$APP_DIR/runtime/raspberry-pi/main" || fail "Cannot open the app directory."
DEVICE_DIR="${KNEESPA_DEVICE_DIR:-$APP_DIR/devices/local}"
LOG_DIR="$DEVICE_DIR/raspberry-pi/logs"
mkdir -p -- "$LOG_DIR" || fail "Cannot create the startup log directory: $LOG_DIR"

command -v flock >/dev/null 2>&1 || fail "The launcher needs flock (the util-linux package)."
exec 9>"$LOG_DIR/desktop-launch.lock" || fail "Cannot open the desktop launcher lock."
if flock --exclusive --nonblock --conflict-exit-code 10 9; then
    :
else
    lock_status=$?
    if [[ "$lock_status" -eq 10 ]]; then
        fail "KneeSpa is already open or a firmware update is running. Close it or wait for the update."
    fi
    fail "Cannot lock the desktop launcher (exit $lock_status)."
fi

# Keep the current and previous desktop sessions, including early import errors.
LOG_FILE="$LOG_DIR/desktop-launch.log"
if [[ -f "$LOG_FILE" ]]; then
    mv -f -- "$LOG_FILE" "$LOG_FILE.previous" || fail "Cannot rotate the startup log."
fi
exec >"$LOG_FILE" 2>&1 || fail "Cannot write the startup log: $LOG_FILE"
printf 'KneeSpa desktop launch: %s\nPython: %s\nApp: %s\n' \
    "$(date --iso-8601=seconds)" "$PYTHON" "$APP_DIR"

# Inherit the desktop display session and retain the lock across app restarts.
exec "$PYTHON" -u kneespa.py "$@"
