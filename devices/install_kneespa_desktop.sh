#!/usr/bin/env bash
set -euo pipefail

# Run as pi, without sudo. This wrapper can be copied anywhere on the Pi.
status=0
bash /home/pi/drx/devices/maintenance/raspberry-pi/desktop/install.sh "$@" || status=$?
if [[ -t 0 ]]; then
    printf '\nFinished (exit %s). You can close this window.\n' "$status"
    read -r -p "Or press Enter to close... " _ || true
fi
exit "$status"
