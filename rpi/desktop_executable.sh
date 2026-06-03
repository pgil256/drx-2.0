#!/usr/bin/env bash
# launch_kneespa.sh – double-click to start the KneeSpa app

# --- adjust this path if your repo lives elsewhere ---
APP_DIR="$HOME/drx-2.3"

cd "$APP_DIR" || { echo "Cannot cd to $APP_DIR"; exit 1; }

# activate virtual-env
source kneespa_env/bin/activate

# run the app
cd main
exec python3 kneespa.py
