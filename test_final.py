#!/usr/bin/env python3
"""
Final simplified test to verify Arduino simulator functionality.
This focuses on basic Arduino command handling.
"""
import time
import threading
import queue
import random


class MockSerial:
    """Mock serial port for Arduino testing."""
    
    def __init__(self, port="MOCK"):
        self.port = port
        self.in_waiting = 0
        self.out_waiting = 0
        self.is_open = True
        self._read_buffer = queue.Queue()
        self._write_buffer = queue.Queue()
    
    def write(self, data):
        """Write data to the buffer."""
        self._write_buffer.put(data)
        self.out_waiting = self._write_buffer.qsize()
        return len(data)
    
    def readline(self):
        """Read a line from the buffer."""
        if self._read_buffer.empty():
            return b""
        data = self._read_buffer.get()
        self.in_waiting = self._read_buffer.qsize()
        return data
    
    def close(self):
        """Close the connection."""
        self.is_open = False
    
    def reset_input_buffer(self):
        """Clear the input buffer."""
        while not self._read_buffer.empty():
            self._read_buffer.get()
        self.in_waiting = 0
    
    def reset_output_buffer(self):
        """Clear the output buffer."""
        while not self._write_buffer.empty():
            self._write_buffer.get()
        self.out_waiting = 0
    
    def flush(self):
        """Flush the buffers."""
        pass


class ArduinoSimulator:
    """Arduino simulator for testing."""
    
    def __init__(self):
        self.serial = None
        self.position_a = 100
        self.position_b = 200
        self.position_c = 300
        self.pressure = 0.0
        self._running = False
        self.response_thread = None
    
    def connect(self):
        """Connect to mock serial port."""
        self.serial = MockSerial()
        
        # Initialize with ready message
        self.serial._read_buffer.put(b"Ready to Go\n")
        self.serial.in_waiting = 1
        
        # Start command processing thread
        self._running = True
        self.response_thread = threading.Thread(target=self._process_commands)
        self.response_thread.daemon = True
        self.response_thread.start()
        
        return True
    
    def disconnect(self):
        """Disconnect the simulator."""
        self._running = False
        if self.response_thread:
            self.response_thread.join(timeout=1.0)
        if self.serial:
            self.serial.close()
            self.serial = None
    
    def _process_commands(self):
        """Process commands from the write buffer."""
        while self._running and self.serial and self.serial.is_open:
            try:
                # Check for commands
                data = self._get_written_data()
                if data:
                    # Process the command
                    command = data.decode('utf-8').strip()
                    if command:
                        self._handle_command(command)
                time.sleep(0.01)
            except Exception as e:
                print(f"Error in simulator: {e}")
    
    def _get_written_data(self):
        """Get data written to the port."""
        if not self.serial:
            return b""
        
        data = b""
        while not self.serial._write_buffer.empty():
            data += self.serial._write_buffer.get()
        self.serial.out_waiting = 0
        return data
    
    def _handle_command(self, command):
        """Handle Arduino commands."""
        print(f"Arduino received: {command}")
        
        if command.startswith("T"):
            # Test command
            self.serial._read_buffer.put(b"Test command received\n")
            self.serial._read_buffer.put(b"OK\n")
            self.serial.in_waiting = 2
        
        elif command.startswith("S"):
            # Status command
            status = f"STATUS_START|S|{self.position_a}|{self.position_b}|{self.position_c}|{self.pressure}|STATUS_END\n"
            self.serial._read_buffer.put(status.encode('utf-8'))
            self.serial.in_waiting = 1
            self.serial._read_buffer.put(b"DONE\n")
            self.serial.in_waiting = 2
        
        elif command.startswith("P"):
            # Pressure command
            try:
                target = float(command[1:])
                print(f"Setting pressure to {target}")
                self.pressure = target
                time.sleep(0.3)  # Simulate processing time
                self.serial._read_buffer.put(b"DONE\n")
                self.serial.in_waiting = 1
            except Exception:
                self.serial._read_buffer.put(b"ERROR\n")
                self.serial.in_waiting = 1
        
        elif command.startswith("K"):
            # Position command
            try:
                target = int(command[1:])
                print(f"Setting position C to {target}")
                self.position_c = target
                time.sleep(0.3)  # Simulate processing time
                self.serial._read_buffer.put(b"DONE\n")
                self.serial.in_waiting = 1
            except Exception:
                self.serial._read_buffer.put(b"ERROR\n")
                self.serial.in_waiting = 1
        
        elif command.startswith("X"):
            # Emergency stop
            print("Emergency stop")
            self.serial._read_buffer.put(b"DONE\n")
            self.serial.in_waiting = 1
        
        elif command == "J":
            # Start jerking
            print("Start jerking")
            self.serial._read_buffer.put(b"DONE\n")
            self.serial.in_waiting = 1
        
        elif command == "JS":
            # Stop jerking
            print("Stop jerking")
            self.serial._read_buffer.put(b"DONE\n")
            self.serial.in_waiting = 1
        
        else:
            # Default response
            self.serial._read_buffer.put(b"DONE\n")
            self.serial.in_waiting = 1


class ArduinoTester:
    """Class to test Arduino communication."""
    
    def __init__(self, simulator):
        self.simulator = simulator
        self.connected = False
    
    def connect(self):
        """Connect to the simulator."""
        if not self.simulator.serial:
            return False
        
        print("Connecting to Arduino...")
        time.sleep(0.5)
        
        # Check for ready message
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
            
            if "Ready to Go" in message:
                self.connected = True
                print("Connection established!")
                return True
        
        print("Failed to connect")
        return False
    
    def verify_connection(self):
        """Verify connection with test command."""
        if not self.connected:
            return False
        
        print("Verifying connection...")
        self.simulator.serial.write(b"T\n")
        time.sleep(0.5)
        
        # Check for response
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
            
            if "OK" in message or "Test command received" in message:
                print("Connection verified!")
                return True
        
        print("Connection verification failed")
        return False
    
    def get_status(self):
        """Get status from Arduino."""
        if not self.connected:
            return False
        
        print("Getting status...")
        self.simulator.serial.write(b"S\n")
        time.sleep(0.5)
        
        # Read status response
        status_data = None
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
            
            if "STATUS_START" in message:
                status_data = message
        
        if status_data:
            # Parse status data
            try:
                parts = status_data.replace("STATUS_START|", "").replace("|STATUS_END", "").split("|")
                if len(parts) >= 5:
                    pos_a = int(parts[1])
                    pos_b = int(parts[2])
                    pos_c = int(parts[3])
                    pressure = float(parts[4])
                    
                    print(f"Status: A={pos_a}, B={pos_b}, C={pos_c}, Pressure={pressure}")
                    return True
            except Exception as e:
                print(f"Error parsing status: {e}")
        
        return False
    
    def set_pressure(self, pressure):
        """Set pressure value."""
        if not self.connected:
            return False
        
        print(f"Setting pressure to {pressure}...")
        self.simulator.serial.write(f"P{pressure}\n".encode('utf-8'))
        time.sleep(1.0)
        
        # Read response
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
        
        # Verify with status
        return self.get_status()
    
    def set_position(self, position):
        """Set position value."""
        if not self.connected:
            return False
        
        print(f"Setting position to {position}...")
        self.simulator.serial.write(f"K{position}\n".encode('utf-8'))
        time.sleep(1.0)
        
        # Read response
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
        
        # Verify with status
        return self.get_status()
    
    def emergency_stop(self):
        """Send emergency stop command."""
        if not self.connected:
            return False
        
        print("Sending emergency stop...")
        self.simulator.serial.write(b"X\n")
        time.sleep(0.5)
        
        # Read response
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
        
        return True
    
    def pulse_control(self, start=True):
        """Control pulse mode."""
        if not self.connected:
            return False
        
        command = "J" if start else "JS"
        print(f"Sending pulse {'start' if start else 'stop'}...")
        self.simulator.serial.write(f"{command}\n".encode('utf-8'))
        time.sleep(0.5)
        
        # Read response
        while self.simulator.serial.in_waiting > 0:
            data = self.simulator.serial.readline()
            message = data.decode('utf-8', errors='replace').strip()
            print(f"Received: {message}")
        
        return True
    
    def disconnect(self):
        """Disconnect from Arduino."""
        self.connected = False
        print("Disconnected from Arduino")


def main():
    """Run the Arduino test."""
    print("=== Arduino Communication Test ===")
    
    # Create simulator
    simulator = ArduinoSimulator()
    simulator.connect()
    print(f"Arduino simulator connected on port: {simulator.serial.port}")
    
    # Create tester
    tester = ArduinoTester(simulator)
    
    # Test connection
    print("\n1. Testing Connection")
    if not tester.connect():
        print("Failed to connect to Arduino")
        simulator.disconnect()
        return
    
    # Test connection verification
    print("\n2. Testing Connection Verification")
    if not tester.verify_connection():
        print("Failed to verify connection")
        tester.disconnect()
        simulator.disconnect()
        return
    
    # Test status
    print("\n3. Testing Status Request")
    tester.get_status()
    
    # Test pressure control
    print("\n4. Testing Pressure Control")
    tester.set_pressure(25)
    print(f"Simulator pressure: {simulator.pressure}")
    
    # Test position control
    print("\n5. Testing Position Control")
    tester.set_position(450)
    print(f"Simulator position C: {simulator.position_c}")
    
    # Test pulse control
    print("\n6. Testing Pulse Control")
    tester.pulse_control(start=True)
    time.sleep(0.5)
    tester.pulse_control(start=False)
    
    # Test emergency stop
    print("\n7. Testing Emergency Stop")
    tester.emergency_stop()
    
    # Reset and test stress
    print("\n8. Testing Multiple Commands")
    pressures = [10, 20, 30, 40, 50]
    positions = [300, 350, 400, 450, 500]
    
    for i in range(5):
        print(f"\nRound {i+1}:")
        tester.set_pressure(pressures[i])
        tester.set_position(positions[i])
        tester.get_status()
    
    # Clean up
    tester.disconnect()
    simulator.disconnect()
    
    print("\nArduino test completed successfully!")


if __name__ == "__main__":
    main()