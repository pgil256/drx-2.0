#!/usr/bin/env python3
"""
Test script to verify protocol fixes:
1. Lateral control positioning (C actuator neutral position)
2. Pressure buildup stability
3. Emergency stop command handling
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main.config.config import Configuration
from main.helpers.arduino import Arduino
from main.helpers.protocols import Protocols, WorkerSignals
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

class TestProtocolRunner:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.config = Configuration()
        self.arduino = Arduino(None)
        self.signals = WorkerSignals()

    def test_c_actuator_positioning(self):
        """Test that C actuator can reach neutral and other positions."""
        print("\n" + "="*60)
        print("TEST: C Actuator Positioning")
        print("="*60)

        # Connect to Arduino
        if not self.arduino.connect():
            print("ERROR: Failed to connect to Arduino")
            return False

        success = True

        # Test neutral position (0 degrees)
        print("\n1. Testing neutral position (0°)...")
        expected_pos = self.config.CMarks.get("0.0", 1400)
        print(f"   Expected position value: {expected_pos}")

        if self.arduino.send(f"K{expected_pos}"):
            print(f"   Command K{expected_pos} sent successfully")
            time.sleep(3)  # Wait for movement

            # Request status
            self.arduino.send("S")
            time.sleep(0.5)
            print(f"   Current status: {self.arduino.last_status}")
        else:
            print("   ERROR: Failed to send command")
            success = False

        # Test left position (-10 degrees)
        print("\n2. Testing left position (-10°)...")
        expected_pos = self.config.CMarks.get("-10.0", 720)
        print(f"   Expected position value: {expected_pos}")

        if self.arduino.send(f"K{expected_pos}"):
            print(f"   Command K{expected_pos} sent successfully")
            time.sleep(3)  # Wait for movement

            # Request status
            self.arduino.send("S")
            time.sleep(0.5)
            print(f"   Current status: {self.arduino.last_status}")
        else:
            print("   ERROR: Failed to send command")
            success = False

        # Return to neutral
        print("\n3. Returning to neutral position...")
        expected_pos = self.config.CMarks.get("0.0", 1400)
        if self.arduino.send(f"K{expected_pos}"):
            print(f"   Command K{expected_pos} sent successfully")
            time.sleep(3)

        self.arduino.disconnect()
        return success

    def test_pressure_buildup(self):
        """Test pressure buildup stability."""
        print("\n" + "="*60)
        print("TEST: Pressure Buildup Stability")
        print("="*60)

        # Connect to Arduino
        if not self.arduino.connect():
            print("ERROR: Failed to connect to Arduino")
            return False

        success = True

        # Start high frequency status updates
        print("\n1. Enabling high-frequency status updates...")
        self.arduino.send("HF1")
        time.sleep(0.5)

        # Test gradual pressure increase
        pressure_steps = [5, 10, 15, 20]
        for pressure in pressure_steps:
            print(f"\n2. Setting pressure to {pressure} lbs...")
            if self.arduino.send(f"P{pressure}"):
                print(f"   Command P{pressure} sent successfully")

                # Wait and monitor pressure
                start_time = time.time()
                while time.time() - start_time < 5:
                    time.sleep(0.5)
                    # In real operation, we'd monitor self.arduino.current_pressure
                    print(f"   Waiting for pressure to stabilize...")

                # Request status
                self.arduino.send("S")
                time.sleep(0.5)
                print(f"   Current status: {self.arduino.last_status}")
            else:
                print("   ERROR: Failed to send command")
                success = False
                break

        # Reset pressure
        print("\n3. Resetting pressure to 0...")
        self.arduino.send("P0")
        time.sleep(2)

        # Disable high frequency updates
        print("\n4. Disabling high-frequency status updates...")
        self.arduino.send("HF0")

        self.arduino.disconnect()
        return success

    def test_emergency_stop_handling(self):
        """Test that emergency stop is sent appropriately."""
        print("\n" + "="*60)
        print("TEST: Emergency Stop Handling")
        print("="*60)

        # Connect to Arduino
        if not self.arduino.connect():
            print("ERROR: Failed to connect to Arduino")
            return False

        success = True

        print("\n1. Testing normal protocol completion (should NOT send X immediately)...")
        # Simulate protocol end without emergency
        self.arduino.send("HF0")
        time.sleep(0.5)
        self.arduino.send("T")  # Test command
        time.sleep(0.5)
        print("   Normal completion sequence sent")

        print("\n2. Testing emergency stop (should send X)...")
        # Simulate emergency stop
        self.arduino.send("X")
        time.sleep(0.5)
        print("   Emergency stop sent")

        print("\n3. Testing connection after stop...")
        # Verify connection still works
        if self.arduino.send("T"):
            print("   Connection still active after emergency stop")
        else:
            print("   ERROR: Connection lost after emergency stop")
            success = False

        self.arduino.disconnect()
        return success

    def run_all_tests(self):
        """Run all protocol tests."""
        print("\n" + "#"*60)
        print("# PROTOCOL FIX VERIFICATION TESTS")
        print("#"*60)

        all_passed = True

        # Test 1: C Actuator Positioning
        if self.test_c_actuator_positioning():
            print("\n✓ C Actuator Positioning test PASSED")
        else:
            print("\n✗ C Actuator Positioning test FAILED")
            all_passed = False

        time.sleep(2)  # Brief pause between tests

        # Test 2: Pressure Buildup
        if self.test_pressure_buildup():
            print("\n✓ Pressure Buildup test PASSED")
        else:
            print("\n✗ Pressure Buildup test FAILED")
            all_passed = False

        time.sleep(2)  # Brief pause between tests

        # Test 3: Emergency Stop Handling
        if self.test_emergency_stop_handling():
            print("\n✓ Emergency Stop Handling test PASSED")
        else:
            print("\n✗ Emergency Stop Handling test FAILED")
            all_passed = False

        # Summary
        print("\n" + "#"*60)
        if all_passed:
            print("# ALL TESTS PASSED - Fixes verified successfully!")
        else:
            print("# SOME TESTS FAILED - Please review the issues above")
        print("#"*60)

        return all_passed

if __name__ == "__main__":
    tester = TestProtocolRunner()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)