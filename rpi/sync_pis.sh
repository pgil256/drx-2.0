#!/usr/bin/env bash
set -euo pipefail

# Sync the current repo's main/ directory to one or more Raspberry Pi devices.
# Override defaults with environment variables:
#   SOURCE_DIR=/path/to/main/ DEST_DIR=/home/pi/drx-2.0/main/ PI_HOSTS="host1 host2" ./sync_pis.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$PROJECT_DIR/main/}"
DEST_DIR="${DEST_DIR:-/home/pi/drx-2.0/main/}"
PI_USER="${PI_USER:-pi}"
PI_HOSTS="${PI_HOSTS:-100.111.162.21 100.93.117.101 100.95.232.121}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=no}"

echo "Starting sync from $SOURCE_DIR to $DEST_DIR"

for host in $PI_HOSTS; do
    echo "----------------------------------------"
    echo "Syncing to $host..."
    rsync -avzu --progress -e "ssh $SSH_OPTS" "$SOURCE_DIR" "$PI_USER@$host:$DEST_DIR"
    echo "Sync to $host complete."
done

echo "All devices have been synced."
