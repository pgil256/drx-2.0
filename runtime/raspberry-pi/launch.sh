#!/usr/bin/env bash
set -euo pipefail

# Double-click launcher for the KneeSpa app.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${KNEESPA_APP_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

cd "$APP_DIR"

if [ -f kneespa_env/bin/activate ]; then
    # shellcheck disable=SC1091
    source kneespa_env/bin/activate
elif [ -f "$HOME/kneespa_env/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$HOME/kneespa_env/bin/activate"
fi

cd runtime/raspberry-pi/main
exec python3 kneespa.py
