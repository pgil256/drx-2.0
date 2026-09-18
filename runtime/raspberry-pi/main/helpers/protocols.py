from datetime import datetime
import time
import threading
import logging
from helpers.logging import setup_logger
from helpers.controller_operations import (
    ControllerOperations, OperationCancelled, OperationRejected,
)
from helpers.conversions import lateral_degrees_to_position
from helpers.motor_speed import motor_speed_command, motor_speed_values
from typing import Mapping, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import QUrl, Qt, QObject

from config.constants import (
    PRESSURE_MAX,
    AXIAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
    LATERAL_MAX_DEGREES,
    PROTOCOL_DEFAULT_SETTINGS,
    PRESSURE_BUILD_TIMEOUT_S,
    LATERAL_MOVE_TIMEOUT_S,
    PULSE_RATE_FIRMWARE_SUPPORT,
    MIN_JERK_INTERVAL_MS,
    MAX_JERK_INTERVAL_MS,
)
try:
    from main.config.constants import (
        MOTOR_SPEED_ACK_TIMEOUT_S, PRESSURE_TARGET_TOLERANCE, PRESSURE_OVERSHOOT_ALLOWANCE,
    )
except ModuleNotFoundError:  # Direct entry point: python runtime/raspberry-pi/main/kneespa.py
    from config.constants import (
        MOTOR_SPEED_ACK_TIMEOUT_S, PRESSURE_TARGET_TOLERANCE, PRESSURE_OVERSHOOT_ALLOWANCE,
    )

# Constants
DEGREES0 = PROTOCOL_DEFAULT_SETTINGS["DEGREES0"]          # Center/neutral position
MIN_PRESSURE = PROTOCOL_DEFAULT_SETTINGS["MIN_PRESSURE"]  # Minimum starting pressure in lbs
MAX_SAFE_PRESSURE = PROTOCOL_DEFAULT_SETTINGS["MAX_SAFE_PRESSURE"]  # Maximum safe pressure in lbs
HOLD_TIME_SHORT = PROTOCOL_DEFAULT_SETTINGS["HOLD_TIME_SHORT"]
HOLD_TIME_LONG = PROTOCOL_DEFAULT_SETTINGS["HOLD_TIME_LONG"]        # Default hold duration in seconds
PRESSURE_INCREMENT = PROTOCOL_DEFAULT_SETTINGS["PRESSURE_INCREMENT"]  # Standard pressure increase step
ANGLE_INCREMENT = PROTOCOL_DEFAULT_SETTINGS["ANGLE_INCREMENT"]        # Standard angle adjustment step

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    finished = QtCore.pyqtSignal(bool)
    prepared = QtCore.pyqtSignal(float, float)
    baseline_changed = QtCore.pyqtSignal(bool)
    operation_failed = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal(bool)
    error = QtCore.pyqtSignal(tuple)
    result = QtCore.pyqtSignal(object)
    progress = QtCore.pyqtSignal(str)
    pressure_emit = QtCore.pyqtSignal(float)
    status_emit = QtCore.pyqtSignal(int, int, int, float)
    reset_needed = QtCore.pyqtSignal()
    motor_speed_failed = QtCore.pyqtSignal(str)

class Protocols(QtCore.QRunnable):
    """Main protocol handler for KneeSpa treatment sequences."""

    def __init__(
        self,
        a_factor: float,
        protocol: str,
        max_pressure: int,
        max_left: float,
        max_right: float,
        duration: int,
        use_pulse: bool,
        ser=None,
        config=None,
        pulse_rate=None,
        motor_speeds: Optional[Mapping[str, float]] = None,
    ):
        """Initialize protocol handler.

        ``pulse_rate`` (pulses/sec, optional) sets the firmware pulse cadence
        when the device supports it (PULSE_RATE_FIRMWARE_SUPPORT); otherwise the
        worker falls back to a bare ``J`` (on/off) and ``pulse_rate`` only acts
        as an on/off hint. ``use_pulse`` remains the master on/off gate.
        """
        super().__init__()
        print("Initializing Protocols class...")

        # System setup
        self.logger = setup_logger(component="Protocols")
        self.arduino = ser
        self.a_factor = a_factor
        self.config = config
        self.signals = WorkerSignals()

        # Protocol parameters
        self.protocol = protocol
        self.max_pressure = max_pressure
        self.max_left = -abs(max_left)     # Ensure negative for left
        self.max_right = abs(max_right)    # Ensure positive for right
        self.duration = duration * 60      # Convert to seconds
        self.use_pulse = use_pulse
        self.pulse_rate = pulse_rate       # pulses/sec, or None for bare-J
        self.motor_speeds = None if motor_speeds is None else motor_speed_values(motor_speeds)

        # State tracking
        self.is_running = False
        self.is_paused = False
        self._pause_started = None
        self.start_time = None
        self.elapsed_time = 0
        self._state_lock = threading.Lock()
        self._command_lock = threading.RLock()
        self._stop_requested = threading.Event()
        self._firmware_stopped = False
        self.completed = threading.Event()
        self._operations = None
        self._run_success = False
        self._failure_reason = ""
        self._terminal_failure = threading.Event()
        self._current_pressure = 0.0
        self._current_pos_c = 0
        self.target_pos_c = None
        self.angle_set = False
        self._last_overpressure_correction = 0.0
        # Live Treatment-slider requests originate on the Qt UI thread and are
        # consumed by the protocol worker. Revisions coalesce rapid slider
        # movement and ensure a newer request cannot be cleared by an older
        # command that is still completing.
        self._live_settings_lock = threading.Lock()
        self._pressure_revision = 0
        self._applied_pressure_revision = 0
        self._angle_revisions = {"left": 0, "right": 0}
        self._applied_angle_revisions = {"left": 0, "right": 0}
        self._pulse_revision = 0
        self._applied_pulse_revision = 0
        self._active_lateral_side = None
        self._live_phase = False
        # Firmware pulsing believed active (a J was sent and no JS since).
        # GUI-thread paths (pause, pulse slider -> 0) consult this before
        # sending JS: on pre-FAILSAFE-6 firmware JS zeroes whichever SMC was
        # last addressed, so a JS during the ramp or a lateral move stalled
        # that move and failed the treatment.
        self._pulse_active = False
        # Firmware acks consumed by the worker thread: DONE closes the
        # pressure move the worker last commanded; BUSY means the firmware
        # refused the command outright (J while an axial move is still
        # driving), so the worker must retry rather than assume success.
        self._move_done = threading.Event()
        self._busy_seen = threading.Event()
        self._pulse_retry_after = 0.0

        # Connect signals if arduino is provided
        if ser is not None:
            ser.fault_emit.connect(self._on_controller_fault, Qt.DirectConnection)
            ser.command_rejected.connect(self._on_command_rejected, Qt.DirectConnection)
            ser.connection_lost.connect(self._on_link_lost, Qt.DirectConnection)
        if ser is not None and hasattr(ser, "done_emit"):
            try:
                ser.done_emit.disconnect(self._on_firmware_done)
            except Exception:
                pass
            ser.done_emit.connect(self._on_firmware_done)
        if ser is not None and hasattr(ser, "error_emit"):
            try:
                ser.error_emit.disconnect(self._on_firmware_error)
            except Exception:
                pass
            ser.error_emit.connect(self._on_firmware_error)
        if ser is not None and hasattr(ser, "status_emit"):
            # First disconnect any existing connections to avoid duplicates
            try:
                ser.status_emit.disconnect(self.update_status)
            except Exception:
                pass  # Ignore if not previously connected
                
            # Now connect the signal
            ser.status_emit.connect(self.update_status)
            print("Protocol: Connected Arduino status_emit signal to update_status method")
        else:
            print("WARNING: Arduino object missing status_emit signal - status updates won't work!")

        print(f"Protocols class initialized with use_pulse={use_pulse}")

    def _send_command(self, command: str) -> bool:
        """Serialize cancellation with enqueueing, including live UI updates."""
        with self._command_lock:
            if self._stop_requested.is_set():
                return False
            return bool(self.arduino.send(command))

    def cancel(self, firmware_stopped: bool = False) -> None:
        """Cancel this worker permanently without sending device commands."""
        with self._command_lock:
            self._stop_requested.set()
            self._firmware_stopped = self._firmware_stopped or firmware_stopped
            self.is_running = False
            self.is_paused = False
            self._pause_started = None
            self._pulse_active = False
        self._disconnect_status()

    def _on_controller_fault(self, result: dict) -> None:
        self._failure_reason = "Controller fault: " + result["reason"]
        self._terminal_failure.set()
        self.cancel(firmware_stopped=True)

    def _on_command_rejected(self, result: dict) -> None:
        self._failure_reason = "{}: {}".format(result["command"], result["reason"])
        self._terminal_failure.set()
        self.cancel()
        self.arduino.send("X")

    def _on_link_lost(self) -> None:
        self._on_controller_fault({"reason": "DISCONNECTED"})

    @property
    def current_pressure(self) -> float:
        with self._state_lock:
            return self._current_pressure

    @current_pressure.setter
    def current_pressure(self, value: float):
        with self._state_lock:
            self._current_pressure = float(value)

    @property
    def current_pos_c(self) -> int:
        with self._state_lock:
            return self._current_pos_c

    @current_pos_c.setter
    def current_pos_c(self, value: int):
        with self._state_lock:
            self._current_pos_c = int(value)

    def update_status(self, pos_a, pos_b, pos_c, pressure):
        """Update current status values from Arduino feedback."""
        # Store values with explicit type conversion
        self.current_pressure = float(pressure)
        self.current_pos_c = int(pos_c)

        # Emit separate pressure signal for dialogs and UI updates
        self.signals.pressure_emit.emit(float(pressure))
        
        # Also emit the full status update for other components
        print(f"Protocol emitting status_emit with all values")
        self.signals.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))

    def check_duration(self) -> bool:
        """Check if protocol duration has expired.

        While paused, elapsed time is frozen at the moment pause began so the
        protocol never expires mid-pause (resume() shifts ``start_time`` past the
        paused span to keep the post-resume clock correct)."""
        if not self.start_time:
            print("Warning: No start time set for duration check")
            return False

        now = time.time()
        if self.is_paused and self._pause_started is not None:
            now = self._pause_started  # freeze the clock during a pause

        self.elapsed_time = now - self.start_time

        # Only print status every 15 seconds
        if int(self.elapsed_time) % 15 == 0:
            print(f"Duration check - Elapsed: {self.elapsed_time:.1f}s / Total: {self.duration}s")

        return self.elapsed_time < self.duration

    # ----- Pause / Resume (Phase 3.5 §15.1) -------------------------------
    # Pause HOLDS: it stops issuing new pressure/position commands and freezes
    # the phase clock, but never sends an emergency stop ('X') — the firmware
    # keeps holding the last commanded pressure/position. Pulsing is stopped on
    # pause and re-armed on resume so the limb is held static while paused.
    def pause(self):
        """Hold the running protocol (no-op if not running or already paused)."""
        if not self.is_running or self.is_paused:
            return
        print("Protocol pause requested — holding")
        self.is_paused = True
        self._pause_started = time.time()
        # Stop an ACTIVE firmware pulse so the limb is held static (NOT 'X').
        # Unconditional JS used to stall an in-flight ramp/lateral move on
        # the deployed firmware (see _pulse_active).
        if self._pulse_active and not self._send_pulse_stop():
            print("Error stopping pulse on pause")

    def resume(self):
        """Resume a paused protocol, shifting the clock past the paused span."""
        if not self.is_running or not self.is_paused:
            return
        print("Protocol resume requested")
        if self._pause_started is not None and self.start_time is not None:
            self.start_time += (time.time() - self._pause_started)
        self._pause_started = None
        self.is_paused = False

    def _wait_while_paused(self):
        """Block the worker thread while paused (cooperative; respects stop)."""
        while self.is_running and self.is_paused:
            time.sleep(0.1)

    # ----- Live treatment settings ---------------------------------------
    def request_live_pressure(self, value: float) -> bool:
        """Queue a new pressure ceiling for the active protocol.

        The worker applies increases in normal pressure increments and applies
        decreases directly. Hardware commands stay on the protocol thread so a
        slider event cannot race an in-flight pressure or lateral move.
        """
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        if value < 0 or value > MAX_SAFE_PRESSURE:
            return False
        with self._live_settings_lock:
            self.max_pressure = value
            self._pressure_revision += 1
        return True

    def request_live_angle(self, side: str, value: float) -> bool:
        """Queue a left or right lateral limit for the active protocol."""
        if side not in ("left", "right"):
            return False
        try:
            value = abs(float(value))
        except (TypeError, ValueError):
            return False
        if value > abs(LATERAL_MAX_DEGREES):
            return False
        with self._live_settings_lock:
            if side == "left":
                self.max_left = -value
            else:
                self.max_right = value
            self._angle_revisions[side] += 1
        return True

    def request_live_pulse_rate(self, value: float) -> bool:
        """Queue a pulse cadence change; zero stops pulsing immediately."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        max_rate = 1000.0 / MIN_JERK_INTERVAL_MS
        if value < 0 or value > max_rate:
            return False
        with self._live_settings_lock:
            self.pulse_rate = value
            self.use_pulse = value > 0
            self._pulse_revision += 1

        # Turning pulsing off is a safety-reducing action and must not wait for
        # the worker to leave a blocking pressure/position wait. Arduino.send()
        # is thread-safe and only enqueues onto the single-owner I/O thread.
        # Only when pulsing is actually active, though: otherwise the worker
        # simply never starts it (see _pulse_active for why JS is not free).
        if value == 0 and self.is_running and self.arduino and self._pulse_active:
            return self._send_pulse_stop()
        return True

    def _mark_angle_applied(self, side: str) -> None:
        with self._live_settings_lock:
            self._applied_angle_revisions[side] = self._angle_revisions[side]

    def _apply_live_pressure_target(self, target: float) -> bool:
        """Apply a live pressure target without bypassing the ramp limit."""
        current = float(self.current_pressure)
        if target == current:
            return True
        if target < current:
            return self.set_to_pressure(target)

        command = current
        while self.is_running and command < target:
            command = min(target, command + PRESSURE_INCREMENT)
            if not self.set_to_pressure(command):
                return False
        return self.is_running

    def _sync_live_pulse(self, pulse_active: bool) -> Tuple[bool, bool]:
        """Bring firmware pulse on/off and cadence in sync with the slider."""
        with self._live_settings_lock:
            use_pulse = self.use_pulse
            revision = self._pulse_revision

        if self.is_paused or not use_pulse:
            if pulse_active and self.arduino and not self._send_pulse_stop():
                return False, pulse_active
            with self._live_settings_lock:
                self._applied_pulse_revision = revision
            return True, False

        if not pulse_active or revision != self._applied_pulse_revision:
            if pulse_active and revision != self._applied_pulse_revision:
                if not self._send_pulse_stop():
                    return False, pulse_active
            if not self._start_pulse():
                return False, pulse_active
            pulse_active = self._pulse_active  # False while firmware is busy
            if pulse_active:
                with self._live_settings_lock:
                    self._applied_pulse_revision = revision
        return True, pulse_active

    def _service_live_motion_updates(
        self, pulse_active: bool
    ) -> Tuple[bool, bool]:
        """Apply coalesced pressure/angle requests on the protocol thread."""
        with self._live_settings_lock:
            pressure_revision = self._pressure_revision
            pressure_target = float(self.max_pressure)
            side = self._active_lateral_side
            angle_revision = self._angle_revisions.get(side, 0)
            angle_target = (
                self.max_left if side == "left"
                else self.max_right if side == "right"
                else None
            )
            pressure_pending = pressure_revision != self._applied_pressure_revision
            angle_pending = (
                side is not None
                and angle_revision != self._applied_angle_revisions[side]
            )

        if not pressure_pending and not angle_pending:
            return True, pulse_active

        # Pressure and position moves must not compete with axial pulsing.
        if pulse_active:
            if not self._send_pulse_stop():
                return False, pulse_active
            pulse_active = False

        if pressure_pending:
            if not self._apply_live_pressure_target(pressure_target):
                return False, pulse_active
            with self._live_settings_lock:
                self._applied_pressure_revision = pressure_revision

        if angle_pending:
            if not self.set_to_c_distance(angle_target):
                return False, pulse_active
            with self._live_settings_lock:
                self._applied_angle_revisions[side] = angle_revision

        return self._sync_live_pulse(pulse_active)

    def _start_pulse(self) -> bool:
        """Start firmware pulsing. Sends ``J<interval_ms>`` only on a flashed
        device (PULSE_RATE_FIRMWARE_SUPPORT); otherwise a bare ``J`` so the old
        firmware keeps working."""
        cmd = "J"
        if (PULSE_RATE_FIRMWARE_SUPPORT and self.pulse_rate
                and self.pulse_rate > 0):
            interval = int(round(1000.0 / self.pulse_rate))
            interval = max(MIN_JERK_INTERVAL_MS, min(MAX_JERK_INTERVAL_MS, interval))
            cmd = f"J{interval}"
        if time.time() < self._pulse_retry_after:
            return True  # backing off after a BUSY; not active yet
        self._busy_seen.clear()
        if not self._send_command(cmd):
            return False
        # The firmware answers BUSY (and does nothing) if an axial pressure
        # move or a position move is still running. Give that reply a moment
        # to arrive before believing the pulse is on.
        deadline = time.time() + 0.3
        while time.time() < deadline and not self._busy_seen.is_set():
            time.sleep(0.02)
        if self._busy_seen.is_set():
            self._busy_seen.clear()
            self._pulse_active = False
            self._pulse_retry_after = time.time() + 1.0
            print("Firmware busy; pulse start deferred, will retry")
            return True
        self._pulse_active = True
        return True

    def _send_pulse_stop(self) -> bool:
        """Send ``JS`` and record that firmware pulsing is no longer active."""
        if self._stop_requested.is_set():
            return True  # The stop path owns cleanup; do not disturb its release.
        if not self.arduino:
            self._pulse_active = False
            return False
        try:
            ok = self._send_command("JS")
        except Exception as e:
            print(f"Error sending JS: {e}")
            ok = False
        if ok:
            self._pulse_active = False
        return ok

    def _on_firmware_done(self):
        """Unqualified DONE used by the legacy pressure-settling wait.

        Clearing this event removes already-received acknowledgements, but a
        later DONE can belong to another command. It cannot prove lateral arrival.
        """
        self._move_done.set()

    def _on_firmware_error(self, message):
        if message == "BUSY":
            self._busy_seen.set()

    def _disconnect_status(self):
        """Detach from the Arduino signals once this run is over.

        The per-run connect in __init__ was never undone, so every finished
        worker kept being invoked on every status frame for the kiosk's
        uptime (N workers after N treatments)."""
        ser = self.arduino
        if ser is None:
            return
        for signal_name, slot in (
            ("done_emit", self._on_firmware_done),
            ("error_emit", self._on_firmware_error),
            ("fault_emit", self._on_controller_fault),
            ("command_rejected", self._on_command_rejected),
            ("connection_lost", self._on_link_lost),
        ):
            sig = getattr(ser, signal_name, None)
            if sig is None:
                continue
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        if not hasattr(ser, "status_emit"):
            return
        try:
            ser.status_emit.disconnect(self.update_status)
        except (TypeError, RuntimeError):
            pass  # already disconnected / signal gone

    def _check_cancelled(self) -> None:
        if self._stop_requested.is_set() or not self.is_running:
            raise OperationCancelled("Treatment cancelled")

    def _send_tracked(self, command: str) -> object:
        with self._command_lock:
            self._check_cancelled()
            return self.arduino.send_tracked(command)

    def _perform(self, command: str, expected: tuple, timeout: float) -> bool:
        operations = self._operations
        temporary = operations is None
        if temporary:
            operations = ControllerOperations(self.arduino, self._send_tracked, self._check_cancelled)
        try:
            operations.perform(command, expected, timeout)
            return True
        except OperationCancelled:
            return False
        except Exception as exc:
            self._failure_reason = str(exc)
            self.logger.error("Controller operation failed: %s", exc)
            return False
        finally:
            if temporary:
                operations.close()

    def run_pressure_sequence(self, starting_pressure: float, target_pressure: float) -> bool:
        """Send each new waypoint once and require proof that its motor stopped."""
        if not (0 <= starting_pressure <= MAX_SAFE_PRESSURE
                and 0 <= target_pressure <= MAX_SAFE_PRESSURE):
            return False
        command = float(starting_pressure)  # _preamble already completed this waypoint.
        while self.is_running:
            self._wait_while_paused()
            target_pressure = min(float(self.max_pressure), float(MAX_SAFE_PRESSURE))
            if command == target_pressure:
                return True
            command = min(target_pressure, command + PRESSURE_INCREMENT)
            if not self.set_to_pressure(command):
                return False
        return False

    def set_to_pressure(self, target_pressure: float) -> bool:
        """Wait for a typed P completion and its ack, never just nearby telemetry."""
        self._wait_while_paused()
        if not self.is_running or not 0 <= target_pressure <= MAX_SAFE_PRESSURE:
            return False
        selected = max(float(target_pressure), float(self.max_pressure)) if target_pressure else 0
        low = (float(target_pressure) if target_pressure > self.current_pressure
               else max(0, float(target_pressure) - PRESSURE_TARGET_TOLERANCE))
        high = min(100, selected + PRESSURE_OVERSHOOT_ALLOWANCE) if target_pressure else 2
        return self._perform(
            f"P{target_pressure:g}|{selected:g}",
            ("motion", "P", float(target_pressure), low, high), PRESSURE_BUILD_TIMEOUT_S,
        )

    def set_to_c_distance(self, degrees: float) -> bool:
        """Serialize lateral arrival before any subsequent pressure/pulse command."""
        self._wait_while_paused()
        if not self.is_running:
            return False
        try:
            position, degrees = lateral_degrees_to_position(self.config.CMarks, degrees)
            self.target_pos_c = position
            self.angle_set = self._perform(
                f"K{position}", ("motion", "K", position, max(0, position - 100),
                                min(4095, position + 100)), LATERAL_MOVE_TIMEOUT_S,
            )
            return self.angle_set
        except (TypeError, ValueError) as exc:
            self._failure_reason = str(exc)
            return False

    # ------------------------------------------------------------------
    # Shared protocol phases
    #
    # protocol_1..4 used to be four ~90%-duplicated copies of the same
    # sequence; fixes did not propagate between them (the reset_needed
    # safety emit existed only in 2/3, the post-centering settle only in
    # 3/4, and a too-short duration exited without emitting finished,
    # leaving the UI stuck on "Stop").
    # ------------------------------------------------------------------

    def _fail(self, reason: str, reset_needed: bool = False) -> bool:
        """Defer the terminal signal until all worker cleanup has finished."""
        self._failure_reason = self._failure_reason or reason
        self.logger.error("Protocol %s failed: %s", self.protocol, self._failure_reason)
        self.is_running = False
        self._run_success = False
        return False

    def _initial_pressure(self) -> float:
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            print(
                f"Setting higher initial pressure of {initial_pressure} lbs "
                f"for max_pressure={self.max_pressure}"
            )
        return initial_pressure

    def _preamble(self, banner: str) -> bool:
        """Duration guard, banner, initial pressure, ramp to setpoint."""
        if not self.check_duration():
            return self._fail("duration already elapsed before start")
        self.signals.progress.emit(banner)

        initial_pressure = self._initial_pressure()
        if not self.set_to_pressure(initial_pressure):
            return self._fail("initial pressure not reached")
        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            return self._fail("pressure ramp failed")
        return True

    def _pulse_or_hold_phase(self) -> bool:
        """Run a hold that responds to every live Treatment setting."""
        if not self.is_running:
            return True

        self._live_phase = True
        pulse_active = False
        pulse_stop_failed = False
        last_keepalive_time = time.time()
        print(
            f"Protocol {self.protocol}: entering pulse/hold phase "
            f"(use_pulse={self.use_pulse})"
        )
        try:
            while self.is_running and self.check_duration():
                if self.is_paused:
                    ok, pulse_active = self._sync_live_pulse(pulse_active)
                    if not ok:
                        return self._fail("could not stop pulse for pause")
                    self._wait_while_paused()
                    continue

                ok, pulse_active = self._service_live_motion_updates(pulse_active)
                if not ok:
                    return self._fail(
                        "live treatment setting could not be applied",
                        reset_needed=True,
                    )
                ok, pulse_active = self._sync_live_pulse(pulse_active)
                if not ok:
                    return self._fail("pulse update failed", reset_needed=True)

                if time.time() - last_keepalive_time >= 30:
                    if not self._send_command("T"):
                        return self._fail("keepalive failed")
                    last_keepalive_time = time.time()
                time.sleep(0.2)
        finally:
            self._live_phase = False
            if pulse_active and self.arduino and not self._send_pulse_stop():
                self.logger.error("Could not stop pulse while leaving hold phase")
                pulse_stop_failed = True
        if pulse_stop_failed:
            return self._fail("could not send final JS")
        return True

    def _release(self, center_first: bool) -> bool:
        """Return to neutral: center laterally if needed, then release."""
        if center_first:
            if not self.set_to_c_distance(0):
                return self._fail("could not return to center")
            time.sleep(1)  # settle at center before releasing traction
        if not self.set_to_pressure(0):
            return self._fail("could not release pressure")
        print(f"Protocol {self.protocol} complete")
        self.signals.progress.emit("Retracting and zeroing resting pressure")
        self.signals.baseline_changed.emit(False)
        try:
            self._operations.baseline(self.config, retract=True)
            with self._command_lock:
                self._check_cancelled()
                self.arduino.baseline_valid = True
                self._run_success = True
                self.signals.baseline_changed.emit(True)
        except OperationCancelled:
            return False
        except Exception as exc:
            return self._fail(str(exc))
        self.signals.progress.emit("Protocol complete")
        return True

    def _run_standard_protocol(
        self, banner: str, target_side: Optional[str] = None
    ) -> None:
        """Protocols 1-3: ramp, optional lateral move, pulse/hold, release."""
        if not self._preamble(banner):
            return

        moved_lateral = False
        if self.is_running and target_side is not None:
            self._active_lateral_side = target_side
            target_angle = (
                self.max_left if target_side == "left" else self.max_right
            )
            print(f"Moving to {target_angle}°")
            if not self.set_to_c_distance(target_angle):
                self._fail("lateral positioning failed")
                return
            self._mark_angle_applied(target_side)
            moved_lateral = True

        if not self._pulse_or_hold_phase():
            return

        self._release(center_first=moved_lateral)
        self._active_lateral_side = None

    def protocol_1(self):
        """Axial protocol - pressure only."""
        print("Running protocol 1...")
        self._run_standard_protocol(">>Starting axial protocol", None)

    def protocol_2(self):
        """Axial with left lateral movement."""
        print("Running protocol 2...")
        self._run_standard_protocol(
            ">>Starting left lateral protocol", "left"
        )

    def protocol_3(self):
        """Axial with right lateral movement."""
        print("Running protocol 3...")
        self._run_standard_protocol(
            ">>Starting right lateral protocol", "right"
        )

    def protocol_4(self):
        """Axial with oscillating lateral movement between left and right."""
        print("Running protocol 4...")
        if not self._preamble(">>Starting oscillating lateral protocol"):
            return

        oscillation_period = 30
        hold_at_extreme = 2
        position_at_left = True
        last_position_change = time.time()
        last_keepalive_time = time.time()
        pulse_active = False
        pulse_stop_failed = False
        self._active_lateral_side = "left"
        self._live_phase = True

        try:
            print(
                f"Starting oscillation between {self.max_left}° "
                f"and {self.max_right}°"
            )
            if not self.set_to_c_distance(self.max_left):
                self._fail("initial lateral positioning failed")
                return
            self._mark_angle_applied("left")

            while self.is_running and self.check_duration():
                if self.is_paused:
                    ok, pulse_active = self._sync_live_pulse(pulse_active)
                    if not ok:
                        self._fail("could not stop pulse for pause")
                        return
                    self._wait_while_paused()
                    last_position_change = time.time()
                    continue

                ok, pulse_active = self._service_live_motion_updates(pulse_active)
                if not ok:
                    self._fail(
                        "live treatment setting could not be applied",
                        reset_needed=True,
                    )
                    return
                ok, pulse_active = self._sync_live_pulse(pulse_active)
                if not ok:
                    self._fail("pulse update failed", reset_needed=True)
                    return

                current_time = time.time()
                if current_time - last_position_change >= oscillation_period / 2:
                    if pulse_active:
                        if not self._send_pulse_stop():
                            self._fail("could not stop pulse for lateral move")
                            return
                        pulse_active = False

                    side = "right" if position_at_left else "left"
                    self._active_lateral_side = side
                    target = self.max_right if side == "right" else self.max_left
                    print(f"Oscillating to {side} {target}°")
                    self.signals.progress.emit(f">>Moving to {side} {target}°")
                    if not self.set_to_c_distance(target):
                        self._fail("oscillation move failed")
                        return
                    self._mark_angle_applied(side)
                    position_at_left = side == "left"
                    last_position_change = time.time()

                    hold_start = time.time()
                    while (
                        time.time() - hold_start < hold_at_extreme
                        and self.is_running
                        and self.check_duration()
                    ):
                        time.sleep(0.1)

                ok, pulse_active = self._sync_live_pulse(pulse_active)
                if not ok:
                    self._fail("could not restart pulse", reset_needed=True)
                    return

                if current_time - last_keepalive_time >= 30:
                    if not self._send_command("T"):
                        self._fail("keepalive failed")
                        return
                    last_keepalive_time = current_time
                time.sleep(0.1)
        finally:
            self._live_phase = False
            self._active_lateral_side = None
            if pulse_active and self.arduino and not self._send_pulse_stop():
                self.logger.error("Could not stop pulse while leaving protocol 4")
                pulse_stop_failed = True
        if pulse_stop_failed:
            self._fail("could not stop final pulsing")
            return
        self._release(center_first=True)

    def _configure_motor_speeds(self) -> bool:
        """Require firmware acceptance before dispatching treatment motion."""
        if self.motor_speeds is None:
            return True  # Legacy callers that do not expose speed controls.
        command = motor_speed_command(self.motor_speeds)
        with self._command_lock:
            if self._stop_requested.is_set():
                return False
            handle = self.arduino.send_tracked(command)
        if handle is None:
            return False
        deadline = time.monotonic() + MOTOR_SPEED_ACK_TIMEOUT_S
        while not handle.completed.is_set():
            if self._stop_requested.is_set() or time.monotonic() >= deadline:
                return False
            handle.completed.wait(0.05)
        return handle.result == "OK"

    def run(self) -> None:
        """Prepare, run, retract/zero on success, then publish one terminal result."""
        try:
            with self._command_lock:
                self.is_running = not self._stop_requested.is_set()
            self._check_cancelled()
            self._operations = ControllerOperations(
                self.arduino, self._send_tracked, self._check_cancelled,
            )
            self._operations.require_firmware()
            # X discards queued commands: enable telemetry AFTER stopping old work.
            if not self._send_command("X") or not self._send_command("HF1"):
                raise OperationRejected("Cannot prepare controller")
            self.signals.progress.emit("Preparing: centering and zeroing resting pressure")
            self.signals.baseline_changed.emit(False)
            if not self.set_to_c_distance(0):
                raise OperationRejected(self._failure_reason or "Lateral centering failed")
            self._operations.baseline(self.config)
            if not self._configure_motor_speeds():
                raise OperationRejected("Controller did not accept treatment motor speeds")
            with self._command_lock:
                self._check_cancelled()
                self.arduino.baseline_valid = True
                self.signals.baseline_changed.emit(True)
                self.start_time = time.time()
                self.signals.prepared.emit(self.start_time, time.monotonic())
            handler = getattr(self, "protocol_" + self.protocol, None)
            if handler is None:
                raise OperationRejected("Unknown protocol " + self.protocol)
            handler()
        except OperationCancelled:
            pass
        except Exception as exc:
            self._fail(str(exc))
        finally:
            if not self._stop_requested.is_set() and not self._run_success:
                self._send_command("X")
                self.arduino.baseline_valid = False
                self.signals.baseline_changed.emit(False)
            if self._operations is not None:
                self._operations.close()
                self._operations = None
            self._disconnect_status()
            self.is_running = False
            self.completed.set()
            if self._failure_reason and (self._terminal_failure.is_set()
                                         or not self._stop_requested.is_set()):
                self.signals.operation_failed.emit(self._failure_reason)
            self.signals.finished.emit(self._run_success and not self._stop_requested.is_set())

    def stop(self):
        """Safely stop a running protocol and release applied traction.

        The screw actuators hold whatever force was applied when motion
        stops, so a stop is not safe until the load is actively backed
        off ("P0"). Connection health is owned by the Arduino transport;
        the old 60s keepalive thread this method used to spawn per stop
        flushed buffers and fought reconnects concurrently with whatever
        the user started next.
        """
        print("Initiating protocol stop sequence...")
        self.cancel()
        if self._firmware_stopped:
            # X aborts firmware's autonomous release, and P0 is rejected while
            # the physical button is held. Leave that release in control.
            self.signals.stopped.emit(True)
            return

        if not self.arduino:
            print("Warning: No Arduino connection available for stop sequence")
            self.signals.stopped.emit(True)
            return

        try:
            # Emergency stop first: halts pulsing/motion immediately
            # (X jumps the transport's queue and the firmware's limiter)
            stop_sent = self.arduino.send("X")
            print(f"Emergency stop command sent: {'Success' if stop_sent else 'FAILED'}")
            self._pulse_active = False  # X halts pulsing along with everything else

            # Actively release traction; the firmware ramps the axial
            # actuator back until the load cell reads zero
            release_sent = self.arduino.send("P0")
            print(f"Pressure release command sent: {'Success' if release_sent else 'FAILED'}")

            # Telemetry continues during the release via the firmware's
            # active-motion status path even after HF mode is off
            self.arduino.send("HF0")

            self.signals.stopped.emit(stop_sent and release_sent)

        except Exception as e:
            print(f"Error during protocol stop: {e}")
            self.signals.stopped.emit(False)
