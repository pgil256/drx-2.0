import sys
import time
import traceback
import threading
import serial
import logging
import os
import subprocess
from helpers.logging import setup_logger
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class Arduino(QObject):
    connection_ready = pyqtSignal()  # Signal for successful connection
    connection_failed = pyqtSignal(str)  # Signal for connection failure
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    done_emit = pyqtSignal()
    pressure_emit = pyqtSignal(str)
    ready_to_go_emit = pyqtSignal()
    position_emit = pyqtSignal(int, int, str, int)
    status_emit = pyqtSignal(int, int, int, float)
    buffer_warning = pyqtSignal(str)
    connection_lost = pyqtSignal()  # Signal for connection loss
    display_weight_emit = pyqtSignal(str)  # Added missing signal for weight display

    def __init__(self):
        super().__init__()
        self.logger = setup_logger(component="Arduino Communication")
        self.serial_com = None
        self.connected = False
        self._lock = threading.Lock() # Add this lock
        self.BUFFER_WARNING_THRESHOLD = 0.8  # 80% full
        self.ARDUINO_BUFFER_SIZE = 64  # Standard Arduino buffer size
        self._running = False
        self.ARDUINO_PORT = "/dev/serial0"
        self.ok_event = threading.Event() 

    def release_busy_port(self):
        """Attempt to release the serial0 port if busy"""
        try:
            port = self.ARDUINO_PORT
            print(f"Attempting to release busy port: {port}")

            # Check if port is busy using lsof
            result = subprocess.run(
                ["lsof", port], capture_output=True, text=True, check=False
            )

            if result.returncode == 0:  # Port is busy
                print(f"Port {port} is busy. Current users:")
                print(result.stdout)

                # Try to kill processes using fuser
                print(f"Attempting to kill processes using port {port}")
                subprocess.run(["fuser", "-k", port], check=False)

                # For serial0, stop getty service
                print("Stopping serial-getty@serial0.service")
                subprocess.run(
                    ["systemctl", "stop", "serial-getty@serial0.service"], check=False
                )

                # Wait for port to be released
                time.sleep(2)

                # Check if release was successful
                result = subprocess.run(
                    ["lsof", port], capture_output=True, text=True, check=False
                )
                if result.returncode == 0:
                    print(
                        f"Failed to release port {port}. Still in use by:"
                    )
                    print(result.stdout)
                    return False
                else:
                    print(f"Successfully released port {port}")
                    return True
            else:
                print(f"Port {port} is not busy")
                return True

        except Exception as e:
            print(f"Error attempting to release port {self.ARDUINO_PORT}: {e}")
            return False

    def reset_dtr(self):
        """Reset Arduino by toggling DTR line (simulates opening serial monitor)."""
        try:
            if not self.serial_com:
                return False

            print("Resetting Arduino via DTR...")

            # Save current DTR state
            original_dtr = self.serial_com.dtr

            # Toggle DTR
            self.serial_com.dtr = False
            time.sleep(0.1)  # Brief delay
            self.serial_com.dtr = True
            time.sleep(5)  # Allow Arduino to initialize

            # Restore original DTR state
            self.serial_com.dtr = original_dtr

            return True

        except Exception as e:
            print(f"Error resetting Arduino: {e}")
            return False


    def disconnect(self):
        """Forcefully closes the current serial connection if open."""
        with self._lock:
            if self.serial_com:
                print("Forcefully closing existing serial connection")
                try:
                    # Stop the reader thread *before* closing the port
                    self._running = False
                    time.sleep(0.1) # Give thread a moment to exit loop

                    self.serial_com.close()
                    print("Serial connection closed successfully.")
                    time.sleep(1)  # Give system time to reset port (can be shorter now)
                except Exception as ex:
                    print(f"Error closing the serial port: {ex}")
                finally:
                    # Ensure these are reset even if close fails
                    self.serial_com = None
                    self.connected = False
                    # Don't reset self._running here if it's controlled by the reader thread loop condition
            else:
                 # If no serial_com object, ensure flags are false
                 self._running = False
                 self.connected = False

        # --- REMOVE THE RECONNECT CALL ---
        # self.reconnect()

    @pyqtSlot()
    def verify_connection(self, tries=3, timeout_s=10.0):
        """
        1. Runs both during initial connect *and* from inside the reader loop.
        2. Never resets the input buffer after sending 'T' (prevents eating the reply).
        3. Uses a single blocking readline() with a per-call timeout = deadline.
        4. Holds self._lock only around the WRITE, so other threads can’t interleave.
        """
        if not self.serial_com or not self.serial_com.is_open:
            return False

        for n in range(tries):
            self.ok_event.clear()   
            with self._lock:
                self.serial_com.reset_input_buffer()   # flush junk *before* we talk
                self.serial_com.write(b"T\n")
                self.serial_com.flush()
            if self.ok_event.wait(timeout_s):  
                print(f"Sent OK on attempt {n+1}")
                return True
            print(f"No OK on attempt {n+1}")
            time.sleep(0.5)
        return False



    def connect_to_arduino(self, max_retries=3, retry_delay=3, emit_connection_failed=True):
        """
        Unified method to establish Arduino connection with retries.
        
        Args:
            max_retries: Number of connection attempts before giving up
            retry_delay: Delay in seconds between retry attempts
            emit_connection_failed: Whether to emit connection_failed signal on failure
            
        Returns:
            bool: True if connection was established, False otherwise
        """
        for attempt in range(1, max_retries + 1):
            print(f"Connection attempt {attempt}/{max_retries} to {self.ARDUINO_PORT}")
            
            # Check if port exists
            if not os.path.exists(self.ARDUINO_PORT):
                print(f"Port {self.ARDUINO_PORT} does not exist")
                if emit_connection_failed:
                    self.connection_failed.emit(f"Port {self.ARDUINO_PORT} not found")
                time.sleep(retry_delay)
                continue
                
            try:
                # Close any existing connection
                self.disconnect()
                time.sleep(1)
                
                # Release port if busy
                self.release_busy_port()

                # Open new connection
                self.serial_com = serial.Serial(self.ARDUINO_PORT, 115200, timeout=10, write_timeout=1)
                time.sleep(5)  # Wait for Arduino initialization

                # Reset Arduino via DTR
                if not self.reset_dtr():
                    print("DTR reset failed")

                if not self._running:               
                    self._running = True
                    threading.Thread(target=self.read_from_com,
                                    daemon=True).start()

                # Verify Arduino responds after reset
                self.verify_connection(tries=3, timeout_s=10.0)

                # Verify connection
                if self.verify_connection():
                    print(f"Connected to Arduino on {self.ARDUINO_PORT}")
                    self.connected = True
                    self._running = True
                    # Successfully connected
                    self.connection_ready.emit()
                    return True
                    
                # Clean up failed connection
                self.disconnect()
                
            except Exception as e:
                print(f"Connection attempt to {self.ARDUINO_PORT} failed: {e}")
                self.disconnect()
            
            # Wait before next attempt
            time.sleep(retry_delay)
            
        # All attempts failed
        print(f"Failed to establish Arduino connection after {max_retries} attempts")
        if emit_connection_failed:
            self.connection_failed.emit(f"Failed to connect to {self.ARDUINO_PORT} after {max_retries} attempts")
        return False
        
    def reconnect(self, max_retries=3): # Accept argument, default to 3
        """Attempt to reestablish Arduino connection if lost."""
        print("Attempting to reconnect to Arduino...")
        # *** USE THE ARGUMENT HERE ***
        return self.connect_to_arduino(max_retries=max_retries, emit_connection_failed=False)
        
    def run(self):
        """Connect to Arduino and start reading data."""
        self.connect_to_arduino()

            
    # Keeping compatibility with old method name
    def try_connect(self):
        """Try to connect to serial0 (compatibility method)."""
        return self.connect_to_arduino(max_retries=1, emit_connection_failed=False)

    def monitor_buffer(self):
        if not self.serial_com:
            return

        try:
            in_waiting = self.serial_com.in_waiting
            in_buffer_usage = in_waiting / self.ARDUINO_BUFFER_SIZE

            # Only check output buffer if input is OK
            if in_buffer_usage <= self.BUFFER_WARNING_THRESHOLD:
                out_waiting = self.serial_com.out_waiting
                out_buffer_usage = out_waiting / self.ARDUINO_BUFFER_SIZE

                if out_buffer_usage > self.BUFFER_WARNING_THRESHOLD:
                    warning = f"Output buffer at {out_buffer_usage*100:.1f}% capacity"
                    self.buffer_warning.emit(warning)
                    print(warning)

            # Emergency flush if input buffer critical
            if in_buffer_usage > 0.9:
                self.serial_com.reset_input_buffer()
                print("Emergency input buffer flush performed")

        except Exception as ex:
            print(f"Buffer monitoring error: {ex}")
            self.connection_failed.emit(str(ex))

    def read_from_com(self):
        """Continuously reads data from the serial connection."""
        print("Starting to read from serial communication")
        last_data_time = time.time()

        while self._running and self.serial_com and self.serial_com.is_open:
            try:
                # Monitor buffer before reading
                self.monitor_buffer()

                # Check for connection timeout (no data received in 120 seconds)
                current_time = time.time()
                if current_time - last_data_time > 120:
                    print("Connection timeout: No data received in 120 seconds. Verifying connection...")
                    
                    # Try to send a test command directly
                    try:
                        with self._lock:
                            self.serial_com.reset_input_buffer()
                            self.serial_com.write(b"T\n")
                            self.serial_com.flush()
                        print("Sent direct test command")
                        
                        # Update last_data_time to give more time for a response
                        last_data_time = current_time - 60  # Give 60 more seconds
                        continue  # Skip verification for now and check again later
                        
                    except Exception as test_err:
                        print(f"Error sending test command: {test_err}")
                    
                    # Only verify connection if direct test failed
                    if not self.verify_connection():
                        print("Connection verification failed. Connection is lost.")
                        
                        # Try reconnecting once before giving up
                        print("Attempting emergency reconnect...")
                        if self.reconnect(max_retries=1):
                            print("Emergency reconnect successful!")
                            last_data_time = time.time()  # Reset timer
                            continue
                        
                        # If reconnect failed, signal loss
                        self.connected = False
                        self.connection_lost.emit()
                        self.connection_failed.emit("Connection timeout (verification failed)")
                        break
                    else:
                        print("Connection verified after timeout. Resetting timeout timer.")
                        last_data_time = current_time  # Reset the timer since connection is actually OK

                if self.serial_com and self.serial_com.in_waiting > 0:
                    try:
                        data = (
                            self.serial_com.readline().decode(errors="replace").strip()
                        )
                        last_data_time = time.time()  # Update last data time

                        if len(data) > 0:
                            print(f"Raw received data: {data}")
                            self.handle_com(data)
                    except Exception as e:
                        print(f"Error reading data: {e}")
                else:
                    time.sleep(0.01)

            except serial.SerialException as ex:
                print(f"Serial connection error: {ex}")
                self.connected = False
                self.connection_lost.emit()
                break
            except Exception as ex:
                print(f"Unexpected error in read loop: {ex}")
                # Try to continue, but mark time so we don't timeout
                last_data_time = time.time()

    def handle_com(self, data):
        """Handles incoming serial messages."""
        try:
            # Handle STATUS_START format messages
            if "STATUS_START|" in data:
                try:
                    # Extract data between markers
                    if "|STATUS_END" in data:
                        status_data = data.replace("STATUS_START|", "").replace(
                            "|STATUS_END", ""
                        )

                    else:
                        # Handle truncated message
                        status_data = data.replace("STATUS_START|", "")
                        print(f"Warning: Truncated status message: {status_data}")

                    tokens = status_data.split("|")

                    if tokens[0] == "S" and len(tokens) >= 5:
                        pos_a = int(tokens[1])
                        pos_b = int(tokens[2])
                        pos_c = int(tokens[3])
                        pressure = float(tokens[4])

                        # Emit status signal with explicit type conversion
                        self.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))
                        print(f"Emitting status: A {pos_a} B {pos_b} C {pos_c} Pressure {pressure}")
                        
                        # Send acknowledgment to Arduino that we processed the status
                        if self.connected and self.serial_com:
                            try:
                                # Use with lock to ensure exclusive access to serial port
                                with self._lock:
                                    self.serial_com.write(b"Q\n")
                                    self.serial_com.flush()
                                    time.sleep(0.1)  # Small delay to ensure flush completes
                                print("Status acknowledgment sent")
                            except Exception as ack_err:
                                print(f"ERROR sending acknowledgment: {ack_err}")
                        else:
                            print("Cannot send status acknowledgment - not connected")
                        return
                except Exception as e:
                    print(f"Error parsing status data: {e}")
                    return

            # Handle regular messages
            tokens = data.split("|")

            if tokens[0] == "DONE":
                self.done_emit.emit()
            elif tokens[0] == "P":
                self.position_emit.emit(int(tokens[1]), 0, "", 0)
            elif tokens[0] == "PR":
                self.pressure_emit.emit(tokens[1])
            elif tokens[0] == "E":
                self.position_emit.emit(
                    int(tokens[1]), int(tokens[2]), tokens[3], int(tokens[4])
                )
            elif tokens[0] == "S" and len(tokens) >= 5:
                self.status_emit.emit(
                    int(tokens[1]), int(tokens[2]), int(tokens[3]), float(tokens[4])
                )
            elif tokens[0] == "Ready to Go" or "Ready to Go" in data:
                self.ready_to_go_emit.emit()
            elif tokens[0] == "weight":
                self.display_weight_emit.emit(tokens[1])
            elif (
                tokens[0] == "Test command received" or "Test command received" in data
            ):
                print("Arduino acknowledged test command")
            elif "OK" in tokens[0] or tokens[0] == "OK":
                self.ok_event.set()    
                print("Arduino sent OK acknowledgment")
            else:
                print(f"Unrecognized data format: {data}")
        except Exception as ex:
            print(f"Error handling data '{data}': {ex}")

    def send(self, command):
        """Send a command to the Arduino with reconnection capability."""
        with self._lock:
            # Check connection first
            if not self.connected or not self.serial_com:
                print("Not connected - attempting to reconnect")
                if not self.reconnect(max_retries=3):
                    print("Cannot send command - not connected")
                    return False

            try:
                if not self.serial_com:  # Double-check after reconnect
                    return False

                self.serial_com.reset_input_buffer()
                command_with_newline = command + "\n"
                # Only log the command being sent once
                self.serial_com.write(command_with_newline.encode())
                self.serial_com.flush()
                time.sleep(0.3)  # Increased from 0.1 to give more time for flush
                # Remove redundant success message to reduce log noise
                return True

            except Exception as ex:
                print(f"Failed to send command '{command}': {ex}")
                self.connected = False  # Mark as disconnected
                self.connection_lost.emit()  # Signal that connection was lost
                return False