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

Pressure commands aim for the target within +/-2 lbs. Firmware corrects in
either direction if a reading skips past that band. It first uses the existing
80-second pressure-move window to settle; at that point, a reading from target
minus 2 lbs through target plus 10 lbs is accepted with DONE and no pressure
timeout warning. The host uses the same bands with its 90-second wait, across
initial buildup, ramp increments, final verification, and live adjustments.
The +10 lb allowance is inclusive and does not widen the underpressure band.

P0 still seeks zero pressure. Commanded treatment targets remain capped at
80 lbs, and the independent measured-pressure warning remains at 100 lbs.
Outside the settling allowance, existing timeout handling applies: firmware
warns and continues correcting; the host's bounded waits/retries can fail the
protocol. The paired pressure constants are checked by
`scripts/check_limits_sync.py`.

# Treatment motor speed

The app's Motor Speed controls require this firmware's `V<axial%>,<lateral%>,<pulse%>`
command. See [motor-speed.md](../../docs/motor-speed.md) for output limits,
acknowledgments, defaults, and deployment/bench-validation notes.
