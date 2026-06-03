Canonical Motor Firmware
========================

This is the canonical KneeSpa motor-controller firmware tree.

Use `main/motor/motor.ino` for the Arduino Mega motor controller. This tree also
contains the PlatformIO test harness:

```bash
cd main/motor
pio test -e native
```

The duplicate legacy sketch previously under `main/arduino/motor/` was removed to
avoid two diverging motor firmware sources.
