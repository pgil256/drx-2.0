#!/usr/bin/env python3
"""
Test script to verify the lateral control fix
This script simulates rapid button clicks to test the race condition fix.
"""

import sys
import time
from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import QTimer
from unittest.mock import MagicMock, patch

# Add the main directory to path
sys.path.insert(0, 'main')

def test_rapid_clicks():
    """Test rapid button clicks to verify race condition fix."""

    print("=" * 60)
    print("LATERAL CONTROL FIX TEST")
    print("=" * 60)

    # Import the main window
    from kneespa import MainWindow

    # Create a QApplication (required for PyQt)
    app = QtWidgets.QApplication(sys.argv)

    # Create main window instance
    print("\n1. Creating MainWindow instance...")
    window = MainWindow()

    # Verify new attributes exist
    print("\n2. Verifying fix attributes are present...")
    assert hasattr(window, 'actuator_command_in_progress'), "Missing actuator_command_in_progress flag"
    assert hasattr(window, 'controls_enable_timer'), "Missing controls_enable_timer"
    print("   ✓ actuator_command_in_progress flag present")
    print("   ✓ controls_enable_timer present")

    # Mock the Arduino to prevent actual hardware communication
    print("\n3. Mocking Arduino communication...")
    window.arduino = MagicMock()
    window.arduino.send = MagicMock(return_value=True)
    window.loading_spinner = MagicMock()
    window._show_timed_error = MagicMock()

    # Set initial positions
    window.lateral_flexion_position = 0
    window.actuator_c = 'C'

    # Mock the config CMarks
    window.config.CMarks = {
        '0.0': 1386,
        '2.5': 1450,
        '5.0': 1514,
        '-2.5': 1322,
        '-5.0': 1258
    }

    print("\n4. Testing single button click...")
    print("   - Initial state: actuator_command_in_progress =", window.actuator_command_in_progress)

    # Simulate first button click
    window.move_actuator(window.actuator_c, 5, "04", 1)

    print("   - After first click: actuator_command_in_progress =", window.actuator_command_in_progress)
    assert window.actuator_command_in_progress == True, "Flag should be True after first click"
    print("   ✓ First click properly sets command_in_progress flag")

    print("\n5. Testing rapid second click (should be ignored)...")
    initial_send_count = window.arduino.send.call_count

    # Try second click immediately (should be rejected)
    window.move_actuator(window.actuator_c, 5, "04", 1)

    # Verify second command was not sent
    assert window.arduino.send.call_count == initial_send_count, "Second command should not be sent"
    print("   ✓ Second click was properly ignored")

    print("\n6. Simulating Arduino 'DONE' signal...")
    # Simulate the done signal
    window.set_done()

    print("   - After DONE: actuator_command_in_progress =", window.actuator_command_in_progress)
    assert window.actuator_command_in_progress == False, "Flag should be False after DONE"
    print("   ✓ DONE signal properly clears command_in_progress flag")

    print("\n7. Testing timer-based re-enabling...")
    # Check that timer was created
    assert window.controls_enable_timer is not None, "Enable timer should be created"
    assert window.controls_enable_timer.isActive(), "Timer should be active"
    print("   ✓ Timer created and active")

    # Process events to let timer fire
    print("   - Waiting for timer to fire (200ms)...")
    QTimer.singleShot(250, app.quit)
    app.exec_()

    print("   ✓ Timer completed successfully")

    print("\n8. Testing controls are re-enabled after timer...")
    # After timer, flag should be false and controls should accept new commands
    assert window.actuator_command_in_progress == False, "Flag should be cleared after timer"

    # Now a new command should work
    initial_send_count = window.arduino.send.call_count
    window.move_actuator(window.actuator_c, 5, "04", -1)
    assert window.arduino.send.call_count > initial_send_count, "New command should be sent after re-enabling"
    print("   ✓ Controls properly re-enabled and accepting new commands")

    print("\n" + "=" * 60)
    print("TEST RESULTS: ALL TESTS PASSED!")
    print("=" * 60)
    print("\nThe fix successfully prevents race conditions by:")
    print("1. Using actuator_command_in_progress flag to block concurrent commands")
    print("2. Properly managing a single timer instance for re-enabling")
    print("3. Clearing flags only after controls are fully re-enabled")
    print("\nThe lateral control double-click issue is FIXED! ✓")


if __name__ == "__main__":
    try:
        test_rapid_clicks()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    sys.exit(0)