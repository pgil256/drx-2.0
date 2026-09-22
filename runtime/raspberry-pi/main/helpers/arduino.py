import math
import os
import re
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import serial
from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from helpers.logging import LoggerSetup, setup_logger
from helpers.firmware_protocol import HX711_PROTOCOL_DRIVER, parse_diagnostic_frame
from config.constants import ARDUINO_SETTINGS


def xor_checksum(payload: str) -> int:
    """XOR of all payload bytes; mirrors the firmware's frame checksum."""
    value = 0
    for byte in payload.encode():
        value ^= byte
    return value


@dataclass
class CommandHandle:
    """Observable lifecycle for a queued command.

    Protocol v2 resolves ``completed`` only from an acknowledgement carrying
    this handle's sequence number. ``written`` is independent: shutdown uses it
    to prove a safety command reached the OS serial driver before teardown.
    """

    command: str
    sequence: Optional[int] = None
    written: threading.Event = field(default_factory=threading.Event)
    completed: threading.Event = field(default_factory=threading.Event)
    result: Optional[str] = None
    reason: str = ""
    retries: int = 0  # link-level resends after a parse rejection
    generation: int = 0


# Firmware rejections that mean "I could not parse what arrived", i.e. the
# command was NOT executed. On 2026-09-10 a single corrupted byte on
# /dev/serial0 turned I131340 into an "Invalid I value" and the host faulted
# the whole reset. A rejected command is always safe to resend once.
PARSE_REJECTIONS = frozenset({
    "A value out of range",
    "Checksum mismatch",
    "Command too long",
    "Invalid A value",
    "Invalid F direction",
    "Invalid I value",
    "Invalid K value",
    "Invalid L0 factor",
    "Invalid L5 zero marks",
    "Invalid P value",
    "Invalid device",
    "Malformed frame",
})
# v1 rejections carry no sequence number; map the reason back to the
# command letter it can have come from so the right recent write is resent.
_REJECTION_LETTERS = {
    "A value out of range": "A",
    "Invalid A value": "A",
    "Invalid F direction": "F",
    "Invalid I value": "I",
    "Invalid K value": "K",
    "Invalid L0 factor": "L",
    "Invalid L5 zero marks": "L",
    "Invalid P value": "P",
}
RETRY_MATCH_WINDOW_S = 2.0
MAX_LINK_RETRIES = 1


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
    error_emit = pyqtSignal(str)  # Firmware ERROR:/BUSY command and device errors
    warning_emit = pyqtSignal(str)  # Firmware WARNING: advisory notices
    released_emit = pyqtSignal()  # Firmware finished an autonomous pressure release
    zeros_emit = pyqtSignal(int, int)  # Firmware echo of applied AZERO/BZERO
    motion_done = pyqtSignal(str, float, float)
    calibration_result = pyqtSignal(dict)
    firmware_identity = pyqtSignal(dict)
    sensor_diagnostics = pyqtSignal(dict)
    hardware_diagnostics = pyqtSignal(dict)
    pressure_warning = pyqtSignal(dict)
    command_rejected = pyqtSignal(dict)
    fault_emit = pyqtSignal(dict)

    # The firmware processes at most one command per 200 ms
    # (MIN_COMMAND_INTERVAL); X and Q bypass its limiter
    SEND_INTERVAL_S = 0.22
    # Healthy firmware emits idle status every 5 s; silence beyond this
    # triggers an active probe
    RX_SILENCE_LIMIT_S = 15.0
    PROBE_TIMEOUT_S = 5.0

    def __init__(self, transport_factory: Optional[Callable[..., object]] = None,
                 port: Optional[str] = None) -> None:
        """Create a hardware link, or an explicitly injected development transport."""
        super().__init__()
        self.logger = setup_logger(component="Arduino Communication")
        self.serial_com = None
        self.connected = False
        self._lock = threading.RLock()  # guards queues + connection state
        self._queue_condition = threading.Condition(self._lock)
        self._running = False
        self._connect_cancel = threading.Event()
        self.ARDUINO_PORT = port if port is not None else ARDUINO_SETTINGS["ARDUINO_PORT"]
        # Development transports may use a local socket instead of a device file.
        # Keep the real queue, parser, tracking, and I/O thread for either transport.
        self._transport_factory = transport_factory
        self.ok_event = threading.Event()
        self.ready_event = threading.Event()  # set on firmware "Ready to Go"
        self._reader_ready = threading.Event()
        self.connection_ready_event = threading.Event()
        self._tx_queue = deque()
        self._priority_queue = deque()  # emergency stop jumps the line
        self._last_tx = 0.0
        self._write_in_progress = 0
        self._io_thread = None
        # Protocol v2: per-command sequence numbers + checksums on
        # commands and status frames. Requires firmware
        # 2026-06-11-FAILSAFE-2+; disabled by default so the Batch-1
        # flash behavior is unchanged until the hardware checkout
        # enables it (KNEESPA_PROTOCOL_V2=1).
        self.protocol_v2 = os.environ.get("KNEESPA_PROTOCOL_V2", "0") == "1"
        self._seq = 0
        self.last_done_seq = None
        self.checksum_failures = 0
        # Once the device demonstrates checksummed telemetry, never accept a
        # missing trailer as legacy traffic (UART damage can erase it).
        self._status_checksum_required = False
        self._pending_v2 = {}
        # (written_at, handle) for the last few writes, newest last: lets a
        # v1 "ERROR: Invalid X value" be matched to the command it rejected
        self._recent_writes = deque(maxlen=16)
        self._write_generation = 0
        self.firmware_driver = None
        self.firmware_version = None
        self.baseline_valid = False
        self.link_retries = 0  # parse rejections answered with a resend
        # Every run records traffic using this single-owner transport. The E2E
        # harness can additionally request a copy without opening a second port.
        self._log_setup = LoggerSetup()
        self._serial_trace_path = os.environ.get(
            "KNEESPA_SERIAL_TRACE_FILE", ""
        ).strip()
        self._serial_trace_lock = threading.Lock()
        self._serial_trace_disabled = False

    def _trace_serial(self, direction: str, data: str) -> None:
        """Record TX/RX for this run and optionally copy it to the E2E trace.

        Trace failures are deliberately non-fatal: diagnostics must never
        interfere with serial safety or motion control.
        """
        self._log_setup.trace_serial(direction, data)
        if not self._serial_trace_path or self._serial_trace_disabled:
            return
        safe_data = str(data).replace("\r", "\\r").replace("\n", "\\n")
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        try:
            directory = os.path.dirname(os.path.abspath(self._serial_trace_path))
            os.makedirs(directory, exist_ok=True)
            with self._serial_trace_lock:
                with open(self._serial_trace_path, "a", encoding="utf-8") as trace:
                    trace.write(f"[{timestamp}] {direction} {safe_data}\n")
                    trace.flush()
        except OSError as exc:
            self._serial_trace_disabled = True
            self.logger.warning("Serial trace disabled after write failure: %s", exc)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def disconnect(self, drain_timeout=0.0):
        """Close the serial connection and stop the I/O thread.

        When ``drain_timeout`` is positive, queued commands are allowed to
        reach the serial driver first. This is used by application shutdown so
        an emergency stop cannot be queued and then immediately discarded.
        Returns whether the requested drain completed.
        """
        drained = True
        if drain_timeout:
            drained = self.wait_for_drain(drain_timeout)
        self._running = False
        io_thread = self._io_thread
        if io_thread and io_thread.is_alive() and io_thread is not threading.current_thread():
            io_thread.join(timeout=3.0)
        with self._lock:
            self._fail_pending("DISCONNECTED", "Serial connection closed")
            self._invalidate_identity()
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
            self._queue_condition.notify_all()
        return drained

    @pyqtSlot()
    def verify_connection(self, tries=3, timeout_s=5.0):
        """Send 'T' probes and wait for the firmware's OK."""
        if not self.serial_com or not getattr(self.serial_com, "is_open", False):
            self.connection_ready_event.clear()
            return False

        for attempt in range(1, tries + 1):
            if self._connect_cancel.is_set():
                return False
            self.ok_event.clear()
            handle = self.send_tracked("T", priority=True)
            if handle is None:
                return False
            event = handle.completed if self.protocol_v2 else self.ok_event
            deadline = time.monotonic() + timeout_s
            while not event.wait(0.05):
                if self._connect_cancel.is_set() or time.monotonic() >= deadline:
                    break
            if self._connect_cancel.is_set():
                return False
            verified = event.is_set() and (not self.protocol_v2 or handle.result == "OK")
            if verified:
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
            if self._connect_cancel.is_set():
                return False
            self.logger.info(
                "Connection attempt %d/%d to %s", attempt, max_retries, self.ARDUINO_PORT
            )

            if self._transport_factory is None and not os.path.exists(self.ARDUINO_PORT):
                last_error = f"Port {self.ARDUINO_PORT} not found"
                self.logger.error(last_error)
                self._connect_cancel.wait(retry_delay)
                continue

            try:
                self.disconnect()

                # Short read timeout keeps the I/O loop responsive: a
                # partial line can no longer pin the thread for 10 s
                factory = self._transport_factory or serial.Serial
                self.serial_com = factory(
                    self.ARDUINO_PORT, 115200, timeout=1, write_timeout=1
                )
                # Boot grace: USB-serial Arduinos auto-reset on open
                if self._connect_cancel.wait(2):
                    return False

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

            self._connect_cancel.wait(retry_delay)

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
        try:
            self.connect_to_arduino()
        finally:
            # The QObject is hosted by a QThread in the application. Always
            # signal that its startup slot returned so the Qt event loop can be
            # shut down deterministically instead of leaking across reconnects.
            self.finished.emit()

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
        self._trace_serial("TX", command)
        self.logger.debug("TX: %s", command)

    def _write_queued(self, command: str, handle: CommandHandle) -> None:
        """Write a dequeued command while making drain state observable."""
        try:
            with self._lock:
                if handle.generation != self._write_generation:
                    handle.result = "CANCELLED"
                    handle.completed.set()
                    return
            self._write_now(command)
            handle.written.set()
            with self._lock:
                if handle.generation == self._write_generation:
                    self._recent_writes.append((time.time(), handle))
        except Exception:
            with self._lock:
                self._pending_v2.pop(handle.sequence, None)
                handle.result = "DISCONNECTED"
                handle.reason = "Serial write failed"
                handle.completed.set()
            raise
        finally:
            with self._queue_condition:
                self._write_in_progress -= 1
                self._queue_condition.notify_all()

    def _service_tx_queue(self):
        """Send queued commands, pacing normal traffic to the firmware's
        command interval. Priority commands (X, T probes) skip pacing."""
        while True:
            with self._lock:
                if not self._priority_queue:
                    break
                cmd, handle = self._priority_queue.popleft()
                self._write_in_progress += 1
            self._write_queued(cmd, handle)

        with self._lock:
            due = (
                self._tx_queue
                and time.time() - self._last_tx >= self.SEND_INTERVAL_S
            )
            queued = self._tx_queue.popleft() if due else None
            if queued is not None:
                self._last_tx = time.time()
                self._write_in_progress += 1
        if queued is not None:
            self._write_queued(*queued)

    def wait_for_drain(self, timeout_s=1.0):
        """Wait until all queued writes have reached ``serial.flush()``."""
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._queue_condition:
            while self._priority_queue or self._tx_queue or self._write_in_progress:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._queue_condition.wait(remaining)
        return True

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
                    raw_data = self.serial_com.readline().decode(errors="replace")
                    if raw_data:
                        self._trace_serial("RX", raw_data.rstrip("\r\n"))
                    data = raw_data.strip()
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
        self._invalidate_identity()
        self.connected = False
        self.connection_ready_event.clear()
        with self._lock:
            self._running = False  # under the lock: pairs with send()'s check
            self._fail_pending("DISCONNECTED", "Serial link lost")
            self._queue_condition.notify_all()
        self.connection_lost.emit()

    def _discard_queued(self, result: str, reason: str) -> None:
        """Cancel unsent commands under the queue lock without claiming a write."""
        for queue in (self._tx_queue, self._priority_queue):
            while queue:
                _, handle = queue.popleft()
                self._pending_v2.pop(handle.sequence, None)
                handle.result = result
                handle.reason = reason
                handle.completed.set()

    def cancel_pending_commands(self) -> None:
        """Forget work aborted by a physical stop without interrupting its release."""
        with self._queue_condition:
            self._fail_pending("CANCELLED", "Physical emergency stop")
            self._queue_condition.notify_all()

    def _fail_pending(self, result, reason):
        """Resolve queued and outstanding v2 handles after teardown/link loss."""
        self._discard_queued(result, reason)
        for handle in self._pending_v2.values():
            handle.result = result
            handle.reason = reason
            handle.completed.set()
        for _, handle in self._recent_writes:
            if not handle.completed.is_set():
                handle.result = result
                handle.reason = reason
                handle.completed.set()
        self._pending_v2.clear()
        self._recent_writes.clear()
        self._write_generation += 1

    def _invalidate_identity(self) -> None:
        """A reboot/disconnect removes authority to send live calibration."""
        self.firmware_driver = self.firmware_version = None
        self.baseline_valid = False

    def _requeue_front(self, wire: str, handle: CommandHandle) -> None:
        """Resend ahead of anything queued later, at the normal pacing."""
        handle.retries += 1
        self.link_retries += 1
        self._tx_queue.appendleft((wire, handle))
        self._queue_condition.notify_all()

    def _retry_rejected_v2(self, seq, reason) -> bool:
        """ERR|seq|<parse reason>: resend that exact command under a new
        sequence number, once. Returns True if a resend was queued."""
        with self._queue_condition:
            handle = self._pending_v2.get(seq)
            if handle is None or handle.retries >= MAX_LINK_RETRIES:
                return False
            self._pending_v2.pop(seq, None)
            self._seq = (self._seq + 1) % 1000000
            handle.sequence = self._seq
            body = f"{self._seq}:{handle.command}"
            wire = f"#{body}*{xor_checksum(body):02X}"
            self._pending_v2[self._seq] = handle
            self._requeue_front(wire, handle)
        self.logger.warning(
            "Firmware could not parse '%s' (%s); resending as seq=%s",
            handle.command, reason, handle.sequence,
        )
        return True

    def _retry_rejected_v1(self, reason) -> bool:
        """Bare "ERROR: <parse reason>": find the most recent write it can
        refer to and resend it once. Returns True if a resend was queued."""
        letter = _REJECTION_LETTERS.get(reason)
        now = time.time()
        with self._queue_condition:
            for written_at, handle in reversed(self._recent_writes):
                if now - written_at > RETRY_MATCH_WINDOW_S:
                    break
                first = handle.command[:1]
                if first in ("Q", "T", "X") or handle.sequence is not None:
                    continue
                if letter is not None and first != letter:
                    continue
                if handle.retries >= MAX_LINK_RETRIES:
                    return False
                self._recent_writes.remove((written_at, handle))
                self._requeue_front(handle.command, handle)
                break
            else:
                return False
        self.logger.warning(
            "Firmware could not parse '%s' (%s); resending once",
            handle.command, reason,
        )
        return True

    def _resolve_v2_ack(self, seq, result, reason=""):
        with self._lock:
            handle = self._pending_v2.pop(seq, None)
        if handle is None:
            self.logger.warning("Ignoring stale/unknown %s acknowledgement seq=%s", result, seq)
            return False
        handle.result = result
        handle.reason = reason
        handle.completed.set()
        return True

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def _handle_status_report(self, data: str) -> None:
        """Validate a complete telemetry report before publishing any values."""
        frame, separator, checksum = data.partition("*")
        if separator:
            if not re.fullmatch(r"[0-9A-Fa-f]{2}", checksum):
                self.checksum_failures += 1
                self.logger.warning("Bad status checksum field: %s", data)
                return
            if xor_checksum(frame) != int(checksum, 16):
                self.checksum_failures += 1
                self.logger.warning("Rejected status frame with bad checksum: %s", data)
                return
        elif self.protocol_v2 or self._status_checksum_required:
            self.checksum_failures += 1
            self.logger.warning("Rejected unchecksummed status report: %s", data)
            return

        tokens = frame.split("|")
        framed = tokens[0] == "STATUS_START"
        if framed:
            if len(tokens) != 7 or tokens[-1] != "STATUS_END":
                self.logger.warning("Rejected malformed status frame: %s", data)
                return
            tokens = tokens[1:-1]
        if len(tokens) != 5 or tokens[0] not in (("S",) if framed else ("S", "A")):
            self.logger.warning("Rejected malformed status report: %s", data)
            return
        # int()/float() also accept underscores, Unicode digits and NaN/Inf;
        # none of those are values the firmware writes onto this ASCII link.
        if not all(re.fullmatch(r"[+-]?[0-9]+", token) for token in tokens[1:4]):
            self.logger.warning("Rejected invalid status position: %s", data)
            return
        if not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", tokens[4]):
            self.logger.warning("Rejected invalid status pressure: %s", data)
            return
        pos_a, pos_b, pos_c = (int(token) for token in tokens[1:4])
        pressure = float(tokens[4])
        if (not math.isfinite(pressure) or pressure < 0
                or any(not 0 <= pos <= 4095 for pos in (pos_a, pos_b, pos_c))):
            self.logger.warning("Rejected non-finite status pressure: %s", data)
            return

        if separator and not self._status_checksum_required:
            self._status_checksum_required = True
            self.logger.info("Checksummed status telemetry detected; checksums now required")
        # Do not clamp or filter by travel limits here: a valid report of an
        # actual excursion must still reach the safety monitor immediately.
        self.status_emit.emit(pos_a, pos_b, pos_c, pressure)
        if framed and self.connected and self.serial_com:
            try:
                self._write_now("Q")
            except Exception:
                self.logger.exception("Error sending status ack")

    def handle_com(self, data):
        """Handles incoming serial messages."""
        try:
            typed = parse_diagnostic_frame(data)
            if typed is not None:
                signal, result = typed
                if signal == "firmware_identity":
                    self.firmware_driver = result["driver"]
                    self.firmware_version = result["version"]
                elif signal == "fault_emit":
                    self.baseline_valid = False
                elif signal == "calibration_result" and result["operation"] == "tare":
                    # Only the worker's STARTED/OK/DONE transaction grants authority.
                    self.baseline_valid = False
                if signal == "motion_done":
                    self.motion_done.emit(result["kind"], result["target"], result["actual"])
                else:
                    getattr(self, signal).emit(result)
                return
            # Diagnostic text must never be interpreted as telemetry, even
            # when it quotes a status frame.
            if data.startswith("LOG|"):
                self.logger.info("Firmware: %s", data[len("LOG|"):])
                return
            if data.startswith(("STATUS_START|", "S|", "A|")):
                self._handle_status_report(data)
                return

            # Firmware safety/error lines must reach the operator; they
            # were previously logged as "unrecognized" and dropped
            if data.startswith("ERROR:"):
                message = data[len("ERROR:"):].strip()
                if message in PARSE_REJECTIONS and self._retry_rejected_v1(message):
                    return  # nothing executed; the resend is queued
                self.logger.error("Firmware error: %s", message)
                self.error_emit.emit(message)
                return
            if data.startswith("WARNING:"):
                message = data[len("WARNING:"):].strip()
                self.logger.warning("Firmware warning: %s", message)
                self.warning_emit.emit(message)
                return
            if data == "RELEASED":
                self.logger.info("Firmware completed autonomous pressure release")
                self.released_emit.emit()
                return
            # Handle regular messages
            tokens = data.split("|")

            if tokens[0] == "SPEED":
                # Legacy speed settings use their own exact-value echo, so a
                # centering DONE or keepalive OK cannot confirm configuration.
                if self.protocol_v2 or not re.fullmatch(r"SPEED\|[0-9]+\|[0-9]+\|[0-9]+", data):
                    return
                command = "V" + ",".join(tokens[1:])
                with self._lock:
                    for _written_at, handle in reversed(self._recent_writes):
                        if handle.command == command and not handle.completed.is_set():
                            handle.result = "OK"
                            handle.completed.set()
                            break
            elif tokens[0] == "BUSY":
                # v1: bare BUSY; v2: BUSY|<seq>
                self.logger.warning("Firmware dropped a command: %s", data)
                if len(tokens) >= 2:
                    try:
                        seq = int(tokens[1])
                    except ValueError:
                        return
                    if not self._resolve_v2_ack(seq, "BUSY", "Firmware busy"):
                        return
                self.error_emit.emit("BUSY")
            elif tokens[0] == "ERR" and len(tokens) >= 3:
                # v2 command error: ERR|<seq>|<reason>
                reason = tokens[2]
                try:
                    seq = int(tokens[1])
                except ValueError:
                    return
                if reason in PARSE_REJECTIONS and self._retry_rejected_v2(seq, reason):
                    return  # nothing executed; the resend is queued
                self.logger.error(
                    "Firmware rejected command seq=%s: %s", tokens[1], reason
                )
                if not self._resolve_v2_ack(seq, "ERR", reason):
                    return
                self.error_emit.emit(reason)
            elif tokens[0] == "DONE":
                # v1: bare DONE; v2: DONE|<seq>
                if len(tokens) not in (1, 2):
                    return
                if len(tokens) == 2:
                    try:
                        self.last_done_seq = int(tokens[1])
                    except ValueError:
                        return
                    if not self._resolve_v2_ack(self.last_done_seq, "DONE"):
                        return
                self.done_emit.emit()
            elif (tokens[0] == "ZEROS" and len(tokens) == 3
                  and all(re.fullmatch(r"[0-9]+", t) and 0 <= int(t) <= 4095
                          for t in tokens[1:])):
                self.zeros_emit.emit(int(tokens[1]), int(tokens[2]))
            elif (tokens[0] == "P" and len(tokens) == 2
                  and re.fullmatch(r"[0-9]+", tokens[1]) and 0 <= int(tokens[1]) <= 4095):
                self.position_emit.emit(int(tokens[1]), 0, "", 0)
            elif (tokens[0] == "PR" and len(tokens) == 2
                  and math.isfinite(float(tokens[1])) and float(tokens[1]) >= 0):
                self.pressure_emit.emit(tokens[1])
            elif data == "Ready to Go":
                self._invalidate_identity()
                self.ready_event.set()
                self.ready_to_go_emit.emit()
            elif (tokens[0] == "weight" and len(tokens) == 2
                  and math.isfinite(float(tokens[1])) and float(tokens[1]) >= 0):
                self.display_weight_emit.emit(tokens[1])
            elif (
                tokens[0] == "Test command received" or "Test command received" in data
            ):
                self.logger.debug("Arduino acknowledged test command")
            elif tokens[0] == "OK":
                if len(tokens) >= 2:
                    try:
                        seq = int(tokens[1])
                    except ValueError:
                        return
                    if not self._resolve_v2_ack(seq, "OK"):
                        return
                self.ok_event.set()
            else:
                # Anything else the device says should be visible on the
                # console (INFO), not buried in debug.log
                self.logger.info("Unrecognized data format: %s", data)
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
        return self.send_tracked(command) is not None

    def send_tracked(self, command, priority=False):
        """Queue a command and return its observable lifecycle handle.

        Existing callers may continue using :meth:`send` as a boolean API.
        Reset/shutdown code uses this method when it must correlate a v2 ack or
        prove that a safety command was physically written before disconnect.
        """
        command = str(command).strip()
        if not command:
            self.logger.warning("Refusing to send empty Arduino command")
            return None

        is_emergency = command.startswith("X")
        handle = CommandHandle(command=command)
        with self._queue_condition:
            if command.startswith(("L0", "L1")) and self.firmware_driver != HX711_PROTOCOL_DRIVER:
                self.logger.error("Calibration blocked: compatible NB2 firmware not confirmed")
                return None
            # Evaluate connectivity under the same lock link-loss uses to
            # clear the queues, so a stop cannot be reported as queued and
            # then silently dropped by a concurrent _handle_link_lost
            usable = (
                self._running
                and self.serial_com is not None
                and getattr(self.serial_com, "is_open", False)
            )
            if not usable:
                self.logger.error("Cannot send '%s' - not connected", command)
                return None
            if is_emergency:
                # X stops the device, but it does not latch out later commands.
                # Discard old work atomically so it cannot restart motion after
                # the stop. New cleanup commands (P0/HF0) may still be queued.
                self._fail_pending("CANCELLED", "Superseded by emergency stop")
            if command == "Y":
                self._invalidate_identity()
                self.ready_event.clear()
            if command.startswith(("L0", "L1")):
                self.baseline_valid = False
            handle.generation = self._write_generation
            if self.protocol_v2:
                self._seq = (self._seq + 1) % 1000000
                handle.sequence = self._seq
                body = f"{self._seq}:{command}"
                command = f"#{body}*{xor_checksum(body):02X}"
                self._pending_v2[self._seq] = handle
            # Keep each write paired with its own handle, including identical
            # legacy commands and priority probes with the same wire text.
            if is_emergency or priority:
                # An emergency stop never waits in line
                self._priority_queue.append((command, handle))
            else:
                self._tx_queue.append((command, handle))
            self._queue_condition.notify_all()
        return handle
