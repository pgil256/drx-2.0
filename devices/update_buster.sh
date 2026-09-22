#!/usr/bin/env bash
# Run as the KneeSpa desktop user. Python must remain the OS-managed interpreter.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec /usr/bin/python3 "$SCRIPT_DIR/maintenance/raspberry-pi/update_buster.py" "$@"
