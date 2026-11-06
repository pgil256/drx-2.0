#!/usr/bin/env bash
# Build and run the firmware native unit tests without PlatformIO.
# Equivalent to `pio test -e native`, but hermetic: uses the system
# C/C++ compiler and the vendored Unity framework in unity/.
#
# ARCH_FLAGS adds compiler flags to every build, for example
#   ARCH_FLAGS=-m32 BUILD_DIR=.native-build/m32 bash run_native_tests.sh
# A -m32 build gives `long` the Mega's 32 bits (millis() and long
# arithmetic then wrap as on the device); x86 cannot give `int` the Mega's
# 16 bits. It needs 32-bit libraries (g++-multilib on Debian/Ubuntu).
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
BUILD_DIR="${BUILD_DIR:-.native-build}"
mkdir -p "$BUILD_DIR"

CC="${CC:-gcc}"
CXX="${CXX:-g++}"
read -r -a ARCH <<< "${ARCH_FLAGS:-}"

# Report the widths this build actually gets, so a CI log shows the flags
# took effect (AVR: int 16, long 32, pointer 16 bits).
cat > "$BUILD_DIR/width_probe.cpp" <<'EOF'
#include <cstdio>
int main() {
    std::printf("Type widths: int %u, long %u, pointer %u bits\n",
                (unsigned)(8 * sizeof(int)), (unsigned)(8 * sizeof(long)),
                (unsigned)(8 * sizeof(void *)));
    return 0;
}
EOF
"$CXX" ${ARCH[@]+"${ARCH[@]}"} -o "$BUILD_DIR/width_probe" "$BUILD_DIR/width_probe.cpp"
"$BUILD_DIR/width_probe"

"$CC" ${ARCH[@]+"${ARCH[@]}"} -std=c99 -c unity/unity.c -I unity -o "$BUILD_DIR/unity.o"

status=0
for suite in test_*/; do
    name=$(basename "$suite")
    src=("$suite"*.cpp)
    bin="$BUILD_DIR/$name"
    echo "=== Building $name ==="
    if ! "$CXX" ${ARCH[@]+"${ARCH[@]}"} -std=c++11 -DUNIT_TEST -Wall -I unity -o "$bin" \
            "${src[@]}" "$BUILD_DIR/unity.o"; then
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
