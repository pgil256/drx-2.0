#!/usr/bin/env python3
"""
Simple validation script for critical bug fixes in the KneeSpa application.
This validates the code changes without requiring full module imports.
"""

import os
import sys
import re

def check_file_for_pattern(filepath, patterns, description):
    """Check if a file contains specific patterns indicating the fix is applied."""
    if not os.path.exists(filepath):
        return False, f"File not found: {filepath}"

    with open(filepath, 'r') as f:
        content = f.read()

    for pattern in patterns:
        if not re.search(pattern, content, re.MULTILINE | re.DOTALL):
            return False, f"Pattern not found: {pattern}"

    return True, f"✓ {description}"


def validate_fixes():
    """Validate that all critical fixes have been applied."""
    print("=" * 60)
    print("VALIDATING CRITICAL BUG FIXES")
    print("=" * 60)
    print()

    results = []
    base_path = "/mnt/c/users/user/desktop/drx-demo-final/main"

    # 1. Check Arduino signal fix
    print("1. Checking Arduino signal fix...")
    success, msg = check_file_for_pattern(
        f"{base_path}/helpers/arduino.py",
        [r"display_weight_emit\s*=\s*pyqtSignal"],
        "display_weight_emit signal is defined"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 2. Check pressure safety validation
    print("\n2. Checking pressure safety validation...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r"CRITICAL SAFETY CHECK.*Prevent dangerous pressure",
            r"if pressure > PRESSURE_MAX:",
            r"pressure = PRESSURE_MAX"
        ],
        "Pressure safety validation in axial_flexion_pressure_go_button_clicked"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 3. Check axial position limit fix
    print("\n3. Checking axial position limit fix...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r'axial_max = ACTUATORS\["AXIAL"\]\["LIMITS"\]\[1\]',
            r"if direction > 0 and new_position > axial_max:"
        ],
        "Axial position uses correct AXIAL_MAX constant"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 4. Check division by zero protection in read_position
    print("\n4. Checking division by zero protection...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r"if self\.config\.a_factor == 0:",
            r"if self\.config\.b_factor == 0:",
            r"if self\.config\.c_factor == 0:"
        ],
        "Division by zero protection in read_position"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 5. Check I2Cstatus thread-safe event
    print("\n5. Checking I2Cstatus thread safety...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r"self\.I2Cstatus_event = threading\.Event\(\)",
            r"self\.I2Cstatus_event\.set\(\)"
        ],
        "I2Cstatus uses thread-safe event"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 6. Check reset_worker thread-safe wait
    print("\n6. Checking reset_worker thread safety...")
    success, msg = check_file_for_pattern(
        f"{base_path}/helpers/reset_worker.py",
        [
            r"if hasattr\(self\.main_window, 'I2Cstatus_event'\):",
            r"self\.main_window\.I2Cstatus_event\.wait\(timeout=timeout\)",
            r"self\.main_window\.I2Cstatus_event\.clear\(\)"
        ],
        "reset_worker uses thread-safe event waiting"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 7. Check config error handling
    print("\n7. Checking configuration error handling...")
    success, msg = check_file_for_pattern(
        f"{base_path}/config/config.py",
        [
            r'if "CMarks" in allSections:',
            r'if "AMarks" in allSections:',
            r'if "BMarks" in allSections:',
            r"def _get_default_marks\(self, actuator_type\):"
        ],
        "Configuration has proper error handling and defaults"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 8. Check file handle leak fixes
    print("\n8. Checking file handle leak fixes...")
    success, msg = check_file_for_pattern(
        f"{base_path}/config/config.py",
        [
            r"with open\(self\.configFile, \"w\"\) as config_file:",
            r"self\.config\.write\(config_file\)"
        ],
        "File handles use context managers"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 9. Check adjust_pressure validation
    print("\n9. Checking adjust_pressure validation...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r"def adjust_pressure.*with safety validation",
            r"CRITICAL SAFETY VALIDATION",
            r"if target_pressure > PRESSURE_MAX:"
        ],
        "adjust_pressure has safety validation"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 10. Check lateral position safety
    print("\n10. Checking lateral position safety...")
    success, msg = check_file_for_pattern(
        f"{base_path}/kneespa.py",
        [
            r'lateral_max = ACTUATORS\["LATERAL"\]\["LIMITS"\]\[1\]',
            r'lateral_min = ACTUATORS\["LATERAL"\]\["LIMITS"\]\[0\]',
            r"if direction > 0 and new_position > lateral_max:"
        ],
        "Lateral position uses safety constants"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # 11. Check division by zero in protocols
    print("\n11. Checking protocol division safety...")
    success, msg = check_file_for_pattern(
        f"{base_path}/helpers/protocols.py",
        [
            r"# Prevent division by zero",
            r"if deg2 - deg1 != 0:",
            r"ratio = \(degrees - deg1\) / \(deg2 - deg1\)"
        ],
        "Protocol interpolation has division protection"
    )
    results.append((success, msg))
    print(f"   {msg}")

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    passed = sum(1 for success, _ in results if success)
    failed = len(results) - passed

    print(f"\nTotal checks: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed == 0:
        print("\n✓ SUCCESS: All critical fixes have been validated!")
    else:
        print("\n✗ FAILURE: Some fixes are missing or incomplete!")
        print("\nFailed checks:")
        for success, msg in results:
            if not success:
                print(f"  - {msg}")

    return failed == 0


if __name__ == "__main__":
    success = validate_fixes()
    sys.exit(0 if success else 1)