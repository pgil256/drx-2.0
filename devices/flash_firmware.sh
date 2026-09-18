#!/usr/bin/env bash
# Build and flash the checked-out Mega firmware over USB; run as pi, not sudo.
set -euo pipefail
umask 077

APP_DIR="${KNEESPA_APP_DIR:-/home/pi/drx}"
SERVICE="${KNEESPA_SERVICE:-kneespa.service}"
PORT=""
case "${1:-}" in
    --help|-h)
        echo "Usage: bash flash_firmware.sh [--port /dev/ttyACM0]"
        echo "Defaults to /home/pi/drx; detects a Mega or shows a USB port picker."
        exit 0 ;;
    --port)
        [[ $# -eq 2 && -n "$2" ]] || { echo "--port needs one device path." >&2; exit 2; }
        PORT="$2" ;;
    "") ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

finish() {
    status=$?
    trap - EXIT
    if (( status != 0 )); then
        printf '\nFirmware update did not complete (exit %s). KneeSpa has not been restarted.\n' \
            "$status" >&2
    fi
    if [[ -t 0 ]]; then
        read -r -p "You can close this window, or press Enter... " _ || true
    fi
    exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }

[[ "$EUID" -ne 0 ]] || fail "Run as the desktop user, without sudo."
[[ -f "$APP_DIR/runtime/arduino/motor/platformio.ini" &&
   -f "$APP_DIR/runtime/arduino/motor/motor.ino" ]] || fail "Firmware not found in $APP_DIR."
APP_DIR="$(cd -- "$APP_DIR" && pwd)"
FIRMWARE_DIR="$APP_DIR/runtime/arduino/motor"
for command in python3 sudo flock systemctl; do
    command -v "$command" >/dev/null || fail "Required program is missing: $command"
done

STATE_DIR="${KNEESPA_DEVICE_DIR:-$APP_DIR/devices/local}/raspberry-pi"
mkdir -p -- "$STATE_DIR/logs" "$STATE_DIR/firmware"
exec 9>"$STATE_DIR/logs/desktop-launch.lock"
flock --exclusive --nonblock 9 || fail "Close the KneeSpa app or other firmware window first."
RECORD_DIR="$(mktemp -d "$STATE_DIR/firmware/$(date +%Y%m%d-%H%M%S)-XXXXXX")"
exec > >(tee "$RECORD_DIR/flash.log") 2>&1
printf 'Firmware source: %s\nUpdate record: %s\n' "$FIRMWARE_DIR" "$RECORD_DIR"
echo "Connect the Mega by USB. Perform this maintenance with the device unoccupied."

# First-click setup uses a private environment, leaving the app's Python alone.
packages=()
command -v fuser >/dev/null || packages+=(psmisc)
command -v zenity >/dev/null || packages+=(zenity)
PIO="${KNEESPA_PIO:-}"
if [[ -z "$PIO" ]]; then
    for candidate in "$(command -v pio || true)" "$HOME/.platformio/penv/bin/pio" \
        "$HOME/.local/share/kneespa/platformio/bin/pio"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            PIO="$candidate"
            break
        fi
    done
fi
if [[ -z "$PIO" ]] && ! python3 -c 'import ensurepip, venv' >/dev/null 2>&1; then
    packages+=(python3-venv)
fi
if (( ${#packages[@]} )); then
    echo "Installing firmware tools. The system may ask for your pi password."
    sudo apt-get update
    sudo apt-get install -y "${packages[@]}"
fi
if [[ -z "$PIO" ]]; then
    TOOL_ENV="$HOME/.local/share/kneespa/platformio"
    python3 -m venv "$TOOL_ENV"
    "$TOOL_ENV/bin/python" -m pip install platformio
    PIO="$TOOL_ENV/bin/pio"
fi
[[ -x "$PIO" && ! -d "$PIO" ]] || fail "Cannot run PlatformIO: $PIO"

if [[ -z "$PORT" ]]; then
    "$PIO" device list --json-output > "$RECORD_DIR/ports.json"
    python3 - "$RECORD_DIR/ports.json" > "$RECORD_DIR/ports.tsv" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    ports = json.load(stream)
for port in ports:
    device = port.get("port", "")
    if not re.fullmatch(r"/dev/tty(?:ACM|USB)\d+", device):
        continue
    description = str(port.get("description", "USB serial")).replace("\t", " ")
    description = description.replace("\n", " ").replace("\r", " ")
    known_mega = "VID:PID=2341:0042" in str(port.get("hwid", "")).upper()
    print(device, description, int(known_mega), sep="\t")
PY
    choices=()
    known_ports=()
    while IFS=$'\t' read -r device description known; do
        [[ -n "$device" ]] || continue
        choices+=("$device" "$description")
        [[ "$known" != 1 ]] || known_ports+=("$device")
    done < "$RECORD_DIR/ports.tsv"
    (( ${#choices[@]} )) || fail "No USB serial board found. Connect the Mega's USB cable and retry."
    if (( ${#known_ports[@]} == 1 )); then
        PORT="${known_ports[0]}"
    else
        PORT="$(zenity --list --title="Select the KneeSpa Arduino Mega" \
            --text="Select the USB port connected to the KneeSpa Mega 2560." \
            --column="Port" --column="Device" --width=650 --height=300 "${choices[@]}")" ||
            fail "No board selected; nothing was flashed."
    fi
fi
[[ -c "$PORT" && -r "$PORT" && -w "$PORT" ]] ||
    fail "Cannot access $PORT. Check the USB connection and pi's serial-port permissions."
PORT="$(readlink -f -- "$PORT")"
case "$PORT" in
    /dev/ttyAMA*|/dev/ttyS*) fail "Use the Mega's USB port, not the Pi GPIO serial port." ;;
esac
printf 'Upload port: %s\n' "$PORT"

# A fresh build prevents reuse of a stale .hex copied from another checkout.
export PLATFORMIO_CORE_DIR="${PLATFORMIO_CORE_DIR:-$HOME/.platformio}"
export PLATFORMIO_WORKSPACE_DIR="$APP_DIR/.cache/firmware-platformio"
export PLATFORMIO_BUILD_DIR="$PLATFORMIO_WORKSPACE_DIR/build"
"$PIO" run --project-dir "$FIRMWARE_DIR" --environment mega --target clean
"$PIO" run --project-dir "$FIRMWARE_DIR" --environment mega
CURRENT_HEX="$PLATFORMIO_BUILD_DIR/mega/firmware.hex"
[[ -s "$CURRENT_HEX" ]] || fail "The build produced no firmware.hex."
cp -- "$CURRENT_HEX" "$RECORD_DIR/current.hex"
sha256sum "$FIRMWARE_DIR/motor.ino" "$FIRMWARE_DIR/hx711_sampler.h" \
    "$FIRMWARE_DIR/platformio.ini" "$RECORD_DIR/current.hex" > "$RECORD_DIR/sha256.txt"

# Use the same uploader, protocol and speed as PlatformIO's megaatmega2560 board.
AVRDUDE_DIR="$PLATFORMIO_CORE_DIR/packages/tool-avrdude"
AVRDUDE="$AVRDUDE_DIR/avrdude"
[[ -x "$AVRDUDE" ]] || AVRDUDE="$AVRDUDE_DIR/bin/avrdude"
[[ -x "$AVRDUDE" && -f "$AVRDUDE_DIR/avrdude.conf" ]] ||
    fail "Cannot find PlatformIO's avrdude package in $AVRDUDE_DIR."
UPLOAD=("$AVRDUDE" -C "$AVRDUDE_DIR/avrdude.conf" -p atmega2560 \
    -c wiring -P "$PORT" -b 115200 -D)

# Compile before stopping the service; leave it stopped for the hardware checkout.
sudo -v
service_state="$(systemctl show --property=ActiveState --value "$SERVICE")"
case "$service_state" in
    active|activating|reloading|deactivating)
        sudo systemctl stop "$SERVICE"
        service_state="$(systemctl show --property=ActiveState --value "$SERVICE")" ;;
esac
[[ "$service_state" == inactive || "$service_state" == failed ]] ||
    fail "The service is not stopped: $SERVICE ($service_state)."
ports_to_check=("$PORT")
[[ ! -e /dev/serial0 ]] || ports_to_check+=(/dev/serial0)
if sudo fuser -- "${ports_to_check[@]}"; then
    fail "A process still owns a serial port. Close KneeSpa or the serial monitor and retry."
else
    owner_status=$?
    [[ "$owner_status" -eq 1 ]] || fail "Could not check serial-port ownership."
fi

echo "Backing up the firmware already on the Mega..."
"${UPLOAD[@]}" -U "flash:r:$RECORD_DIR/previous.hex:i"
[[ -s "$RECORD_DIR/previous.hex" ]] || fail "No firmware backup was produced; upload cancelled."
echo "Writing and verifying the newly built firmware..."
"${UPLOAD[@]}" -U "flash:w:$RECORD_DIR/current.hex:i"
echo "SUCCESS: firmware written and verified. KneeSpa remains stopped."
printf 'Backup and upload log: %s\n' "$RECORD_DIR"
echo "Complete the firmware boot/hardware checkout, then open KneeSpa from its desktop icon."
