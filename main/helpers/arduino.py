import time
import traceback
import threading
import serial
import logging
import os
import subprocess
from datetime import datetime
from helpers.logging import (
    setup_logger, debug, debug_serial, debug_thread,
    debug_state_change, debug_timing, debug_error, debug_lock, debug_signal
)
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
    display_weight_emit = pyqtSignal(str)  # Signal for weight display

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
        self.message_counter = 0  # Track total messages received
        self.lock_wait_times = []  # Track lock acquisition times
        self.last_buffer_log_time = time.time()  # Track buffer logging frequency
        debug(f"Arduino initialized", component="Arduino", level="INFO",
              port=self.ARDUINO_PORT, buffer_size=self.ARDUINO_BUFFER_SIZE)

    def release_busy_port(self):
        """Attempt to release the serial0 port if busy"""
        try:
            port = self.ARDUINO_PORT
            debug(f"Attempting to release busy port", component="Arduino", port=port)

            # Check if port is busy using lsof
            result = subprocess.run(
                ["lsof", port], capture_output=True, text=True, check=False
            )

            if result.returncode == 0:  # Port is busy
                debug(f"Port is busy. Current users:\n{result.stdout}", component="Arduino", level="WARNING")

                # Try to kill processes using fuser
                debug(f"Killing processes using port", component="Arduino", port=port)
                subprocess.run(["fuser", "-k", port], check=False)

                # For serial0, stop getty service
                debug("Stopping serial-getty@serial0.service", component="Arduino")
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
                    debug(f"Failed to release port - still in use:\n{result.stdout}",
                          component="Arduino", level="ERROR", port=port)
                    return False
                else:
                    debug(f"Successfully released port", component="Arduino", level="INFO", port=port)
                    return True
            else:
                debug(f"Port is not busy", component="Arduino", port=port)
                return True

        except Exception as e:
            debug_error(f"Error attempting to release port", exception=e, component="Arduino", port=self.ARDUINO_PORT)
            return False

    def reset_dtr(self):
        """Reset Arduino by toggling DTR line (simulates opening serial monitor)."""
        start_time = time.time()
        try:
            if not self.serial_com:
                debug("DTR Reset FAILED - No serial connection", component="Arduino", level="ERROR")
                return False

            debug("Starting DTR Reset sequence...", component="Arduino")

            # Save current DTR state
            original_dtr = self.serial_com.dtr
            debug(f"Original DTR state", component="Arduino", dtr_state=original_dtr)

            # Toggle DTR
            self.serial_com.dtr = False
            debug("DTR set to FALSE", component="Arduino")
            time.sleep(0.1)  # Brief delay
            self.serial_com.dtr = True
            debug("DTR set to TRUE - Waiting 5s for Arduino init...", component="Arduino")
            time.sleep(5)  # Allow Arduino to initialize

            # Restore original DTR state
            self.serial_com.dtr = original_dtr
            debug_timing("DTR Reset COMPLETE", start_time=start_time, component="Arduino", dtr_restored=original_dtr)

            return True

        except Exception as e:
            debug_error("DTR Reset ERROR", exception=e, component="Arduino")
            return False


    def disconnect(self):
        """Forcefully closes the current serial connection if open."""
        lock_start = time.time()
        with self._lock:
            debug_lock("Acquired lock for disconnect", lock_name="serial_lock", acquired=True,
                      wait_time=time.time()-lock_start)

            if self.serial_com:
                debug("Forcefully closing existing serial connection", component="Arduino", level="WARNING")
                try:
                    # Stop the reader thread *before* closing the port
                    old_running = self._running
                    self._running = False
                    debug_state_change("Arduino", old_running, False, "Stopping reader thread before disconnect")
                    time.sleep(0.1) # Give thread a moment to exit loop

                    self.serial_com.close()
                    debug("Serial connection closed successfully", component="Arduino", level="INFO")
                    time.sleep(1)  # Give system time to reset port (can be shorter now)
                except Exception as ex:
                    debug_error("Error closing the serial port", exception=ex, component="Arduino")
                finally:
                    # Ensure these are reset even if close fails
                    self.serial_com = None
                    old_connected = self.connected
                    self.connected = False
                    if old_connected:
                        debug_state_change("Arduino", old_connected, False, "Connection reset after disconnect")
                    # Don't reset self._running here if it's controlled by the reader thread loop condition
            else:
                 # If no serial_com object, ensure flags are false
                 self._running = False
                 self.connected = False
                 debug("No active connection to disconnect", component="Arduino")

    @pyqtSlot()
    def verify_connection(self, tries=3, timeout_s=10.0):
        """
        1. Runs both during initial connect *and* from inside the reader loop.
        2. Never resets the input buffer after sending 'T' (prevents eating the reply).
        3. Uses a single blocking readline() with a per-call timeout = deadline.
        4. Holds self._lock only around the WRITE, so other threads can't interleave.
        """
        if not self.serial_com or not self.serial_com.is_open:
            debug("Cannot verify connection - port not open", component="Arduino", level="WARNING")
            return False

        debug(f"Starting connection verification", component="Arduino", tries=tries, timeout=timeout_s)

        for n in range(tries):
            self.ok_event.clear()
            lock_start = time.time()
            with self._lock:
                lock_time = time.time() - lock_start
                debug_lock("Sending test command 'T'", lock_name="serial_lock", acquired=True, wait_time=lock_time)
                self.serial_com.reset_input_buffer()   # flush junk *before* we talk
                self.serial_com.write(b"T\n")
                self.serial_com.flush()

            debug(f"Test command sent, waiting for OK response", component="Arduino", attempt=n+1)
            if self.ok_event.wait(timeout_s):
                debug(f"OK received on attempt {n+1}/{tries}", component="Arduino", level="INFO")
                return True
            debug(f"No OK response on attempt {n+1}/{tries}", component="Arduino", level="WARNING")
            time.sleep(0.5)

        debug(f"Connection verification FAILED after {tries} attempts", component="Arduino", level="ERROR")
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
        debug(f"Starting Arduino connection sequence", component="Arduino", level="INFO",
              max_retries=max_retries, retry_delay=retry_delay)

        for attempt in range(1, max_retries + 1):
            debug(f"Connection attempt {attempt}/{max_retries}", component="Arduino",
                  port=self.ARDUINO_PORT)

            # Check if port exists
            if not os.path.exists(self.ARDUINO_PORT):
                debug(f"Port does not exist", component="Arduino", level="ERROR", port=self.ARDUINO_PORT)
                if emit_connection_failed:
                    debug_signal("Emitting connection_failed", signal_name="connection_failed",
                                data=f"Port {self.ARDUINO_PORT} not found")
                    self.connection_failed.emit(f"Port {self.ARDUINO_PORT} not found")
                time.sleep(retry_delay)
                continue

            try:
                # Close any existing connection
                debug("Closing any existing connections before attempt", component="Arduino")
                self.disconnect()
                time.sleep(1)

                # Release port if busy
                if not self.release_busy_port():
                    debug("Failed to release busy port, continuing anyway", component="Arduino", level="WARNING")

                # Open new connection
                debug(f"Opening serial connection", component="Arduino",
                      port=self.ARDUINO_PORT, baud=115200, timeout=10)
                self.serial_com = serial.Serial(self.ARDUINO_PORT, 115200, timeout=10, write_timeout=1)
                time.sleep(5)  # Wait for Arduino initialization

                # Reset Arduino via DTR
                if not self.reset_dtr():
                    debug("DTR reset failed but continuing", component="Arduino", level="WARNING")

                if not self._running:
                    debug_state_change("Arduino._running", False, True, "Starting reader thread")
                    self._running = True
                    debug_thread("Starting serial reader thread", thread_name="read_from_com", state="STARTING")
                    threading.Thread(target=self.read_from_com,
                                    daemon=True).start()

                # Clear any startup messages after DTR reset
                time.sleep(1)
                if self.serial_com:
                    debug("Clearing input buffer of startup messages", component="Arduino")
                    self.serial_com.reset_input_buffer()

                # Verify Arduino responds after reset - SINGLE CALL
                if self.verify_connection(tries=3, timeout_s=10.0):
                    debug(f"SUCCESS: Connected to Arduino", component="Arduino", level="INFO",
                          port=self.ARDUINO_PORT, attempt=attempt)
                    debug_state_change("Arduino.connected", False, True, "Connection verified")
                    self.connected = True
                    self._running = True
                    # Successfully connected
                    debug_signal("Emitting connection_ready", signal_name="connection_ready")
                    self.connection_ready.emit()
                    return True

                # Clean up failed connection
                debug("Connection verification failed, cleaning up", component="Arduino", level="WARNING")
                self.disconnect()

            except Exception as e:
                debug_error(f"Connection attempt {attempt} failed", exception=e, component="Arduino",
                           port=self.ARDUINO_PORT)
                self.disconnect()

            # Wait before next attempt
            if attempt < max_retries:
                debug(f"Waiting {retry_delay}s before retry", component="Arduino")
                time.sleep(retry_delay)

        # All attempts failed
        debug(f"FAILURE: All connection attempts exhausted", component="Arduino", level="ERROR",
              max_retries=max_retries)
        if emit_connection_failed:
            msg = f"Failed to connect to {self.ARDUINO_PORT} after {max_retries} attempts"
            debug_signal("Emitting connection_failed", signal_name="connection_failed", data=msg)
            self.connection_failed.emit(msg)
        return False

    def reconnect(self, max_retries=3): # Accept argument, default to 3
        """Attempt to reestablish Arduino connection if lost."""
        debug("Attempting to reconnect to Arduino...", component="Arduino", level="WARNING",
              max_retries=max_retries)
        # *** USE THE ARGUMENT HERE ***
        return self.connect_to_arduino(max_retries=max_retries, emit_connection_failed=False)

    def run(self):
        """Connect to Arduino and start reading data."""
        debug("Arduino.run() called - initiating connection", component="Arduino")
        self.connect_to_arduino()


    # Keeping compatibility with old method name
    def try_connect(self):
        """Try to connect to serial0 (compatibility method)."""
        debug("try_connect() called (compatibility method)", component="Arduino")
        return self.connect_to_arduino(max_retries=1, emit_connection_failed=False)

    def monitor_buffer(self):
        if not self.serial_com:
            return

        try:
            in_waiting = self.serial_com.in_waiting
            in_buffer_usage = in_waiting / self.ARDUINO_BUFFER_SIZE

            # Log buffer status periodically (every 5 seconds) or when high
            current_time = time.time()
            should_log = (in_buffer_usage > 0.5) or (current_time - self.last_buffer_log_time > 5)

            if should_log and in_waiting > 0:
                self.last_buffer_log_time = current_time
                debug(f"Buffer status", component="Arduino",
                      in_buffer=f"{in_buffer_usage*100:.1f}%",
                      bytes_waiting=in_waiting)

            # Only check output buffer if input is OK
            if in_buffer_usage <= self.BUFFER_WARNING_THRESHOLD:
                out_waiting = self.serial_com.out_waiting
                out_buffer_usage = out_waiting / self.ARDUINO_BUFFER_SIZE

                if out_buffer_usage > self.BUFFER_WARNING_THRESHOLD:
                    warning = f"Output buffer at {out_buffer_usage*100:.1f}% capacity"
                    debug(warning, component="Arduino", level="WARNING",
                          out_bytes=out_waiting)
                    self.buffer_warning.emit(warning)

            # Emergency flush if input buffer critical
            if in_buffer_usage > 0.9:
                debug("EMERGENCY: Input buffer critical - flushing", component="Arduino", level="ERROR",
                      bytes_waiting=in_waiting, usage=f"{in_buffer_usage*100:.1f}%")
                self.serial_com.reset_input_buffer()

        except Exception as ex:
            debug_error("Buffer monitoring error", exception=ex, component="Arduino")
            self.connection_failed.emit(str(ex))

    def read_from_com(self):
        """Continuously reads data from the serial connection."""
        debug_thread("Serial reader thread started", thread_name="read_from_com", state="RUNNING")
        last_data_time = time.time()
        timeout_warnings = 0

        while self._running and self.serial_com and self.serial_com.is_open:
            try:
                # Monitor buffer before reading
                self.monitor_buffer()

                # Check for connection timeout (no data received in 120 seconds)
                current_time = time.time()
                time_since_data = current_time - last_data_time

                if time_since_data > 120:
                    timeout_warnings += 1
                    debug(f"Connection timeout detected", component="Arduino", level="WARNING",
                          seconds_since_data=time_since_data, warning_count=timeout_warnings)

                    # Try to send a test command directly
                    try:
                        lock_start = time.time()
                        with self._lock:
                            lock_time = time.time() - lock_start
                            debug_lock("Sending direct test for timeout check",
                                      lock_name="serial_lock", acquired=True, wait_time=lock_time)
                            self.serial_com.reset_input_buffer()
                            self.serial_com.write(b"T\n")
                            self.serial_com.flush()
                        debug("Direct test command sent during timeout", component="Arduino")

                        # Update last_data_time to give more time for a response
                        last_data_time = current_time - 60  # Give 60 more seconds
                        continue  # Skip verification for now and check again later

                    except Exception as test_err:
                        debug_error("Error sending timeout test command", exception=test_err, component="Arduino")

                    # Only verify connection if direct test failed
                    if not self.verify_connection():
                        debug("Connection verification failed - connection lost", component="Arduino", level="ERROR")

                        # Try reconnecting once before giving up
                        debug("Attempting emergency reconnect...", component="Arduino", level="WARNING")
                        if self.reconnect(max_retries=1):
                            debug("Emergency reconnect successful!", component="Arduino", level="INFO")
                            last_data_time = time.time()  # Reset timer
                            timeout_warnings = 0
                            continue

                        # If reconnect failed, signal loss
                        debug_state_change("Arduino.connected", True, False, "Reconnection failed")
                        self.connected = False
                        debug_signal("Emitting connection_lost", signal_name="connection_lost")
                        self.connection_lost.emit()
                        debug_signal("Emitting connection_failed", signal_name="connection_failed",
                                    data="Connection timeout (verification failed)")
                        self.connection_failed.emit("Connection timeout (verification failed)")
                        break
                    else:
                        debug("Connection verified after timeout - resetting timer", component="Arduino", level="INFO")
                        last_data_time = current_time  # Reset the timer since connection is actually OK
                        timeout_warnings = 0

                if self.serial_com and self.serial_com.in_waiting > 0:
                    try:
                        data = (
                            self.serial_com.readline().decode(errors="replace").strip()
                        )
                        last_data_time = time.time()  # Update last data time
                        self.message_counter += 1

                        if len(data) > 0:
                            debug_serial("Received data", data=data, msg_count=self.message_counter)
                            self.handle_com(data)
                    except Exception as e:
                        debug_error("Error reading data", exception=e, component="Arduino")
                else:
                    time.sleep(0.01)

            except serial.SerialException as ex:
                debug_error("Serial connection error - marking disconnected", exception=ex, component="Arduino")
                debug_state_change("Arduino.connected", True, False, "Serial exception")
                self.connected = False
                debug_signal("Emitting connection_lost", signal_name="connection_lost")
                self.connection_lost.emit()
                break
            except Exception as ex:
                debug_error("Unexpected error in read loop", exception=ex, component="Arduino")
                # Try to continue, but mark time so we don't timeout
                last_data_time = time.time()

        debug_thread("Serial reader thread exiting", thread_name="read_from_com", state="STOPPED",
                    running=self._running, connected=self.connected)

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
                        debug("Truncated status message detected", component="Arduino", level="WARNING",
                              data=status_data)

                    tokens = status_data.split("|")

                    if tokens[0] == "S" and len(tokens) >= 5:
                        pos_a = int(tokens[1])
                        pos_b = int(tokens[2])
                        pos_c = int(tokens[3])
                        pressure = float(tokens[4])

                        # Emit status signal with explicit type conversion
                        debug_signal("Emitting status_emit", signal_name="status_emit",
                                    data={"pos_a": pos_a, "pos_b": pos_b, "pos_c": pos_c, "pressure": pressure})
                        self.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))

                        # Send acknowledgment to Arduino that we processed the status
                        if self.connected and self.serial_com:
                            try:
                                # Use with lock to ensure exclusive access to serial port
                                lock_start = time.time()
                                with self._lock:
                                    lock_time = time.time() - lock_start
                                    debug_lock("Sending status acknowledgment 'Q'",
                                              lock_name="serial_lock", acquired=True, wait_time=lock_time)
                                    self.serial_com.write(b"Q\n")
                                    self.serial_com.flush()
                                    time.sleep(0.1)  # Small delay to ensure flush completes
                                debug("Status acknowledgment sent", component="Arduino")
                            except Exception as ack_err:
                                debug_error("ERROR sending acknowledgment", exception=ack_err, component="Arduino")
                        else:
                            debug("Cannot send status acknowledgment - not connected", component="Arduino", level="WARNING")
                        return
                except Exception as e:
                    debug_error("Error parsing status data", exception=e, component="Arduino", data=data)
                    return

            # Handle regular messages
            tokens = data.split("|")

            if tokens[0] == "DONE":
                debug_signal("Emitting done_emit", signal_name="done_emit")
                self.done_emit.emit()
            elif tokens[0] == "P":
                debug_signal("Emitting position_emit", signal_name="position_emit",
                            data={"pos": int(tokens[1])})
                self.position_emit.emit(int(tokens[1]), 0, "", 0)
            elif tokens[0] == "PR":
                debug_signal("Emitting pressure_emit", signal_name="pressure_emit",
                            data={"pressure": tokens[1]})
                self.pressure_emit.emit(tokens[1])
            elif tokens[0] == "E":
                debug_signal("Emitting position_emit (E format)", signal_name="position_emit",
                            data={"t1": int(tokens[1]), "t2": int(tokens[2]),
                                  "t3": tokens[3], "t4": int(tokens[4])})
                self.position_emit.emit(
                    int(tokens[1]), int(tokens[2]), tokens[3], int(tokens[4])
                )
            elif tokens[0] == "S" and len(tokens) >= 5:
                status_data = {"pos_a": int(tokens[1]), "pos_b": int(tokens[2]),
                              "pos_c": int(tokens[3]), "pressure": float(tokens[4])}
                debug_signal("Emitting status_emit (S format)", signal_name="status_emit", data=status_data)
                self.status_emit.emit(
                    int(tokens[1]), int(tokens[2]), int(tokens[3]), float(tokens[4])
                )
            elif tokens[0] == "Ready to Go" or "Ready to Go" in data:
                debug_signal("Emitting ready_to_go_emit", signal_name="ready_to_go_emit")
                self.ready_to_go_emit.emit()
            elif tokens[0] == "weight":
                debug_signal("Emitting display_weight_emit", signal_name="display_weight_emit",
                            data={"weight": tokens[1]})
                self.display_weight_emit.emit(tokens[1])
            elif (
                tokens[0] == "Test command received" or "Test command received" in data
            ):
                debug("Arduino acknowledged test command", component="Arduino", level="INFO")
            elif "OK" in tokens[0] or tokens[0] == "OK":
                self.ok_event.set()
                debug("Arduino sent OK acknowledgment - setting ok_event", component="Arduino", level="INFO")
            else:
                debug(f"Unrecognized data format", component="Arduino", level="WARNING", data=data)
        except Exception as ex:
            debug_error(f"Error handling data", exception=ex, component="Arduino", data=data)

    def send(self, command):
        """Send a command to the Arduino with reconnection capability."""
        lock_start = time.time()
        with self._lock:
            lock_time = time.time() - lock_start
            debug_lock(f"Sending command: {command}", lock_name="serial_lock",
                      acquired=True, wait_time=lock_time)

            # Check connection first
            if not self.connected or not self.serial_com:
                debug("Not connected - attempting to reconnect", component="Arduino", level="WARNING")
                if not self.reconnect(max_retries=3):
                    debug(f"Cannot send command - not connected", component="Arduino", level="ERROR",
                          command=command)
                    return False

            try:
                if not self.serial_com:  # Double-check after reconnect
                    debug("Serial com still None after reconnect", component="Arduino", level="ERROR")
                    return False

                self.serial_com.reset_input_buffer()
                command_with_newline = command + "\n"
                debug_serial(f"Sending command", data=command_with_newline)
                self.serial_com.write(command_with_newline.encode())
                self.serial_com.flush()
                time.sleep(0.3)  # Increased from 0.1 to give more time for flush
                debug(f"Command sent successfully", component="Arduino", command=command)
                return True

            except Exception as ex:
                debug_error(f"Failed to send command", exception=ex, component="Arduino", command=command)
                debug_state_change("Arduino.connected", True, False, "Send failed")
                self.connected = False  # Mark as disconnected
                debug_signal("Emitting connection_lost", signal_name="connection_lost")
                self.connection_lost.emit()  # Signal that connection was lost
                return False