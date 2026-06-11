import os
import time
import threading
from collections import deque

import serial
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from helpers.logging import setup_logger
from config.constants import ARDUINO_SETTINGS


class Arduino(QObject):
    """Serial link to the motor-controller firmware.

    Single-owner transport: exactly one I/O thread reads and writes the
    port. Other threads interact only through send() (which enqueues),
    the threading.Events, and Qt signals. This removes the historical
    races between the reader thread, UI-thread sends, reconnects spawned
    from inside the reader, and per-protocol keepalive threads.
    """

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
    error_emit = pyqtSignal(str)  # Firmware ERROR:/BUSY lines (safety events)
    released_emit = pyqtSignal()  # Firmware finished an autonomous pressure release
    zeros_emit = pyqtSignal(int, int)  # Firmware echo of applied AZERO/BZERO

    # The firmware processes at most one command per 200 ms
    # (MIN_COMMAND_INTERVAL); X and Q bypass its limiter
    SEND_INTERVAL_S = 0.22
    # Healthy firmware emits idle status every 5 s; silence beyond this
    # triggers an active probe
    RX_SILENCE_LIMIT_S = 15.0
    PROBE_TIMEOUT_S = 5.0

    def __init__(self):
        super().__init__()
        self.logger = setup_logger(component="Arduino Communication")
        self.serial_com = None
        self.connected = False
        self._lock = threading.RLock()  # guards queues + connection state
        self._running = False
        self.ARDUINO_PORT = ARDUINO_SETTINGS["ARDUINO_PORT"]
        self.ok_event = threading.Event()
        self.ready_event = threading.Event()  # set on firmware "Ready to Go"
        self._reader_ready = threading.Event()
        self.connection_ready_event = threading.Event()
        self._tx_queue = deque()
        self._priority_queue = deque()  # emergency stop jumps the line
        self._last_tx = 0.0
        self._io_thread = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def disconnect(self):
        """Close the serial connection and stop the I/O thread."""
        self._running = False
        io_thread = self._io_thread
        if io_thread and io_thread.is_alive() and io_thread is not threading.current_thread():
            io_thread.join(timeout=3.0)
        with self._lock:
            self._tx_queue.clear()
            self._priority_queue.clear()
            if self.serial_com:
                self.logger.info("Closing serial connection")
                try:
                    self.serial_com.close()
                except Exception:
                    self.logger.exception("Error closing the serial port")
                finally:
                    self.serial_com = None
            self.connected = False
            self.connection_ready_event.clear()

    @pyqtSlot()
    def verify_connection(self, tries=3, timeout_s=5.0):
        """Send 'T' probes and wait for the firmware's OK."""
        if not self.serial_com or not getattr(self.serial_com, "is_open", False):
            self.connection_ready_event.clear()
            return False

        for attempt in range(1, tries + 1):
            self.ok_event.clear()
            with self._lock:
                self._priority_queue.append("T")
            if self.ok_event.wait(timeout_s):
                self.logger.debug("Connection verified on attempt %d", attempt)
                return True
            self.logger.warning("No OK on verify attempt %d", attempt)
        return False

    def connect_to_arduino(self, max_retries=3, retry_delay=3, emit_connection_failed=True):
        """Establish the Arduino connection with retries.

        Emits connection_failed at most once, after the final attempt,
        instead of stacking one dialog per retry.
        """
        last_error = ""
        for attempt in range(1, max_retries + 1):
            self.logger.info(
                "Connection attempt %d/%d to %s", attempt, max_retries, self.ARDUINO_PORT
            )

            if not os.path.exists(self.ARDUINO_PORT):
                last_error = f"Port {self.ARDUINO_PORT} not found"
                self.logger.error(last_error)
                time.sleep(retry_delay)
                continue

            try:
                self.disconnect()

                # Short read timeout keeps the I/O loop responsive: a
                # partial line can no longer pin the thread for 10 s
                self.serial_com = serial.Serial(
                    self.ARDUINO_PORT, 115200, timeout=1, write_timeout=1
                )
                # Boot grace: USB-serial Arduinos auto-reset on open
                time.sleep(2)

                self._start_io_thread()

                if self.verify_connection():
                    self.logger.info("Connected to Arduino on %s", self.ARDUINO_PORT)
                    self.connected = True
                    self.connection_ready_event.set()
                    self.connection_ready.emit()
                    return True

                last_error = "Arduino did not answer the test command"
                self.disconnect()

            except Exception as e:
                last_error = str(e)
                self.logger.exception("Connection attempt to %s failed", self.ARDUINO_PORT)
                self.disconnect()

            time.sleep(retry_delay)

        self.logger.error(
            "Failed to establish Arduino connection after %d attempts", max_retries
        )
        if emit_connection_failed:
            self.connection_failed.emit(
                f"Failed to connect to {self.ARDUINO_PORT}: {last_error}"
            )
        self.connection_ready_event.clear()
        return False

    def reconnect(self, max_retries=3):
        """Attempt to reestablish the Arduino connection."""
        self.logger.info("Attempting to reconnect to Arduino...")
        return self.connect_to_arduino(max_retries=max_retries, emit_connection_failed=False)

    def run(self):
        """Connect to Arduino and start reading data."""
        self.connect_to_arduino()

    # Keeping compatibility with old method name
    def try_connect(self):
        """Try to connect to serial0 (compatibility method)."""
        return self.connect_to_arduino(max_retries=1, emit_connection_failed=False)

    def _start_io_thread(self):
        if self._io_thread and self._io_thread.is_alive():
            return
        self._reader_ready.clear()
        self._running = True
        self._io_thread = threading.Thread(target=self.read_from_com, daemon=True)
        self._io_thread.start()
        self._reader_ready.wait(timeout=5.0)

    # ------------------------------------------------------------------
    # I/O loop (the only code that touches the port)
    # ------------------------------------------------------------------

    def _write_now(self, command):
        """Write one command from the I/O thread. Raises on port failure."""
        payload = (command + "\n").encode()
        self.serial_com.write(payload)
        self.serial_com.flush()
        self.logger.debug("TX: %s", command)

    def _service_tx_queue(self):
        """Send queued commands, pacing normal traffic to the firmware's
        command interval. Priority commands (X, T probes) skip pacing."""
        while True:
            with self._lock:
                if not self._priority_queue:
                    break
                cmd = self._priority_queue.popleft()
            self._write_now(cmd)

        with self._lock:
            due = (
                self._tx_queue
                and time.time() - self._last_tx >= self.SEND_INTERVAL_S
            )
            cmd = self._tx_queue.popleft() if due else None
            if cmd is not None:
                self._last_tx = time.time()
        if cmd is not None:
            self._write_now(cmd)

    def read_from_com(self):
        """I/O loop: services the TX queue, reads lines, watches for
        silence. Runs until disconnect() or a port failure."""
        self.logger.info("Starting to read from serial communication")
        self._reader_ready.set()
        last_rx = time.time()
        probe_sent_at = None

        while self._running and self.serial_com and getattr(self.serial_com, "is_open", False):
            try:
                self._service_tx_queue()

                if self.serial_com.in_waiting > 0:
                    data = (
                        self.serial_com.readline().decode(errors="replace").strip()
                    )
                    if data:
                        last_rx = time.time()
                        probe_sent_at = None
                        self.handle_com(data)
                else:
                    time.sleep(0.01)

                # RX-silence watchdog: probe, then declare the link lost.
                # (The previous implementation extended its own deadline
                # after every probe write, so a dead link was never
                # detected -- writes succeed on a UART with the cable cut.)
                now = time.time()
                if now - last_rx > self.RX_SILENCE_LIMIT_S:
                    if probe_sent_at is None:
                        self.logger.warning(
                            "No data for %.0fs - probing Arduino", self.RX_SILENCE_LIMIT_S
                        )
                        self._write_now("T")
                        probe_sent_at = now
                    elif now - probe_sent_at > self.PROBE_TIMEOUT_S:
                        raise serial.SerialException(
                            "No response to probe after RX silence"
                        )

            except serial.SerialException:
                self.logger.exception("Serial connection error")
                self._handle_link_lost()
                break
            except Exception:
                # Do NOT touch last_rx here: a persistently failing loop
                # must still be able to trip the silence watchdog
                self.logger.exception("Unexpected error in I/O loop")
                time.sleep(0.1)

        self.logger.info("I/O loop exited")

    def _handle_link_lost(self):
        self.connected = False
        self.connection_ready_event.clear()
        self._running = False
        with self._lock:
            self._tx_queue.clear()
            self._priority_queue.clear()
        self.connection_lost.emit()

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def handle_com(self, data):
        """Handles incoming serial messages."""
        try:
            # Handle STATUS_START format messages
            if "STATUS_START|" in data:
                if "|STATUS_END" not in data:
                    # A truncated frame means corrupted values; never feed
                    # them into the safety-limit checks
                    self.logger.warning("Rejected truncated status frame: %s", data)
                    return
                try:
                    status_data = data.replace("STATUS_START|", "").replace(
                        "|STATUS_END", ""
                    )
                    tokens = status_data.split("|")

                    if tokens[0] == "S" and len(tokens) >= 5:
                        pos_a = int(tokens[1])
                        pos_b = int(tokens[2])
                        pos_c = int(tokens[3])
                        pressure = float(tokens[4])

                        self.status_emit.emit(pos_a, pos_b, pos_c, pressure)

                        # Acknowledge so the firmware sends the next frame.
                        # Written by the I/O thread inline: no lock dance,
                        # no sleep while holding a lock.
                        if self.connected and self.serial_com:
                            try:
                                self._write_now("Q")
                            except Exception:
                                self.logger.exception("Error sending status ack")
                except Exception:
                    self.logger.exception("Error parsing status data: %s", data)
                return

            # Firmware safety/error lines must reach the operator; they
            # were previously logged as "unrecognized" and dropped
            if data.startswith("ERROR:"):
                message = data[len("ERROR:"):].strip()
                self.logger.error("Firmware error: %s", message)
                self.error_emit.emit(message)
                return
            if data == "BUSY":
                self.logger.warning("Firmware dropped a command: BUSY")
                self.error_emit.emit("BUSY")
                return
            if data == "RELEASED":
                self.logger.info("Firmware completed autonomous pressure release")
                self.released_emit.emit()
                return

            # Handle regular messages
            tokens = data.split("|")

            if tokens[0] == "DONE":
                self.done_emit.emit()
            elif tokens[0] == "ZEROS" and len(tokens) >= 3:
                self.zeros_emit.emit(int(tokens[1]), int(tokens[2]))
            elif tokens[0] == "P" and len(tokens) >= 2:
                self.position_emit.emit(int(tokens[1]), 0, "", 0)
            elif tokens[0] == "PR" and len(tokens) >= 2:
                self.pressure_emit.emit(tokens[1])
            elif tokens[0] == "S" and len(tokens) >= 5:
                self.status_emit.emit(
                    int(tokens[1]), int(tokens[2]), int(tokens[3]), float(tokens[4])
                )
            elif tokens[0] == "A" and len(tokens) >= 5:
                # L6 report: positions + pressure
                self.status_emit.emit(
                    int(tokens[1]), int(tokens[2]), int(tokens[3]), float(tokens[4])
                )
            elif tokens[0] == "Ready to Go" or "Ready to Go" in data:
                self.ready_event.set()
                self.ready_to_go_emit.emit()
            elif tokens[0] == "weight" and len(tokens) >= 2:
                self.display_weight_emit.emit(tokens[1])
            elif (
                tokens[0] == "Test command received" or "Test command received" in data
            ):
                self.logger.debug("Arduino acknowledged test command")
            elif tokens[0] == "OK":
                self.ok_event.set()
            else:
                self.logger.debug("Unrecognized data format: %s", data)
        except Exception:
            self.logger.exception("Error handling data '%s'", data)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send(self, command):
        """Queue a command for the I/O thread.

        Returns True if the command was queued on a live connection,
        False if there is no usable link. Never blocks on the port and
        never attempts a reconnect: a multi-second reconnect inside
        send() used to freeze the UI thread exactly when the device was
        misbehaving, and the caller could not tell.
        """
        command = str(command).strip()
        if not command:
            self.logger.warning("Refusing to send empty Arduino command")
            return False

        usable = (
            self._running
            and self.serial_com is not None
            and getattr(self.serial_com, "is_open", False)
        )
        if not usable:
            self.logger.error("Cannot send '%s' - not connected", command)
            return False

        with self._lock:
            if command.startswith("X"):
                # An emergency stop never waits in line
                self._priority_queue.append(command)
            else:
                self._tx_queue.append(command)
        return True
