# Treatment motor speed

Open **Protocols → Settings → Motor Speed** before starting a treatment.
Three independent sliders set axial movement, lateral movement, and motor
movement during pulsation. The existing **Pulse Rate** setting still controls
the interval between pulse strokes; changing pulsation motor speed does not
change that interval.

- Sliders range from 50–100% in 5% increments. Percentages refer to the
  configured treatment output ceiling of 1600 controller units, not a measured
  travel velocity or percentage of the previous speed.
- Axial and lateral default to 50% (800 units); pulsation defaults to 100%
  (1600 units). These preserve the previous fixed outputs.
- The 800-unit minimum preserves the documented axial breakaway floor.
  Axial/lateral cannot be reduced below their previous output in this version.
  The ceiling preserves the previous pulsation maximum. Actual travel speed
  depends on load and hardware; the new range needs bench validation.
- Motor speeds lock during treatment, including pause and reset/reconnect.
  Stop remains available. **Mark As Default** saves all three speeds with the
  other treatment settings. Old configurations load the original output defaults.
- Horizontal movement retains its fixed output. Pressure release (`P0`) and
  emergency release retain their fixed 800-unit output. `X` also restores the
  original speed defaults so later Setup moves use their original output.

## Firmware and protocol

Deploy the updated app **and flash `main/motor/motor.ino`** together. The new
Treatment flow requires an acknowledged speed command and does not start
traction or pulsation if firmware is old, disconnected, busy, or rejects the
settings. The existing initial lateral centering can precede configuration
and continues at its original speed.

`V<axial>,<lateral>,<pulse>` sets three whole-number percentages atomically.
Example: `V75,90,60` selects 1200, 1440, and 960 controller units. Invalid
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

Host tests cover bounds, independent settings, persistence, firmware
acknowledgments, cancellation, and UI locking. Native firmware tests inspect
actual encoded motor writes for axial/lateral position moves, pressure moves,
and alternating pulse strokes, plus release and emergency stop behavior.
Physical device testing remains necessary before treatment use.
