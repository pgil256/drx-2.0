"""
Integration tests for Arduino and Protocol classes working together.
"""
import pytest
import time
import threading
from typing import Tuple, List, Dict, Any, Optional

from main.helpers.arduino import Arduino
from main.helpers.protocols import Protocols
from tests.fixtures.arduino_simulator import ArduinoSimulator
from tests.unit.test_protocols import MockConfig


@pytest.mark.integration
@pytest.mark.arduino
@pytest.mark.protocol
class TestArduinoProtocolsIntegration:
    """Test suite for Arduino and Protocol integration."""
    
    def test_protocol_with_arduino_communication(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test protocol execution with Arduino communication."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Test values for tracking
        status_updates = []
        pressure_updates = []
        protocol_finished = False
        reset_requested = False
        
        # Set up Arduino signal handlers
        def on_status(pos_a, pos_b, pos_c, pressure):
            status_updates.append((pos_a, pos_b, pos_c, pressure))
            
        arduino.status_emit.connect(on_status)
        
        # Create protocol instance with short duration
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="1",  # Axial protocol
            max_pressure=30,
            max_left=5.0,
            max_right=5.0,
            duration=1,  # 1 minute
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Set up protocol signal handlers
        def on_pressure(value):
            pressure_updates.append(value)
            
        def on_finished(success):
            nonlocal protocol_finished
            protocol_finished = success
            
        def on_reset():
            nonlocal reset_requested
            reset_requested = True
            
        protocol.signals.pressure_emit.connect(on_pressure)
        protocol.signals.finished.connect(on_finished)
        protocol.signals.reset_needed.connect(on_reset)
        
        # Mock check_duration to make test faster
        protocol.start_time = time.time()
        check_count = 0
        
        def mock_check_duration():
            nonlocal check_count
            check_count += 1
            if check_count < 4:  # Allow a few cycles
                return True
            return False
            
        protocol.check_duration = mock_check_duration
        
        # Run the protocol in a separate thread
        thread = threading.Thread(target=protocol.run)
        thread.daemon = True
        thread.start()
        
        # Wait for protocol to complete (with timeout)
        start_time = time.time()
        while thread.is_alive() and time.time() - start_time < 10:
            time.sleep(0.1)
            
        # Ensure thread completes
        if thread.is_alive():
            protocol.stop()
            thread.join(timeout=2.0)
            
        # Check results
        assert not protocol.is_running
        assert protocol_finished
        assert reset_requested
        
        # Should have received status updates
        assert len(status_updates) > 0
        
        # Should have received pressure updates
        assert len(pressure_updates) > 0
        
        # Final pressure should be near the target
        assert simulator.pressure > 0
        
    def test_protocol_recovery_from_disconnect(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test protocol recovery after Arduino disconnection."""
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
            use_pulse=False,
            ser=arduino,
            config=config
        )
        
        # Set up tracking
        connection_lost = False
        reconnect_success = None
        
        def on_connection_lost():
            nonlocal connection_lost
            connection_lost = True
            
        arduino.connection_lost.connect(on_connection_lost)
        
        # Start protocol
        protocol.is_running = True
        
        # Set some initial pressure
        success = protocol.set_to_pressure(20)
        assert success
        time.sleep(0.5)
        
        # Simulate a disconnection
        simulator.disconnect()
        time.sleep(0.5)
        
        # Try to set pressure - should fail
        success = protocol.set_to_pressure(30)
        assert not success
        
        # Verify connection lost was detected
        assert connection_lost
        assert not arduino.connected
        
        # Reconnect simulator
        simulator.connect()
        time.sleep(0.5)
        
        # Manually trigger reconnect
        reconnect_success = arduino.reconnect()
        assert reconnect_success
        
        # Now we should be able to set pressure again
        success = protocol.set_to_pressure(25)
        assert success
        
        # Check simulator state
        time.sleep(0.5)
        assert abs(simulator.pressure - 25) < 3
        
    def test_protocol_with_continuous_pulse(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test protocol with continuous pulse."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance with pulse enabled
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="2",  # Left lateral protocol
            max_pressure=30,
            max_left=5.0,
            max_right=5.0,
            duration=1,
            use_pulse=True,  # Enable pulsing
            ser=arduino,
            config=config
        )
        
        # Mock check_duration to make test faster
        protocol.start_time = time.time()
        check_count = 0
        
        def mock_check_duration():
            nonlocal check_count
            check_count += 1
            if check_count < 5:  # Allow enough cycles for protocol
                return True
            return False
            
        protocol.check_duration = mock_check_duration
        
        # Set up tracking
        protocol_finished = False
        
        def on_finished(success):
            nonlocal protocol_finished
            protocol_finished = success
            
        protocol.signals.finished.connect(on_finished)
        
        # Run the protocol in a separate thread
        thread = threading.Thread(target=protocol.run)
        thread.daemon = True
        thread.start()
        
        # Wait for protocol to complete (with timeout)
        start_time = time.time()
        while thread.is_alive() and time.time() - start_time < 10:
            time.sleep(0.1)
            
        # Ensure thread completes
        if thread.is_alive():
            protocol.stop()
            thread.join(timeout=2.0)
            
        # Check results
        assert not protocol.is_running
        assert protocol_finished
        
        # Should have pressure, angle, and jerking
        assert simulator.pressure > 0
        assert simulator.position_c < 300  # Left angle
        
        # Jerking should be stopped at the end
        assert not simulator.is_jerking
        
    def test_emergency_stop(self, arduino_mock: Tuple[Arduino, ArduinoSimulator]) -> None:
        """Test emergency stop functionality."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create protocol instance
        config = MockConfig()
        protocol = Protocols(
            a_factor=1.0,
            protocol="3",  # Right lateral protocol
            max_pressure=30,
            max_left=5.0,
            max_right=5.0,
            duration=5,  # 5 minutes
            use_pulse=True,
            ser=arduino,
            config=config
        )
        
        # Override check_duration for testing
        protocol.check_duration = lambda: True
        
        # Set up signal tracking
        stopped_signal_received = False
        
        def on_stopped(success):
            nonlocal stopped_signal_received
            stopped_signal_received = success
            
        protocol.signals.stopped.connect(on_stopped)
        
        # Start protocol
        protocol.is_running = True
        
        # Set some state
        protocol.set_to_pressure(20)
        time.sleep(0.5)
        protocol.set_to_angle(5.0)
        time.sleep(0.5)
        
        # Check simulator state before stop
        assert simulator.pressure > 0
        assert simulator.position_c > 300  # Right angle
        
        # Now stop the protocol
        protocol.stop()
        
        # Check results
        assert not protocol.is_running
        assert stopped_signal_received
        assert protocol.exit_flag.is_set()
        
        # Reset should be triggered for safety
        success = protocol.reset_actuators()
        assert success
        
        # Check simulator state after reset
        time.sleep(0.5)
        assert simulator.position_c == 300  # Neutral position
        assert simulator.pressure == 0  # No pressure