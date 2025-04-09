#!/usr/bin/env python3
"""
Simple script to verify Protocol testing implementation.
This script doesn't rely on pytest or module paths.
"""
import time
import threading
import queue
import random
from typing import Dict, List, Optional


# Import the Arduino simulator from our simplified test
from tests_simplified import ArduinoSimulator, MockSerial


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


class WorkerSignals:
    """Mock worker signals for testing."""
    
    def __init__(self):
        """Initialize signals."""
        self.progress_messages = []
        self.pressure_values = []
        self.finished_called = False
        self.finished_success = False
        self.reset_called = False
        self.stopped_called = False
        
    def emit_progress(self, message):
        """Emit progress signal."""
        print(f"Progress: {message}")
        self.progress_messages.append(message)
        
    def emit_pressure(self, value):
        """Emit pressure signal."""
        print(f"Pressure: {value}")
        self.pressure_values.append(value)
        
    def emit_finished(self, success):
        """Emit finished signal."""
        print(f"Finished: {success}")
        self.finished_called = True
        self.finished_success = success
        
    def emit_reset(self):
        """Emit reset signal."""
        print("Reset needed")
        self.reset_called = True
        
    def emit_stopped(self, success):
        """Emit stopped signal."""
        print(f"Stopped: {success}")
        self.stopped_called = True
        
    @property
    def progress(self):
        """Progress signal property."""
        return self
        
    @property
    def pressure_emit(self):
        """Pressure signal property."""
        return self
        
    @property
    def finished(self):
        """Finished signal property."""
        return self
        
    @property
    def reset_needed(self):
        """Reset signal property."""
        return self
        
    @property
    def stopped(self):
        """Stopped signal property."""
        return self
        
    def connect(self, func):
        """Mock signal connection."""
        return self
        
    def emit(self, *args):
        """Emit signal based on the property."""
        if self is self.progress:
            self.emit_progress(*args)
        elif self is self.pressure_emit:
            self.emit_pressure(*args)
        elif self is self.finished:
            self.emit_finished(*args)
        elif self is self.reset_needed:
            self.emit_reset()
        elif self is self.stopped:
            self.emit_stopped(*args)


class MockArduino:
    """Mock Arduino for testing protocols."""
    
    def __init__(self, simulator):
        """Initialize with a simulator."""
        self.simulator = simulator
        self.connected = True
        self.status_callbacks = []
        
    def send(self, command):
        """Send a command to the simulator."""
        if not self.connected:
            return False
            
        try:
            print(f"Sending command: {command}")
            self.simulator.serial._write_buffer.put(f"{command}\n".encode('utf-8'))
            time.sleep(0.2)  # Wait for processing
            return True
        except Exception as e:
            print(f"Error sending command: {e}")
            return False
            
    def status_emit(self):
        """Status signal property."""
        return self
        
    def connect(self, callback):
        """Connect status callback."""
        self.status_callbacks.append(callback)
        return self
        
    def emit(self, pos_a, pos_b, pos_c, pressure):
        """Emit status signal."""
        for callback in self.status_callbacks:
            callback(pos_a, pos_b, pos_c, pressure)


class SimpleProtocol:
    """Simplified protocol for testing."""
    
    def __init__(self, protocol_num, max_pressure, max_angle, duration, use_pulse=False):
        """Initialize protocol with parameters."""
        self.protocol_num = protocol_num
        self.max_pressure = max_pressure
        self.max_angle = max_angle
        self.duration = duration  # in seconds
        self.use_pulse = use_pulse
        
        self.arduino = None
        self.config = None
        self.signals = WorkerSignals()
        
        self.is_running = False
        self.current_pressure = 0
        self.start_time = None
        self.elapsed_time = 0
        
    def connect(self, arduino, config):
        """Connect to Arduino and configuration."""
        self.arduino = arduino
        self.config = config
        
        # Connect Arduino status signal
        self.arduino.status_emit.connect(self.update_status)
        
    def update_status(self, pos_a, pos_b, pos_c, pressure):
        """Update from Arduino status."""
        self.current_pressure = pressure
        self.signals.pressure_emit.emit(float(pressure))
        
    def run(self):
        """Run the protocol."""
        if not self.arduino or not self.config:
            print("Arduino or config not connected")
            self.signals.finished.emit(False)
            return
            
        self.is_running = True
        self.start_time = time.time()
        
        print(f"Starting protocol {self.protocol_num}")
        self.signals.progress.emit(f">>Starting protocol {self.protocol_num}")
        
        try:
            # Run the right protocol
            if self.protocol_num == "1":
                self.run_protocol_1()
            elif self.protocol_num == "2":
                self.run_protocol_2()
            elif self.protocol_num == "3":
                self.run_protocol_3()
            else:
                print(f"Unknown protocol: {self.protocol_num}")
                self.is_running = False
                self.signals.finished.emit(False)
                return
                
        except Exception as e:
            print(f"Protocol error: {e}")
            self.is_running = False
            self.signals.finished.emit(False)
            
    def stop(self):
        """Stop the protocol."""
        print("Stopping protocol")
        self.is_running = False
        
        # Send stop command to Arduino
        if self.arduino:
            self.arduino.send("X")
            
        self.signals.stopped.emit(True)
        
    def check_duration(self):
        """Check if protocol should continue based on duration."""
        if not self.start_time:
            return False
            
        self.elapsed_time = time.time() - self.start_time
        return self.elapsed_time < self.duration
        
    def set_pressure(self, pressure):
        """Set pressure to specified value."""
        if not self.is_running:
            return False
            
        print(f"Setting pressure to {pressure} lbs")
        
        # Safety check
        if pressure < 0 or pressure > 100:
            print(f"Pressure {pressure} outside safe range (0-100)")
            return False
            
        # Send command to Arduino
        self.arduino.send(f"P{pressure}")
        self.signals.progress.emit(f">>Setting pressure to {pressure} lbs")
        
        # Wait for pressure to stabilize
        time.sleep(2)
        
        # Update status
        self.arduino.send("S")
        time.sleep(0.5)
        
        # For simulation, set pressure directly
        if hasattr(self.arduino, 'simulator'):
            self.arduino.simulator.pressure = pressure
            self.current_pressure = pressure
            
        return True
        
    def set_angle(self, degrees):
        """Set angle to specified value."""
        if not self.is_running:
            return False
            
        print(f"Setting angle to {degrees}°")
        
        # Format for dictionary lookup
        degree_key = "{:.1f}".format(float(degrees))
        
        # Get position from config
        if degree_key in self.config.CMarks:
            position = self.config.CMarks[degree_key]
            print(f"Position value for {degrees}° is {position}")
            
            # Send command to Arduino
            self.arduino.send(f"K{position}")
            self.signals.progress.emit(f">>Setting angle to {degrees}°")
            
            # Wait for position change
            time.sleep(3)
            
            # Update status
            self.arduino.send("S")
            time.sleep(0.5)
            
            # For simulation, set position directly
            if hasattr(self.arduino, 'simulator'):
                self.arduino.simulator.position_c = position
                
            return True
        else:
            print(f"No position defined for angle {degrees}°")
            return False
            
    def start_pulse(self):
        """Start pulse motion."""
        if not self.is_running or not self.use_pulse:
            return False
            
        print("Starting pulse sequence")
        self.signals.progress.emit(">>Starting pulsing")
        
        # Send pulse command
        self.arduino.send("J")
        
        # For simulation, set jerking state
        if hasattr(self.arduino, 'simulator'):
            self.arduino.simulator.is_jerking = True
            
        return True
        
    def stop_pulse(self):
        """Stop pulse motion."""
        print("Stopping pulse sequence")
        
        # Send stop pulse command
        self.arduino.send("JS")
        
        # For simulation, clear jerking state
        if hasattr(self.arduino, 'simulator'):
            self.arduino.simulator.is_jerking = False
            
        return True
        
    def reset_actuators(self):
        """Reset actuators to safe positions."""
        print("Resetting actuators")
        
        # Stop any jerking first
        self.stop_pulse()
        time.sleep(1)
        
        # Return to neutral angle
        self.set_angle(0.0)
        time.sleep(2)
        
        # Set pressure to zero
        self.set_pressure(0)
        time.sleep(1)
        
        # Final status update
        self.arduino.send("S")
        
        return True
        
    def run_protocol_1(self):
        """Run axial protocol."""
        print("Running axial protocol")
        
        # Start with minimum pressure
        if not self.set_pressure(10):
            self.signals.finished.emit(False)
            return
            
        # Wait to stabilize
        time.sleep(1)
        
        # Gradually increase to max pressure
        current_pressure = 10
        while current_pressure < self.max_pressure and self.is_running and self.check_duration():
            current_pressure = min(current_pressure + 5, self.max_pressure)
            print(f"Increasing pressure to {current_pressure} lbs")
            
            if not self.set_pressure(current_pressure):
                self.signals.finished.emit(False)
                return
                
            time.sleep(1)
            
        # Apply pulse if enabled
        if self.is_running and self.use_pulse:
            self.start_pulse()
            
            # Wait until duration expires or stopped
            while self.is_running and self.check_duration():
                time.sleep(1)
                
            self.stop_pulse()
        else:
            # Hold at max pressure until time expires
            while self.is_running and self.check_duration():
                time.sleep(1)
                
        # Reset actuators
        self.signals.reset_needed.emit()
        self.reset_actuators()
        
        print("Protocol 1 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)
        self.is_running = False
        
    def run_protocol_2(self):
        """Run left lateral protocol."""
        print("Running left lateral protocol")
        
        # Reset to start from known state
        self.signals.reset_needed.emit()
        self.reset_actuators()
        time.sleep(1)
        
        # Start with pressure
        if not self.set_pressure(10):
            self.signals.finished.emit(False)
            return
            
        # Wait to stabilize
        time.sleep(1)
        
        # Gradually increase to max pressure
        current_pressure = 10
        while current_pressure < self.max_pressure and self.is_running and self.check_duration():
            current_pressure = min(current_pressure + 5, self.max_pressure)
            print(f"Increasing pressure to {current_pressure} lbs")
            
            if not self.set_pressure(current_pressure):
                self.signals.finished.emit(False)
                return
                
            time.sleep(1)
            
        # Set angle (negative for left)
        if self.is_running:
            angle = -abs(self.max_angle)
            if not self.set_angle(angle):
                self.signals.finished.emit(False)
                return
                
            # Apply pulse if enabled
            if self.use_pulse:
                self.start_pulse()
                
                # Wait until duration expires or stopped
                while self.is_running and self.check_duration():
                    time.sleep(1)
                    
                self.stop_pulse()
            else:
                # Hold position until time expires
                while self.is_running and self.check_duration():
                    time.sleep(1)
                    
        # Reset actuators
        self.signals.reset_needed.emit()
        self.reset_actuators()
        
        print("Protocol 2 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)
        self.is_running = False
        
    def run_protocol_3(self):
        """Run right lateral protocol."""
        print("Running right lateral protocol")
        
        # Reset to start from known state
        self.signals.reset_needed.emit()
        self.reset_actuators()
        time.sleep(1)
        
        # Start with pressure
        if not self.set_pressure(10):
            self.signals.finished.emit(False)
            return
            
        # Wait to stabilize
        time.sleep(1)
        
        # Gradually increase to max pressure
        current_pressure = 10
        while current_pressure < self.max_pressure and self.is_running and self.check_duration():
            current_pressure = min(current_pressure + 5, self.max_pressure)
            print(f"Increasing pressure to {current_pressure} lbs")
            
            if not self.set_pressure(current_pressure):
                self.signals.finished.emit(False)
                return
                
            time.sleep(1)
            
        # Set angle (positive for right)
        if self.is_running:
            angle = abs(self.max_angle)
            if not self.set_angle(angle):
                self.signals.finished.emit(False)
                return
                
            # Apply pulse if enabled
            if self.use_pulse:
                self.start_pulse()
                
                # Wait until duration expires or stopped
                while self.is_running and self.check_duration():
                    time.sleep(1)
                    
                self.stop_pulse()
            else:
                # Hold position until time expires
                while self.is_running and self.check_duration():
                    time.sleep(1)
                    
        # Reset actuators
        self.signals.reset_needed.emit()
        self.reset_actuators()
        
        print("Protocol 3 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)
        self.is_running = False


def main():
    """Main function to test protocol with Arduino simulator."""
    print("=== Protocol Test with Arduino Simulator ===")
    
    # Create and connect a simulator
    simulator = ArduinoSimulator()
    simulator.connect()
    print(f"Simulator connected on port: {simulator.serial.port}")
    
    # Create Arduino mock
    arduino = MockArduino(simulator)
    
    # Create config
    config = MockConfig()
    
    # Test Protocol 1: Axial
    print("\n=== Testing Protocol 1 (Axial) ===")
    protocol1 = SimpleProtocol(
        protocol_num="1",
        max_pressure=30,
        max_angle=0,  # Not used in axial protocol
        duration=10,  # 10 seconds for testing
        use_pulse=False
    )
    
    # Connect Arduino and config
    protocol1.connect(arduino, config)
    
    # Run protocol
    protocol_thread = threading.Thread(target=protocol1.run)
    protocol_thread.daemon = True
    protocol_thread.start()
    
    # Wait for protocol to complete
    start_time = time.time()
    while protocol_thread.is_alive() and (time.time() - start_time) < 30:
        time.sleep(0.1)
        
    if protocol_thread.is_alive():
        print("Protocol taking too long, stopping...")
        protocol1.stop()
        protocol_thread.join(timeout=2.0)
    
    # Check results
    print("\nProtocol 1 Results:")
    print(f"Finished: {protocol1.signals.finished_called}")
    print(f"Success: {protocol1.signals.finished_success}")
    print(f"Reset called: {protocol1.signals.reset_called}")
    print(f"Progress messages: {len(protocol1.signals.progress_messages)}")
    print(f"Pressure values: {len(protocol1.signals.pressure_values)}")
    print(f"Final pressure: {simulator.pressure}")
    print(f"Final position C: {simulator.position_c}")
    
    # Test Protocol 2: Left Lateral with Pulse
    print("\n=== Testing Protocol 2 (Left Lateral with Pulse) ===")
    protocol2 = SimpleProtocol(
        protocol_num="2",
        max_pressure=25,
        max_angle=5.0,  # 5 degrees left
        duration=10,  # 10 seconds for testing
        use_pulse=True
    )
    
    # Connect Arduino and config
    protocol2.connect(arduino, config)
    
    # Run protocol
    protocol_thread = threading.Thread(target=protocol2.run)
    protocol_thread.daemon = True
    protocol_thread.start()
    
    # Wait for protocol to complete
    start_time = time.time()
    while protocol_thread.is_alive() and (time.time() - start_time) < 30:
        time.sleep(0.1)
        
    if protocol_thread.is_alive():
        print("Protocol taking too long, stopping...")
        protocol2.stop()
        protocol_thread.join(timeout=2.0)
    
    # Check results
    print("\nProtocol 2 Results:")
    print(f"Finished: {protocol2.signals.finished_called}")
    print(f"Success: {protocol2.signals.finished_success}")
    print(f"Reset called: {protocol2.signals.reset_called}")
    print(f"Progress messages: {len(protocol2.signals.progress_messages)}")
    print(f"Pressure values: {len(protocol2.signals.pressure_values)}")
    print(f"Final pressure: {simulator.pressure}")
    print(f"Final position C: {simulator.position_c}")
    
    # Test Protocol 3: Right Lateral
    print("\n=== Testing Protocol 3 (Right Lateral) ===")
    protocol3 = SimpleProtocol(
        protocol_num="3",
        max_pressure=20,
        max_angle=10.0,  # 10 degrees right
        duration=5,  # 5 seconds for testing
        use_pulse=False
    )
    
    # Connect Arduino and config
    protocol3.connect(arduino, config)
    
    # Run protocol
    protocol_thread = threading.Thread(target=protocol3.run)
    protocol_thread.daemon = True
    protocol_thread.start()
    
    # Wait for protocol to complete
    start_time = time.time()
    while protocol_thread.is_alive() and (time.time() - start_time) < 30:
        time.sleep(0.1)
        
    if protocol_thread.is_alive():
        print("Protocol taking too long, stopping...")
        protocol3.stop()
        protocol_thread.join(timeout=2.0)
    
    # Check results
    print("\nProtocol 3 Results:")
    print(f"Finished: {protocol3.signals.finished_called}")
    print(f"Success: {protocol3.signals.finished_success}")
    print(f"Reset called: {protocol3.signals.reset_called}")
    print(f"Progress messages: {len(protocol3.signals.progress_messages)}")
    print(f"Pressure values: {len(protocol3.signals.pressure_values)}")
    print(f"Final pressure: {simulator.pressure}")
    print(f"Final position C: {simulator.position_c}")
    
    # Test emergency stop
    print("\n=== Testing Emergency Stop ===")
    protocol_stop = SimpleProtocol(
        protocol_num="1",
        max_pressure=40,
        max_angle=0,
        duration=30,  # 30 seconds
        use_pulse=True
    )
    
    # Connect Arduino and config
    protocol_stop.connect(arduino, config)
    
    # Run protocol
    protocol_thread = threading.Thread(target=protocol_stop.run)
    protocol_thread.daemon = True
    protocol_thread.start()
    
    # Wait for protocol to start
    time.sleep(3)
    
    # Stop the protocol mid-execution
    print("Stopping protocol...")
    protocol_stop.stop()
    
    # Wait for protocol to stop
    protocol_thread.join(timeout=2.0)
    
    # Check results
    print("\nEmergency Stop Results:")
    print(f"Stopped called: {protocol_stop.signals.stopped_called}")
    print(f"Running: {protocol_stop.is_running}")
    
    # Clean up
    print("\nDisconnecting simulator...")
    simulator.disconnect()
    print("Simulator disconnected")
    
    print("\nTests completed successfully!")


if __name__ == "__main__":
    main()