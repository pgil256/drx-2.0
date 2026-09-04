#!/usr/bin/env python3
"""Assert the host/firmware safety-limit pairs have not drifted (H7).

The same physical limits are declared twice -- in main/config/constants.py
(host-side clamps) and in main/motor/motor.ino (the authoritative firmware
clamps). Nothing ties them together at build time, and they have drifted
before (the firmware booted at a 200 ms pulse cadence while the host UI
claimed 2 pulses/sec). This script parses both files and fails when any
paired value differs, so CI catches the drift instead of a patient.

Intentionally NOT paired: host MIN_PRESSURE (10 lbs, the lowest *target* a
protocol may request) vs firmware MIN_PRESSURE_LBS (0, the clamp floor --
the firmware must accept P0 for full release).

Run from anywhere: paths resolve relative to the repo root.
Exit code 0 = in sync, 1 = drift detected or a constant went missing.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTANTS_PY = REPO_ROOT / "main" / "config" / "constants.py"
CONFIG_PY = REPO_ROOT / "main" / "config" / "config.py"
MOTOR_INO = REPO_ROOT / "main" / "motor" / "motor.ino"

# (constants.py name, motor.ino #define name)
PAIRS = [
    ("PRESSURE_MAX", "MAX_PRESSURE_LBS"),
    ("PRESSURE_WARNING_MAX", "PRESSURE_WARNING_LBS"),
    ("AXIAL_MAX", "AXIAL_MAX_POS"),
    ("LATERAL_MIN", "LATERAL_MIN_POS"),
    ("LATERAL_MAX", "LATERAL_MAX_POS"),
    ("HORIZONTAL_MIN", "HORIZONTAL_MIN_POS"),
    ("HORIZONTAL_MAX", "HORIZONTAL_MAX_POS"),
    ("MIN_JERK_INTERVAL_MS", "MIN_JERK_INTERVAL"),
    ("MAX_JERK_INTERVAL_MS", "MAX_JERK_INTERVAL"),
]


def parse_py_int(source: str, name: str):
    match = re.search(
        rf"^{re.escape(name)}\s*=\s*(\d+)\b", source, re.MULTILINE
    )
    return int(match.group(1)) if match else None


def parse_define_int(source: str, name: str):
    match = re.search(
        rf"^#define\s+{re.escape(name)}\s+(\d+)\b", source, re.MULTILINE
    )
    return int(match.group(1)) if match else None


def check_limits_sync():
    """Return a list of human-readable problems (empty = in sync)."""
    problems = []
    constants_src = CONSTANTS_PY.read_text(encoding="utf-8")
    config_src = CONFIG_PY.read_text(encoding="utf-8")
    motor_src = MOTOR_INO.read_text(encoding="utf-8")

    for py_name, ino_name in PAIRS:
        py_val = parse_py_int(constants_src, py_name)
        ino_val = parse_define_int(motor_src, ino_name)
        if py_val is None:
            problems.append(f"{py_name} not found in {CONSTANTS_PY.name}")
        if ino_val is None:
            problems.append(f"#define {ino_name} not found in {MOTOR_INO.name}")
        if py_val is not None and ino_val is not None and py_val != ino_val:
            problems.append(
                f"DRIFT: {py_name}={py_val} (constants.py) != "
                f"{ino_name}={ino_val} (motor.ino)"
            )

    # The firmware's boot cadence is a plain initializer, not a #define.
    default_ms = parse_py_int(constants_src, "DEFAULT_JERK_INTERVAL_MS")
    boot_match = re.search(
        r"^\s*unsigned long jerkInterval\s*=\s*(\d+)\b", motor_src, re.MULTILINE
    )
    boot_ms = int(boot_match.group(1)) if boot_match else None
    if default_ms is None:
        problems.append("DEFAULT_JERK_INTERVAL_MS not found in constants.py")
    if boot_ms is None:
        problems.append("jerkInterval initializer not found in motor.ino")
    if default_ms is not None and boot_ms is not None and default_ms != boot_ms:
        problems.append(
            f"DRIFT: DEFAULT_JERK_INTERVAL_MS={default_ms} (constants.py) != "
            f"jerkInterval boot default={boot_ms} (motor.ino)"
        )

    # And the UI-facing default pulse rate must agree with that cadence:
    # Configuration.default_pulse_rate is what the Treatment slider shows.
    rate_match = re.search(
        r"self\.default_pulse_rate\s*=\s*([\d.]+)", config_src
    )
    if rate_match is None:
        problems.append("default_pulse_rate not found in config.py")
    elif default_ms is not None:
        implied_ms = int(round(1000.0 / float(rate_match.group(1))))
        if implied_ms != default_ms:
            problems.append(
                f"DRIFT: config.py default_pulse_rate={rate_match.group(1)}/sec "
                f"implies {implied_ms} ms != DEFAULT_JERK_INTERVAL_MS={default_ms}"
            )

    return problems


def main():
    problems = check_limits_sync()
    if problems:
        print("Host/firmware safety-limit sync check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    pair_count = len(PAIRS) + 2  # + boot cadence + UI pulse-rate default
    print(f"Host/firmware safety limits in sync ({pair_count} checks).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
