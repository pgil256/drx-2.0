// main/motor/test/arduino_shim.h
// Minimal Arduino core shim so motor.ino compiles on platform = native.
// Include this BEFORE the mock headers and motor.ino. Each test suite is a
// single translation unit, so state lives directly in this header.
#ifndef ARDUINO_SHIM_H
#define ARDUINO_SHIM_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <cmath>
#include <string>

// --- Digital I/O ---
#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define A0 54

#define SHIM_MAX_PINS 70
int _pin_levels[SHIM_MAX_PINS];
int _pin_modes[SHIM_MAX_PINS];

inline void pinMode(int pin, int mode) {
    if (pin >= 0 && pin < SHIM_MAX_PINS) {
        _pin_modes[pin] = mode;
        if (mode == INPUT_PULLUP) _pin_levels[pin] = HIGH;
    }
}

inline void digitalWrite(int pin, int level) {
    if (pin >= 0 && pin < SHIM_MAX_PINS) _pin_levels[pin] = level;
}

inline int digitalRead(int pin) {
    return (pin >= 0 && pin < SHIM_MAX_PINS) ? _pin_levels[pin] : LOW;
}

// Provided by each test translation unit (controllable clock)
unsigned long millis();
void delay(unsigned long ms);

// --- Flash-string macro ---
#define F(x) (x)

// Arduino's abs() accepts floats. <cmath> already places float/double
// abs overloads in the global namespace on glibc, so no shim is needed;
// motor.ino's abs(float) calls resolve to std::abs(float).

// Arduino defines min/max as macros; provide float overloads natively
inline float min(float a, float b) { return a < b ? a : b; }
inline float max(float a, float b) { return a > b ? a : b; }

// --- elapsedMillis ---
class elapsedMillis {
    unsigned long _start;

public:
    elapsedMillis(unsigned long value = 0) { _start = millis() - value; }
    operator unsigned long() const { return millis() - _start; }
    elapsedMillis &operator=(unsigned long value) {
        _start = millis() - value;
        return *this;
    }
};

// --- avr/wdt.h ---
#define WDTO_15MS 0
#define WDTO_30MS 1
#define WDTO_60MS 2
#define WDTO_120MS 3
#define WDTO_250MS 4
#define WDTO_500MS 5
#define WDTO_1S 6
#define WDTO_2S 7
#define WDTO_4S 8
#define WDTO_8S 9

bool _wdt_enabled = false;
int _wdt_timeout = -1;
int _wdt_reset_count = 0;

inline void wdt_enable(int timeout) {
    _wdt_enabled = true;
    _wdt_timeout = timeout;
}
inline void wdt_disable() { _wdt_enabled = false; }
inline void wdt_reset() { _wdt_reset_count++; }

// --- Arduino String ---
class String {
    std::string s;

public:
    String() {}
    String(const char *c) : s(c ? c : "") {}
    String(const std::string &other) : s(other) {}
    String(char c) : s(1, c) {}
    String(int v) : s(std::to_string(v)) {}
    String(unsigned int v) : s(std::to_string(v)) {}
    String(long v) : s(std::to_string(v)) {}
    String(unsigned long v) : s(std::to_string(v)) {}
    String(float v) {
        char buf[33];
        snprintf(buf, sizeof(buf), "%.2f", (double)v);
        s = buf;
    }

    unsigned int length() const { return (unsigned int)s.length(); }
    char charAt(unsigned int i) const { return i < s.length() ? s[i] : '\0'; }
    char operator[](unsigned int i) const { return charAt(i); }

    String substring(unsigned int from) const {
        if (from >= s.length()) return String();
        return String(s.substr(from));
    }
    String substring(unsigned int from, unsigned int to) const {
        if (to > s.length()) to = (unsigned int)s.length();
        if (from >= to) return String();
        return String(s.substr(from, to - from));
    }

    long toInt() const { return strtol(s.c_str(), nullptr, 10); }
    float toFloat() const { return strtof(s.c_str(), nullptr); }
    const char *c_str() const { return s.c_str(); }

    int indexOf(char c) const {
        size_t p = s.find(c);
        return p == std::string::npos ? -1 : (int)p;
    }
    int indexOf(const char *sub) const {
        size_t p = s.find(sub);
        return p == std::string::npos ? -1 : (int)p;
    }
    bool startsWith(const String &prefix) const {
        return s.compare(0, prefix.s.length(), prefix.s) == 0;
    }
    void reserve(unsigned int n) { s.reserve(n); }
    void trim() {
        size_t b = s.find_first_not_of(" \t\r\n");
        size_t e = s.find_last_not_of(" \t\r\n");
        s = (b == std::string::npos) ? "" : s.substr(b, e - b + 1);
    }

    String &operator+=(char c) {
        s += c;
        return *this;
    }
    String &operator+=(const char *c) {
        s += c;
        return *this;
    }
    String &operator+=(const String &other) {
        s += other.s;
        return *this;
    }

    bool operator==(const char *c) const { return s == c; }
    bool operator==(const String &other) const { return s == other.s; }
    bool operator!=(const char *c) const { return s != c; }
    bool operator!=(const String &other) const { return s != other.s; }

    friend String operator+(String lhs, const String &rhs) {
        lhs.s += rhs.s;
        return lhs;
    }
    friend String operator+(String lhs, const char *rhs) {
        lhs.s += rhs;
        return lhs;
    }
    friend String operator+(const char *lhs, const String &rhs) {
        return String(std::string(lhs) + rhs.s);
    }
};

#endif // UNIT_TEST
#endif // ARDUINO_SHIM_H
