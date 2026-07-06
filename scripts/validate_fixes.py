#!/usr/bin/env python3
"""
Validate the high-priority audit fixes without importing GUI or hardware modules.

A fast, import-free snapshot check: each entry greps for the code shape a
past audit fix introduced, so an accidental revert fails CI immediately.
Patterns were updated 2026-07-05 for the reconciled FAILSAFE tree (single
I/O-thread Arduino, decomposed controllers, emergencyStopAndRelease).
Runs in CI next to scripts/check_limits_sync.py.
"""

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "main"


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def check(path, patterns, description):
    content = read(path)
    missing = [
        pattern
        for pattern in patterns
        if not re.search(pattern, content, re.MULTILINE | re.DOTALL)
    ]
    if missing:
        return False, f"{description}: missing {missing[0]}"
    return True, description


def check_absent(path, description):
    if path.exists():
        return False, f"{description}: still present at {path}"
    return True, description


def validate_fixes():
    checks = [
        check(
            MAIN / "helpers" / "arduino.py",
            [
                r"connection_ready_event = threading\.Event\(\)",
                r"def send\(self, command\):.*Never blocks on the port",
                r"self\._priority_queue\.append\(command\)",
            ],
            "Arduino readiness event and non-blocking queued send",
        ),
        check(
            MAIN / "kneespa.py",
            [
                r"def ensure_arduino_connection\(self\):\s*"
                r"return self\.connection\.ensure_arduino_connection\(\)",
            ],
            "Main window delegates connection readiness to ConnectionManager",
        ),
        check(
            MAIN / "controllers" / "connection_manager.py",
            [
                r"def ensure_arduino_connection\(self\):",
                r"connection_ready_event",
            ],
            "ConnectionManager owns the Arduino readiness gate",
        ),
        check(
            MAIN / "controllers" / "protocol_controller.py",
            [
                r"if not window\.ensure_arduino_connection\(\):",
            ],
            "Protocol start is gated on Arduino readiness",
        ),
        check(
            MAIN / "helpers" / "protocols.py",
            [
                r"if not self\.arduino\.send\(f\"P\{current_command\}\"\):",
                r"return False\s+.*Pressure did not stabilize",
                r"if not self\.arduino\.send\(f\"K\{position\}\"\):",
                r"Angle position not verified within timeout.*return False",
            ],
            "Protocols fail on unverified commands",
        ),
        check(
            MAIN / "kneespa.py",
            [
                r"AXIAL_MAX_INCHES",
                r"LATERAL_MAX_DEGREES",
                r"HORIZONTAL_MAX_DEGREES",
            ],
            "UI uses explicit human-unit limits",
        ),
        check(
            MAIN / "motor" / "motor.ino",
            [
                r"#define MAX_PRESSURE_LBS\s+80",
                r"clampPressureTarget",
                r"clampPositionTarget",
                r"emergencyStopAndRelease\(\"Pressure limit exceeded\"\)",
            ],
            "Primary firmware has hard clamps",
        ),
        check_absent(
            MAIN / "arduino" / "motor" / "motor.ino",
            "Duplicate motor firmware tree removed",
        ),
        check(
            MAIN / "helpers" / "secure_auth.py",
            [
                r"ADMIN_PIN_HASH",
                r"USER_PIN_HASH",
                r"hashlib\.sha256",
            ],
            "Authentication uses hashed PIN keys",
        ),
        check(
            MAIN / "config" / "constants.py",
            [
                r"KNEESPA_BASE_DIR",
                r"KNEESPA_CONFIG_PATH",
                r"KNEESPA_SMTP_PASSWORD",
            ],
            "Paths and credentials are environment-configurable",
        ),
        check(
            MAIN / "config" / "config.py",
            [
                r"def _write_default_config",
                r"self\.config\[\"AMarks\"\]",
                r"self\.config\[\"BMarks\"\]",
                r"self\.config\[\"CMarks\"\]",
            ],
            "Missing config creates complete defaults",
        ),
        check(
            MAIN / "kneespa.py",
            [
                r'parser\.add_argument\("--config"',
                r'parser\.add_argument\(\s*"--sync-logs"',
                r'parser\.add_argument\(\s*"--print-logs"',
            ],
            "Documented CLI options are implemented",
        ),
    ]

    print("=" * 60)
    print("VALIDATING AUDIT FIXES")
    print("=" * 60)

    passed = 0
    for success, message in checks:
        status = "PASS" if success else "FAIL"
        print(f"{status}: {message}")
        if success:
            passed += 1

    failed = len(checks) - passed
    print("=" * 60)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if validate_fixes() else 1)
