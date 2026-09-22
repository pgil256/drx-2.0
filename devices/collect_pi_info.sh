#!/usr/bin/env bash
# Read-only Pi and KneeSpa dependency inventory. Run as the desktop user, without sudo.
set -u

case "${1:-}" in
    --help|-h)
        printf 'Usage: bash devices/collect_pi_info.sh\n'
        printf 'Print Pi, OS, Python, and firmware-tool information for update planning.\n'
        printf 'No packages are installed, services changed, or serial ports opened.\n'
        exit 0 ;;
    "") ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac
if (( $# > 0 )); then
    printf 'This script does not accept positional arguments.\n' >&2
    exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${KNEESPA_APP_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"

section() { printf '\n=== %s ===\n' "$1"; }

section 'COLLECTED'
date -Is
printf 'Project: %s\n' "$APP_DIR"

section 'PI MODEL'
if [[ -r /proc/device-tree/model ]]; then
    tr -d '\0' < /proc/device-tree/model
    printf '\n'
else
    printf 'Pi model information unavailable. Run this script on the Raspberry Pi.\n'
fi

section 'OPERATING SYSTEM'
if [[ -r /etc/os-release ]]; then
    cat /etc/os-release
fi
uname -rm
printf 'Userspace bits: '
getconf LONG_BIT

section 'MEMORY AND STORAGE'
free -h
df -h / /boot 2>/dev/null

section 'DESKTOP SESSION'
printf 'Session: %s\nDesktop: %s\n' \
    "${XDG_SESSION_TYPE:-unknown}" "${XDG_CURRENT_DESKTOP:-unknown}"
printf 'An SSH session may not report the Pi desktop session.\n'

section 'SYSTEM PACKAGES'
if command -v dpkg-query >/dev/null 2>&1; then
    dpkg-query -W -f='${Package} ${Version} ${Status}\n' \
        python3 python3-venv python3-pyqt5 python3-rpi.gpio \
        python3-rpi-lgpio libvlc5 vlc 2>/dev/null
    printf 'Missing packages may be omitted above.\n'
else
    printf 'dpkg-query is unavailable.\n'
fi

section 'PYTHON ENVIRONMENTS'
declare -A seen_python=()
for py in "${KNEESPA_PYTHON:-}" /usr/bin/python3 \
    "$(command -v python3 2>/dev/null || true)" \
    "$APP_DIR/kneespa_env/bin/python" "$APP_DIR/.venv/bin/python" \
    "$HOME/kneespa_env/bin/python" \
    "$HOME/drx/kneespa_env/bin/python" "$HOME/drx/.venv/bin/python" \
    "$HOME/drx-2.0/kneespa_env/bin/python" "$HOME/drx-2.0/.venv/bin/python"; do
    [[ -n "$py" && -x "$py" && ! -d "$py" ]] || continue
    [[ -z "${seen_python[$py]:-}" ]] || continue
    seen_python["$py"]=1
    printf '\nInterpreter: %s\n' "$py"
    "$py" --version
    if packages="$("$py" -m pip list --disable-pip-version-check --format=freeze 2>/dev/null)"; then
        printf '%s\n' "$packages" |
            grep -Ei '^(pip|setuptools|PyQt5(-Qt5|-sip)?|RPi.GPIO|rpi-lgpio|pyserial|python-dotenv|configparser|python-vlc|platformio)=' ||
            printf 'No matching pip packages found.\n'
    else
        printf 'pip inventory unavailable for this interpreter.\n'
    fi
done

section 'FIRMWARE BUILD TOOL'
declare -A seen_pio=()
for pio in "${KNEESPA_PIO:-}" "$(command -v pio 2>/dev/null || true)" \
    "$HOME/.platformio/penv/bin/pio" \
    "$HOME/.local/share/kneespa/platformio/bin/pio"; do
    [[ -n "$pio" && -x "$pio" && ! -d "$pio" ]] || continue
    [[ -z "${seen_pio[$pio]:-}" ]] || continue
    seen_pio["$pio"]=1
    printf '\nTool: %s\n' "$pio"
    "$pio" --version
done
if (( ${#seen_pio[@]} == 0 )); then
    printf 'PlatformIO not found in the usual locations.\n'
fi

section 'SERIAL DEVICE PATHS'
shopt -s nullglob
ports=(/dev/ttyACM* /dev/ttyUSB*)
if [[ -e /dev/serial0 || -L /dev/serial0 ]]; then
    ports=(/dev/serial0 "${ports[@]}")
fi
if (( ${#ports[@]} )); then
    ls -l -- "${ports[@]}"
else
    printf 'No standard Pi UART or USB serial paths found.\n'
fi

section 'DONE'
printf 'Send this output along with how you normally start KneeSpa.\n'
