#!/usr/bin/env bash
set -euo pipefail

# Double-click launcher for the KneeSpa app.
APP_DIR="${KNEESPA_APP_DIR:-$HOME/drx-2.0}"

cd "$APP_DIR"

if [ -f kneespa_env/bin/activate ]; then
    # shellcheck disable=SC1091
    source kneespa_env/bin/activate
fi

cd main
exec python3 kneespa.py
