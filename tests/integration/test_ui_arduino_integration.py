"""
Integration tests for UI components, Arduino, and Protocol classes.
"""
import pytest
import sys
import os
import time
import threading
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, List, Tuple

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Conditionally import PyQt5
try:
    from PyQt5.QtWidgets import QApplication, QWidget, QDialog
    from PyQt5.QtCore import QObject, pyqtSignal
    PyQt5_AVAILABLE = True
except ImportError:
    PyQt5_AVAILABLE = False

# Import test fixtures
from tests.fixtures.arduino_simulator import ArduinoSimulator
from tests.fixtures.arduino_mock import ArduinoTestFixture
from tests.fixtures.ui_mock import (
    UITestFixture, 
    mock_pressure_dialog,
    mock_timer_dialog,
    UITestingNotSupportedError
)
from tests.fixtures.test_logger import capture_logs
from tests.unit.test_protocols import MockConfig

# Import application classes
from main.helpers.arduino import Arduino
from main.helpers.protocols import Protocols
if PyQt5_AVAILABLE:
    from main.ui.dialogs.pressure_dialog import PressureDialog
    from main.ui.dialogs.timer_dialog import TimerDialog


class MockUIHandler(QObject if PyQt5_AVAILABLE else object):
    """Mock UI handler for testing the integration of UI, Arduino and Protocols.
    
    This class simulates a UI component that would use Arduino and Protocols.
    """
    
    # Define signals if PyQt5 is available
    if PyQt5_AVAILABLE:
        protocol_started = pyqtSignal(bool)
        protocol_finished = pyqtSignal(bool)
        protocol_progress = pyqtSignal(str)
        protocol_pressure = pyqtSignal(float)
        protocol_reset = pyqtSignal()
    
    def __init__(self, arduino: Arduino, config: MockConfig):
        """Initialize the mock UI handler.
        
        Args:
            arduino: Arduino instance
            config: Configuration instance
        """
        if PyQt5_AVAILABLE:
            super().__init__()
        
        self.arduino = arduino
        self.config = config
        self.protocol = None
        self.protocol_thread = None
        self.is_running = False
        
        # Track signal emissions
        self.signals_received = {
            'started': False,
            'finished': False,
            'progress': [],
            'pressure': [],
            'reset': False
        }
        
        # Connect Arduino signals
        if PyQt5_AVAILABLE:
            self.arduino.connection_ready.connect(self.on_connection_ready)
            self.arduino.connection_failed.connect(self.on_connection_failed)
            self.arduino.connection_lost.connect(self.on_connection_lost)
            
    def on_connection_ready(self):
        """Handle connection ready signal."""
        print("Arduino connected successfully")
        
    def on_connection_failed(self, error_message):
        """Handle connection failed signal."""
        print(f"Arduino connection failed: {error_message}")
        
    def on_connection_lost(self):
        """Handle connection lost signal."""
        print("Arduino connection lost")
        
    def on_protocol_progress(self, message):
        """Handle protocol progress signal."""
        print(f"Protocol progress: {message}")
        self.signals_received['progress'].append(message)
        
        if PyQt5_AVAILABLE:
            self.protocol_progress.emit(message)
        
    def on_protocol_pressure(self, pressure):
        """Handle protocol pressure signal."""
        print(f"Protocol pressure: {pressure}")
        self.signals_received['pressure'].append(pressure)
        
        if PyQt5_AVAILABLE:
            self.protocol_pressure.emit(pressure)
        
    def on_protocol_finished(self, success):
        """Handle protocol finished signal."""
        print(f"Protocol finished with success: {success}")
        self.is_running = False
        self.signals_received['finished'] = True
        
        if PyQt5_AVAILABLE:
            self.protocol_finished.emit(success)
        
    def on_protocol_reset(self):
        """Handle protocol reset signal."""
        print("Protocol reset requested")
        self.signals_received['reset'] = True
        
        if PyQt5_AVAILABLE:
            self.protocol_reset.emit()
        
    def start_protocol(self, protocol_num, max_pressure, max_left, max_right, duration, use_pulse):
        """Start a protocol with the given parameters.
        
        Args:
            protocol_num: Protocol number (1, 2, or 3)
            max_pressure: Maximum pressure in lbs
            max_left: Maximum left angle in degrees
            max_right: Maximum right angle in degrees
            duration: Duration in minutes
            use_pulse: Whether to use pulse mode
            
        Returns:
            True if protocol started successfully, False otherwise
        """
        if self.is_running:
            print("Protocol already running")
            return False
            
        # Create protocol instance
        self.protocol = Protocols(
            a_factor=1.0,
            protocol=protocol_num,
            max_pressure=max_pressure,
            max_left=max_left,
            max_right=max_right,
            duration=duration,
            use_pulse=use_pulse,
            ser=self.arduino,
            config=self.config
        )
        
        # Connect protocol signals
        self.protocol.signals.progress.connect(self.on_protocol_progress)
        self.protocol.signals.pressure_emit.connect(self.on_protocol_pressure)
        self.protocol.signals.finished.connect(self.on_protocol_finished)
        self.protocol.signals.reset_needed.connect(self.on_protocol_reset)
        
        # Start protocol in a separate thread
        self.protocol_thread = threading.Thread(target=self.protocol.run)
        self.protocol_thread.daemon = True
        self.protocol_thread.start()
        
        self.is_running = True
        self.signals_received['started'] = True
        
        if PyQt5_AVAILABLE:
            self.protocol_started.emit(True)
            
        return True
        
    def stop_protocol(self):
        """Stop the running protocol.
        
        Returns:
            True if protocol was stopped, False if no protocol was running
        """
        if not self.is_running or not self.protocol:
            return False
            
        self.protocol.stop()
        self.is_running = False
        return True
        
    def wait_for_completion(self, timeout=10.0):
        """Wait for protocol to complete.
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            True if protocol completed within timeout, False otherwise
        """
        if not self.protocol_thread:
            return False
            
        start_time = time.time()
        while self.protocol_thread.is_alive() and time.time() - start_time < timeout:
            time.sleep(0.1)
            
        if self.protocol_thread.is_alive():
            self.stop_protocol()
            return False
            
        return True


@pytest.mark.integration
@pytest.mark.skipif(not PyQt5_AVAILABLE, reason="PyQt5 not available")
class TestUIArduinoIntegration:
    """Integration tests for UI, Arduino, and Protocol classes."""
    
    def test_protocol_with_ui(self, arduino_mock: Tuple[Arduino, ArduinoSimulator], ui_fixture: UITestFixture):
        """Test protocol execution with UI integration."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create mock config
        config = MockConfig()
        
        # Create UI handler
        ui_handler = MockUIHandler(arduino, config)
        
        with capture_logs() as logs:
            # Start a protocol
            success = ui_handler.start_protocol(
                protocol_num="1",
                max_pressure=30,
                max_left=5.0,
                max_right=5.0,
                duration=1,  # 1 minute
                use_pulse=False
            )
            
            assert success
            assert ui_handler.is_running
            
            # Wait for protocol to complete (with timeout)
            # Mock check_duration to make test faster
            if ui_handler.protocol:
                ui_handler.protocol.start_time = time.time()
                check_count = 0
                
                def mock_check_duration():
                    nonlocal check_count
                    check_count += 1
                    if check_count < 3:
                        return True
                    return False
                    
                ui_handler.protocol.check_duration = mock_check_duration
            
            # Wait for protocol to complete
            completed = ui_handler.wait_for_completion(timeout=5.0)
            assert completed
            
            # Check that signals were received
            assert ui_handler.signals_received['started']
            assert ui_handler.signals_received['finished']
            assert len(ui_handler.signals_received['progress']) > 0
            assert len(ui_handler.signals_received['pressure']) > 0
            assert ui_handler.signals_received['reset']
            
            # Check logs for protocol messages
            assert logs.contains_message("Protocol")
            
    def test_protocol_stop_from_ui(self, arduino_mock: Tuple[Arduino, ArduinoSimulator], ui_fixture: UITestFixture):
        """Test stopping a protocol from the UI."""
        arduino, simulator = arduino_mock
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create mock config
        config = MockConfig()
        
        # Create UI handler
        ui_handler = MockUIHandler(arduino, config)
        
        with capture_logs() as logs:
            # Start a protocol
            success = ui_handler.start_protocol(
                protocol_num="2",  # Left lateral protocol
                max_pressure=30,
                max_left=5.0,
                max_right=5.0,
                duration=5,  # 5 minutes (would be long, but we'll stop it)
                use_pulse=True
            )
            
            assert success
            assert ui_handler.is_running
            
            # Let it run briefly
            time.sleep(1.0)
            
            # Stop the protocol
            stopped = ui_handler.stop_protocol()
            assert stopped
            assert not ui_handler.is_running
            
            # Wait for thread to complete
            if ui_handler.protocol_thread:
                ui_handler.protocol_thread.join(timeout=2.0)
                
            # Check logs for stop message
            assert logs.contains_message("stop")
            
    @patch('main.ui.dialogs.pressure_dialog.PressureDialog.exec_')
    @patch('main.ui.dialogs.timer_dialog.TimerDialog.exec_')
    def test_protocol_with_ui_dialogs(self, 
                                      mock_timer_exec, 
                                      mock_pressure_exec,
                                      arduino_mock: Tuple[Arduino, ArduinoSimulator], 
                                      ui_fixture: UITestFixture):
        """Test protocol execution with UI dialogs."""
        arduino, simulator = arduino_mock
        
        # Configure mocks
        mock_timer_exec.return_value = 1  # Accepted
        mock_pressure_exec.return_value = 1  # Accepted
        
        # Connect Arduino
        arduino.run()
        time.sleep(0.5)
        
        # Create mock config
        config = MockConfig()
        
        # Create UI handler
        ui_handler = MockUIHandler(arduino, config)
        
        with capture_logs() as logs:
            # Create dialogs
            timer_dialog = TimerDialog(5)  # Default 5 minutes
            pressure_dialog = PressureDialog(30)  # Default 30 lbs
            
            # Patch get methods to return test values
            with patch.object(timer_dialog, 'get_minutes', return_value=2):
                with patch.object(pressure_dialog, 'get_pressure', return_value=25):
                    # Show dialogs (mocked)
                    timer_result = timer_dialog.exec_()
                    pressure_result = pressure_dialog.exec_()
                    
                    assert timer_result == 1  # Accepted
                    assert pressure_result == 1  # Accepted
                    
                    # Get values from dialogs
                    duration = timer_dialog.get_minutes()
                    pressure = pressure_dialog.get_pressure()
                    
                    assert duration == 2
                    assert pressure == 25
                    
                    # Start protocol with dialog values
                    success = ui_handler.start_protocol(
                        protocol_num="3",  # Right lateral protocol
                        max_pressure=pressure,
                        max_left=5.0,
                        max_right=5.0,
                        duration=duration,
                        use_pulse=False
                    )
                    
                    assert success
                    
                    # Mock check_duration for faster test
                    if ui_handler.protocol:
                        ui_handler.protocol.start_time = time.time()
                        check_count = 0
                        
                        def mock_check_duration():
                            nonlocal check_count
                            check_count += 1
                            if check_count < 3:
                                return True
                            return False
                            
                        ui_handler.protocol.check_duration = mock_check_duration
                    
                    # Wait for protocol to complete
                    completed = ui_handler.wait_for_completion(timeout=5.0)
                    assert completed
                    
                    # Check simulator state - pressure should match dialog setting
                    time.sleep(0.5)
                    assert simulator.pressure > 0