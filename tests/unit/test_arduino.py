"""
Unit tests for the Arduino class.
"""
import pytest
import time
from unittest.mock import MagicMock
from typing import Tuple, List, Dict, Any, Optional

from main.helpers.arduino import Arduino
from tests.fixtures.arduino_simulator import ArduinoSimulator


@pytest.mark.unit
@pytest.mark.arduino
class TestArduino:
    """Test suite for the Arduino class."""

    def test_initialization(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test that Arduino initializes properly."""
        arduino, _ = arduino_mock
        
        # Check initial state
        assert arduino.serial_com is None
        assert not arduino.connected
        assert arduino.current_port is None
        
    def test_connection_successful(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test successful connection to Arduino."""
        arduino, simulator = arduino_mock
        
        # Set up signals to track
        connection_ready_called = False
        connection_failed_called = False
        
        def on_connection_ready():
            nonlocal connection_ready_called
            connection_ready_called = True
            
        def on_connection_failed(error_message):
            nonlocal connection_failed_called
            connection_failed_called = True
            
        arduino.connection_ready.connect(on_connection_ready)
        arduino.connection_failed.connect(on_connection_failed)
        
        # Run the connection process
        arduino.run()
        
        # Wait for connection to complete
        time.sleep(0.5)
        
        # Check connection status
        assert arduino.connected
        assert arduino.serial_com is not None
        assert arduino.current_port is not None
        assert connection_ready_called
        assert not connection_failed_called
        
    def test_verify_connection(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test verify_connection method."""
        arduino, simulator = arduino_mock
        
        # Run connection
        arduino.run()
        time.sleep(0.5)
        
        # Verify the connection
        result = arduino.verify_connection()
        assert result is True
        
    def test_send_command(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test sending commands to Arduino."""
        arduino, simulator = arduino_mock
        
        # Connect first
        arduino.run()
        time.sleep(0.5)
        
        # Send a test command
        result = arduino.send("T")
        assert result is True
        
        # Allow time for command processing
        time.sleep(0.5)
        
    def test_reconnection(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test reconnection after disconnect."""
        arduino, simulator = arduino_mock
        
        # Connect first
        arduino.run()
        time.sleep(0.5)
        assert arduino.connected
        
        # Track signal emissions
        connection_lost_called = False
        
        def on_connection_lost():
            nonlocal connection_lost_called
            connection_lost_called = True
            
        arduino.connection_lost.connect(on_connection_lost)
        
        # Simulate a disconnect
        simulator.disconnect()
        
        # Send a command to trigger connection lost detection
        result = arduino.send("T")
        assert result is False
        assert not arduino.connected
        
        # Reconnect the simulator
        simulator.connect()
        
        # Try reconnecting
        success = arduino.reconnect()
        assert success
        assert arduino.connected
        
    def test_handle_com(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test handling of different communication messages."""
        arduino, simulator = arduino_mock
        
        # Connect first
        arduino.run()
        time.sleep(0.5)
        
        # Set up signal tracking
        signals_received = {
            "done": False,
            "position": False,
            "pressure": False,
            "status": False,
            "ready": False
        }
        
        position_values = []
        status_values = []
        
        def on_done():
            signals_received["done"] = True
            
        def on_position(pos_a, pos_b, pos_c, pos_d):
            signals_received["position"] = True
            position_values.append((pos_a, pos_b, pos_c, pos_d))
            
        def on_pressure(value):
            signals_received["pressure"] = True
            
        def on_status(pos_a, pos_b, pos_c, pressure):
            signals_received["status"] = True
            status_values.append((pos_a, pos_b, pos_c, pressure))
            
        def on_ready():
            signals_received["ready"] = True
            
        arduino.done_emit.connect(on_done)
        arduino.position_emit.connect(on_position)
        arduino.pressure_emit.connect(on_pressure)
        arduino.status_emit.connect(on_status)
        arduino.ready_to_go_emit.connect(on_ready)
        
        # Test different message types
        arduino.handle_com("DONE")
        assert signals_received["done"]
        
        arduino.handle_com("P|123")
        assert signals_received["position"]
        assert position_values[0][0] == 123
        
        arduino.handle_com("PR|45.6")
        assert signals_received["pressure"]
        
        arduino.handle_com("STATUS_START|S|100|200|300|45.6|STATUS_END")
        assert signals_received["status"]
        assert status_values[0] == (100, 200, 300, 45.6)
        
        arduino.handle_com("Ready to Go")
        assert signals_received["ready"]
        
    def test_error_handling(self, arduino_mock_with_errors: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test error handling during communication."""
        arduino, simulator = arduino_mock_with_errors
        
        # Connect
        arduino.run()
        time.sleep(0.5)
        
        # Set a high error rate
        simulator.set_error_conditions(error_rate=0.5, dropped_bytes_rate=0.2)
        
        # Send multiple commands to test error handling
        success_count = 0
        for _ in range(10):
            result = arduino.send("T")
            if result:
                success_count += 1
            time.sleep(0.1)
            
        # We should have some successful commands and some failures
        assert success_count > 0
        assert success_count < 10
        
    def test_disconnect(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test disconnect method."""
        arduino, simulator = arduino_mock
        
        # Connect first
        arduino.run()
        time.sleep(0.5)
        assert arduino.connected
        
        # Disconnect
        arduino.disconnect()
        
        # Check state
        assert not arduino.connected
        assert arduino.serial_com is None
        assert arduino.current_port is None


@pytest.mark.integration
@pytest.mark.arduino
class TestArduinoIntegration:
    """Integration tests for Arduino communication."""
    
    def test_continuous_communication(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test continuous communication with Arduino."""
        arduino, simulator = arduino_mock
        
        # Connect first
        arduino.run()
        time.sleep(0.5)
        
        # Send a series of commands
        commands = ["S", "P50", "K500", "S", "T"]
        
        for cmd in commands:
            result = arduino.send(cmd)
            assert result
            time.sleep(0.3)  # Allow time for processing
            
        # Check simulator state
        assert simulator.pressure == 50.0
        assert simulator.position_c == 500