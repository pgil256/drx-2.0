# Archived tools

## calibrate_gui.py
Retired 2026-06-11 and removed on 2026-09-30; recover it from git history if
it is ever needed for reference. This GUI calibration tool was protocol-incompatible
with the production firmware: it sent malformed move commands
(`A{actuator}{int}` truncated sub-inch moves to zero and addressed device 0),
used a `HA` homing command the firmware never implemented, and parsed a
status format (`A:1234 B:5678`) the firmware never emits -- so every
"recorded" position was 0. Its two-click full-inch measurement also
completed within a single click (delta always 0), and its
"Update Arduino Values" feature would have written `AFULLINCH 1` into
motor.ino.

Use the in-app Hardware Tests & Calibration wizard
(`development/docs/hardware-service.md`).

## calibrate.py
The serial-console calibration script `development/tools/calibrate.py` was
removed on 2026-10-06; the in-app wizard supersedes it. Recover it from git
history if a console fallback is ever needed.
