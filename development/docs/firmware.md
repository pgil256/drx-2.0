Canonical Motor Firmware
========================

This is the canonical KneeSpa motor-controller firmware tree.

Use `runtime/arduino/motor/motor.ino` for the Arduino Mega motor controller.
The native unit-test harness is separate in `development/tests/firmware/`
(g++ + vendored Unity). From the repository root:

```bash
bash development/tests/firmware/run_native_tests.sh
```

Where PlatformIO is available, run `pio test -e native` in `runtime/arduino/motor/`.
The tests stub the Arduino core via `development/tests/firmware/arduino_shim.h`; in test builds the
stub `delay()` advances the mock `millis()` clock so timeout loops terminate.

The duplicate legacy sketch previously under `devices/maintenance/arduino/motor/` was removed to
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
`development/scripts/check_limits_sync.py`.

Pulsing (`J<ms>`) alternates axial release and push strokes around the
pressure target. A release reverses for the whole interval and stops early only
if pressure reads zero (contact lost); it does not restart on rebound. The push
that follows drives forward until pressure is back at target, then starts the
next release at once instead of waiting out the interval. A push that has not
reached target within 5 seconds (10 seconds if it starts in the first 30 seconds
of pulsing) latches `FAULT|PULSE_RECOVERY_TIMEOUT`. A full pulse takes the
interval plus the push, so the app's Pulse Rate (interval = 1000 ms divided by
pulses/sec) is the fastest rate a pulse can reach.

# Pulse stroke stop and recovery window

Firmware `2026-10-28-DRX2-pulse-overshoot` changes only pulsing (`J`). It ports
the drx-demo `2026-10-28-pulse-overshoot` fix onto the strokes described above.
Demo's strokes differ: its release still stops 2 lb under target and its push
still holds at target until the interval ends. From 10/16 to 10/28, 12 of
KS-FB's 55 demo runs ended in a pulse safety stop:

- **Six `PRESSURE_LIMIT` stops.** Forward strokes on a stiff leg (high targets,
  or the actuator far extended) overshot past target + 10 lb. Each stroke used
  to stop only on a sample at or above target. It now also stops when the rise
  since the previous sample (measured within 250 ms) would carry the next
  sample, 100 ms ahead (`PULSE_STOP_LEAD_MS`), to target. If the coast stalls
  below target, the stroke pushes again. A release still starts only from a
  sample at or above target.
- **Six `PULSE_RECOVERY_TIMEOUT` stops**, all in the first 20 s of pulsing while
  the load sagged. At the operator's request, a recovery that starts within the
  first 30 s of pulsing now has 10 s to regain target; later recoveries keep
  5 s. A duplicate `J` does not restart either window.

The +10 lb overshoot limit, the absolute cutoff, the sensor timeout, the
adjustable pulse cadence and speed, and stop handling are unchanged. In a
synthetic stiff load (15 lb/s, 100 ms actuator lag, 40 lb target, `test_nb2`)
the peak drops from 42.5 to 41 lb. The real gain depends on how far the actuator
coasts after a stop, and a lag well past the 100 ms lead still overshoots, so
`PULSE_STOP_LEAD_MS` needs a bench check. The demo version is on the units, but
this version, with these strokes, has not been flashed or bench-tested.

# Treatment motor speed

The app's Motor Speed controls require this firmware's `V<axial%>,<lateral%>,<pulse%>`
command. See [motor-speed.md](motor-speed.md) for output limits,
acknowledgments, defaults, and deployment/bench-validation notes.
