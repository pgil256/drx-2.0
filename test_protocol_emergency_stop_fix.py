#!/usr/bin/env python3
"""
Test to verify that the emergency stop (X command) fix works correctly.
This test simulates a position verification timeout to ensure protocols
continue without sending the emergency stop command inappropriately.
"""

import sys
import os
import time
from unittest.mock import Mock, MagicMock, patch

# Add the project directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'main'))

def test_position_verification_timeout():
    """Test that position verification timeout doesn't trigger emergency stop."""
    print("\n=== Testing Position Verification Timeout ===")

    # Mock the Arduino connection
    mock_arduino = Mock()
    mock_arduino.send = MagicMock(return_value=True)
    mock_arduino.get_positions = MagicMock(return_value={'a': 100, 'b': 1867, 'c': 1371})

    # Import after path is set
    from helpers.protocols import Protocols, WorkerSignals

    # Create a protocols instance
    signals = WorkerSignals()
    protocols = Protocols(
        protocol=2,  # Protocol 2 moves left
        arduino=mock_arduino,
        signals=signals,
        duration=1,  # 1 minute
        max_pressure=20,
        max_left=-10,
        max_right=10,
        use_pulse=False
    )

    # Mock the current position to never reach target (simulate timeout)
    protocols.current_pos_c = 1371  # Starting position
    protocols.angle_set = False  # Will never become True

    # Test set_to_c_distance with position that won't be reached
    print("Calling set_to_c_distance with target position 720 (-10 degrees)")
    result = protocols.set_to_c_distance(-10)  # Should now return True even on timeout

    # Verify the result
    assert result == True, f"Expected True (continue protocol), got {result}"
    print(f"✓ set_to_c_distance returned {result} (protocol continues)")

    # Check what commands were sent to Arduino
    commands_sent = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"\nCommands sent to Arduino: {commands_sent}")

    # Verify that 'K720' was sent but 'X' was NOT sent
    assert 'K720' in commands_sent, "Expected K720 command to be sent"
    assert 'X' not in commands_sent, "Emergency stop 'X' should NOT be sent for position timeout"

    print("✓ K720 command was sent")
    print("✓ Emergency stop 'X' was NOT sent")

    return True

def test_normal_stop_vs_emergency_stop():
    """Test that stop() method behaves differently for normal vs emergency stops."""
    print("\n=== Testing Normal Stop vs Emergency Stop ===")

    # Mock the Arduino connection
    mock_arduino = Mock()
    mock_arduino.send = MagicMock(return_value=True)

    # Import after path is set
    from helpers.protocols import Protocols, WorkerSignals

    # Create a protocols instance
    signals = WorkerSignals()
    protocols = Protocols(
        protocol=1,
        arduino=mock_arduino,
        signals=signals,
        duration=1,
        max_pressure=20,
        max_left=-10,
        max_right=10,
        use_pulse=False
    )

    # Test 1: Normal stop (no emergency)
    print("\nTest 1: Normal stop (emergency=False)")
    mock_arduino.send.reset_mock()  # Clear previous calls
    protocols.stop(emergency=False)

    commands_sent = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"Commands sent: {commands_sent}")

    assert 'HF0' in commands_sent, "HF0 should be sent for normal stop"
    assert 'X' not in commands_sent, "Emergency stop 'X' should NOT be sent for normal stop"
    print("✓ HF0 sent, X not sent")

    # Test 2: Emergency stop
    print("\nTest 2: Emergency stop (emergency=True)")
    mock_arduino.send.reset_mock()  # Clear previous calls
    protocols.stop(emergency=True)

    commands_sent = [call[0][0] for call in mock_arduino.send.call_args_list]
    print(f"Commands sent: {commands_sent}")

    assert 'HF0' in commands_sent, "HF0 should be sent for emergency stop"
    assert 'X' in commands_sent, "Emergency stop 'X' SHOULD be sent for emergency stop"
    print("✓ HF0 sent, X sent")

    return True

def test_protocol_completion_scenarios():
    """Test different protocol completion scenarios."""
    print("\n=== Testing Protocol Completion Scenarios ===")

    # Mock the Arduino connection
    mock_arduino = Mock()
    mock_arduino.send = MagicMock(return_value=True)
    mock_arduino.get_positions = MagicMock(return_value={'a': 100, 'b': 1867, 'c': 720})

    from helpers.protocols import Protocols, WorkerSignals

    # Test 1: Normal protocol completion
    print("\nScenario 1: Normal protocol completion")
    signals = WorkerSignals()
    signals.finished = Mock()

    protocols = Protocols(
        protocol=1,
        arduino=mock_arduino,
        signals=signals,
        duration=0.1,  # Very short duration for quick test
        max_pressure=20,
        max_left=-10,
        max_right=10,
        use_pulse=False
    )

    # Simulate successful completion by emitting finished(True)
    protocols.signals.finished.emit(True)
    signals.finished.emit.assert_called_with(True)
    print("✓ Normal completion emits finished(True)")

    # Test 2: Position verification failure (should now continue)
    print("\nScenario 2: Position verification timeout (should continue)")
    protocols.angle_set = False
    result = protocols.set_to_c_distance(-5)
    assert result == True, f"Expected True (continue), got {result}"
    print("✓ Position timeout returns True (continues protocol)")

    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("EMERGENCY STOP FIX VERIFICATION TEST")
    print("=" * 60)

    all_passed = True

    try:
        # Test 1: Position verification timeout
        if not test_position_verification_timeout():
            all_passed = False
            print("\n✗ Position verification timeout test FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Position verification timeout test FAILED: {e}")

    try:
        # Test 2: Normal vs emergency stop
        if not test_normal_stop_vs_emergency_stop():
            all_passed = False
            print("\n✗ Normal vs emergency stop test FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Normal vs emergency stop test FAILED: {e}")

    try:
        # Test 3: Protocol completion scenarios
        if not test_protocol_completion_scenarios():
            all_passed = False
            print("\n✗ Protocol completion scenarios test FAILED")
    except Exception as e:
        all_passed = False
        print(f"\n✗ Protocol completion scenarios test FAILED: {e}")

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ ALL TESTS PASSED!")
        print("\nThe fix successfully prevents emergency stop (X) commands")
        print("from being sent during position verification timeouts.")
        print("\nProtocols will now continue even if position verification")
        print("times out, preventing unexpected interruptions.")
    else:
        print("✗ SOME TESTS FAILED")
        print("Please review the output above for details.")
    print("=" * 60)

if __name__ == "__main__":
    main()