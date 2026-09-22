# Treatment motor speed

The treatment screen puts a full-width live monitor above a compact settings strip,
loaded from device defaults or the linked patient's plan. Select a protocol using the
1–4 buttons beside its description. Open **Edit treatment** to change settings
in the popup. **Motor Speed**, directly below
**Pulse Rate**, sets axial, lateral, and pulsation output to one percentage.
Pulse Rate continues to control the interval between pulse strokes.

- Motor Speed defaults to **50%** and ranges from 50–100% in 5% increments.
  Percentages refer to the configured output ceiling of 1600 controller units,
  not measured travel velocity. The default is 800 units for all three outputs.
- Protocol, duration and motor speed lock throughout treatment, including pause.
  Permitted live pressure, angle and pulse-rate edits retain their existing
  confirmation and controller checks. The popup includes Stop during a run.
- Edits apply immediately; Done closes the popup. The main screen's Start button
  retains the existing start confirmation and device readiness checks.
- Mark As Default saves the shared speed using equal values in the existing
  three-field configuration format. Older unequal saved speeds load as their
  lowest percentage, so consolidation does not increase any motor's output.
- Patient plans retain their existing cloud fields; motor speed uses the current
  device treatment setting because the patient API has no motor-speed field.
- Horizontal movement, pressure release (`P0`), emergency release, and firmware
  reset defaults retain their existing behavior.

## Firmware and protocol

Deploy the updated app **and flash `runtime/arduino/motor/motor.ino`** together. The new
Treatment flow requires an acknowledged speed command and does not start
traction or pulsation if firmware is old, disconnected, busy, or rejects the
settings. The existing initial lateral centering can precede configuration
and continues at its original speed.

`V<axial>,<lateral>,<pulse>` sets three whole-number percentages atomically.
The shared UI sends equal values: `V75,75,75` selects 1200 units for each output. Invalid
fields or values outside 50–100 are rejected without changing any setting.
Configuration does not start a motor; active axial/pressure/pulse/release
operations reject it with `BUSY`.

Legacy firmware acknowledgment: `SPEED|75|90|60`. The host matches the exact
values to the queued command; a position `DONE` or keepalive `OK` cannot
confirm it. Protocol v2 uses the normal checksummed command frame and
sequence-correlated `OK|<seq>`. Missing acknowledgment fails within six seconds,
and Stop interrupts that wait.

The minimum axial/lateral outputs are unchanged, so the existing pressure and
lateral movement timeouts remain valid. This change does not extend them.

## Verification

Host tests cover bounds, shared and legacy settings, persistence, firmware
acknowledgments, cancellation, and UI locking. Native firmware tests inspect
actual encoded motor writes for axial/lateral position moves, pressure moves,
and alternating pulse strokes, plus release and emergency stop behavior.
Physical device testing remains necessary before treatment use.
