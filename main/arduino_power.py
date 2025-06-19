#!/usr/bin/env python3
"""
Toggle Arduino power via a relay/MOSFET on GPIO 17.

Usage:
    sudo python3 arduino_power.py on
    sudo python3 arduino_power.py off
    sudo python3 arduino_power.py cycle 3      # off 3 s then on
"""

import sys
import time
import RPi.GPIO as GPIO

PIN = 17          # BCM numbering
ACTIVE_HIGH = True  # False if your relay is active-low

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT, initial=GPIO.LOW if ACTIVE_HIGH else GPIO.HIGH)


def set_state(enable: bool):
    """Enable (True) or disable (False) the relay/MOSFET."""
    GPIO.output(PIN, GPIO.HIGH if (enable == ACTIVE_HIGH) else GPIO.LOW)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    try:
        if cmd == "on":
            set_state(True)

        elif cmd == "off":
            set_state(False)

        elif cmd == "cycle":
            delay = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
            set_state(False)
            time.sleep(delay)
            set_state(True)

        else:
            print("Unknown command:", cmd)
            print(__doc__)

    finally:
        # leave GPIO configured so relay stays in chosen state
        GPIO.cleanup(exclude=[PIN])  # requires RPi.GPIO ≥0.7


if __name__ == "__main__":
    main()
