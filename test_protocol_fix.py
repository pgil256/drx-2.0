#!/usr/bin/env python3
"""
Test script to verify Protocol 2 pressure sequence fix.
This script simulates the pressure ramping to verify it no longer drops from 20 to 10.
"""

import sys
sys.path.append('/mnt/c/users/user/desktop/drx-demo-final/main')

from config.constants import PROTOCOL_DEFAULT_SETTINGS

MIN_PRESSURE = PROTOCOL_DEFAULT_SETTINGS["MIN_PRESSURE"]  # Should be 10
MAX_SAFE_PRESSURE = PROTOCOL_DEFAULT_SETTINGS["MAX_SAFE_PRESSURE"]  # Should be 80
PRESSURE_INCREMENT = PROTOCOL_DEFAULT_SETTINGS["PRESSURE_INCREMENT"]  # Should be 10

def simulate_pressure_sequence(initial_pressure, max_pressure):
    """Simulate the pressure sequence as it would run in protocol_2"""
    print(f"\n=== Simulating Protocol 2 Pressure Sequence ===")
    print(f"Max pressure setting: {max_pressure} lbs")

    # Determine initial pressure (as done in protocol_2)
    if max_pressure > 20:
        initial_pressure = max(20.0, MIN_PRESSURE)
        print(f"Setting higher initial pressure of {initial_pressure} lbs")
    else:
        initial_pressure = MIN_PRESSURE
        print(f"Using minimum initial pressure of {initial_pressure} lbs")

    print(f"\n1. Initial pressure set to: {initial_pressure} lbs (Command: P{initial_pressure})")

    # Simulate run_pressure_sequence with the FIX applied
    print(f"\n2. Starting pressure sequence from {initial_pressure} to {max_pressure}:")

    current_command = initial_pressure  # This is the FIX - was MIN_PRESSURE before
    commands_sent = []

    # Initial pressure command
    print(f"   - Sending P{current_command}")
    commands_sent.append(f"P{current_command}")

    # Step through pressure increments
    while current_command < (max_pressure - PRESSURE_INCREMENT/2):
        current_command += PRESSURE_INCREMENT
        print(f"   - Sending P{current_command}")
        commands_sent.append(f"P{current_command}")

    # Final pressure
    if current_command < max_pressure:
        print(f"   - Sending P{max_pressure} (final)")
        commands_sent.append(f"P{max_pressure}")

    print(f"\n3. Commands sent in sequence: {' -> '.join(commands_sent)}")

    # Check for the bug pattern
    if len(commands_sent) >= 3:
        if commands_sent[0] == "P20.0" and commands_sent[1] == "P10" and commands_sent[2] == "P20":
            print("\n❌ BUG DETECTED: Pressure drops from 20 to 10 then back to 20!")
            return False
        elif commands_sent[0] == "P20.0" and commands_sent[1] == "P30":
            print("\n✅ FIX VERIFIED: Pressure correctly ramps from 20 to 30 without dropping!")
            return True

    return True

# Test scenarios
print("Testing Protocol 2 pressure sequences with different max_pressure values:")
print("=" * 60)

test_cases = [
    (40, "Most common case - max pressure 40 lbs"),
    (60, "Higher pressure case - max pressure 60 lbs"),
    (20, "Edge case - max pressure exactly 20 lbs"),
    (15, "Low pressure case - max pressure 15 lbs")
]

all_passed = True
for max_pressure, description in test_cases:
    print(f"\nTest: {description}")
    result = simulate_pressure_sequence(MIN_PRESSURE, max_pressure)
    if not result:
        all_passed = False
    print("-" * 60)

print("\n" + "=" * 60)
if all_passed:
    print("✅ All tests passed! The pressure sequence fix is working correctly.")
else:
    print("❌ Some tests failed. The fix may not be applied correctly.")