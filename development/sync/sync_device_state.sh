#!/usr/bin/env bash
# Explicit one-device state transfer. Never uses --delete or bulk host lists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ $# -lt 4 || $# -gt 5 ]]; then
    echo "Usage: bash $0 pull|push PROFILE HOST config|credentials|environment|logs|uploads [--apply|--dry-run]" >&2
    exit 2
fi
direction="$1"
profile="$2"
host="$3"
category="$4"
mode="${5:---dry-run}"
PI_USER="${PI_USER:-pi}"
DEST_ROOT="${DEST_ROOT:-/home/pi/drx-2.0}"
SERVICE="${SERVICE:-kneespa.service}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=accept-new}"
if [[ ! "$profile" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ||
      ! "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ||
      ! "$PI_USER" =~ ^[a-zA-Z0-9_-]+$ || ! "$SERVICE" =~ ^[a-zA-Z0-9_.@-]+$ ||
      ! "$DEST_ROOT" =~ ^/[a-zA-Z0-9_./-]+$ || "$DEST_ROOT" == / ||
      "$DEST_ROOT" == *..* || ( "$mode" != --dry-run && "$mode" != --apply ) ||
      ( "$direction" != pull && "$direction" != push ) ]]; then
    echo "Invalid state transfer arguments." >&2
    exit 2
fi
case "$category" in
    config) files=(config/kneespa.cfg) ;;
    credentials) files=(data/user_pins.csv) ;;
    environment) files=(.env cloud.env) ;;
    logs) files=(logs/) ;;
    uploads) files=(data/pending_uploads.json) ;;
    *) echo "Unknown state category: $category" >&2; exit 2 ;;
esac
if [[ "$direction" == push && ( "$category" == logs || "$category" == uploads ) ]]; then
    echo "Logs and queued treatment uploads are download-only." >&2
    exit 2
fi
local_dir="$PROJECT_DIR/devices/profiles/$profile/raspberry-pi"
remote_dir="${DEST_ROOT%/}/devices/local/raspberry-pi"
flags=(-avz --relative --itemize-changes --backup "--suffix=.backup-$(date +%Y%m%d-%H%M%S)")
if [[ "$mode" == --dry-run ]]; then flags+=(--dry-run); fi
sources=()
for file in "${files[@]}"; do
    if [[ "$direction" == push ]]; then
        if [[ ! -e "$local_dir/$file" ]]; then
            echo "Missing profile file: $local_dir/$file" >&2
            exit 2
        fi
        sources+=("$local_dir/./$file")
    else
        sources+=("$PI_USER@$host:$remote_dir/./$file")
    fi
done
echo "$mode: $direction $category for profile $profile on $host"
if [[ "$mode" == --apply ]]; then
    # Freeze mutable state for a consistent transfer. Never suppress stop errors.
    ssh $SSH_OPTS "$PI_USER@$host" "sudo systemctl stop '$SERVICE'"
    if [[ "$direction" == push ]]; then
        ssh $SSH_OPTS "$PI_USER@$host" "mkdir -p '$remote_dir'"
    fi
fi
if [[ "$direction" == pull ]]; then
    mkdir -p "$local_dir"
    destination="$local_dir/"
else
    destination="$PI_USER@$host:$remote_dir/"
fi
if ! rsync "${flags[@]}" -e "ssh $SSH_OPTS" "${sources[@]}" "$destination"; then
    echo "State transfer failed; in apply mode the service remains stopped." >&2
    exit 1
fi
if [[ "$mode" == --apply ]]; then
    ssh $SSH_OPTS "$PI_USER@$host" "sudo systemctl start '$SERVICE'"
fi
