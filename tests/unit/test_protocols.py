"""
Unit tests for the Protocols class.
"""
import pytest
import time
from unittest.mock import MagicMock, patch
from typing import Tuple, Dict, Any, List, Optional

from main.helpers.protocols import Protocols
from main.helpers.arduino import Arduino
from main.config.config import Config
from tests.fixtures.arduino_simulator import ArduinoSimulator


class MockConfig:
    """Mock configuration for testing protocols."""
    
    def __init__(self):
        """Initialize with test configuration values."""
        self.CMarks = {
            "0.0": 300,    # Neutral position
            "-5.0": 200,   # Left 5 degrees
            "5.0": 400,    # Right 5 degrees
            "-10.0": 100,  # Left 10 degrees
            "10.0": 500    # Right 10 degrees
        }


@pytest.mark.unit
@pytest.mark.protocol
class TestProtocols:
    """Test suite for the Protocols class."""
    
    def test_initialization(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test protocol initialization."""
        arduino, _ = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",
            max_pressure=50,
            max_left=5.0,
            max_right=5.0,
            duration=5,  # 5 minutes
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Check initial state
        assert protocol.protocol == "1"
        assert protocol.max_pressure == 50
        assert protocol.max_left == -5.0  # Should be negative
        assert protocol.max_right == 5.0
        assert protocol.duration == 300  # Converted to seconds
        assert not protocol.use_pulse
        assert not protocol.is_running
        assert protocol.current_pressure == 0
        
    def test_update_status(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test status update handling."""
        arduino, _ = arduino_mock
        config = MockConfig()
        
        # Create protocol instance
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",
            max_pressure=50,
            max_left=5.0,
            max_right=5.0,
            duration=5,
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Mock the pressure signal
        pressure_value = None
        
        def on_pressure(value):
            nonlocal pressure_value
            pressure_value = value
            
        protocol.signals.pressure_emit.connect(on_pressure)
        
        # Update status
        protocol.update_status(100, 200, 300, 45.6)
        
        # Check that values were updated
        assert protocol.current_pressure == 45.6
        assert pressure_value == 45.6
        
    def test_set_to_angle(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test setting angle."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",
            max_pressure=50,
            max_left=5.0,
            max_right=5.0,
            duration=5,
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Start protocol
        protocol.is_running = True
        
        # Set angle to 5 degrees right
        success = protocol.set_to_angle(5.0)
        assert success
        
        # Allow time for angle to be set
        time.sleep(1.0)
        
        # Check simulator state
        assert simulator.position_c == 400
        assert protocol.angle_set
        
        # Test setting to a non-existent angle
        success = protocol.set_to_angle(7.5)
        assert not success
        
    def test_set_to_pressure(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test setting pressure."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",
            max_pressure=50,
            max_left=5.0,
            max_right=5.0,
            duration=5,
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Start protocol
        protocol.is_running = True
        
        # Set pressure
        success = protocol.set_to_pressure(30)
        assert success
        
        # Allow time for pressure to be set
        time.sleep(1.0)
        
        # Check simulator state
        assert abs(simulator.pressure - 30) < 2  # Within 2 lbs
        
        # Test with invalid pressure
        success = protocol.set_to_pressure(150)  # Exceeds MAX_SAFE_PRESSURE
        assert not success
        
    @pytest.mark.parametrize("protocol_num", ["1", "2", "3"])
    def test_protocol_execution(self, arduino_mock: Tuple[Arduino, ArduinoSimulator], protocol_num: str) -> None:
        """Test execution of protocols."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance with short duration for testing
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol=protocol_num,
            max_pressure=30,
            max_left=5.0,
            max_right=5.0,
            duration=1,  # 1 minute to keep test short
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Track signals
        finished_called = False
        reset_called = False
        finish_success = None
        
        def on_finished(success):
            nonlocal finished_called, finish_success
            finished_called = True
            finish_success = success
            
        def on_reset():
            nonlocal reset_called
            reset_called = True
            
        protocol.signals.finished.connect(on_finished)
        protocol.signals.reset_needed.connect(on_reset)
        
        # Mock check_duration to make test faster
        protocol.start_time = time.time()
        original_check_duration = protocol.check_duration
        
        # Make check_duration return False after a couple of cycles
        check_count = 0
        
        def mock_check_duration():
            nonlocal check_count
            check_count += 1
            if check_count < 3:
                return True
            return False
            
        protocol.check_duration = mock_check_duration
        
        # Run the protocol
        protocol.run()
        
        # Wait for protocol to complete (should be fast with our mock)
        time.sleep(1.0)
        
        # Check results
        assert not protocol.is_running
        assert finished_called
        assert finish_success
        assert reset_called
        
        # Check simulator state - should have some pressure applied
        assert simulator.pressure > 0
        
        # If protocol 2 or 3, should have some angle set
        if protocol_num == "2":
            assert simulator.position_c < 300  # Left angle
        elif protocol_num == "3":
            assert simulator.position_c > 300  # Right angle
            
    def test_apply_continuous_pulse(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test pulse application."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",
            max_pressure=30,
            max_left=5.0,
            max_right=5.0,
            duration=1,
            use_pulse=True,
            ser=arduino,
            config=config
        )
        
        # Start protocol
        protocol.is_running = True
        protocol.start_time = time.time()
        
        # Mock check_duration to make test faster
        check_count = 0
        
        def mock_check_duration():
            nonlocal check_count
            check_count += 1
            if check_count < 2:
                return True
            return False
            
        protocol.check_duration = mock_check_duration
        
        # Apply pulse
        result = protocol.apply_continuous_pulse()
        assert result
        
        # Check that jerk command was sent to Arduino
        assert simulator.is_jerking
        
        # Check that jerk was stopped at the end
        assert not simulator.is_jerking