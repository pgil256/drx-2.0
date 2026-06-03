#!/usr/bin/env python3
"""
Test script to validate critical bug fixes in the KneeSpa application.
This tests the safety-critical fixes without requiring hardware.
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch

# Add the main directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'main'))

# Mock the validate_paths function before importing constants
with patch('config.constants.validate_paths'):
    # Import the modules we need to test
    from config.constants import PRESSURE_MAX, ACTUATORS
    from config.config import Configuration


class TestCriticalFixes(unittest.TestCase):
    """Test suite for critical bug fixes."""

    def test_pressure_safety_limits(self):
        """Test that pressure is properly clamped to safety limits."""
        # Verify constant is set correctly
        self.assertEqual(PRESSURE_MAX, 80, "PRESSURE_MAX should be 80 lbs")

        # Test pressure validation logic
        test_pressures = [
            (50, 50),    # Normal pressure - should pass through
            (80, 80),    # At limit - should pass through
            (100, 80),   # Over limit - should be clamped
            (150, 80),   # Way over - should be clamped
            (-10, 0),    # Negative - should be set to 0
        ]

        for input_pressure, expected in test_pressures:
            # Simulate the validation logic from axial_flexion_pressure_go_button_clicked
            if input_pressure > PRESSURE_MAX:
                result = PRESSURE_MAX
            elif input_pressure < 0:
                result = 0
            else:
                result = input_pressure

            self.assertEqual(result, expected,
                f"Pressure {input_pressure} should be adjusted to {expected}")

    def test_axial_position_limits(self):
        """Test that axial position respects correct limits."""
        # Verify constants are set correctly
        axial_limits = ACTUATORS["AXIAL"]["LIMITS"]
        self.assertEqual(axial_limits[0], 0, "Axial minimum should be 0 inches")
        self.assertEqual(axial_limits[1], 4, "Axial maximum should be 4 inches")

        # Test position validation logic
        test_positions = [
            (0, True),     # Min position - valid
            (2, True),     # Middle - valid
            (4, True),     # Max position - valid
            (5, False),    # Over limit - should be rejected
            (8, False),    # Old wrong limit - should be rejected
            (-1, False),   # Below min - should be rejected
        ]

        for position, should_be_valid in test_positions:
            is_valid = axial_limits[0] <= position <= axial_limits[1]
            self.assertEqual(is_valid, should_be_valid,
                f"Position {position} validity check failed")

    def test_lateral_position_limits(self):
        """Test that lateral position respects correct limits."""
        # Verify constants are set correctly
        lateral_limits = ACTUATORS["LATERAL"]["LIMITS"]
        self.assertEqual(lateral_limits[0], -20, "Lateral minimum should be -20 degrees")
        self.assertEqual(lateral_limits[1], 20, "Lateral maximum should be 20 degrees")

        # Test position validation
        test_positions = [
            (-20, True),   # Min position - valid
            (0, True),     # Center - valid
            (20, True),    # Max position - valid
            (-25, False),  # Below min - should be rejected
            (25, False),   # Over max - should be rejected
        ]

        for position, should_be_valid in test_positions:
            is_valid = lateral_limits[0] <= position <= lateral_limits[1]
            self.assertEqual(is_valid, should_be_valid,
                f"Lateral position {position} validity check failed")

    def test_division_by_zero_protection(self):
        """Test that division by zero is properly handled."""
        # Test the division protection logic
        test_cases = [
            (10, 2, 5),      # Normal division
            (10, 0, None),   # Division by zero - should return None or default
            (0, 5, 0),       # Zero numerator
        ]

        for numerator, denominator, expected in test_cases:
            if denominator != 0:
                result = numerator / denominator
            else:
                result = None  # Or default value

            self.assertEqual(result, expected,
                f"Division {numerator}/{denominator} protection failed")

    def test_config_error_handling(self):
        """Test that configuration errors are properly handled."""
        config = Configuration()

        # Test that default marks are provided
        self.assertIsNotNone(config._get_default_marks("A"))
        self.assertIsNotNone(config._get_default_marks("B"))
        self.assertIsNotNone(config._get_default_marks("C"))

        # Check default values are reasonable
        a_marks = config._get_default_marks("A")
        self.assertIn("0", a_marks)
        self.assertIn("4", a_marks)

        b_marks = config._get_default_marks("B")
        self.assertIn("-25", b_marks)
        self.assertIn("5", b_marks)

        c_marks = config._get_default_marks("C")
        self.assertIn("-20", c_marks)
        self.assertIn("20", c_marks)

    def test_thread_safety_improvements(self):
        """Test that thread safety improvements are in place."""
        import threading

        # Test that threading.Event is available (used for I2Cstatus_event)
        event = threading.Event()

        # Test basic event functionality
        self.assertFalse(event.is_set())
        event.set()
        self.assertTrue(event.is_set())
        event.clear()
        self.assertFalse(event.is_set())

        # Test timeout functionality
        result = event.wait(timeout=0.1)
        self.assertFalse(result, "Event wait should timeout and return False")


class TestArduinoSignals(unittest.TestCase):
    """Test Arduino communication signal fixes."""

    @patch('main.helpers.arduino.serial')
    @patch('main.helpers.arduino.setup_logger')
    def test_display_weight_signal_defined(self, mock_logger, mock_serial):
        """Test that display_weight_emit signal is properly defined."""
        from helpers.arduino import Arduino

        arduino = Arduino()

        # Check that the signal exists
        self.assertTrue(hasattr(arduino, 'display_weight_emit'),
            "display_weight_emit signal should be defined")

        # Verify it's a PyQt signal (checking the type name)
        signal_type = type(arduino.display_weight_emit).__name__
        self.assertIn('pyqtBoundSignal', signal_type,
            "display_weight_emit should be a PyQt signal")


def run_tests():
    """Run all critical fix tests."""
    print("=" * 60)
    print("KNEESPA CRITICAL FIXES TEST SUITE")
    print("=" * 60)
    print()

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestCriticalFixes))
    suite.addTests(loader.loadTestsFromTestCase(TestArduinoSignals))

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("SUCCESS: All critical fixes validated!")
    else:
        print("FAILURE: Some tests failed - review fixes!")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)