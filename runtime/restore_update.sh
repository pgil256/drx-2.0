#!/usr/bin/env bash
# Put the previous software back if a software install stopped between its
# two folder renames, for example on a power cut (checklist U1).
#
# The installer (raspberry-pi/main/helpers/release_installer.py) moves
# runtime/raspberry-pi aside, then moves the new software into its place. In
# between, the app folder does not exist, so this script lives in runtime/,
# outside it. The launchers run it before starting the app.
#
# Usage: restore_update.sh [--lock FILE] [RUNTIME_DIR]
#   RUNTIME_DIR  the runtime/ folder (default: this script's folder).
#   --lock FILE  take the KneeSpa launcher lock first. If the app holds it, it
#                may be installing right now, so change nothing. A caller that
#                already holds the lock omits this.
# Exit status: 0 when the app folder is in place (restored or untouched), or
# when the app is running; 1 when it is missing and cannot be restored.
set -euo pipefail

lock=""
if [[ "${1:-}" == "--lock" ]]; then
    lock="${2:?--lock needs a file}"
    shift 2
fi
RUNTIME_DIR="${1:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}"
TARGET="$RUNTIME_DIR/raspberry-pi"
JOURNAL="$RUNTIME_DIR/.software-swap"

say() {
    printf 'restore_update: %s\n' "$1" >&2
}

if [[ -n "$lock" ]]; then
    mkdir -p -- "$(dirname -- "$lock")"
    exec 8>"$lock"
    if ! flock --exclusive --nonblock 8; then
        say "KneeSpa is running; leaving its software alone."
        exit 0
    fi
fi

if [[ -d "$TARGET" && ! -L "$TARGET" ]]; then
    exit 0
fi
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
    say "$TARGET exists but is not a folder. Restore the software by hand."
    exit 1
fi

# The journal, flushed to disk before the first rename, names the folder the
# install moved aside. Only its name is used, looked up in RUNTIME_DIR.
retired=""
if [[ -f "$JOURNAL" ]]; then
    name="$(sed -n 's/^retired=//p' "$JOURNAL" | head -n 1)"
    name="${name##*/}"
    if [[ "$name" =~ ^\.software-old-[0-9a-f]{32}$ && -d "$RUNTIME_DIR/$name" &&
        ! -L "$RUNTIME_DIR/$name" ]]; then
        retired="$RUNTIME_DIR/$name"
    fi
fi
# Without a usable journal, take the most recently changed retired folder.
if [[ -z "$retired" ]]; then
    for folder in "$RUNTIME_DIR"/.software-old-*; do
        [[ -d "$folder" && ! -L "$folder" ]] || continue
        [[ "${folder##*/}" =~ ^\.software-old-[0-9a-f]{32}$ ]] || continue
        if [[ -z "$retired" || "$folder" -nt "$retired" ]]; then
            retired="$folder"
        fi
    done
fi
if [[ -z "$retired" ]]; then
    say "$TARGET is missing and no previous software was found to restore."
    exit 1
fi

# Same filesystem, so this is a single rename.
mv -T -- "$retired" "$TARGET"
sync
rm -f -- "$JOURNAL"
sync
say "Restored the previous software from ${retired##*/} after an interrupted update."
