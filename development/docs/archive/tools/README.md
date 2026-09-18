# Archived tools

## calibrate_gui.py
Retired 2026-06-11. This GUI calibration tool was protocol-incompatible
with the production firmware: it sent malformed move commands
(`A{actuator}{int}` truncated sub-inch moves to zero and addressed device 0),
used a `HA` homing command the firmware never implemented, and parsed a
status format (`A:1234 B:5678`) the firmware never emits -- so every
"recorded" position was 0. Its two-click full-inch measurement also
completed within a single click (delta always 0), and its
"Update Arduino Values" feature would have written `AFULLINCH 1` into
motor.ino.

Use `tools/calibrate.py` instead.
