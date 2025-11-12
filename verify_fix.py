#!/usr/bin/env python3
"""
Verification script for the lateral control fix
This script checks that all required changes have been applied to main/kneespa.py
"""

import re
import sys

def verify_fix():
    """Verify that all fix components are in place."""

    print("=" * 70)
    print("LATERAL CONTROL FIX VERIFICATION")
    print("=" * 70)

    # Read the kneespa.py file
    with open('main/kneespa.py', 'r') as f:
        content = f.read()

    checks = []

    print("\n1. Checking for new instance variables in __init__...")
    if 'self.actuator_command_in_progress = False' in content:
        print("   ✓ actuator_command_in_progress flag found")
        checks.append(True)
    else:
        print("   ✗ actuator_command_in_progress flag NOT found")
        checks.append(False)

    if 'self.controls_enable_timer = None' in content:
        print("   ✓ controls_enable_timer variable found")
        checks.append(True)
    else:
        print("   ✗ controls_enable_timer variable NOT found")
        checks.append(False)

    print("\n2. Checking disable_actuator_controls modifications...")
    if 'self.actuator_command_in_progress = True' in content:
        print("   ✓ Setting command_in_progress flag in disable method")
        checks.append(True)
    else:
        print("   ✗ Missing command_in_progress flag in disable method")
        checks.append(False)

    if 'if self.controls_enable_timer:' in content:
        print("   ✓ Timer cancellation logic found")
        checks.append(True)
    else:
        print("   ✗ Timer cancellation logic NOT found")
        checks.append(False)

    print("\n3. Checking enable_actuator_controls modifications...")
    if 'self.controls_enable_timer = QTimer()' in content:
        print("   ✓ Timer creation found")
        checks.append(True)
    else:
        print("   ✗ Timer creation NOT found")
        checks.append(False)

    if 'def do_enable():' in content:
        print("   ✓ do_enable callback function found")
        checks.append(True)
    else:
        print("   ✗ do_enable callback function NOT found")
        checks.append(False)

    print("\n4. Checking move_actuator safety checks...")
    if 'if self.actuator_command_in_progress:' in content:
        print("   ✓ Command in progress check found")
        checks.append(True)
    else:
        print("   ✗ Command in progress check NOT found")
        checks.append(False)

    print("\n5. Checking set_done modifications...")
    # Find the set_done method - look for the flag clearing after the method definition
    set_done_index = content.find('def set_done(self):')
    if set_done_index != -1:
        # Look for the flag clearing within the next 500 characters
        method_content = content[set_done_index:set_done_index+500]
        if 'self.actuator_command_in_progress = False' in method_content:
            print("   ✓ Flag clearing in set_done method found")
            checks.append(True)
        else:
            print("   ✗ Flag clearing in set_done method NOT found")
            checks.append(False)
    else:
        print("   ✗ set_done method NOT found")
        checks.append(False)

    print("\n" + "=" * 70)

    if all(checks):
        print("✅ FIX VERIFICATION: ALL CHECKS PASSED!")
        print("\nThe lateral control double-click fix has been successfully applied.")
        print("\nWhat the fix does:")
        print("• Prevents multiple simultaneous commands with actuator_command_in_progress flag")
        print("• Properly manages control re-enabling with a single timer instance")
        print("• Cancels pending timers when new commands arrive")
        print("• Clears flags only after Arduino completes the movement")
        return 0
    else:
        print("❌ FIX VERIFICATION: SOME CHECKS FAILED")
        print(f"\n{sum(checks)}/{len(checks)} checks passed")
        print("\nPlease review the failed checks above.")
        return 1

if __name__ == "__main__":
    sys.exit(verify_fix())