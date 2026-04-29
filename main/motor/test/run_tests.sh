#!/bin/bash
# Run Arduino motor firmware C++ unit tests natively using g++ and Unity
# Usage: ./run_tests.sh
#
# Prerequisites: g++ (C++17), Unity framework at /tmp/unity_framework
# If Unity is not present, it will be cloned automatically.

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOTOR_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$(dirname "$MOTOR_DIR")")"
BUILD_DIR="/tmp/arduino_test_build"
SHIMS_DIR="/tmp/arduino_shims"
UNITY_DIR="/tmp/unity_framework"

# Clone Unity if not present
if [ ! -f "$UNITY_DIR/src/unity.h" ]; then
    echo "Downloading Unity test framework..."
    git clone --depth 1 https://github.com/ThrowTheSwitch/Unity.git "$UNITY_DIR"
fi

# Create shims directory
mkdir -p "$SHIMS_DIR/avr"
mkdir -p "$BUILD_DIR"

# Create Arduino.h shim
cat > "$SHIMS_DIR/Arduino.h" << 'ARDUINO_EOF'
#ifndef ARDUINO_H
#define ARDUINO_H
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <math.h>
#include <cmath>
#include <cstdlib>
#include <string>
typedef uint8_t byte;
typedef bool boolean;
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define HIGH 1
#define LOW 0
#define A0 54
#define F(x) x
extern unsigned long millis();
extern void delay(unsigned long ms);
inline void pinMode(int, int) {}
inline int digitalRead(int) { return HIGH; }
inline void digitalWrite(int, int) {}
inline int analogRead(int) { return 0; }
inline void analogWrite(int, int) {}
class String {
    std::string _s;
public:
    String() {}
    String(const char* s) : _s(s ? s : "") {}
    String(const std::string& s) : _s(s) {}
    String(int val) : _s(std::to_string(val)) {}
    String(long val) : _s(std::to_string(val)) {}
    String(unsigned long val) : _s(std::to_string(val)) {}
    String(float val) { char buf[32]; snprintf(buf, 32, "%.1f", val); _s = buf; }
    String(double val) { char buf[32]; snprintf(buf, 32, "%.1f", val); _s = buf; }
    String(char c) : _s(1, c) {}
    int length() const { return _s.length(); }
    char charAt(int i) const { return _s[i]; }
    char operator[](int i) const { return _s[i]; }
    String substring(int from) const { return String(_s.substr(from)); }
    String substring(int from, int to) const { return String(_s.substr(from, to - from)); }
    int toInt() const { return atoi(_s.c_str()); }
    float toFloat() const { return atof(_s.c_str()); }
    int indexOf(char c) const { auto p = _s.find(c); return p == std::string::npos ? -1 : (int)p; }
    String operator+(const String& other) const { return String(_s + other._s); }
    String operator+(const char* other) const { return String(_s + other); }
    friend String operator+(const char* lhs, const String& rhs) { return String(std::string(lhs) + rhs._s); }
    String& operator+=(char c) { _s += c; return *this; }
    String& operator+=(const char* s) { _s += s; return *this; }
    String& operator+=(const String& other) { _s += other._s; return *this; }
    bool operator==(const char* s) const { return _s == s; }
    bool operator==(const String& other) const { return _s == other._s; }
    bool operator!=(const char* s) const { return _s != s; }
    bool operator!=(const String& other) const { return _s != other._s; }
    const char* c_str() const { return _s.c_str(); }
    operator const char*() const { return _s.c_str(); }
};
#endif
ARDUINO_EOF

# Create elapsedMillis.h shim
cat > "$SHIMS_DIR/elapsedMillis.h" << 'ELAPSED_EOF'
#ifndef ELAPSED_MILLIS_H
#define ELAPSED_MILLIS_H
class elapsedMillis {
public:
    unsigned long ms = 0;
    elapsedMillis() : ms(0) {}
    elapsedMillis(int v) : ms(v) {}
    elapsedMillis(unsigned long v) : ms(v) {}
    operator unsigned long() const { return ms; }
    elapsedMillis& operator=(int val) { ms = val; return *this; }
    elapsedMillis& operator=(unsigned long val) { ms = val; return *this; }
    bool operator>(unsigned long val) const { return ms > val; }
    bool operator>(int val) const { return ms > (unsigned long)val; }
    bool operator>=(unsigned long val) const { return ms >= val; }
    bool operator<(unsigned long val) const { return ms < val; }
};
#endif
ELAPSED_EOF

# Create Wire.h shim (redirects to mock when UNIT_TEST defined)
cat > "$SHIMS_DIR/Wire.h" << 'WIRE_EOF'
#ifndef MOCK_WIRE_H
#include "../test/mock_wire.h"
#endif
WIRE_EOF

# Create HX711.h shim
cat > "$SHIMS_DIR/HX711.h" << 'HX711_EOF'
#ifndef MOCK_HX711_H
#include "../test/mock_hx711.h"
#endif
HX711_EOF

# Create avr/wdt.h shim
cat > "$SHIMS_DIR/avr/wdt.h" << 'WDT_EOF'
#define wdt_enable(x)
#define wdt_disable()
#define wdt_reset()
#define WDTO_2S 0
WDT_EOF

# Common compile flags
CXXFLAGS="-std=c++17 -DUNIT_TEST -include $SHIMS_DIR/Arduino.h -I$SHIMS_DIR -I$UNITY_DIR/src -I$SCRIPT_DIR"

# Compile Unity (C)
gcc -c "$UNITY_DIR/src/unity.c" -o "$BUILD_DIR/unity.o"

# Track results
TOTAL=0
FAILED=0

# Build and run each test suite
for test_dir in "$SCRIPT_DIR"/test_*/; do
    test_name=$(basename "$test_dir")
    cpp_file="$test_dir/${test_name}.cpp"

    if [ ! -f "$cpp_file" ]; then
        continue
    fi

    echo "=== Building $test_name ==="

    # Compile
    if ! g++ $CXXFLAGS -c "$cpp_file" -o "$BUILD_DIR/${test_name}.o" 2>&1 | grep -v "warning:"; then
        echo "COMPILE FAILED: $test_name"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Link
    if ! g++ "$BUILD_DIR/${test_name}.o" "$BUILD_DIR/unity.o" -o "$BUILD_DIR/$test_name"; then
        echo "LINK FAILED: $test_name"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Run with timeout
    echo "=== Running $test_name ==="
    if timeout 10 "$BUILD_DIR/$test_name"; then
        echo ""
    else
        FAILED=$((FAILED + 1))
    fi

    TOTAL=$((TOTAL + 1))
done

echo ""
echo "=============================="
echo "Test suites run: $TOTAL"
echo "Test suites failed: $FAILED"
echo "=============================="

exit $FAILED
