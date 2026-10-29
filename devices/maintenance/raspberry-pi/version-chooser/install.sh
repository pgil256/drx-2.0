#!/usr/bin/env bash
set -euo pipefail

# Run on the Pi as pi, without sudo: bash install.sh [--uninstall]
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${KNEESPA_APP_DIR:-/home/pi/drx}"
DESKTOP_DIR="${KNEESPA_DESKTOP_DIR:-/home/pi/Desktop}"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
MENU_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRIES=("$AUTOSTART_DIR/kneespa-version-chooser.desktop"
         "$DESKTOP_DIR/Choose KneeSpa Version.desktop"
         "$MENU_DIR/kneespa-version-chooser.desktop")

if [[ "$EUID" -eq 0 ]]; then
    echo "Run this installer as the desktop user, without sudo." >&2
    exit 1
fi
case "${1:-}" in
    --uninstall)
        rm -f -- "${ENTRIES[@]}"
        echo "Removed the version chooser's autostart entry and shortcuts."
        echo "Device settings and registered images in devices/local were kept."
        exit 0 ;;
    "") ;;
    *) echo "Usage: bash install.sh [--uninstall]" >&2; exit 2 ;;
esac

TEMPLATE="$APP_DIR/devices/templates/raspberry-pi/version-chooser.cfg.example"
[[ -f "$SCRIPT_DIR/version_chooser.py" && -f "$SCRIPT_DIR/start_version_chooser.sh" &&
   -f "$TEMPLATE" ]] || { echo "Cannot find the chooser files in $APP_DIR." >&2; exit 1; }
APP_DIR="$(cd -- "$APP_DIR" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo "Python 3 is required." >&2; exit 1; }

CHOOSER_STATE="${KNEESPA_DEVICE_DIR:-$APP_DIR/devices/local}/raspberry-pi/version-chooser"
mkdir -p -- "$CHOOSER_STATE/images" "$AUTOSTART_DIR" "$DESKTOP_DIR" "$MENU_DIR"
if [[ ! -f "$CHOOSER_STATE/versions.cfg" ]]; then
    # The template's KneeSpa 2.0 paths name the default /home/pi/drx checkout.
    python3 - "$TEMPLATE" "$CHOOSER_STATE/versions.cfg" "$APP_DIR" <<'PY'
import pathlib
import sys

template, destination, app_dir = sys.argv[1:]
text = pathlib.Path(template).read_text(encoding="utf-8").replace("/home/pi/drx", app_dir)
pathlib.Path(destination).write_text(text, encoding="utf-8")
PY
    echo "Created $CHOOSER_STATE/versions.cfg; set the legacy app's command in it."
fi
chmod 0755 "$SCRIPT_DIR/start_version_chooser.sh" "$SCRIPT_DIR/install.sh"

python3 - "$SCRIPT_DIR/start_version_chooser.sh" "$APP_DIR" "${ENTRIES[@]}" <<'PY'
import pathlib
import sys


def exec_argument(value: str) -> str:
    """Quote one Exec argument using Desktop Entry escaping, not shell quoting."""
    value = value.replace("\\", "\\\\")
    for character in ('"', '`', '$'):
        value = value.replace(character, "\\" + character)
    value = value.replace("\\", "\\\\").replace("%", "%%")
    return '"' + value + '"'


launcher, app_dir, autostart, desktop, menu = sys.argv[1:]
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
    "Name=Choose KneeSpa Version\n"
    "Comment=Start the legacy or new KneeSpa app with matching Mega firmware\n"
    f"Exec={command}\n"
    f"Icon={icon_value}\n"
    "Terminal=false\n"
    "StartupNotify=false\n"
    "Categories=Education;MedicalSoftware;\n"
)
for destination in (autostart, desktop, menu):
    path = pathlib.Path(destination)
    path.write_text(entry, encoding="utf-8")
    path.chmod(0o755)
PY

if command -v gio >/dev/null 2>&1; then
    gio set "${ENTRIES[1]}" metadata::trusted true >/dev/null 2>&1 || true
fi
printf 'Installed:\n'
printf '  %s\n' "${ENTRIES[@]}"

if command -v systemctl >/dev/null 2>&1 &&
    systemctl is-enabled --quiet kneespa.service 2>/dev/null; then
    printf '\nkneespa.service still starts KneeSpa 2.0 at boot. Disable it so only the\n'
    printf 'chooser starts an app:\n  sudo systemctl disable --now kneespa.service\n'
fi
printf '\nAlso remove whatever started the legacy app at login, if anything did.\n'
printf 'Setup check (does not touch the Mega):\n'
KNEESPA_APP_DIR="$APP_DIR" python3 "$SCRIPT_DIR/version_chooser.py" status || true
