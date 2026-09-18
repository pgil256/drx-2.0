#pragma once
#if !defined(DRX_FIRMWARE_TEST)
#include <Arduino.h>
#endif
#if defined(ARDUINO_ARCH_AVR)
#include <util/atomic.h>
#endif

// Repository-owned channel-A/gain-128 reader. No wait_ready(), delay(), tare(),
// or averaging call can block the motor/Stop loop. One attempt is <=25 clocks.
class Hx711Sampler {
  uint8_t dataPin = 7, clockPin = 6;
  long offset = 0;
  float factor = 1;
public:
  enum Result { NOT_READY, SAMPLE, INVALID };
  void begin(uint8_t data, uint8_t clock) {
    dataPin = data;
    clockPin = clock;
    digitalWrite(clockPin, LOW);
    pinMode(clockPin, OUTPUT);
    // An open data connection fails not-ready rather than floating low.
    pinMode(dataPin, INPUT_PULLUP);
  }
  bool is_ready() const { return digitalRead(dataPin) == LOW; }
  void set_scale(float value) { factor = value; }
  float get_scale() const { return factor; }
  void set_offset(long value) { offset = value; }
  long get_offset() const { return offset; }
  float units(long raw) const { return ((float)raw - (float)offset) / factor; }

  Result read_if_ready(long &raw, unsigned long &elapsedUs) {
    if (!is_ready()) return NOT_READY;
    uint32_t bits = 0;
    bool started = false, released = false;
    unsigned long began = micros();
    for (uint8_t bit = 0; bit < 25; ++bit) {
      // Only HIGH/read/LOW is atomic. UART/I2C interrupts can run between
      // clocks while SCK is LOW, avoiding a whole-word interrupt blackout.
#if defined(ARDUINO_ARCH_AVR)
      ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
#else
    // Host tests run the same bit acquisition against fake pins. Production
    // targets are AVR Mega; do not silently ship unprotected clocks elsewhere.
#if !defined(DRX_FIRMWARE_TEST)
#error "Hx711Sampler requires AVR atomic clock protection"
#endif
      {
#endif
        // Readiness may have changed since the outer check: return, never wait.
        if (bit != 0 || digitalRead(dataPin) == LOW) {
          started = true;
          digitalWrite(clockPin, HIGH);
          if (bit < 24) bits = (bits << 1) | (digitalRead(dataPin) == HIGH ? 1UL : 0UL);
          digitalWrite(clockPin, LOW);
          // 25th clock selects channel A / gain128. DOUT must return HIGH.
          if (bit == 24) released = digitalRead(dataPin) == HIGH;
        }
      }
      if (!started) { elapsedUs = micros() - began; return NOT_READY; }
    }
    elapsedUs = micros() - began;
    raw = (bits & 0x800000UL) ? (long)(bits | 0xFF000000UL) : (long)bits;
    // Explicit int32 sign extension also works on 64-bit host test machines.
    raw = (long)(int32_t)raw;
    if (!released || raw == -8388608L || raw == 8388607L) return INVALID;
    return SAMPLE;
  }
};
