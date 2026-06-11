#!/usr/bin/env bash
set -euo pipefail

# Sync the current repo's main/ directory to one or more Raspberry Pi devices.
# Override defaults with environment variables:
#   SOURCE_DIR=/path/to/main/ DEST_DIR=/home/pi/drx-2.0/main/ PI_HOSTS="host1 host2" ./sync_pis.sh
#
# Safety properties (the old version had none of these):
# - Stops the kneespa service before syncing: Restart=always used to be
#   able to relaunch the app mid-rsync into a half-synced tree.
# - Device-local state (calibration file, user PINs, logs) is excluded
#   so a deploy can never clobber a device's calibration.
# - --delete keeps the code tree clean (the old -u flag meant deleted
#   files lived on devices forever).
# - Host keys are verified (accept-new on first contact) instead of
#   StrictHostKeyChecking=no on a medical device.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SOURCE_DIR="${SOURCE_DIR:-$PROJECT_DIR/main/}"
DEST_DIR="${DEST_DIR:-/home/pi/drx-2.0/main/}"
PI_USER="${PI_USER:-pi}"
PI_HOSTS="${PI_HOSTS:-100.111.162.21 100.93.117.101 100.95.232.121}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=accept-new}"
SERVICE="${SERVICE:-kneespa.service}"

# Device-local state that a deploy must never overwrite or delete
EXCLUDES=(
    --exclude "config/kneespa.cfg"
    --exclude "data/user_pins.csv"
    --exclude "logs/"
    --exclude "__pycache__/"
)

echo "Starting sync from $SOURCE_DIR to $DEST_DIR"
failures=0

for host in $PI_HOSTS; do
    echo "----------------------------------------"
    echo "Deploying to $host..."
    if ! ssh $SSH_OPTS "$PI_USER@$host" "sudo systemctl stop $SERVICE 2>/dev/null || true"; then
        echo "WARNING: could not reach $host - skipping"
        failures=$((failures + 1))
        continue
    fi

    if rsync -avz --delete "${EXCLUDES[@]}" --progress -e "ssh $SSH_OPTS" \
        "$SOURCE_DIR" "$PI_USER@$host:$DEST_DIR"; then
        ssh $SSH_OPTS "$PI_USER@$host" "sudo systemctl start $SERVICE 2>/dev/null || true"
        echo "Deploy to $host complete; service restarted."
    else
        echo "ERROR: sync to $host failed; service left STOPPED for safety."
        echo "       Fix the sync, then: ssh $PI_USER@$host sudo systemctl start $SERVICE"
        failures=$((failures + 1))
    fi
done

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
    echo "Done with $failures failure(s)."
    exit 1
fi
echo "All devices have been synced."
