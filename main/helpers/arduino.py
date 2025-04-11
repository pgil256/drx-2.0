import sys
import time
import traceback
import serial
import logging
import os
import subprocess
from utils.logging import setup_logger
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class Arduino(QObject):
    connection_ready = pyqtSignal()  # New signal for successful connection
    connection_failed = pyqtSignal(str)  # New signal for connection failure
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    done_emit = pyqtSignal()
    pressure_emit = pyqtSignal(str)
    ready_to_go_emit = pyqtSignal()
    position_emit = pyqtSignal(int, int, str, int)
    status_emit = pyqtSignal(int, int, int, float)
    axial_status_emit = pyqtSignal(int, int, int, float)
    int_ready = pyqtSignal(int)
    display_weight_emit = pyqtSignal(str)
    buffer_warning = pyqtSignal(str)
    connection_lost = pyqtSignal()  # New signal for connection loss

    def __init__(self):
        super().__init__()
        self.logger = setup_logger(component="Arduino Communication")
        self.serial_com = None
        self.connected = False
        self.BUFFER_WARNING_THRESHOLD = 0.8  # 80% full
        self.ARDUINO_BUFFER_SIZE = 64  # Standard Arduino buffer size
        self._running = False
        self.current_port = None

    def release_busy_port(self, port):
        """Attempt to release a busy port by killing processes"""
        try:
            self.logger.info(f"Attempting to release busy port: {port}")

            # Check if port is busy using lsof
            result = subprocess.run(
                ["lsof", port], capture_output=True, text=True, check=False
            )

            if result.returncode == 0:  # Port is busy
                self.logger.info(f"Port {port} is busy. Current users:")
                self.logger.info(result.stdout)

                # Try to kill processes using fuser
                self.logger.info(f"Attempting to kill processes using port {port}")
                subprocess.run(["fuser", "-k", port], check=False)

                # If port is ttyS0, also try stopping getty service
                if port == "/dev/ttyS0":
                    self.logger.info("Stopping serial-getty@ttyS0.service")
                    subprocess.run(
                        ["systemctl", "stop", "serial-getty@ttyS0.service"], check=False
                    )

                # Wait for ports to be released
                time.sleep(2)

                # Check if release was successful
                result = subprocess.run(
                    ["lsof", port], capture_output=True, text=True, check=False
                )
                if result.returncode == 0:
                    self.logger.warning(
                        f"Failed to release port {port}. Still in use by:"
                    )
                    self.logger.warning(result.stdout)
                    return False
                else:
                    self.logger.info(f"Successfully released port {port}")
                    return True
            else:
                self.logger.info(f"Port {port} is not busy")
                return True

        except ArduinoCommandError as e:
            print(f"Error attempting to release port {port}: {e}")
            return False
        except Exception as e:
            from utils.exceptions import ArduinoException
            print(f"Error attempting to release port {port}: {e}")
            return False

    def disconnect(self):
        """Forcefully closes the current serial connection if open."""
        try:
            print("Forcefully closing existing serial connection")
            # Indicate we're not connected first to stop any ongoing read operations
            self.connected = False
            
            # Safely close the serial connection if it exists
            if self.serial_com:
                try:
                    # Only try to close if the port is still open
                    if hasattr(self.serial_com, 'is_open') and self.serial_com.is_open:
                        self.serial_com.close()
                        print("Serial connection closed successfully.")
                    else:
                        print("Serial port was already closed.")
                except serial.SerialException as ex:
                    print(f"Error closing the serial port: {ex}")
                except Exception as ex:
                    from utils.exceptions import ArduinoConnectionError
                    error = ArduinoConnectionError(f"Error closing the serial port: {ex}")
                    print(f"Error closing the serial port: {error}")
                finally:
                    # Always clear the reference even if errors occur
                    self.serial_com = None
                    time.sleep(1)  # Reduced from 2 to 1 second
        except Exception as ex:
            print(f"Unexpected error in disconnect: {ex}")
        finally:
            # Always make sure these are reset
            self.serial_com = None
            self.connected = False
            self.current_port = None

    @pyqtSlot()
    def verify_connection(self):
        """Verify Arduino communication is working."""
        tries = 0
        max_tries = 4  # Increased max tries

        # Debug buffer state at start
        try:
            if self.serial_com:
                print(
                    f"Buffer state before verify: in_waiting={self.serial_com.in_waiting}"
                )
        except serial.SerialException:
            pass
        except Exception:
            pass

        while tries < max_tries:
            try:
                if not self.serial_com:
                    return False

                # Thoroughly clear any pending data
                self.serial_com.reset_input_buffer()
                self.serial_com.reset_output_buffer()
                time.sleep(1)  # Longer time for buffers to clear

                # Read and discard any leftover data
                while self.serial_com.in_waiting > 0:
                    self.serial_com.read(self.serial_com.in_waiting)
                time.sleep(0.5)

                print(f"Verifying connection (attempt {tries + 1}/{max_tries})")

                # Send test command multiple times to increase chance of response
                for _ in range(2):
                    self.serial_com.write(b"T\n")
                    self.serial_com.flush()
                    time.sleep(0.2)  # Small delay between command repeats

                print("Test command sent, waiting for response...")

                # Wait for response with timeout (longer timeout)
                start_time = time.time()
                response_buffer = ""

                while time.time() - start_time < 3:  # 3 second timeout per try
                    if self.serial_com.in_waiting:
                        response = (
                            self.serial_com.readline().decode(errors="replace").strip()
                        )
                        print(f"Raw response: '{response}' (length: {len(response)})")

                        # Accept both "OK" and "Ready to Go" as valid responses
                        if (
                            response == "OK"
                            or "Ready to Go" in response
                            or "Test command received" in response
                        ):
                            print(f"Valid response from Arduino: {response}")
                            print("Arduino SoftwareSerial communication verified")
                            return True

                        response_buffer += response + " | "
                    time.sleep(0.1)

                print(f"No valid response received. Buffer contents: {response_buffer}")
                tries += 1
                time.sleep(1)  # Longer wait between attempts

            except serial.SerialException as e:
                print(f"Serial error during verification attempt {tries + 1}: {e}")
                tries += 1
                time.sleep(1)
            except Exception as e:
                from utils.exceptions import ArduinoCommandError
                error = ArduinoCommandError(f"Verification attempt {tries + 1} failed: {e}")
                print(f"Verification attempt {tries + 1} failed: {error}")
                tries += 1
                time.sleep(1)

        return False

    def reconnect(self):
        """Attempt to reestablish Arduino connection if lost."""
        print("Attempting to reconnect to Arduino...")

        # Use only ttyS0 for Raspberry Pi hardware serial to Arduino
        port = "/dev/ttyS0"
        
        if os.path.exists(port):
            # Try reconnection up to 3 times
            for attempt in range(3):
                print(f"Reconnection attempt {attempt+1}/3")
                if self.try_connect_to_port(port):
                    print("Successfully reconnected to Arduino")
                    # Emergency stop immediately after reconnection for safety
                    try:
                        print("Sending emergency stop after reconnection for safety")
                        self.send("X")  # Stop all movements
                        time.sleep(0.5)  # Wait for command to process
                        return True
                    except Exception as e:
                        print(f"Warning: Failed to send emergency stop: {e}")
                        # Continue anyway since we did reconnect
                        return True
                time.sleep(2)  # Wait between attempts
        else:
            print(f"Serial port {port} does not exist")
            
        print("Failed to reconnect to Arduino")
        return False

    def try_connect_to_port(self, port):
        """Try to connect to a specific port."""
        try:
            print(f"Attempting connection to {port}")

            # Close existing connection
            self.disconnect()
            time.sleep(1)

            # Release port if busy
            self.release_busy_port(port)

            # Open new connection
            self.serial_com = serial.Serial(port, 115200, timeout=10, write_timeout=1)
            print(f"Opened serial connection to {port} at 115200 baud")
            time.sleep(5)  # Wait for Arduino initialization

            # Verify connection
            if self.verify_connection():
                print(f"Successfully connected to Arduino on {port}")
                print("Communication with Arduino SoftwareSerial established")
                self.connected = True
                self._running = True
                self.current_port = port
                return True

            self.disconnect()
            return False

        except serial.SerialException as e:
            from utils.exceptions import ArduinoConnectionError
            error = ArduinoConnectionError(f"Serial connection error to {port}: {e}")
            print(f"Connection attempt to {port} failed: {error}")
            self.disconnect()
            return False
        except Exception as e:
            from utils.exceptions import ArduinoConnectionError
            error = ArduinoConnectionError(f"Connection attempt to {port} failed: {e}")
            print(f"Connection attempt to {port} failed: {error}")
            self.disconnect()
            return False

    def run(self):
        max_retries = 3
        retry_delay = 3  # Increased from 2

        # Only use ttyS0 for direct Raspberry Pi hardware serial to Arduino SoftwareSerial
        port = "/dev/ttyS0"

        for attempt in range(1, max_retries + 1):
            print(f"Attempting Arduino connection on {port} (attempt {attempt}/{max_retries})")
            
            if os.path.exists(port):
                if self.try_connect_to_port(port):
                    # Start reading loop
                    self.read_from_com()
                    return
            else:
                print(f"Serial port {port} does not exist")
                
            # Wait before next attempt
            time.sleep(retry_delay)

        print(f"Failed to establish Arduino connection on {port} after {max_retries} attempts")
        self.connection_failed.emit("Failed to establish connection")

    def monitor_buffer(self):
        """Monitor serial buffer usage with improved error handling."""
        # If serial_com is None or we're not connected, exit early
        if not self.serial_com or not self.connected:
            return

        try:
            # Verify the serial port is still open before accessing
            if not hasattr(self.serial_com, 'is_open') or not self.serial_com.is_open:
                # The port is closed but we still have a reference; reset it
                print("Serial port is closed but still referenced in monitor_buffer")
                self.serial_com = None
                self.connected = False
                return
                
            # Now safely check buffer levels
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
            except (OSError, IOError) as ex:
                # Common errors when the file descriptor is invalid
                print(f"Serial port error during buffer monitoring: {ex}")
                self.serial_com = None
                self.connected = False
                
        except Exception as ex:
            print(f"Buffer monitoring error: {ex}")
            # Don't emit connection_failed for every error - only for serious ones
            if "Bad file descriptor" in str(ex) or "argument must be an int" in str(ex):
                print("Serial connection appears broken - marking as disconnected")
                self.serial_com = None
                self.connected = False
            else:
                self.connection_failed.emit(str(ex))

    def read_from_com(self):
        """Continuously reads data from the serial connection with improved error handling."""
        print("Starting to read from serial communication")
        last_data_time = time.time()
        last_status_request = time.time()  # Track when we last requested a status update
        error_count = 0  # Track consecutive errors

        # Main reading loop
        while self.connected and self.serial_com:
            # Guard against too many errors
            if error_count > 5:
                print("Too many consecutive errors, breaking serial communication loop")
                self.connected = False
                self.connection_lost.emit()
                break
                
            try:
                # First verify that the serial port is valid and open
                if not hasattr(self.serial_com, 'is_open') or not self.serial_com.is_open:
                    print("Serial port is closed but still referenced in read_from_com")
                    self.serial_com = None
                    self.connected = False
                    break
                    
                # Monitor buffer before reading (wrapped in try to catch file descriptor errors)
                try:
                    self.monitor_buffer()
                except Exception as buffer_ex:
                    print(f"Error in buffer monitoring (non-fatal): {buffer_ex}")
                    # Don't break the loop here, continue trying to read

                # Request a status update every 15 seconds if no other data received
                # This keeps the connection alive and provides regular feedback
                current_time = time.time()
                if current_time - last_status_request > 15:
                    try:
                        if self.serial_com and self.serial_com.is_open:
                            # Request status update with "S" command
                            self.serial_com.write(b"S\n")
                            self.serial_com.flush()
                            print("Requesting status update to keep connection alive")
                            last_status_request = current_time
                    except Exception as status_ex:
                        print(f"Failed to request status update: {status_ex}")

                # Check for connection timeout (no data received in 2 minutes)
                # We're being more generous with timeout since we're actively requesting status
                if current_time - last_data_time > 120:
                    print("Connection timeout: No data received in 2 minutes")
                    self.connected = False
                    self.connection_lost.emit()
                    self.connection_failed.emit("Connection timeout")
                    break

                # Only try to read if we still have a valid connection
                if self.connected and self.serial_com and hasattr(self.serial_com, 'in_waiting'):
                    try:
                        # Non-blocking check for data
                        if self.serial_com.in_waiting > 0:
                            data = self.serial_com.readline().decode(errors="replace").strip()
                            last_data_time = time.time()  # Update last data time
                            error_count = 0  # Reset error count on successful read

                            if len(data) > 0:
                                print(f"Raw received data: {data}")
                                self.handle_com(data)
                        else:
                            # No data to read, just sleep a bit
                            time.sleep(0.01)
                    except (serial.SerialException, OSError, IOError) as read_ex:
                        print(f"Error reading from serial port: {read_ex}")
                        error_count += 1
                        time.sleep(0.1)  # Brief delay to avoid tight error loop
                    except Exception as e:
                        print(f"Unexpected error reading data: {e}")
                        error_count += 1
                else:
                    # Invalid serial state, break the loop
                    print("Serial connection invalid during read operation")
                    self.connected = False
                    break

            except serial.SerialException as ex:
                print(f"Serial connection exception: {ex}")
                self.connected = False
                self.connection_lost.emit()
                break
            except (OSError, IOError) as io_ex:
                # File descriptor errors
                print(f"I/O error in serial read loop: {io_ex}")
                error_count += 1
                if "Bad file descriptor" in str(io_ex):
                    self.connected = False
                    break
            except Exception as ex:
                print(f"Unexpected error in read loop: {ex}")
                error_count += 1
                # If we can continue, do so but mark time so we don't timeout
                last_data_time = time.time()
                
        print("Exited serial read loop")

    def handle_com(self, data):
        """Handles incoming serial messages."""
        try:
            # Check if we have a pending command to execute after calibration
            if "STATUS_START|" in data and hasattr(self, '_pending_command') and self._pending_command:
                # Only execute pending command if we're getting calibrated pressure readings
                # This indicates calibration is complete
                if "|STATUS_END" in data and "-0." in data:
                    pending_cmd = self._pending_command
                    self._pending_command = None
                    print(f"Calibration complete, executing pending command: {pending_cmd}")
                    # Small delay to ensure Arduino is ready
                    time.sleep(0.5)
                    # Execute the previously stored command
                    self.send(pending_cmd)
            
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

                        self.status_emit.emit(pos_a, pos_b, pos_c, pressure)
                        
                        # Only deduplicate identical consecutive status messages
                        def is_duplicate_message(a, b, c, p, prev_a, prev_b, prev_c, prev_p):
                            # Only suppress if all values are exactly the same
                            return (a == prev_a and 
                                    b == prev_b and 
                                    c == prev_c and 
                                    abs(p - prev_p) < 0.01)
                        
                        # Always print status messages
                        print(f"A {pos_a} B {pos_b} C {pos_c} Pressure {pressure}")
                        # Store values for reference
                        if not hasattr(self, '_last_status'):
                            self._last_status = {'a': 0, 'b': 0, 'c': 0, 'p': 100.0}
                        
                        # Update last values
                        self._last_status = {'a': pos_a, 'b': pos_b, 'c': pos_c, 'p': pressure}
                        
                        # Send acknowledgment
                        if self.connected and self.serial_com:
                            self.serial_com.write(b"Q\n")
                            self.serial_com.flush()
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
            elif tokens[0] == "A" and len(tokens) >= 5:
                self.axial_status_emit.emit(
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
                print("Arduino sent OK acknowledgment")
            else:
                # Filter known non-critical messages
                if not (data.startswith("step ") or data.startswith("Re")):
                    print(f"Unrecognized data format: {data}")
        except Exception as ex:
            print(f"Error handling data '{data}': {ex}")

    def send(self, command):
        """Send a command to the Arduino with improved error handling and reconnection."""
        # Handle calibration at startup (only needed once per session)
        if not hasattr(self, 'is_pressure_zeroed'):
            self.is_pressure_zeroed = False
            # Only send calibration if it's not already a calibration command
            if not command.startswith('L0-'):
                print("First command after startup - initializing pressure calibration")
                self._pending_command = command
                command = "L0-28369.0"
                self.is_pressure_zeroed = True
        
        # Check connection first
        if not self.connected or not self.serial_com:
            print("Not connected - attempting to reconnect")
            if not self.reconnect():
                print("Cannot send command - not connected")
                return False

        try:
            # Verify the port is still valid and open
            if not self.serial_com or not hasattr(self.serial_com, 'is_open') or not self.serial_com.is_open:
                print("Serial port invalid or closed before sending command")
                if self.reconnect():
                    print("Reconnected successfully")
                else:
                    print("Failed to reconnect")
                    return False

            # Safely reset buffers
            try:
                self.serial_com.reset_input_buffer()
            except Exception as buf_ex:
                print(f"Warning: Could not reset input buffer: {buf_ex}")
                
            # Send the command
            command_with_newline = command + "\n"
            print(f"Sending command: {command_with_newline}")
            bytes_written = self.serial_com.write(command_with_newline.encode())
            
            # Verify data was written
            if bytes_written <= 0:
                print("Warning: No bytes written to serial port")
                
            # Flush to ensure command is sent
            try:
                self.serial_com.flush()
            except Exception as flush_ex:
                print(f"Warning: Error flushing serial buffer: {flush_ex}")
                
            time.sleep(0.2)  # Wait for command processing
            print("Command sent successfully.")
            return True

        except serial.SerialException as serial_ex:
            print(f"Serial error sending command '{command}': {serial_ex}")
            self.connected = False
            self.connection_lost.emit()
            return False
        except (OSError, IOError) as io_ex:
            print(f"I/O error sending command '{command}': {io_ex}")
            self.connected = False
            self.connection_lost.emit()
            return False
        except Exception as ex:
            print(f"Failed to send command '{command}': {ex}")
            self.connected = False
            self.connection_lost.emit()
            return False
