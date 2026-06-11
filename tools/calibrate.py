#!/usr/bin/env python3
"""
Interactive calibration script for KneeSpa actuators.

Connects to the Arduino via serial and walks through calibrating
each actuator (A=axial, B=horizontal, C=lateral, leg length).

Usage:
    python tools/calibrate.py [--port /dev/serial0] [--dry-run]

Run from the project root directory.
"""

import argparse
import configparser
import os
import sys
import threading
import time
import serial
import signal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PORT = "/dev/serial0"
BAUD_RATE = 115200
SERIAL_TIMEOUT = 10

CONFIG_PATH_DEFAULT = os.path.join(
    os.path.dirname(__file__), "..", "main", "config", "kneespa.cfg"
)

# Actuator IDs (match constants.py)
ACTUATOR_A_ID = "12"  # Axial
ACTUATOR_B_ID = "13"  # Horizontal
ACTUATOR_C_ID = "14"  # Lateral

# Safety limits
AXIAL_MAX_INCHES = 4.0
HORIZONTAL_RANGE_DEG = (-25, 5)
LATERAL_RANGE_DEG = (-20, 20)
LATERAL_STEP_DEG = 2.5

# GPIO pins for leg length (BCM numbering)
GPIO_EXTRAFORWARD = 27
GPIO_EXTRABACKWARD = 22
GPIO_EXTRAENABLE = 17

# Jog step sizes
JOG_STEPS = {
    # All jogging is in raw potentiometer counts: factors do not exist
    # yet during calibration (~430 counts/inch on A per firmware AFULLINCH)
    "A": {"small": 50, "large": 400, "unit": "counts"},
    "B": {"small": 50, "large": 400, "unit": "counts"},
    "C": {"small": 25, "large": 100, "unit": "counts"},
}


# ---------------------------------------------------------------------------
# Serial communication (no PyQt5 dependency)
# ---------------------------------------------------------------------------

class ArduinoSerial:
    """Lightweight serial interface for calibration."""

    def __init__(self, port: str, dry_run: bool = False):
        self.port = port
        self.dry_run = dry_run
        self.ser = None
        self._lock = threading.Lock()
        self._running = False
        self._reader_thread = None

        # Latest status values (updated by reader thread)
        self.pos_a = 0
        self.pos_b = 0
        self.pos_c = 0
        self.pressure = 0.0
        self._status_lock = threading.Lock()
        self._status_event = threading.Event()
        self._ok_event = threading.Event()

    # -- connection ---------------------------------------------------------

    def connect(self) -> bool:
        if self.dry_run:
            print("[dry-run] Simulating connection")
            return True
        try:
            self.ser = serial.Serial(
                self.port, BAUD_RATE, timeout=SERIAL_TIMEOUT, write_timeout=1
            )
            time.sleep(3)  # wait for Arduino init
            # Toggle DTR to reset Arduino
            self.ser.dtr = False
            time.sleep(0.1)
            self.ser.dtr = True
            time.sleep(5)  # wait for Arduino boot
            self._start_reader()
            # Verify with test command
            if not self._verify():
                print("WARNING: Arduino did not respond to test command.")
                print("Continuing anyway - the connection may still work.")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        self._running = False
        if self._reader_thread:
            self._reader_thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _verify(self, tries: int = 3, timeout_s: float = 5.0) -> bool:
        for n in range(tries):
            self._ok_event.clear()
            with self._lock:
                if self.ser:
                    self.ser.reset_input_buffer()
                    self.ser.write(b"T\n")
                    self.ser.flush()
            if self._ok_event.wait(timeout_s):
                return True
            time.sleep(0.5)
        return False

    # -- send / receive -----------------------------------------------------

    def send(self, command: str) -> bool:
        if self.dry_run:
            print(f"  [dry-run] >> {command}")
            return True
        with self._lock:
            if not self.ser or not self.ser.is_open:
                print("Serial port not open")
                return False
            try:
                self.ser.write((command + "\n").encode())
                self.ser.flush()
                time.sleep(0.3)
                return True
            except Exception as e:
                print(f"Send failed: {e}")
                return False

    def request_status(self) -> bool:
        """Send HF1, wait for a status update, then send HF0."""
        self._status_event.clear()
        self.send("HF1")
        got = self._status_event.wait(timeout=3.0)
        self.send("HF0")
        return got

    def get_status(self):
        """Return latest (pos_a, pos_b, pos_c, pressure)."""
        with self._status_lock:
            return self.pos_a, self.pos_b, self.pos_c, self.pressure

    # -- background reader --------------------------------------------------

    def _start_reader(self):
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self):
        while self._running and self.ser and self.ser.is_open:
            try:
                if self.ser.in_waiting > 0:
                    data = self.ser.readline().decode(errors="replace").strip()
                    if data:
                        self._handle(data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                if self._running:
                    print(f"Read error: {e}")
                break

    def _handle(self, data: str):
        if "STATUS_START|" in data and "|STATUS_END" in data:
            payload = data.replace("STATUS_START|", "").replace("|STATUS_END", "")
            tokens = payload.split("|")
            if tokens[0] == "S" and len(tokens) >= 5:
                with self._status_lock:
                    self.pos_a = int(tokens[1])
                    self.pos_b = int(tokens[2])
                    self.pos_c = int(tokens[3])
                    self.pressure = float(tokens[4])
                self._status_event.set()
                # Send acknowledgment
                with self._lock:
                    if self.ser and self.ser.is_open:
                        self.ser.write(b"Q\n")
                        self.ser.flush()
        elif "OK" in data:
            self._ok_event.set()


# ---------------------------------------------------------------------------
# GPIO helper (optional, for leg length)
# ---------------------------------------------------------------------------

_gpio_available = False

def _init_gpio():
    global _gpio_available
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(GPIO_EXTRAFORWARD, GPIO.OUT)
        GPIO.setup(GPIO_EXTRABACKWARD, GPIO.OUT)
        GPIO.setup(GPIO_EXTRAENABLE, GPIO.OUT)
        GPIO.output(GPIO_EXTRAENABLE, GPIO.HIGH)
        GPIO.output(GPIO_EXTRAFORWARD, GPIO.LOW)
        GPIO.output(GPIO_EXTRABACKWARD, GPIO.LOW)
        _gpio_available = True
    except Exception as e:
        print(f"GPIO not available ({e}). Leg length calibration will use serial only.")
        _gpio_available = False


def _gpio_leg_forward():
    if _gpio_available:
        import RPi.GPIO as GPIO
        GPIO.output(GPIO_EXTRAFORWARD, GPIO.HIGH)
        GPIO.output(GPIO_EXTRABACKWARD, GPIO.LOW)


def _gpio_leg_reverse():
    if _gpio_available:
        import RPi.GPIO as GPIO
        GPIO.output(GPIO_EXTRAFORWARD, GPIO.LOW)
        GPIO.output(GPIO_EXTRABACKWARD, GPIO.HIGH)


def _gpio_leg_stop():
    if _gpio_available:
        import RPi.GPIO as GPIO
        GPIO.output(GPIO_EXTRAFORWARD, GPIO.LOW)
        GPIO.output(GPIO_EXTRABACKWARD, GPIO.LOW)


def _gpio_cleanup():
    if _gpio_available:
        import RPi.GPIO as GPIO
        GPIO.cleanup()


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser(allow_no_value=True)
    if os.path.exists(path):
        cfg.read(path)
    # Ensure required sections exist
    for section in ("Options", "AMarks", "BMarks", "CMarks"):
        if not cfg.has_section(section):
            cfg.add_section(section)
    return cfg


def save_config(cfg: configparser.ConfigParser, path: str):
    with open(path, "w") as f:
        cfg.write(f)
    print(f"\nConfig saved to {path}")


# ---------------------------------------------------------------------------
# User interaction helpers
# ---------------------------------------------------------------------------

def clear_line():
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()


def prompt_enter(msg: str = "Press Enter to continue..."):
    input(f"\n{msg}")


def prompt_yn(msg: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    resp = input(msg + suffix).strip().lower()
    if not resp:
        return default
    return resp in ("y", "yes")


def print_header(title: str):
    width = 60
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def print_status(ard: ArduinoSerial):
    a, b, c, p = ard.get_status()
    print(f"  Raw positions  ->  A: {a}  |  B: {b}  |  C: {c}  |  P: {p:.1f} lbs")


def refresh_status(ard: ArduinoSerial):
    """Request a fresh status update from the Arduino and display it."""
    if ard.dry_run:
        print("  [dry-run] Status: A=0  B=0  C=0  P=0.0")
        return
    if ard.request_status():
        print_status(ard)
    else:
        print("  (no status response - using last known values)")
        print_status(ard)


# ---------------------------------------------------------------------------
# Jog loop - lets user move an actuator with keyboard
# ---------------------------------------------------------------------------

def jog_loop(ard: ArduinoSerial, actuator: str, label: str) -> int:
    """
    Interactive jog loop for a single actuator.

    Controls:
        w / s  = jog forward / back (small step)
        e / d  = jog forward / back (large step)
        r      = refresh status
        x      = emergency stop
        q      = done - record this position

    Returns the raw position when the user presses 'q'.
    """
    steps = JOG_STEPS.get(actuator, JOG_STEPS["A"])
    small = steps["small"]
    large = steps["large"]
    unit = steps["unit"]

    print(f"\n  Jog controls for {label}:")
    print(f"    w/s = small step (+/- {small} {unit})")
    print(f"    e/d = large step (+/- {large} {unit})")
    print(f"    r   = refresh status from Arduino")
    print(f"    x   = emergency stop")
    print(f"    q   = done (record current position)\n")

    while True:
        try:
            cmd = input("  jog> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "q"

        if cmd == "q":
            refresh_status(ard)
            a, b, c, p = ard.get_status()
            if actuator == "A":
                return a
            elif actuator == "B":
                return b
            elif actuator == "C":
                return c
            return 0

        elif cmd == "w":
            _send_jog(ard, actuator, small, forward=True)
        elif cmd == "s":
            _send_jog(ard, actuator, small, forward=False)
        elif cmd == "e":
            _send_jog(ard, actuator, large, forward=True)
        elif cmd == "d":
            _send_jog(ard, actuator, large, forward=False)
        elif cmd == "r":
            refresh_status(ard)
        elif cmd == "x":
            ard.send("X")
            print("  !! Emergency stop sent")
        else:
            print(f"  Unknown command: {cmd}")


def _jog_by_position(ard: ArduinoSerial, device: str, current: int, step, forward: bool):
    """Jog an actuator by raw counts using an absolute I<device> target.

    The position potentiometer is readable before any calibration exists,
    so raw-count jogging needs no factors. The firmware treats moves
    inside its 25-count deadband as already complete, so enforce a
    useful minimum step.
    """
    step = max(int(step), 30)
    target = current + step if forward else current - step
    target = max(0, target)
    ard.send(f"I{device}{target}")
    time.sleep(1.0)  # give the move time to complete
    refresh_status(ard)


def _send_jog(ard: ArduinoSerial, actuator: str, step, forward: bool):
    """Send a jog command appropriate for the actuator type.

    NOTE: 'F' commands drive the FIT/leg-length motor, not actuators
    12/13 -- the previous implementation jogged the wrong motor, so
    recorded A/B positions never changed and any factor computed from
    them was meaningless.
    """
    if actuator == "A":
        a, _, _, _ = ard.get_status()
        _jog_by_position(ard, "12", a, step, forward)
        print(f"  Jogged A {'forward' if forward else 'back'}")

    elif actuator == "B":
        _, b, _, _ = ard.get_status()
        _jog_by_position(ard, "13", b, step, forward)
        print(f"  Jogged B {'forward' if forward else 'back'}")

    elif actuator == "C":
        # Lateral: send K<raw_position> - jog by step counts
        _, _, c_pos, _ = ard.get_status()
        new_pos = c_pos + (int(step) if forward else -int(step))
        new_pos = max(0, new_pos)
        ard.send(f"K{new_pos}")
        direction = "right" if forward else "left"
        print(f"  Jogged C {direction} to raw position {new_pos}")
        time.sleep(0.5)
        refresh_status(ard)


# ---------------------------------------------------------------------------
# Jog loop for leg length (GPIO-driven)
# ---------------------------------------------------------------------------

def jog_leg_loop(ard: ArduinoSerial) -> None:
    """
    Interactive jog loop for leg length actuator.

    Controls:
        w = forward (extend)
        s = reverse (retract)
        e = fast forward
        d = fast reverse
        x = stop
        q = done
    """
    print("\n  Jog controls for leg length:")
    print("    w = forward (extend)")
    print("    s = reverse (retract)")
    print("    e = fast forward")
    print("    d = fast reverse")
    print("    x = stop")
    print("    q = done\n")

    while True:
        try:
            cmd = input("  leg-jog> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "q"

        if cmd == "q":
            _gpio_leg_stop()
            ard.send("F0")
            break
        elif cmd == "w":
            ard.send("F+")
            _gpio_leg_forward()
            print("  Moving forward...")
            time.sleep(0.5)
            _gpio_leg_stop()
            ard.send("F0")
            print("  Stopped")
        elif cmd == "s":
            ard.send("F-")
            _gpio_leg_reverse()
            print("  Moving reverse...")
            time.sleep(0.5)
            _gpio_leg_stop()
            ard.send("F0")
            print("  Stopped")
        elif cmd == "e":
            ard.send("FF")
            _gpio_leg_forward()
            print("  Fast forward...")
            time.sleep(1.0)
            _gpio_leg_stop()
            ard.send("F0")
            print("  Stopped")
        elif cmd == "d":
            ard.send("FR")
            _gpio_leg_reverse()
            print("  Fast reverse...")
            time.sleep(1.0)
            _gpio_leg_stop()
            ard.send("F0")
            print("  Stopped")
        elif cmd == "x":
            _gpio_leg_stop()
            ard.send("F0")
            print("  !! Stopped")
        else:
            print(f"  Unknown command: {cmd}")


# ---------------------------------------------------------------------------
# Calibration routines
# ---------------------------------------------------------------------------

def calibrate_axial(ard: ArduinoSerial, cfg: configparser.ConfigParser):
    """Calibrate Actuator A (axial)."""
    print_header("Actuator A - Axial Calibration")
    print("""
  This calibrates the axial (up/down pressure) actuator.

  Step 1: Jog the actuator to its physical ZERO position
          (fully retracted / home). Record the raw position.
  Step 2: Jog the actuator to a known distance (4 inches).
          Record the raw position.
  Step 3: The script computes a_factor from the two points.
    """)

    # Step 1: Zero position
    print("--- Step 1: Move to ZERO (fully retracted) ---")
    prompt_enter("Physically move actuator A to its home/zero position, then press Enter to start jogging.")
    refresh_status(ard)
    zero_pos = jog_loop(ard, "A", "Actuator A (zero position)")
    print(f"\n  Recorded ZERO position: {zero_pos}")

    # Step 2: Known distance
    known_distance = 4.0
    print(f"\n--- Step 2: Move to {known_distance} inches ---")
    prompt_enter(f"Now jog actuator A to exactly {known_distance} inches of travel, then press Enter.")
    refresh_status(ard)
    far_pos = jog_loop(ard, "A", f"Actuator A ({known_distance} in)")
    print(f"\n  Recorded {known_distance}-inch position: {far_pos}")

    # Compute factor
    delta = abs(far_pos - zero_pos)
    if delta == 0:
        print("\n  ERROR: Zero and far positions are the same. Cannot compute factor.")
        print("  Skipping a_factor calculation.")
        return

    # a_factor relates to: position = inches * (a_factor / 8.0)
    # So: a_factor = (delta / known_distance) * 8
    a_factor = int((delta / known_distance) * 8)

    print(f"\n  Computed a_factor: {a_factor}")
    print(f"    (delta={delta} steps over {known_distance} in => {delta/known_distance:.1f} steps/in)")

    if prompt_yn("  Save these values?"):
        cfg.set("Options", "a_factor", str(a_factor))
        cfg.set("AMarks", "0.0", str(zero_pos))
        print("  Saved a_factor and AMarks[0.0]")
    else:
        print("  Skipped saving.")


def calibrate_horizontal(ard: ArduinoSerial, cfg: configparser.ConfigParser):
    """Calibrate Actuator B (horizontal)."""
    print_header("Actuator B - Horizontal Calibration")
    print("""
  This calibrates the horizontal (flexion angle) actuator.

  Step 1: Jog to the physical ZERO position (neutral).
          Record the raw position.
  Step 2: Jog to a known distance (4 inches of travel).
          Record the raw position.
  Step 3: The script computes b_factor from the two points.
    """)

    # Step 1: Zero position
    print("--- Step 1: Move to ZERO (neutral) ---")
    prompt_enter("Move actuator B to its zero/neutral position, then press Enter.")
    refresh_status(ard)
    zero_pos = jog_loop(ard, "B", "Actuator B (zero position)")
    print(f"\n  Recorded ZERO position: {zero_pos}")

    # Step 2: Known distance
    known_distance = 4.0
    print(f"\n--- Step 2: Move to {known_distance} inches ---")
    prompt_enter(f"Now jog actuator B to exactly {known_distance} inches of travel, then press Enter.")
    refresh_status(ard)
    far_pos = jog_loop(ard, "B", f"Actuator B ({known_distance} in)")
    print(f"\n  Recorded {known_distance}-inch position: {far_pos}")

    # Compute factor
    delta = abs(far_pos - zero_pos)
    if delta == 0:
        print("\n  ERROR: Zero and far positions are the same. Cannot compute factor.")
        return

    b_factor = int((delta / known_distance) * 8)

    print(f"\n  Computed b_factor: {b_factor}")
    print(f"    (delta={delta} steps over {known_distance} in => {delta/known_distance:.1f} steps/in)")

    if prompt_yn("  Save these values?"):
        cfg.set("Options", "b_factor", str(b_factor))
        cfg.set("BMarks", "0.0", str(zero_pos))
        print("  Saved b_factor and BMarks[0.0]")
    else:
        print("  Skipped saving.")


def calibrate_lateral(ard: ArduinoSerial, cfg: configparser.ConfigParser):
    """Calibrate Actuator C (lateral) with multi-point mapping."""
    print_header("Actuator C - Lateral Calibration")
    print("""
  This calibrates the lateral actuator by building a position
  lookup table mapping degrees (-20 to +20) to raw step positions.

  You will jog the actuator to each marked degree position and
  record the raw step count. The script walks through every
  2.5-degree increment.

  Negative degrees = LEFT, Positive degrees = RIGHT, 0 = CENTER.
    """)

    # Generate degree list: -20, -17.5, ... 0 ... 17.5, 20
    degrees_list = []
    deg = -20.0
    while deg <= 20.0:
        degrees_list.append(deg)
        deg = round(deg + LATERAL_STEP_DEG, 1)

    marks = {}
    total = len(degrees_list)

    for i, deg in enumerate(degrees_list):
        deg_label = f"{deg:+.1f}" if deg != 0 else "0.0"
        side = "LEFT" if deg < 0 else "RIGHT" if deg > 0 else "CENTER"
        print(f"\n--- Position {i+1}/{total}: {deg_label} degrees ({side}) ---")
        prompt_enter(f"Jog actuator C to the {deg_label}{chr(176)} mark, then press Enter.")
        refresh_status(ard)
        raw_pos = jog_loop(ard, "C", f"Actuator C ({deg_label}{chr(176)})")
        marks[deg] = raw_pos
        print(f"  Recorded: {deg_label}{chr(176)} => raw position {raw_pos}")

    # Compute c_factor from full range
    if -20.0 in marks and 20.0 in marks:
        full_range = abs(marks[20.0] - marks[-20.0])
        # c_factor: inches = steps / (c_factor / 6)
        # Full range is 40 degrees. The factor relates steps to a 6-unit reference.
        c_factor = int(full_range * 6 / 40) if full_range > 0 else 3640
        print(f"\n  Computed c_factor: {c_factor}")
        print(f"    (full range = {full_range} steps over 40 degrees)")
    else:
        c_factor = None
        print("\n  Could not compute c_factor (missing -20 or +20 positions)")

    # Display summary table
    print("\n  CMarks Summary:")
    print("  " + "-" * 30)
    for deg in sorted(marks.keys()):
        deg_key = f"{deg:.1f}"
        print(f"    {deg_key:>6}{chr(176)}  =>  {marks[deg]}")
    print("  " + "-" * 30)

    if prompt_yn("  Save these values?"):
        # Clear existing CMarks
        cfg.remove_section("CMarks")
        cfg.add_section("CMarks")
        for deg in sorted(marks.keys()):
            cfg.set("CMarks", f"{deg:.1f}", str(marks[deg]))
        if c_factor is not None:
            cfg.set("Options", "c_factor", str(c_factor))
        print("  Saved CMarks table and c_factor")
    else:
        print("  Skipped saving.")


def calibrate_leg_length(ard: ArduinoSerial, cfg: configparser.ConfigParser):
    """Calibrate the leg length actuator."""
    print_header("Leg Length Actuator Calibration")
    print("""
  The leg length actuator is controlled via GPIO + Arduino commands.
  Calibration involves:
    1. Fully retracting to establish the zero/home position
    2. Verifying forward/reverse movement works

  Controls: w=forward, s=reverse, e=fast fwd, d=fast rev, x=stop, q=done
    """)

    if not _gpio_available and not ard.dry_run:
        print("  WARNING: GPIO is not available on this system.")
        print("  Serial commands (F+, F-, FF, FR, F0) will still be sent.")
        if not prompt_yn("  Continue anyway?"):
            return

    # Step 1: Reset to home
    print("--- Step 1: Reset to home position ---")
    if prompt_yn("  Send reset command (FR = fast reverse to home)?"):
        ard.send("FR")
        _gpio_leg_reverse()
        print("  Retracting to home...")
        time.sleep(3)
        _gpio_leg_stop()
        ard.send("F0")
        print("  Home position reached (assumed)")

    # Step 2: Interactive jog to verify
    print("\n--- Step 2: Verify movement ---")
    print("  Use the jog controls to verify the actuator moves correctly.")
    jog_leg_loop(ard)

    print("\n  Leg length calibration complete.")
    print("  (Leg length tracks position in software - no config values to save.)")


MIN_PLAUSIBLE_SCALE_FACTOR = 1000.0


def calibrate_load_cell(ard: ArduinoSerial, cfg: configparser.ConfigParser):
    """Calibrate the load cell with a tare + known-weight procedure.

    The previous flow conflated the tare OFFSET with the SCALE FACTOR:
    the prompt asked for a zero offset but the value was sent as
    L0<value> -> scale.set_scale(), inflating readings by orders of
    magnitude (and a "0" answer meant set_scale(0): division by zero on
    the firmware).
    """
    print_header("Load Cell / Pressure Calibration")
    print("""
  Two-step calibration:

  Step 1: TARE  - remove all load; the firmware zeroes its offset.
  Step 2: SCALE - place a known weight; the factor is derived from the
                  reading and verified before anything is saved.
    """)

    current_cal = cfg.get("Options", "calibration", fallback="1.0")
    try:
        current_factor = float(current_cal)
    except ValueError:
        current_factor = 1.0
    print(f"  Current scale factor in config: {current_factor}")

    # --- Step 1: tare with no load ---
    print("\n--- Step 1: Tare (zero offset) ---")
    prompt_enter("Remove ALL load from the axial actuator, then press Enter.")
    ard.send("L1")  # firmware: set_scale(current) + tare
    time.sleep(2)
    refresh_status(ard)
    _, _, _, zero_reading = ard.get_status()
    print(f"  Reading after tare: {zero_reading:.2f} (should be ~0)")

    # --- Step 2: known weight ---
    print("\n--- Step 2: Known weight ---")
    weight_str = input("  Enter the known weight in lbs (e.g. 25), or blank to skip: ").strip()
    if not weight_str:
        print("  Skipped scale-factor derivation; tare only.")
        return
    try:
        known_weight = float(weight_str)
        if known_weight <= 0:
            raise ValueError("weight must be positive")
    except ValueError as e:
        print(f"  Invalid weight ({e}). Aborting load-cell calibration.")
        return

    prompt_enter(f"Apply the {known_weight} lbs load, then press Enter.")
    time.sleep(2)
    refresh_status(ard)
    _, _, _, reading = ard.get_status()
    print(f"  Reading under load: {reading:.2f} (with factor {current_factor})")

    if abs(reading) < 0.01:
        print("  Reading is zero - check load cell wiring. Aborting.")
        return

    # units = (raw - offset) / factor  =>  new_factor = factor * units / W
    new_factor = current_factor * (reading / known_weight)
    print(f"  Derived scale factor: {new_factor:.2f}")

    if abs(new_factor) < MIN_PLAUSIBLE_SCALE_FACTOR:
        print(
            f"  Factor magnitude {abs(new_factor):.1f} is implausible for this "
            f"hardware (expected tens of thousands). NOT saved."
        )
        return

    # Apply and verify before saving
    ard.send(f"L0{new_factor}")
    time.sleep(2)
    prompt_enter("Re-apply (or keep) the known weight, then press Enter to verify.")
    refresh_status(ard)
    _, _, _, verify_reading = ard.get_status()
    error_pct = abs(verify_reading - known_weight) / known_weight * 100
    print(f"  Verification: reads {verify_reading:.2f} lbs vs {known_weight} lbs "
          f"({error_pct:.1f}% error)")

    if error_pct > 5.0:
        print("  Error exceeds 5% - NOT saved. Check setup and repeat.")
        return

    cfg.set("Options", "calibration", f"{new_factor:.2f}")
    print(f"  Saved calibration = {new_factor:.2f}")


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="KneeSpa actuator calibration tool")
    parser.add_argument(
        "--port", default=DEFAULT_PORT, help=f"Serial port (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--config",
        default=CONFIG_PATH_DEFAULT,
        help=f"Config file path (default: {CONFIG_PATH_DEFAULT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without connecting to Arduino (for testing the script)",
    )
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)

    print_header("KneeSpa Calibration Tool")
    print(f"  Serial port:  {args.port}")
    print(f"  Config file:  {config_path}")
    print(f"  Dry run:      {args.dry_run}")

    # Load config
    cfg = load_config(config_path)

    # Show current calibration values
    print("\n  Current calibration values:")
    print(f"    a_factor:    {cfg.get('Options', 'a_factor', fallback='(not set)')}")
    print(f"    b_factor:    {cfg.get('Options', 'b_factor', fallback='(not set)')}")
    print(f"    c_factor:    {cfg.get('Options', 'c_factor', fallback='(not set)')}")
    print(f"    calibration: {cfg.get('Options', 'calibration', fallback='(not set)')}")
    print(f"    AMarks[0.0]: {cfg.get('AMarks', '0.0', fallback='(not set)')}")
    print(f"    BMarks[0.0]: {cfg.get('BMarks', '0.0', fallback='(not set)')}")
    cmarks_count = len(dict(cfg.items("CMarks"))) if cfg.has_section("CMarks") else 0
    print(f"    CMarks:      {cmarks_count} entries")

    # Init GPIO for leg length
    _init_gpio()

    # Connect to Arduino
    ard = ArduinoSerial(args.port, dry_run=args.dry_run)
    if not ard.connect():
        print("\nFailed to connect. Check the serial port and try again.")
        _gpio_cleanup()
        sys.exit(1)

    print("\n  Arduino connected.\n")

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\n  Interrupted! Sending emergency stop...")
        ard.send("X")
        _gpio_leg_stop()
        ard.disconnect()
        _gpio_cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    # Main menu loop
    try:
        while True:
            print("\n" + "-" * 40)
            print("  Calibration Menu")
            print("-" * 40)
            print("  1) Actuator A - Axial")
            print("  2) Actuator B - Horizontal")
            print("  3) Actuator C - Lateral (multi-point)")
            print("  4) Leg Length Actuator")
            print("  5) Load Cell / Pressure")
            print("  6) Run ALL calibrations")
            print("  7) Show current config values")
            print("  8) Send zero mark + calibration to Arduino")
            print("  9) Save config and exit")
            print("  0) Exit without saving")
            print("-" * 40)

            choice = input("  Select: ").strip()

            if choice == "1":
                calibrate_axial(ard, cfg)
            elif choice == "2":
                calibrate_horizontal(ard, cfg)
            elif choice == "3":
                calibrate_lateral(ard, cfg)
            elif choice == "4":
                calibrate_leg_length(ard, cfg)
            elif choice == "5":
                calibrate_load_cell(ard, cfg)
            elif choice == "6":
                calibrate_axial(ard, cfg)
                calibrate_horizontal(ard, cfg)
                calibrate_lateral(ard, cfg)
                calibrate_leg_length(ard, cfg)
                calibrate_load_cell(ard, cfg)
            elif choice == "7":
                print("\n  Current config values:")
                for section in cfg.sections():
                    print(f"\n  [{section}]")
                    for key, val in cfg.items(section):
                        print(f"    {key} = {val}")
            elif choice == "8":
                a_zero = cfg.get("AMarks", "0.0", fallback="0")
                b_zero = cfg.get("BMarks", "0.0", fallback="0")
                cal = cfg.get("Options", "calibration", fallback="1.0")
                # Delimited form: the fixed-width legacy format truncated
                # 4-digit zero marks (1900 -> 190)
                print(f"  Sending zero mark: L5|{a_zero}|{b_zero}")
                ard.send(f"L5|{a_zero}|{b_zero}")
                time.sleep(1)
                try:
                    cal_value = float(cal)
                except ValueError:
                    cal_value = 0.0
                if abs(cal_value) < MIN_PLAUSIBLE_SCALE_FACTOR:
                    # set_scale(0) divides by zero on the firmware; tiny
                    # factors mean the device was never weight-calibrated
                    print(
                        f"  NOT sending calibration: factor {cal} is "
                        "implausible. Run load-cell calibration first."
                    )
                else:
                    print(f"  Sending calibration: L0{cal}")
                    ard.send(f"L0{cal}")
                print("  Done.")
            elif choice == "9":
                save_config(cfg, config_path)
                break
            elif choice == "0":
                if prompt_yn("  Exit without saving?"):
                    break
            else:
                print("  Invalid selection.")

    finally:
        # Clean up
        ard.send("X")  # safety stop
        ard.disconnect()
        _gpio_cleanup()
        print("  Goodbye.")


if __name__ == "__main__":
    main()
