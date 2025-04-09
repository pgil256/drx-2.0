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
        if self.serial_com:
            print("Forcefully closing existing serial connection")
            try:
                self.serial_com.close()
                # Add additional cleanup steps
                self.serial_com = None
                self.connected = False
                print("Serial connection closed successfully.")
                time.sleep(2)  # Give system time to reset port
            except serial.SerialException as ex:
                print(f"Error closing the serial port: {ex}")
            except Exception as ex:
                from utils.exceptions import ArduinoConnectionError
                error = ArduinoConnectionError(f"Error closing the serial port: {ex}")
                print(f"Error closing the serial port: {error}")

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

        # Try to reconnect to the last used port first
        if self.current_port and os.path.exists(self.current_port):
            if self.try_connect_to_port(self.current_port):
                return True

        # Try other ports
        ports_to_try = ["/dev/ttyS0", "/dev/ttyACM0", "/dev/ttyUSB0"]
        for port in ports_to_try:
            if port != self.current_port and os.path.exists(port):
                if self.try_connect_to_port(port):
                    return True

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
            time.sleep(5)  # Wait for Arduino initialization

            # Verify connection
            if self.verify_connection():
                print(f"Connected to Arduino on {port}")
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

        # Try multiple ports in case one is busy
        ports_to_try = ["/dev/ttyS0", "/dev/ttyACM0", "/dev/ttyUSB0"]

        for attempt in range(1, max_retries + 1):
            # Try each port before moving to next attempt
            for port in ports_to_try:
                if self.try_connect_to_port(port):
                    # Start reading loop
                    self.read_from_com()
                    return

            # After trying all ports, wait before next attempt
            time.sleep(retry_delay)

        print(
            "Failed to establish Arduino connection after trying all ports and attempts"
        )
        self.connection_failed.emit("Failed to establish connection")

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

        while self.connected and self.serial_com:
            try:
                # Monitor buffer before reading
                self.monitor_buffer()

                # Check for connection timeout (no data received in 30 seconds)
                current_time = time.time()
                if current_time - last_data_time > 30:
                    print("Connection timeout: No data received in 30 seconds")
                    self.connected = False
                    self.connection_lost.emit()
                    self.connection_failed.emit("Connection timeout")
                    break

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

                        self.status_emit.emit(pos_a, pos_b, pos_c, pressure)
                        print(f"A {pos_a} B {pos_b} C {pos_c} Pressure {pressure}")
                        # Add this at the end of successful status processing:
                        
                        if self.connected and self.serial_com:
                        # Send acknowledgment
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
                print(f"Unrecognized data format: {data}")
        except Exception as ex:
            print(f"Error handling data '{data}': {ex}")

    def send(self, command):
        """Send a command to the Arduino with reconnection capability."""
        # Check connection first
        if not self.connected or not self.serial_com:
            print("Not connected - attempting to reconnect")
            if not self.reconnect():
                print("Cannot send command - not connected")
                return False

        try:
            if not self.serial_com:  # Double-check after reconnect
                return False

            self.serial_com.reset_input_buffer()
            command_with_newline = command + "\n"
            print(f"Sending command: {command_with_newline}")
            self.serial_com.write(command_with_newline.encode())
            self.serial_com.flush()
            time.sleep(0.2)  # Increased from 0.1 to give more time for flush
            print("Command sent successfully.")
            return True

        except Exception as ex:
            print(f"Failed to send command '{command}': {ex}")
            self.connected = False  # Mark as disconnected
            self.connection_lost.emit()  # Signal that connection was lost
            return False
