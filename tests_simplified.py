#!/usr/bin/env python3
"""
Simple script to verify Arduino test implementation.
This script doesn't rely on pytest or module paths.
"""
import time
import threading
import random
import queue
import re
from typing import Dict, List, Optional, Callable


class MockSerial:
    """Mocks the pyserial Serial class with configurable behavior."""
    
    def __init__(self, port="MOCK", baudrate=115200, timeout=10, write_timeout=1):
        """Initialize a mock serial connection."""
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.is_open = True
        self.in_waiting = 0
        self.out_waiting = 0
        
        # Input and output buffers
        self._read_buffer = queue.Queue()
        self._write_buffer = queue.Queue()
        
        # Simulate behavior
        self._error_rate = 0.0
        
    def write(self, data):
        """Write data to the mock serial port."""
        if random.random() < self._error_rate:
            raise Exception("Simulated write error")
            
        self._write_buffer.put(data)
        self.out_waiting = self._write_buffer.qsize()
        return len(data)
        
    def read(self, size=1):
        """Read data from the mock serial port."""
        if random.random() < self._error_rate:
            raise Exception("Simulated read error")
            
        result = b""
        for _ in range(min(size, self._read_buffer.qsize())):
            try:
                result += self._read_buffer.get_nowait()
            except queue.Empty:
                break
                
        self.in_waiting = self._read_buffer.qsize()
        return result
        
    def readline(self):
        """Read a line from the mock serial port."""
        if random.random() < self._error_rate:
            raise Exception("Simulated readline error")
            
        # Try to find a complete line in the buffer
        result = b""
        start_time = time.time()
        
        while True:
            try:
                byte = self._read_buffer.get(timeout=0.1)
                result += byte
                
                if byte == b'\n':
                    break
                    
            except queue.Empty:
                if time.time() - start_time > self.timeout:
                    break
                continue
                
        self.in_waiting = self._read_buffer.qsize()
        return result
        
    def close(self):
        """Close the mock serial port."""
        self.is_open = False
        
    def flush(self):
        """Flush the write buffer."""
        pass
        
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


class ArduinoSimulator:
    """Simulator for Arduino responses to test KneeSpa without hardware."""
    
    def __init__(self):
        """Initialize the Arduino simulator."""
        self.serial = None
        self.response_thread = None
        self._running = False
        
        # Simulated state
        self.position_a = 100
        self.position_b = 200
        self.position_c = 300
        self.pressure = 0.0
        self.is_jerking = False
        
    def connect(self, port="MOCK", baudrate=115200, timeout=10, write_timeout=1):
        """Create a mock serial connection."""
        self.serial = MockSerial(port, baudrate, timeout, write_timeout)
        
        # Send initial ready message
        self.serial._read_buffer.put(b"Ready to Go\n")
        
        # Start response thread
        self._running = True
        self.response_thread = threading.Thread(target=self._process_commands)
        self.response_thread.daemon = True
        self.response_thread.start()
        
    def disconnect(self):
        """Disconnect the simulator."""
        self._running = False
        if self.response_thread:
            self.response_thread.join(timeout=1.0)
            self.response_thread = None
            
        if self.serial:
            self.serial.close()
            self.serial = None
            
    def _process_commands(self):
        """Process commands from the serial port and generate responses."""
        while self._running and self.serial and self.serial.is_open:
            try:
                # Check if any data has been written
                data = self._get_written_data()
                if data:
                    # Process the command
                    self._handle_command(data.decode('utf-8', errors='replace'))
                    
                # Don't burn CPU
                time.sleep(0.01)
                
            except Exception as e:
                print(f"Error in Arduino simulator: {e}")
                
    def _handle_command(self, command):
        """Process a command and generate appropriate response."""
        command = command.strip()
        if not command:
            return
            
        print(f"Received command: {command}")
        
        # Handle different command types
        if command.startswith("T"):
            self._handle_test()
        elif command.startswith("S"):
            self._handle_status()
        elif command.startswith("P"):
            self._handle_pressure(command[1:])
        elif command.startswith("K"):
            self._handle_angle(command[1:])
        elif command.startswith("X"):
            self._handle_stop()
        elif command.startswith("J") and len(command) == 1:
            self._handle_jerk_start()
        elif command.startswith("JS"):
            self._handle_jerk_stop()
        else:
            # Default response
            time.sleep(0.1)
            self.serial._read_buffer.put(b"DONE\n")
            
    def _handle_test(self):
        """Handle test command."""
        time.sleep(0.1)
        self.serial._read_buffer.put(b"Test command received\n")
        self.serial._read_buffer.put(b"OK\n")
        
    def _handle_status(self):
        """Send status information."""
        time.sleep(0.2)
        
        # Generate a status message
        status = f"STATUS_START|S|{self.position_a}|{self.position_b}|{self.position_c}|{self.pressure}|STATUS_END\n"
        for b in status.encode('utf-8'):
            self.serial._read_buffer.put(bytes([b]))
        
    def _handle_pressure(self, pressure_str):
        """Handle pressure command."""
        try:
            target_pressure = float(pressure_str)
            print(f"Setting pressure to {target_pressure}")
            
            # Simulate pressure change gradually
            start_pressure = self.pressure
            steps = 5
            
            for i in range(1, steps + 1):
                time.sleep(0.2)
                self.pressure = start_pressure + (target_pressure - start_pressure) * (i / steps)
                
                # Periodically send status updates during pressure change
                if i % 2 == 0 or i == steps:
                    self._handle_status()
                    
            time.sleep(0.5)
            self.serial._read_buffer.put(b"DONE\n")
        except Exception as e:
            print(f"Error handling pressure command: {e}")
            self.serial._read_buffer.put(b"ERROR\n")
        
    def _handle_angle(self, position_str):
        """Handle angle position command."""
        try:
            target_position = int(position_str)
            print(f"Setting angle position to {target_position}")
            
            # Simulate position change gradually
            start_position = self.position_c
            steps = 5
            
            for i in range(1, steps + 1):
                time.sleep(0.3)
                self.position_c = start_position + (target_position - start_position) * (i / steps)
                
                # Periodically send status updates during position change
                if i % 2 == 0 or i == steps:
                    self._handle_status()
                    
            time.sleep(0.5)
            self.serial._read_buffer.put(b"DONE\n")
        except Exception as e:
            print(f"Error handling angle command: {e}")
            self.serial._read_buffer.put(b"ERROR\n")
        
    def _handle_stop(self):
        """Handle emergency stop command."""
        self.is_jerking = False
        self.serial._read_buffer.put(b"DONE\n")
        
    def _handle_jerk_start(self):
        """Handle start jerking command."""
        self.is_jerking = True
        time.sleep(0.1)
        self.serial._read_buffer.put(b"DONE\n")
        
    def _handle_jerk_stop(self):
        """Handle stop jerking command."""
        self.is_jerking = False
        time.sleep(0.1)
        self.serial._read_buffer.put(b"DONE\n")
        
    def _get_written_data(self):
        """Get data written to the port."""
        if not self.serial:
            return b""
            
        data = b""
        while not self.serial._write_buffer.empty():
            data += self.serial._write_buffer.get()
        self.serial.out_waiting = 0
        return data
        
    def set_error_rate(self, rate):
        """Set the rate at which operations will fail."""
        if self.serial:
            self.serial._error_rate = max(0.0, min(1.0, rate))


def main():
    """Main function to test the Arduino simulator."""
    print("=== Arduino Simulator Test ===")
    
    # Create and connect a simulator
    simulator = ArduinoSimulator()
    simulator.connect()
    print(f"Simulator connected on port: {simulator.serial.port}")
    
    # Wait for initial message
    time.sleep(0.5)
    
    # Read initial messages
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Initial message: {line.decode('utf-8', errors='replace').strip()}")
    
    # Send a test command
    print("\nSending test command (T)...")
    simulator.serial._write_buffer.put(b"T\n")
    time.sleep(0.5)
    
    # Read response
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    # Send a status command
    print("\nSending status command (S)...")
    simulator.serial._write_buffer.put(b"S\n")
    time.sleep(0.5)
    
    # Read response
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    # Set pressure
    print("\nSetting pressure to 35 lbs (P35)...")
    simulator.serial._write_buffer.put(b"P35\n")
    time.sleep(2.0)  # Longer wait for pressure change
    
    # Read responses
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    print(f"Current pressure: {simulator.pressure} lbs")
    
    # Set angle position
    print("\nSetting angle position to 450 (K450)...")
    simulator.serial._write_buffer.put(b"K450\n")
    time.sleep(2.0)  # Longer wait for position change
    
    # Read responses
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    print(f"Current position C: {simulator.position_c}")
    
    # Start jerking
    print("\nStarting jerking motion (J)...")
    simulator.serial._write_buffer.put(b"J\n")
    time.sleep(0.5)
    
    # Read responses
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    print(f"Jerking state: {simulator.is_jerking}")
    
    # Stop jerking
    print("\nStopping jerking motion (JS)...")
    simulator.serial._write_buffer.put(b"JS\n")
    time.sleep(0.5)
    
    # Read responses
    while simulator.serial.in_waiting > 0:
        line = simulator.serial.readline()
        print(f"Response: {line.decode('utf-8', errors='replace').strip()}")
    
    print(f"Jerking state: {simulator.is_jerking}")
    
    # Test error handling
    print("\nTesting error simulation...")
    simulator.set_error_rate(0.5)  # 50% error rate
    
    for i in range(5):
        print(f"Attempt {i+1}: Sending test command with error chance...")
        try:
            simulator.serial._write_buffer.put(b"T\n")
            time.sleep(0.2)
            
            # Try to read response (may fail)
            try:
                while simulator.serial.in_waiting > 0:
                    line = simulator.serial.readline()
                    print(f"  Response: {line.decode('utf-8', errors='replace').strip()}")
            except Exception as e:
                print(f"  Read error: {e}")
                
        except Exception as e:
            print(f"  Write error: {e}")
    
    # Reset error rate
    simulator.set_error_rate(0.0)
    
    # Clean up
    print("\nDisconnecting simulator...")
    simulator.disconnect()
    print("Simulator disconnected")
    
    print("\nTest completed successfully!")


if __name__ == "__main__":
    main()