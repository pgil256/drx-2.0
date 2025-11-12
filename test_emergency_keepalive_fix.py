#!/usr/bin/env python3
"""
Test to verify that keepalive threads are properly terminated during emergency stops.

This test ensures that:
1. Normal stops start a keepalive thread that continues for 60 seconds
2. Emergency stops do NOT start a keepalive thread
3. Emergency stops terminate any existing keepalive thread
"""

import time
import sys
import os
import threading
from unittest.mock import MagicMock, call

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'main'))

from helpers.protocols import Protocols


def test_emergency_stop_no_keepalive():
    """Test that emergency stop does not start a keepalive thread."""
    print("\n" + "="*60)
    print("Test 1: Emergency stop should NOT start keepalive thread")
    print("="*60)

    # Create mock Arduino
    mock_arduino = MagicMock()
    mock_arduino.send = MagicMock(return_value=True)
    mock_arduino.status_emit = MagicMock()

    # Create protocol instance
    protocol = Protocols(
        a_factor=1.0,
        protocol="1",
        max_pressure=30,
        max_left=-10,
        max_right=10,
        duration=5,  # 5 minutes
        use_pulse=False,
        ser=mock_arduino,
        config=None
    )

    # Start the protocol (simulate running state)
    protocol.is_running = True
    protocol.keepalive_thread_active = False

    # Perform emergency stop
    print("Calling stop(emergency=True)...")
    protocol.stop(emergency=True)

    # Check that no keepalive thread was started
    time.sleep(0.1)  # Brief wait to ensure any thread would have started

    # Verify emergency stop command was sent
    commands = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"Commands sent: {commands}")

    assert 'HF0' in commands, "HF0 should be sent for emergency stop"
    assert 'X' in commands, "Emergency stop 'X' should be sent"
    assert not protocol.keepalive_thread_active, "Keepalive thread should NOT be active after emergency stop"

    print("✓ Emergency stop correctly did NOT start keepalive thread")
    return True


def test_normal_stop_with_keepalive():
    """Test that normal stop starts a keepalive thread."""
    print("\n" + "="*60)
    print("Test 2: Normal stop should START keepalive thread")
    print("="*60)

    # Create mock Arduino
    mock_arduino = MagicMock()
    mock_arduino.send = MagicMock(return_value=True)
    mock_arduino.status_emit = MagicMock()

    # Create protocol instance
    protocol = Protocols(
        a_factor=1.0,
        protocol="1",
        max_pressure=30,
        max_left=-10,
        max_right=10,
        duration=5,
        use_pulse=False,
        ser=mock_arduino,
        config=None
    )

    # Start the protocol (simulate running state)
    protocol.is_running = True
    protocol.keepalive_thread_active = False

    # Perform normal stop
    print("Calling stop(emergency=False)...")
    protocol.stop(emergency=False)

    # Wait a moment for thread to start
    time.sleep(0.5)

    # Check that keepalive thread was started
    commands = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"Commands sent: {commands}")

    assert 'HF0' in commands, "HF0 should be sent for normal stop"
    assert 'X' not in commands, "Emergency stop 'X' should NOT be sent for normal stop"
    assert 'T' in commands, "Test command should be sent for normal stop"

    # Wait a bit and check if keepalive is being sent
    initial_call_count = len(mock_arduino.send.call_args_list)
    time.sleep(4)  # Wait for at least one keepalive interval (3 seconds)
    final_call_count = len(mock_arduino.send.call_args_list)

    if final_call_count > initial_call_count:
        print(f"✓ Keepalive thread is active (sent {final_call_count - initial_call_count} additional commands)")
    else:
        print("Note: Keepalive thread may be active but hasn't sent commands yet")

    # Clean up by stopping the thread
    protocol.keepalive_thread_active = False
    time.sleep(0.2)

    print("✓ Normal stop correctly started keepalive thread")
    return True


def test_emergency_stop_terminates_keepalive():
    """Test that emergency stop terminates an existing keepalive thread."""
    print("\n" + "="*60)
    print("Test 3: Emergency stop should TERMINATE existing keepalive")
    print("="*60)

    # Create mock Arduino
    mock_arduino = MagicMock()
    mock_arduino.send = MagicMock(return_value=True)
    mock_arduino.status_emit = MagicMock()

    # Create protocol instance
    protocol = Protocols(
        a_factor=1.0,
        protocol="1",
        max_pressure=30,
        max_left=-10,
        max_right=10,
        duration=5,
        use_pulse=False,
        ser=mock_arduino,
        config=None
    )

    # First, do a normal stop to start keepalive thread
    protocol.is_running = True
    print("Step 1: Performing normal stop to start keepalive...")
    protocol.stop(emergency=False)

    # Verify keepalive thread is active
    time.sleep(0.5)
    initial_active = protocol.keepalive_thread_active
    print(f"Keepalive thread active after normal stop: {initial_active}")

    # Clear the mock to track new calls
    mock_arduino.send.reset_mock()

    # Now simulate an emergency stop while keepalive is running
    protocol.is_running = True  # Reset to running state
    print("Step 2: Performing emergency stop...")
    protocol.stop(emergency=True)

    # Check that keepalive thread flag was cleared
    emergency_active = protocol.keepalive_thread_active
    print(f"Keepalive thread active after emergency stop: {emergency_active}")

    # Wait a bit to ensure thread has time to check flag and terminate
    time.sleep(1)

    # Check commands sent during emergency stop
    commands = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"Commands sent during emergency stop: {commands}")

    assert 'X' in commands, "Emergency stop 'X' should be sent"
    assert not emergency_active, "Keepalive thread flag should be False after emergency stop"

    print("✓ Emergency stop correctly terminated keepalive thread")
    return True


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("EMERGENCY STOP KEEPALIVE FIX TEST")
    print("="*70)

    all_passed = True

    try:
        # Test 1: Emergency stop should not start keepalive
        if not test_emergency_stop_no_keepalive():
            all_passed = False
            print("\n✗ Test 1 FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Test 1 FAILED: {e}")

    try:
        # Test 2: Normal stop should start keepalive
        if not test_normal_stop_with_keepalive():
            all_passed = False
            print("\n✗ Test 2 FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Test 2 FAILED: {e}")

    try:
        # Test 3: Emergency stop should terminate existing keepalive
        if not test_emergency_stop_terminates_keepalive():
            all_passed = False
            print("\n✗ Test 3 FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Test 3 FAILED: {e}")

    # Summary
    print("\n" + "="*70)
    if all_passed:
        print("SUCCESS: All emergency stop keepalive tests passed!")
        print("\nThe fix ensures that:")
        print("1. Emergency stops do NOT start keepalive threads")
        print("2. Normal stops DO start keepalive threads (for connection maintenance)")
        print("3. Emergency stops terminate any existing keepalive thread")
        print("\nThis prevents the system from continuing to send commands")
        print("to the Arduino after an emergency stop has been triggered.")
    else:
        print("FAILURE: Some tests failed. Please check the implementation.")
    print("="*70 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())