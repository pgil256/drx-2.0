Canonical Motor Firmware
========================

This is the canonical KneeSpa motor-controller firmware tree.

Use `main/motor/motor.ino` for the Arduino Mega motor controller. This tree also
contains the native unit-test harness (g++ + vendored Unity in `test/unity/`):

```bash
cd main/motor
bash run_native_tests.sh
```

Where PlatformIO is available, `pio test -e native` runs the same suites.
The tests stub the Arduino core via `test/arduino_shim.h`; in test builds the
stub `delay()` advances the mock `millis()` clock so timeout loops terminate.

The duplicate legacy sketch previously under `main/arduino/motor/` was removed to
avoid two diverging motor firmware sources.
