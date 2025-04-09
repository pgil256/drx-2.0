"""
Arduino Simulator for KneeSpa Testing.

This module provides simulation capabilities for testing Arduino communication
without requiring physical hardware.
"""
import threading
import time
import queue
import re
import random
from typing import Dict, List, Optional, Callable, Tuple, Union


class MockSerial:
    """Mocks the pyserial Serial class with configurable behavior."""
    
    def __init__(self, port: str, baudrate: int, timeout: int = 10, write_timeout: int = 1):
        """Initialize a mock serial connection.
        
        Args:
            port: Simulated port name
            baudrate: Baud rate (unused in simulation)
            timeout: Read timeout in seconds
            write_timeout: Write timeout in seconds
        """
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
        self._simulate_errors = False
        self._error_rate = 0.0
        self._disconnect_after = None
        self._dropped_bytes_rate = 0.0
        
    def write(self, data: bytes) -> int:
        """Write data to the mock serial port.
        
        Args:
            data: Bytes to write
            
        Returns:
            Number of bytes written
            
        Raises:
            serial.SerialException: If simulation is configured to raise errors
        """
        if self._should_fail():
            from serial.serialutil import SerialException
            raise SerialException("Simulated write error")
        
        # Simulate dropped bytes
        if random.random() < self._dropped_bytes_rate:
            # Drop some bytes
            data = data[:len(data)//2]
        
        self._write_buffer.put(data)
        self.out_waiting = self._write_buffer.qsize()
        return len(data)
        
    def read(self, size: int = 1) -> bytes:
        """Read data from the mock serial port.
        
        Args:
            size: Number of bytes to read
            
        Returns:
            Bytes read
            
        Raises:
            serial.SerialException: If simulation is configured to raise errors
        """
        if self._should_fail():
            from serial.serialutil import SerialException
            raise SerialException("Simulated read error")
            
        result = b""
        for _ in range(min(size, self._read_buffer.qsize())):
            try:
                result += self._read_buffer.get_nowait()
            except queue.Empty:
                break
                
        self.in_waiting = self._read_buffer.qsize()
        return result
        
    def readline(self) -> bytes:
        """Read a line from the mock serial port.
        
        Returns:
            A line of bytes (up to and including newline)
            
        Raises:
            serial.SerialException: If simulation is configured to raise errors
        """
        if self._should_fail():
            from serial.serialutil import SerialException
            raise SerialException("Simulated readline error")
            
        # Try to find a complete line in the buffer
        result = b""
        start_time = time.time()
        
        while True:
            try:
                byte = self._read_buffer.get(timeout=0.1)
                result += byte
                
                # If we have a complete line, return it
                if byte == b'\n':
                    break
                    
            except queue.Empty:
                # If we've been reading for longer than the timeout, return what we have
                if time.time() - start_time > self.timeout:
                    break
                continue
                
            # Check if we've been disconnected during reading
            if self._disconnect_after is not None and time.time() > self._disconnect_after:
                from serial.serialutil import SerialException
                raise SerialException("Simulated disconnect during read")
                
        self.in_waiting = self._read_buffer.qsize()
        return result
        
    def close(self) -> None:
        """Close the mock serial port."""
        self.is_open = False
        
    def flush(self) -> None:
        """Flush the write buffer."""
        pass
        
    def reset_input_buffer(self) -> None:
        """Clear the input buffer."""
        while not self._read_buffer.empty():
            self._read_buffer.get()
        self.in_waiting = 0
        
    def reset_output_buffer(self) -> None:
        """Clear the output buffer."""
        while not self._write_buffer.empty():
            self._write_buffer.get()
        self.out_waiting = 0
            
    def _put_data_in_buffer(self, data: bytes) -> None:
        """Add data to the read buffer to simulate received data.
        
        Args:
            data: Bytes to add to the read buffer
        """
        for b in data:
            self._read_buffer.put(bytes([b]))
        self.in_waiting = self._read_buffer.qsize()
        
    def _get_written_data(self) -> bytes:
        """Get data written to the port.
        
        Returns:
            Bytes that were written to the port
        """
        data = b""
        while not self._write_buffer.empty():
            data += self._write_buffer.get()
        self.out_waiting = 0
        return data
        
    def _should_fail(self) -> bool:
        """Determine if an operation should fail based on error settings.
        
        Returns:
            True if the operation should fail
        """
        if not self._simulate_errors:
            return False
            
        if self._disconnect_after is not None and time.time() > self._disconnect_after:
            return True
            
        return random.random() < self._error_rate
        
    def set_error_rate(self, rate: float) -> None:
        """Set the rate at which operations will fail.
        
        Args:
            rate: Failure rate from 0.0 to 1.0
        """
        self._simulate_errors = rate > 0
        self._error_rate = max(0.0, min(1.0, rate))
        
    def set_disconnect_after(self, seconds: Optional[float]) -> None:
        """Configure the connection to simulate disconnection after a time period.
        
        Args:
            seconds: Number of seconds after which to simulate disconnect,
                    or None to disable disconnect simulation
        """
        if seconds is not None:
            self._disconnect_after = time.time() + seconds
        else:
            self._disconnect_after = None
            
    def set_dropped_bytes_rate(self, rate: float) -> None:
        """Set the rate at which bytes will be dropped during write.
        
        Args:
            rate: Drop rate from 0.0 to 1.0
        """
        self._dropped_bytes_rate = max(0.0, min(1.0, rate))


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
        self.jerk_count = 0
        
        # Command handlers
        self.command_handlers = {
            r'^T': self._handle_test,
            r'^S': self._handle_status,
            r'^Q': self._handle_ack,
            r'^P(\d+)': self._handle_pressure,
            r'^K(\d+)': self._handle_angle,
            r'^X': self._handle_stop,
            r'^G(\d+)': self._handle_get_position,
            r'^J$': self._handle_jerk_start,
            r'^JS': self._handle_jerk_stop,
        }
        
    def connect(self, port: str = "MOCK", baudrate: int = 115200,
                timeout: int = 10, write_timeout: int = 1) -> None:
        """Create a mock serial connection.
        
        Args:
            port: Mock port name
            baudrate: Baud rate (unused in simulation)
            timeout: Read timeout
            write_timeout: Write timeout
        """
        self.serial = MockSerial(port, baudrate, timeout, write_timeout)
        
        # Send initial ready message
        self.serial._put_data_in_buffer(b"Ready to Go\n")
        
        # Start response thread
        self._running = True
        self.response_thread = threading.Thread(target=self._process_commands)
        self.response_thread.daemon = True
        self.response_thread.start()
        
    def disconnect(self) -> None:
        """Disconnect the simulator."""
        self._running = False
        if self.response_thread:
            self.response_thread.join(timeout=1.0)
            self.response_thread = None
            
        if self.serial:
            self.serial.close()
            self.serial = None
            
    def _process_commands(self) -> None:
        """Process commands from the serial port and generate responses."""
        while self._running and self.serial and self.serial.is_open:
            try:
                # Check if any data has been written
                data = self.serial._get_written_data()
                if data:
                    # Process the command
                    self._handle_command(data.decode('utf-8', errors='replace'))
                    
                # Periodically update status if jerking
                if self.is_jerking and random.random() < 0.1:
                    self._simulate_jerk()
                    
                # Don't burn CPU
                time.sleep(0.01)
                
            except Exception as e:
                print(f"Error in Arduino simulator: {e}")
                
    def _handle_command(self, command: str) -> None:
        """Process a command and generate appropriate response.
        
        Args:
            command: Command string from the serial port
        """
        command = command.strip()
        if not command:
            return
            
        # Try to match the command with handlers
        for pattern, handler in self.command_handlers.items():
            match = re.match(pattern, command)
            if match:
                handler(*match.groups())
                return
                
        # If no handler matched, reply with an empty response
        print(f"Unhandled command: {command}")
        time.sleep(0.1)  # Simulate processing time
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_test(self) -> None:
        """Handle test command."""
        time.sleep(0.1)  # Simulate processing time
        self.serial._put_data_in_buffer(b"Test command received\n")
        self.serial._put_data_in_buffer(b"OK\n")
        
    def _handle_status(self) -> None:
        """Send status information."""
        time.sleep(0.2)  # Simulate processing time
        
        # Generate a status message
        status = f"STATUS_START|S|{self.position_a}|{self.position_b}|{self.position_c}|{self.pressure}|STATUS_END\n"
        self.serial._put_data_in_buffer(status.encode('utf-8'))
        
    def _handle_ack(self) -> None:
        """Handle acknowledgment command."""
        # No response needed
        pass
        
    def _handle_pressure(self, pressure: str) -> None:
        """Handle pressure command.
        
        Args:
            pressure: Target pressure value
        """
        target_pressure = float(pressure)
        
        # Simulate pressure change gradually
        start_pressure = self.pressure
        steps = 5
        
        for i in range(1, steps + 1):
            time.sleep(0.2)  # Simulate time to change pressure
            self.pressure = start_pressure + (target_pressure - start_pressure) * (i / steps)
            
            # Periodically send status updates during pressure change
            if i % 2 == 0 or i == steps:
                self._handle_status()
                
        time.sleep(0.5)  # Final delay
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_angle(self, position: str) -> None:
        """Handle angle position command.
        
        Args:
            position: Target position value
        """
        target_position = int(position)
        start_position = self.position_c
        steps = 5
        
        for i in range(1, steps + 1):
            time.sleep(0.3)  # Simulate time to change position
            self.position_c = start_position + (target_position - start_position) * (i / steps)
            
            # Periodically send status updates during position change
            if i % 2 == 0 or i == steps:
                self._handle_status()
                
        time.sleep(0.5)  # Final delay
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_stop(self) -> None:
        """Handle emergency stop command."""
        self.is_jerking = False
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_get_position(self, device: str) -> None:
        """Handle get position command.
        
        Args:
            device: Device number (12, 13, or 14)
        """
        device_num = int(device)
        position = 0
        
        if device_num == 12:
            position = self.position_a
        elif device_num == 13:
            position = self.position_b
        elif device_num == 14:
            position = self.position_c
            
        time.sleep(0.2)  # Simulate processing time
        response = f"P|{position}\n"
        self.serial._put_data_in_buffer(response.encode('utf-8'))
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_jerk_start(self) -> None:
        """Handle start jerking command."""
        self.is_jerking = True
        self.jerk_count = 0
        time.sleep(0.1)  # Simulate processing time
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _handle_jerk_stop(self) -> None:
        """Handle stop jerking command."""
        self.is_jerking = False
        time.sleep(0.1)  # Simulate processing time
        self.serial._put_data_in_buffer(b"DONE\n")
        
    def _simulate_jerk(self) -> None:
        """Simulate a jerking motion by changing position values."""
        jerk_amount = random.randint(5, 15)
        self.position_a += jerk_amount if self.jerk_count % 2 == 0 else -jerk_amount
        self.jerk_count += 1
        
        # Periodically send status during jerking
        if self.jerk_count % 3 == 0:
            self._handle_status()
            
    def set_error_conditions(self, error_rate: float = 0.0, 
                            disconnect_after: Optional[float] = None,
                            dropped_bytes_rate: float = 0.0) -> None:
        """Configure error simulation.
        
        Args:
            error_rate: Rate at which operations will fail (0.0 to 1.0)
            disconnect_after: Seconds after which to simulate disconnect, or None
            dropped_bytes_rate: Rate at which bytes will be dropped (0.0 to 1.0)
        """
        if self.serial:
            self.serial.set_error_rate(error_rate)
            self.serial.set_disconnect_after(disconnect_after)
            self.serial.set_dropped_bytes_rate(dropped_bytes_rate)
            
    def set_device_state(self, position_a: Optional[int] = None,
                        position_b: Optional[int] = None,
                        position_c: Optional[int] = None,
                        pressure: Optional[float] = None) -> None:
        """Set the simulated device state.
        
        Args:
            position_a: Position of actuator A
            position_b: Position of actuator B
            position_c: Position of actuator C
            pressure: Current pressure value
        """
        if position_a is not None:
            self.position_a = position_a
        if position_b is not None:
            self.position_b = position_b
        if position_c is not None:
            self.position_c = position_c
        if pressure is not None:
            self.pressure = pressure


def create_arduino_simulator() -> ArduinoSimulator:
    """Create and connect an Arduino simulator.
    
    Returns:
        A connected ArduinoSimulator instance
    """
    simulator = ArduinoSimulator()
    simulator.connect()
    return simulator