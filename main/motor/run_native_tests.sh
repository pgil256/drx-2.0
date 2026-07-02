#!/usr/bin/env bash
# Build and run the firmware native unit tests without PlatformIO.
# Equivalent to `pio test -e native`, but hermetic: uses the system
# C/C++ compiler and the vendored Unity framework in test/unity/.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
BUILD_DIR="${BUILD_DIR:-.native-build}"
mkdir -p "$BUILD_DIR"

CC="${CC:-gcc}"
CXX="${CXX:-g++}"

"$CC" -std=c99 -c test/unity/unity.c -I test/unity -o "$BUILD_DIR/unity.o"

status=0
for suite in test/test_*/; do
    name=$(basename "$suite")
    src=("$suite"*.cpp)
    bin="$BUILD_DIR/$name"
    echo "=== Building $name ==="
    if ! "$CXX" -std=c++11 -DUNIT_TEST -Wall -I test/unity -o "$bin" "${src[@]}" "$BUILD_DIR/unity.o"; then
        status=1
        continue
    fi
    echo "=== Running $name ==="
    if ! "$bin"; then
        status=1
    fi
done

if [ "$status" -eq 0 ]; then
    echo "All firmware test suites passed."
else
    echo "FIRMWARE TEST FAILURES (see above)."
fi
exit $status
