#!/usr/bin/env bash
#
# run_native_tests.sh - Run the AVR firmware native Unity test suite.
#
# This drives `pio test -e native`, which compiles the firmware (motor.ino)
# against the mock headers in test/ on the host machine (no AVR hardware
# required) and runs the Unity test cases under test/test_*/.
#
# NOTE: The first run downloads the `native` platform and Unity test
# framework from the PlatformIO package registry. If the machine is offline
# or cannot reach the registry, that download fails and the tests cannot run.
# CI is responsible for running this script in an environment with registry
# access; locally it may not work without connectivity.
#
# Usage:
#   bash run_native_tests.sh
#   ./run_native_tests.sh        # after: chmod +x run_native_tests.sh

set -euo pipefail

# (a) Always operate from this script's own directory (main/motor/) so the
#     relative pio environment + test paths resolve regardless of caller CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# (b) Make sure the PlatformIO CLI is available before attempting anything.
if ! command -v pio >/dev/null 2>&1; then
  echo "ERROR: PlatformIO CLI ('pio') was not found on your PATH." >&2
  echo "" >&2
  echo "The native firmware tests require PlatformIO. Install it with one of:" >&2
  echo "  pip install platformio" >&2
  echo "  pipx install platformio" >&2
  echo "Then re-run this script. See https://platformio.org/install for details." >&2
  exit 1
fi

# (c) Run the native test environment defined in platformio.ini ([env:native]).
echo "Running native Unity tests (pio test -e native) in: $SCRIPT_DIR"
exec pio test -e native
