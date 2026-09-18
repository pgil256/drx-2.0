#!/usr/bin/env bash
set -euo pipefail

# Run on the Pi as pi, without sudo. These are the deployed Pi paths.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${KNEESPA_APP_DIR:-/home/pi/drx}"
DESKTOP_DIR="${KNEESPA_DESKTOP_DIR:-/home/pi/Desktop}"
LAUNCHER="$SCRIPT_DIR/launch_kneespa.sh"
FLASHER="$APP_DIR/devices/flash_firmware.sh"

if [[ "$EUID" -eq 0 ]]; then
    echo "Run this installer as the desktop user, without sudo." >&2
    exit 1
fi
if [[ ! -f "$APP_DIR/runtime/raspberry-pi/main/kneespa.py" || ! -f "$LAUNCHER" ||
      ! -f "$FLASHER" || ! -f "$APP_DIR/devices/install_kneespa_desktop.sh" ||
      ! -f "$APP_DIR/devices/Install KneeSpa.desktop" ]]; then
    echo "Cannot find the app or installer files in $APP_DIR. Copy the devices launchers too." >&2
    exit 1
fi
APP_DIR="$(cd -- "$APP_DIR" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required." >&2; exit 1; }

MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p -- "$DESKTOP_DIR" "$MENU_DIR"
chmod 0755 "$LAUNCHER" "$FLASHER" "$APP_DIR/devices/install_kneespa_desktop.sh" \
    "$APP_DIR/devices/Install KneeSpa.desktop"

python3 - "$DESKTOP_DIR/KneeSpa.desktop" "$MENU_DIR/kneespa.desktop" \
    "$LAUNCHER" "$APP_DIR" <<'PY'
import pathlib
import sys


def exec_argument(value: str) -> str:
    """Quote one Exec argument using Desktop Entry escaping, not shell quoting."""
    value = value.replace("\\", "\\\\")
    for character in ('"', '`', '$'):
        value = value.replace(character, "\\" + character)
    value = value.replace("\\", "\\\\").replace("%", "%%")
    return '"' + value + '"'


desktop, menu, launcher, app_dir = sys.argv[1:]
if any(character in launcher + app_dir for character in "\n\r\t"):
    raise SystemExit("The launcher and repository paths must not contain tabs or newlines.")
icon = pathlib.Path(app_dir) / "runtime/raspberry-pi/main/ui/media/images/logos/knee.png"
icon_value = str(icon).replace("\\", "\\\\") if icon.is_file() else "applications-science"
command = " ".join(exec_argument(arg) for arg in (
    "/usr/bin/env", "KNEESPA_APP_DIR=" + app_dir, "/bin/bash", launcher,
))
entry = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=KneeSpa\n"
    "Comment=Open the KneeSpa treatment application\n"
    f"Exec={command}\n"
    f"Icon={icon_value}\n"
    "Terminal=false\n"
    "StartupNotify=false\n"
    "Categories=Education;MedicalSoftware;\n"
)
for destination in (desktop, menu):
    path = pathlib.Path(destination)
    path.write_text(entry, encoding="utf-8")
    path.chmod(0o755)

flash_command = " ".join(exec_argument(arg) for arg in (
    "/usr/bin/env", "KNEESPA_APP_DIR=" + app_dir, "/bin/bash",
    str(pathlib.Path(app_dir) / "devices/flash_firmware.sh"),
))
flash_entry = (
    "[Desktop Entry]\n"
    "Type=Application\n"
    "Name=Flash KneeSpa Firmware\n"
    "Comment=Build, back up, and flash the current Arduino Mega firmware over USB\n"
    f"Exec={flash_command}\n"
    "Icon=applications-engineering\n"
    "Terminal=true\n"
    "StartupNotify=false\n"
    "Categories=System;\n"
)
for destination in (
    pathlib.Path(desktop).with_name("Flash KneeSpa Firmware.desktop"),
    pathlib.Path(menu).with_name("kneespa-firmware.desktop"),
):
    destination.write_text(flash_entry, encoding="utf-8")
    destination.chmod(0o755)
PY

if command -v gio >/dev/null 2>&1; then
    gio set "$DESKTOP_DIR/KneeSpa.desktop" metadata::trusted true >/dev/null 2>&1 || true
    gio set "$DESKTOP_DIR/Flash KneeSpa Firmware.desktop" metadata::trusted true \
        >/dev/null 2>&1 || true
fi
printf 'Installed desktop shortcuts:\n  %s\n  %s\n' \
    "$DESKTOP_DIR/KneeSpa.desktop" "$DESKTOP_DIR/Flash KneeSpa Firmware.desktop"
printf '\nShortcuts and launcher scripts are executable (0755).\n'
printf 'Double-click KneeSpa. If prompted, choose Allow Launching or Execute.\n'
