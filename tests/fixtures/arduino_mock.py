"""
Mock Arduino fixtures for testing the KneeSpa Arduino class.

This module provides mock fixtures that can be used to test the Arduino class
without requiring physical hardware.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import time
from typing import Callable, Dict, Tuple, Any, Optional, List

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from main.helpers.arduino import Arduino
from tests.fixtures.arduino_simulator import ArduinoSimulator, MockSerial


class ArduinoTestFixture:
    """Test fixture for Arduino communication.
    
    This class provides methods to patch Arduino communication for testing.
    """
    
    def __init__(self):
        """Initialize the test fixture."""
        self.simulator = None
        self.arduino = None
        self.patchers = []
        
    def setup(self, simulate_errors: bool = False) -> Tuple[Arduino, ArduinoSimulator]:
        """Set up the fixture by patching the serial module.
        
        Args:
            simulate_errors: If True, configure simulator to randomly generate errors
            
        Returns:
            A tuple of (Arduino instance, ArduinoSimulator instance)
        """
        # Create a simulator
        self.simulator = ArduinoSimulator()
        
        # Create a patcher for the serial.Serial class
        serial_patcher = patch('serial.Serial', self._mock_serial_factory)
        serial_patcher.start()
        self.patchers.append(serial_patcher)
        
        # Create a patcher for subprocess calls
        subprocess_patcher = patch('subprocess.run', self._mock_subprocess_run)
        subprocess_patcher.start()
        self.patchers.append(subprocess_patcher)
        
        # Create the Arduino instance
        self.arduino = Arduino()
        
        # Configure error simulation if requested
        if simulate_errors:
            self.simulator.set_error_conditions(error_rate=0.1, dropped_bytes_rate=0.05)
            
        return self.arduino, self.simulator
        
    def teardown(self) -> None:
        """Tear down the fixture by stopping patchers and disconnecting."""
        # Stop all patchers
        for patcher in self.patchers:
            patcher.stop()
        self.patchers = []
        
        # Disconnect simulator
        if self.simulator:
            self.simulator.disconnect()
            self.simulator = None
            
        # Clean up Arduino
        if self.arduino:
            self.arduino.disconnect()
            self.arduino = None
    
    def _mock_serial_factory(self, port, baudrate, **kwargs):
        """Factory function to create a mock Serial instance.
        
        This function is used to patch serial.Serial.
        
        Args:
            port: Port name
            baudrate: Baud rate
            **kwargs: Additional arguments
            
        Returns:
            A MockSerial instance connected to the simulator
        """
        # Connect the simulator if not already connected
        if self.simulator and not self.simulator.serial:
            self.simulator.connect(port, baudrate, **kwargs)
            
        return self.simulator.serial
        
    def _mock_subprocess_run(self, *args, **kwargs):
        """Mock subprocess.run calls.
        
        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            A mock CompletedProcess object
        """
        mock_result = MagicMock()
        
        # Handle different command types
        if args and len(args) > 0:
            cmd = args[0]
            
            # Mock lsof command to check if port is busy
            if cmd[0] == 'lsof':
                port = cmd[1]
                # Simulate port is not busy (returncode 1 means no matching processes)
                mock_result.returncode = 1
                mock_result.stdout = ""
                
            # Mock fuser command to kill processes
            elif cmd[0] == 'fuser':
                # Simulate successful kill
                mock_result.returncode = 0
                
            # Mock systemctl command
            elif cmd[0] == 'systemctl':
                # Simulate successful service operation
                mock_result.returncode = 0
                
        return mock_result
        
    def simulate_disconnect(self, reconnect_after: Optional[float] = None) -> None:
        """Simulate a disconnection and optional reconnection.
        
        Args:
            reconnect_after: If provided, reconnect after this many seconds
        """
        if not self.simulator:
            return
            
        # Close the serial connection
        self.simulator.disconnect()
        
        # Wait for reconnection if specified
        if reconnect_after is not None:
            time.sleep(reconnect_after)
            self.simulator.connect()
            
    def simulate_communication_errors(self, duration: float = 5.0, 
                                    error_rate: float = 0.2) -> None:
        """Simulate communication errors for a period of time.
        
        Args:
            duration: Duration in seconds to simulate errors
            error_rate: Rate of errors (0.0 to 1.0)
        """
        if not self.simulator:
            return
            
        # Save current error settings
        current_settings = {
            'error_rate': self.simulator.serial._error_rate,
            'dropped_bytes_rate': self.simulator.serial._dropped_bytes_rate
        }
        
        # Set high error rate
        self.simulator.set_error_conditions(error_rate=error_rate, dropped_bytes_rate=error_rate/2)
        
        # Wait for specified duration
        time.sleep(duration)
        
        # Restore previous settings
        self.simulator.set_error_conditions(
            error_rate=current_settings['error_rate'],
            dropped_bytes_rate=current_settings['dropped_bytes_rate']
        )
        
    def simulate_arduino_reset(self) -> None:
        """Simulate an Arduino reset (sends Ready to Go message)."""
        if not self.simulator or not self.simulator.serial:
            return
            
        # Send the Ready to Go message
        self.simulator.serial._put_data_in_buffer(b"Ready to Go\n")


class ArduinoMockTestCase(unittest.TestCase):
    """Base class for Arduino test cases using the mock.
    
    This class provides setup and teardown methods for Arduino tests.
    """
    
    def setUp(self) -> None:
        """Set up the test fixture."""
        self.fixture = ArduinoTestFixture()
        self.arduino, self.simulator = self.fixture.setup()
        
    def tearDown(self) -> None:
        """Tear down the test fixture."""
        self.fixture.teardown()
        
    def run_arduino_thread(self, duration: float = 1.0) -> None:
        """Run the Arduino communication thread for a specified duration.
        
        This method calls run() on the Arduino instance and waits for the 
        specified duration before returning.
        
        Args:
            duration: Duration in seconds to run the thread
        """
        # Start the Arduino thread
        self.arduino.run()
        
        # Wait for the specified duration
        time.sleep(duration)