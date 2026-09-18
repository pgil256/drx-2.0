#!/usr/bin/env bash
# Update shared software and stage Arduino firmware. Requires bash, ssh and rsync.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$PROJECT_DIR/runtime}"
DEST_ROOT="${DEST_ROOT:-/home/pi/drx-2.0}"
PI_USER="${PI_USER:-pi}"
PI_HOSTS="${PI_HOSTS:-}"
SERVICE="${SERVICE:-kneespa.service}"
SSH_OPTS="${SSH_OPTS:--o StrictHostKeyChecking=accept-new}"
MODE="${1:---dry-run}"

if [[ $# -gt 1 || ( "$MODE" != --dry-run && "$MODE" != --apply ) ]]; then
    echo "Usage: PI_HOSTS='verified-host ...' bash $0 [--dry-run|--apply]" >&2
    exit 2
fi
if [[ -z "${PI_HOSTS//[[:space:]]/}" ]]; then
    echo "Set PI_HOSTS to explicitly verified device hosts before deploying." >&2
    exit 2
fi
if [[ -n "${DEST_DIR:-}" ]]; then
    echo "DEST_DIR is retired. Set DEST_ROOT to the project directory, not main/." >&2
    exit 2
fi
if [[ ! "$DEST_ROOT" =~ ^/[a-zA-Z0-9_./-]+$ || "$DEST_ROOT" == / ||
      "$DEST_ROOT" == *..* || ! "$SERVICE" =~ ^[a-zA-Z0-9_.@-]+$ ||
      ! "$PI_USER" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Invalid destination root, service, or SSH user." >&2
    exit 2
fi
for host in $PI_HOSTS; do
    if [[ ! "$host" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
        echo "Invalid device host: $host" >&2
        exit 2
    fi
done
if [[ ! -f "$SOURCE_DIR/raspberry-pi/main/kneespa.py" ||
      ! -f "$SOURCE_DIR/arduino/motor/motor.ino" ]]; then
    echo "SOURCE_DIR must contain the runtime/ Raspberry Pi and Arduino trees." >&2
    exit 2
fi

# Defense in depth: state, documentation and build output never belong in an update.
EXCLUDES=(
    --exclude devices/ --exclude development/ --exclude .env --exclude cloud.env
    --exclude kneespa.cfg --exclude user_pins.csv --exclude auth_state.json
    --exclude pending_uploads.json --exclude logs/ --exclude '*.log*'
    --exclude __pycache__/ --exclude '*.pyc' --exclude .pio/ --exclude .native-build/
    --exclude test/ --exclude tests/ --exclude '*.md'
)
RSYNC_FLAGS=(-avz --delete --itemize-changes)
if [[ "$MODE" == --dry-run ]]; then
    RSYNC_FLAGS+=(--dry-run)
fi
destination="${DEST_ROOT%/}/runtime"
failures=0
for host in $PI_HOSTS; do
    echo "$MODE: shared runtime to $host:$destination/"
    if [[ "$MODE" == --apply ]]; then
        # Reject stale service definitions before changing files. Stop failures
        # must prevent rsync rather than leaving the app running during a copy.
        if ! ssh $SSH_OPTS "$PI_USER@$host" \
            "systemctl show -p ExecStart --value '$SERVICE' | grep -F '$destination/raspberry-pi/main/kneespa.py' >/dev/null && sudo systemctl stop '$SERVICE' && mkdir -p '$destination'"; then
            echo "ERROR: check the service path and stop permissions on $host; skipping." >&2
            failures=$((failures + 1))
            continue
        fi
    fi
    if rsync "${RSYNC_FLAGS[@]}" "${EXCLUDES[@]}" -e "ssh $SSH_OPTS" \
        "${SOURCE_DIR%/}/" "$PI_USER@$host:$destination/"; then
        if [[ "$MODE" == --apply ]]; then
            if ! ssh $SSH_OPTS "$PI_USER@$host" "sudo systemctl start '$SERVICE'"; then
                echo "ERROR: service restart failed on $host." >&2
                failures=$((failures + 1))
            fi
        fi
    else
        echo "ERROR: sync to $host failed; in apply mode service left STOPPED." >&2
        failures=$((failures + 1))
    fi
done
if (( failures )); then
    echo "Finished with $failures failure(s)." >&2
    exit 1
fi
echo "Complete. Arduino firmware is staged only; flashing is a separate operation."
