"""
Unit tests for logging functionality.
"""
import pytest
import logging
import time
from typing import Generator

from main.utils.logging import setup_logger
from tests.fixtures.test_logger import (
    capture_logs,
    assert_log_message,
    assert_no_errors_logged,
    TestLogCapture
)


@pytest.mark.unit
class TestLogging:
    """Test suite for logging functionality."""
    
    def test_log_capture(self):
        """Test capturing logs during a test."""
        with capture_logs() as logs:
            logger = logs.logger
            
            # Generate some logs
            logger.debug("This is a debug message")
            logger.info("This is an info message")
            logger.warning("This is a warning message")
            logger.error("This is an error message")
            
            # Get captured logs
            captured = logs.get_logs()
            assert len(captured) >= 4
            
            # Check log analysis
            analysis = logs.analyze_logs()
            assert analysis['error_lines'] >= 1
            assert analysis['warning_lines'] >= 1
            assert analysis['info_lines'] >= 1
            assert analysis['debug_lines'] >= 1
            
            # Check message search
            assert logs.contains_message("debug message")
            assert logs.contains_message("error message", level="error")
            assert not logs.contains_message("nonexistent message")
            
            # Check message count
            assert logs.count_message_occurrences("message") >= 4
            
    def test_assert_log_message(self):
        """Test assert_log_message context manager."""
        with assert_log_message("specific test message"):
            logger = logging.getLogger("TestLogger")
            logger.info("This is a specific test message")
            
    def test_assert_no_errors(self):
        """Test assert_no_errors_logged context manager."""
        with assert_no_errors_logged() as logs:
            logger = logs.logger
            logger.info("This is an info message")
            logger.debug("This is a debug message")
            
            # Don't log any errors
            
    def test_arduino_logging(self, arduino_mock):
        """Test Arduino logging with log capture."""
        arduino, simulator = arduino_mock
        
        with capture_logs("Arduino Communication") as logs:
            # Connect Arduino
            arduino.run()
            time.sleep(0.5)
            
            # Send a test command
            arduino.send("T")
            time.sleep(0.5)
            
            # Check logs
            assert logs.contains_message("connection")
            assert logs.contains_message("command")
            
    def test_protocol_execution_logging(self, arduino_mock):
        """Test protocol execution logging."""
        arduino, simulator = arduino_mock
        from tests.unit.test_protocols import MockConfig
        from main.helpers.protocols import Protocols
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        with capture_logs("Protocols") as logs:
            # Create and run a protocol
            config = MockConfig()
            protocol = Protocols(
                a_factor=1.0,
                protocol="1",
                max_pressure=30,
                max_left=5.0,
                max_right=5.0,
                duration=1,  # 1 minute
                use_pulse=False,
                ser=arduino,
                config=config
            )
            
            # Mock check_duration to make test faster
            protocol.start_time = time.time()
            check_count = 0
            
            def mock_check_duration():
                nonlocal check_count
                check_count += 1
                if check_count < 2:
                    return True
                return False
                
            protocol.check_duration = mock_check_duration
            
            # Run the protocol
            protocol.run()
            
            # Check logs
            assert logs.contains_message("Running protocol 1")
            assert logs.contains_message("Protocol complete")
            
    def test_error_logging_during_failure(self, arduino_mock_with_errors):
        """Test logging during error conditions."""
        arduino, simulator = arduino_mock_with_errors
        
        with capture_logs("Arduino Communication") as logs:
            # Set high error rate
            simulator.set_error_conditions(error_rate=0.9, dropped_bytes_rate=0.5)
            
            # Try to connect and send commands
            arduino.run()
            time.sleep(0.5)
            
            # Send multiple commands to ensure errors
            for _ in range(5):
                arduino.send("T")
                time.sleep(0.1)
                
            # Check logs for errors
            analysis = logs.analyze_logs()
            assert analysis['error_lines'] > 0
            
            # Should find connection or serial errors
            assert logs.contains_message("error")