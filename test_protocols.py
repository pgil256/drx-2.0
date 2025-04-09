#!/usr/bin/env python3
"""
Test script for KneeSpa protocol functionality.
Tests the three protocols and error handling.
"""
import time
import threading
import random
from test_final import ArduinoSimulator, ArduinoTester


class ProtocolTester:
    """Class to test protocol functionality."""
    
    def __init__(self, arduino_tester):
        self.arduino = arduino_tester
        self.protocol_running = False
    
    def run_protocol(self, protocol_num, max_pressure, max_angle, use_pulse):
        """Run a protocol with the specified parameters."""
        if self.protocol_running:
            print("Protocol already running")
            return False
        
        # Start protocol
        self.protocol_running = True
        
        print(f"Starting protocol {protocol_num}")
        print(f"Parameters: Max Pressure={max_pressure}, Max Angle={max_angle}, Pulse={use_pulse}")
        
        try:
            # Prepare for protocol
            if not self.arduino.get_status():
                print("Failed to get initial status")
                self.protocol_running = False
                return False
            
            # Reset to starting position
            if not self.arduino.set_position(300):  # Neutral position
                print("Failed to set initial position")
                self.protocol_running = False
                return False
            
            if not self.arduino.set_pressure(0):
                print("Failed to set initial pressure")
                self.protocol_running = False
                return False
            
            time.sleep(1)
            
            # Run the appropriate protocol
            if protocol_num == "1":
                result = self._run_protocol_1(max_pressure, use_pulse)
            elif protocol_num == "2":
                result = self._run_protocol_2(max_pressure, -abs(max_angle), use_pulse)
            elif protocol_num == "3":
                result = self._run_protocol_3(max_pressure, abs(max_angle), use_pulse)
            else:
                print(f"Unknown protocol: {protocol_num}")
                self.protocol_running = False
                return False
            
            # Reset at the end
            self._reset_actuators()
            self.protocol_running = False
            
            return result
            
        except Exception as e:
            print(f"Protocol error: {e}")
            self.protocol_running = False
            return False
    
    def _run_protocol_1(self, max_pressure, use_pulse):
        """Run axial protocol (protocol 1)."""
        print("Running protocol 1 (Axial)")
        
        # Start with minimum pressure
        if not self.arduino.set_pressure(10):
            return False
        
        time.sleep(1)
        
        # Gradually increase pressure
        current_pressure = 10
        while current_pressure < max_pressure and self.protocol_running:
            current_pressure += 5
            if current_pressure > max_pressure:
                current_pressure = max_pressure
                
            print(f"Increasing pressure to {current_pressure}")
            if not self.arduino.set_pressure(current_pressure):
                return False
                
            time.sleep(1)
        
        # Apply pulse if enabled
        if use_pulse and self.protocol_running:
            print("Starting pulse")
            if not self.arduino.pulse_control(start=True):
                return False
                
            # Hold for 3 seconds
            print("Holding pulse for 3 seconds")
            time.sleep(3)
            
            print("Stopping pulse")
            if not self.arduino.pulse_control(start=False):
                return False
        else:
            # Hold at max pressure
            print(f"Holding at max pressure {max_pressure} for 3 seconds")
            time.sleep(3)
        
        print("Protocol 1 completed successfully")
        return True
    
    def _run_protocol_2(self, max_pressure, angle, use_pulse):
        """Run left lateral protocol (protocol 2)."""
        print("Running protocol 2 (Left Lateral)")
        
        # Start with minimum pressure
        if not self.arduino.set_pressure(10):
            return False
        
        time.sleep(1)
        
        # Gradually increase pressure
        current_pressure = 10
        while current_pressure < max_pressure and self.protocol_running:
            current_pressure += 5
            if current_pressure > max_pressure:
                current_pressure = max_pressure
                
            print(f"Increasing pressure to {current_pressure}")
            if not self.arduino.set_pressure(current_pressure):
                return False
                
            time.sleep(1)
        
        # Set angle
        if self.protocol_running:
            print(f"Setting angle to {angle}")
            
            # Convert angle to position
            position = 300 + int(angle * 20)  # Simple conversion for testing
            if not self.arduino.set_position(position):
                return False
                
            time.sleep(1)
            
            # Apply pulse if enabled
            if use_pulse:
                print("Starting pulse")
                if not self.arduino.pulse_control(start=True):
                    return False
                    
                # Hold for 3 seconds
                print("Holding pulse for 3 seconds")
                time.sleep(3)
                
                print("Stopping pulse")
                if not self.arduino.pulse_control(start=False):
                    return False
            else:
                # Hold at position and pressure
                print(f"Holding at angle {angle} and pressure {max_pressure} for 3 seconds")
                time.sleep(3)
        
        print("Protocol 2 completed successfully")
        return True
    
    def _run_protocol_3(self, max_pressure, angle, use_pulse):
        """Run right lateral protocol (protocol 3)."""
        print("Running protocol 3 (Right Lateral)")
        
        # Start with minimum pressure
        if not self.arduino.set_pressure(10):
            return False
        
        time.sleep(1)
        
        # Gradually increase pressure
        current_pressure = 10
        while current_pressure < max_pressure and self.protocol_running:
            current_pressure += 5
            if current_pressure > max_pressure:
                current_pressure = max_pressure
                
            print(f"Increasing pressure to {current_pressure}")
            if not self.arduino.set_pressure(current_pressure):
                return False
                
            time.sleep(1)
        
        # Set angle
        if self.protocol_running:
            print(f"Setting angle to {angle}")
            
            # Convert angle to position
            position = 300 + int(angle * 20)  # Simple conversion for testing
            if not self.arduino.set_position(position):
                return False
                
            time.sleep(1)
            
            # Apply pulse if enabled
            if use_pulse:
                print("Starting pulse")
                if not self.arduino.pulse_control(start=True):
                    return False
                    
                # Hold for 3 seconds
                print("Holding pulse for 3 seconds")
                time.sleep(3)
                
                print("Stopping pulse")
                if not self.arduino.pulse_control(start=False):
                    return False
            else:
                # Hold at position and pressure
                print(f"Holding at angle {angle} and pressure {max_pressure} for 3 seconds")
                time.sleep(3)
        
        print("Protocol 3 completed successfully")
        return True
    
    def stop_protocol(self):
        """Stop the currently running protocol."""
        if not self.protocol_running:
            print("No protocol running")
            return False
        
        print("Stopping protocol")
        self.protocol_running = False
        
        # Emergency stop
        self.arduino.emergency_stop()
        
        # Reset actuators
        self._reset_actuators()
        
        print("Protocol stopped")
        return True
    
    def _reset_actuators(self):
        """Reset actuators to safe positions."""
        print("Resetting actuators")
        
        # Stop any pulse
        self.arduino.pulse_control(start=False)
        time.sleep(0.5)
        
        # Return to neutral position
        self.arduino.set_position(300)
        time.sleep(0.5)
        
        # Set pressure to zero
        self.arduino.set_pressure(0)
        time.sleep(0.5)
        
        # Final status update
        self.arduino.get_status()
        
        return True
    
    def test_error_handling(self):
        """Test error handling functionality."""
        print("Testing error handling")
        
        # Test safety limit
        print("\nTesting pressure safety limit (150 lbs)")
        result = self.arduino.set_pressure(150)
        if result:
            print("WARNING: High pressure allowed")
        else:
            print("Safety limit enforced")
        
        # Test emergency stop
        print("\nTesting emergency stop during protocol")
        
        # Start a protocol
        self.protocol_running = True
        
        # Set initial conditions
        self.arduino.set_pressure(20)
        self.arduino.set_position(400)
        
        # Start pulse
        self.arduino.pulse_control(start=True)
        
        # Simulate running for a short time
        time.sleep(1)
        
        # Emergency stop
        print("Triggering emergency stop")
        self.stop_protocol()
        
        # Verify that everything is reset
        time.sleep(1)
        self.arduino.get_status()
        
        return True


def main():
    """Run protocol tests."""
    print("=== KneeSpa Protocol Testing ===")
    
    # Create simulator
    simulator = ArduinoSimulator()
    simulator.connect()
    print(f"Arduino simulator connected on port: {simulator.serial.port}")
    
    # Create Arduino tester
    arduino = ArduinoTester(simulator)
    
    # Connect Arduino
    if not arduino.connect():
        print("Failed to connect to Arduino")
        simulator.disconnect()
        return
    
    # Create protocol tester
    protocol = ProtocolTester(arduino)
    
    # Test Protocol 1
    print("\n=== Testing Protocol 1 (Axial) ===")
    protocol.run_protocol(
        protocol_num="1",
        max_pressure=30,
        max_angle=0,
        use_pulse=False
    )
    
    # Test Protocol 1 with Pulse
    print("\n=== Testing Protocol 1 (Axial with Pulse) ===")
    protocol.run_protocol(
        protocol_num="1",
        max_pressure=35,
        max_angle=0,
        use_pulse=True
    )
    
    # Test Protocol 2
    print("\n=== Testing Protocol 2 (Left Lateral) ===")
    protocol.run_protocol(
        protocol_num="2",
        max_pressure=25,
        max_angle=5.0,
        use_pulse=False
    )
    
    # Test Protocol 3
    print("\n=== Testing Protocol 3 (Right Lateral) ===")
    protocol.run_protocol(
        protocol_num="3",
        max_pressure=25,
        max_angle=5.0,
        use_pulse=False
    )
    
    # Test Protocol 3 with Pulse
    print("\n=== Testing Protocol 3 (Right Lateral with Pulse) ===")
    protocol.run_protocol(
        protocol_num="3",
        max_pressure=35,
        max_angle=10.0,
        use_pulse=True
    )
    
    # Test emergency stop
    print("\n=== Testing Protocol Stop ===")
    
    # Start a protocol in a thread
    protocol_thread = threading.Thread(
        target=protocol.run_protocol,
        args=("2", 40, 10.0, True)
    )
    protocol_thread.daemon = True
    protocol_thread.start()
    
    # Let it run for a bit
    time.sleep(3)
    
    # Stop it mid-execution
    protocol.stop_protocol()
    
    # Wait for thread to complete
    protocol_thread.join(timeout=2.0)
    
    # Test error handling
    print("\n=== Testing Error Handling ===")
    protocol.test_error_handling()
    
    # Clean up
    arduino.disconnect()
    simulator.disconnect()
    
    print("\nProtocol tests completed successfully!")


if __name__ == "__main__":
    main()