from datetime import datetime
import time
import threading
import logging
from helpers.logging import setup_logger
from helpers.conversions import lateral_degrees_to_position
from typing import Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import QUrl, Qt, QObject

from config.constants import (
    PRESSURE_MAX,
    AXIAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
    LATERAL_MAX_DEGREES,
    PROTOCOL_DEFAULT_SETTINGS,
    PULSE_RATE_FIRMWARE_SUPPORT,
    MIN_JERK_INTERVAL_MS,
    MAX_JERK_INTERVAL_MS,
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
    stopped = QtCore.pyqtSignal(bool)
    error = QtCore.pyqtSignal(tuple)
    result = QtCore.pyqtSignal(object)
    progress = QtCore.pyqtSignal(str)
    pressure_emit = QtCore.pyqtSignal(float)
    status_emit = QtCore.pyqtSignal(int, int, int, float)
    reset_needed = QtCore.pyqtSignal()

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

        # State tracking
        self.is_running = False
        self.is_paused = False
        self._pause_started = None
        self.start_time = None
        self.elapsed_time = 0
        self._state_lock = threading.Lock()
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

        # Connect signals if arduino is provided
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

        # Honor a lowered setpoint in ANY phase: if the operator reduced
        # max_pressure mid-protocol and the applied load exceeds it,
        # actively command a back-off (rate-limited to avoid spamming)
        try:
            max_p = float(self.max_pressure)
            if (
                self.is_running
                and float(pressure) > max_p + 3
                and time.time() - self._last_overpressure_correction > 3.0
            ):
                self._last_overpressure_correction = time.time()
                print(
                    f"Applied pressure {pressure} exceeds setpoint {max_p}; "
                    "commanding back-off"
                )
                if self._live_phase and not self.is_paused:
                    # Route through the worker: its hold loop stops pulsing
                    # first (JS), applies the target, then re-arms. A direct
                    # P from this GUI-thread slot raced the pulse handler for
                    # the axial SMC.
                    with self._live_settings_lock:
                        self._pressure_revision += 1
                elif self.is_paused:
                    # Held static: nothing else is driving the axial SMC
                    self.arduino.send(f"P{max_p}")
                # During the ramp the worker's own pressure sequence is in
                # control of the axial SMC; leave it alone.
        except Exception as e:
            print(f"Setpoint check error: {e}")

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
        if abs(target - current) <= 2:
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
            if not self._start_pulse():
                return False, pulse_active
            pulse_active = True
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
        ok = bool(self.arduino.send(cmd))
        if ok:
            self._pulse_active = True
        return ok

    def _send_pulse_stop(self) -> bool:
        """Send ``JS`` and record that firmware pulsing is no longer active."""
        if not self.arduino:
            self._pulse_active = False
            return False
        try:
            ok = bool(self.arduino.send("JS"))
        except Exception as e:
            print(f"Error sending JS: {e}")
            ok = False
        if ok:
            self._pulse_active = False
        return ok

    def _disconnect_status(self):
        """Detach from the Arduino status signal once this run is over.

        The per-run connect in __init__ was never undone, so every finished
        worker kept being invoked on every status frame for the kiosk's
        uptime (N workers after N treatments)."""
        ser = self.arduino
        if ser is None or not hasattr(ser, "status_emit"):
            return
        try:
            ser.status_emit.disconnect(self.update_status)
        except (TypeError, RuntimeError):
            pass  # already disconnected / signal gone

    def run_pressure_sequence(self, starting_pressure: float, target_pressure: float) -> bool:
            """Run a sequence of pressure increases from start to target."""
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                print(f"Error: Pressure {target_pressure} outside safe range (0-{MAX_SAFE_PRESSURE})")
                return False

            current_command = starting_pressure
            pressure_tolerance = 3  # Acceptable pressure difference in lbs
            # Backstop above the firmware's own bounds (5s stall / 30s move
            # timeout); firmware ERRORs flip is_running and exit early --
            # see set_to_pressure for the full rationale
            max_wait_time = 35  # max time to wait for pressure (seconds)
            max_retries = 5    # Increased max retries
            check_interval = 0.5  # Time between pressure checks in seconds
            last_check_time = 0  # Track when we last printed a status update
            
            # Initial pressure command — hold before issuing it if paused.
            self._wait_while_paused()
            if not self.is_running:
                return False
            print(f"Increasing pressure to: {current_command} lbs")
            if not self.arduino.send(f"P{current_command}"):
                print(f"Failed to send pressure command P{current_command}")
                return False

            # Wait for initial pressure to build with less frequent status checks
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time:
                if not self.is_running:
                    print("Emergency stop during initial pressure build")
                    return False
                if self.is_paused:
                    self._wait_while_paused()
                    wait_start = time.time()  # restart the window after a pause
                    continue
                if self.current_pressure >= current_command - pressure_tolerance:
                    break
                # Avoid excessive status printing
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    last_check_time = current_time
                    print(f"Initial pressure build - Target: {current_command}, Current: {self.current_pressure}")
                time.sleep(1)  # Longer sleep to reduce polling
            else:
                print(
                    "Initial pressure did not reach target within timeout: "
                    f"target={current_command}, current={self.current_pressure}"
                )
                return False

            # Step through pressure increments with reduced monitoring.
            # The target re-reads self.max_pressure each step so an
            # operator's mid-protocol setpoint change takes effect during
            # the ramp instead of being silently ignored.
            while True:
                if not self.is_running:
                    print("Emergency stop during pressure ramp")
                    return False
                # Pause must HOLD: never escalate pressure while paused.
                self._wait_while_paused()
                if not self.is_running:
                    return False
                target_pressure = min(float(self.max_pressure), float(MAX_SAFE_PRESSURE))
                if current_command >= (target_pressure - PRESSURE_INCREMENT / 2):
                    break
                current_command += PRESSURE_INCREMENT
                # Clamp to target to prevent floating-point overshoot
                current_command = min(current_command, target_pressure)
                print(f"Increasing pressure to: {current_command} lbs")
                if not self.arduino.send(f"P{current_command}"):
                    print(f"Failed to send pressure command P{current_command}")
                    return False

                # Wait for current increment to stabilize before next increment
                increment_start = time.time()
                increment_stable = False

                while time.time() - increment_start < max_wait_time:
                    if not self.is_running:
                        print("Emergency stop during pressure stabilization")
                        return False
                    if self.is_paused:
                        self._wait_while_paused()
                        increment_start = time.time()  # restart the window after a pause
                        continue
                    # Check if this increment is stable before moving to next
                    if abs(self.current_pressure - current_command) <= pressure_tolerance:
                        print(f"Pressure increment stabilized at {self.current_pressure} lbs")
                        increment_stable = True
                        break
                    time.sleep(0.2)

                if not increment_stable:
                    print(f"Pressure increment {current_command} not stabilized")
                    return False

                # Small delay between increments
                time.sleep(2.0)

            # Send final pressure command (re-read the live setpoint) — hold
            # before issuing it if paused.
            self._wait_while_paused()
            if not self.is_running:
                return False
            target_pressure = min(float(self.max_pressure), float(MAX_SAFE_PRESSURE))
            print(f"Setting final pressure: {target_pressure} lbs")
            final_attempt_start = time.time()
            if not self.arduino.send(f"P{target_pressure}"):
                print(f"Failed to send final pressure command P{target_pressure}")
                return False
            
            # Wait and verify with extended monitoring for final pressure
            retry_count = 0
            final_stabilized = False
            max_final_wait_time = 15  # Longer wait for final pressure to stabilize
            
            while retry_count < max_retries and not final_stabilized:
                if not self.is_running:
                    print("Emergency stop during final pressure verification")
                    return False
                wait_start = time.time()
                last_check_time = 0

                # Give pressure time to stabilize
                while time.time() - wait_start < max_wait_time:
                    if not self.is_running:
                        print("Emergency stop during final pressure wait")
                        return False
                    if self.is_paused:
                        self._wait_while_paused()
                        wait_start = time.time()  # restart the window after a pause
                        continue
                    final_diff = abs(target_pressure - self.current_pressure)
                    
                    # Only print status updates periodically
                    current_time = time.time()
                    if current_time - last_check_time >= check_interval:
                        last_check_time = current_time
                        print(f"Pressure check - Target: {target_pressure}, Current: {self.current_pressure}, Difference: {final_diff} lbs")
                    
                    if final_diff <= pressure_tolerance:
                        print(f"Pressure within tolerance! Achieved {self.current_pressure} lbs")
                        final_stabilized = True
                        break
                    
                    time.sleep(0.2)  # Longer sleep to reduce polling
                
                if final_stabilized:
                    break
                else:
                    retry_count += 1
                    if retry_count < max_retries:
                        print(f"Retrying final pressure command (attempt {retry_count + 1}/{max_retries})")
                        if not self.arduino.send(f"P{target_pressure}"):
                            print(f"Failed retrying final pressure command P{target_pressure}")
                            return False
                    else:
                        print(f"Final pressure of {self.current_pressure} lbs not reaching target {target_pressure} lbs")
                        return False
            
            # Give one final moment to stabilize before continuing
            time.sleep(3)
            
            # Leave high-frequency updates on for next command
            # We'll turn them off after the lateral position is set
            print(f"Pressure sequence complete. Final pressure: {self.current_pressure} lbs")
            return True

    def set_to_pressure(self, target_pressure: float) -> bool:
        """Set axial pressure directly."""
        pressure_tolerance = 2  # Acceptable pressure difference in lbs
        # Backstop only: the firmware owns pressure-move failure detection
        # (no-progress fault at 5s, hard move bound at 30s) and its ERROR
        # flips is_running, exiting the wait loop early with the specific
        # fault reason. This window must sit ABOVE both firmware bounds --
        # at the old 5s it raced the firmware's 5s stall check and won,
        # aborting with a generic timeout before the diagnosis arrived.
        max_wait_time = 35  # Maximum time to wait for pressure to stabilize (seconds)
        
        try:
            if not self.is_running:
                print("Cannot set pressure - protocol not running")
                return False
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                print(f"Error: Pressure {target_pressure} outside safe range (0-{MAX_SAFE_PRESSURE})")
                return False

            # Hold before issuing the pressure command if paused.
            self._wait_while_paused()
            if not self.is_running:
                return False
            print(f"Setting pressure to: {target_pressure} lbs")
            if not self.arduino.send(f"P{target_pressure}"):
                print(f"Failed to send pressure command P{target_pressure}")
                return False

            # Wait for pressure to reach target with live monitoring
            if target_pressure > 0:  # Only wait if we're increasing pressure
                wait_start = time.time()
                while time.time() - wait_start < max_wait_time:
                    if not self.is_running:
                        print("Emergency stop during pressure stabilization")
                        return False
                    if self.is_paused:
                        self._wait_while_paused()
                        wait_start = time.time()  # restart the window after a pause
                        continue
                    diff = abs(target_pressure - self.current_pressure)
                    if diff <= pressure_tolerance:
                        print(f"Pressure stabilized at {self.current_pressure} lbs")
                        break
                    time.sleep(0.1)  # Small sleep to prevent CPU hogging
                else:
                    print(
                        "Pressure did not stabilize within timeout: "
                        f"target={target_pressure}, current={self.current_pressure}"
                    )
                    return False
            
            return True
        except Exception as e:
            print(f"Error setting pressure: {e}")
            return False

    def set_to_c_distance(self, degrees: float) -> bool:
        """Set the C actuator position based on degrees."""
        position_tolerance = 25  # Acceptable position difference
        max_wait_time = 5  # Maximum time to wait for position to be reached (seconds)
        
        try:
            print(f"Setting C actuator to {degrees} degrees")
            position, degrees = lateral_degrees_to_position(
                self.config.CMarks, degrees
            )

            # Send command and ensure high-frequency status updates for position monitoring
            self.angle_set = False
            self.target_pos_c = position
            # Hold before issuing the lateral move if paused.
            self._wait_while_paused()
            if not self.is_running:
                return False
            if not self.arduino.send(f"K{position}"):
                print(f"Failed to send C actuator command K{position}")
                return False

            # Wait for position to be reached with live monitoring
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time:
                if self.is_paused:
                    self._wait_while_paused()
                    wait_start = time.time()  # restart the window after a pause
                    continue
                current_diff = abs(self.current_pos_c - position)
                print(f"Position check - Target: {position}, Current: {self.current_pos_c}, Difference: {current_diff}")
                
                if current_diff <= position_tolerance:
                    print(f"Position reached within tolerance")
                    self.angle_set = True
                    break
                time.sleep(0.1)  # Small sleep to prevent CPU hogging
            
            if not self.angle_set:
                print("Warning: Angle position not verified within timeout")
                return False
                 
            return True

        except Exception as e:
            print(f"Error in set_to_c_distance: {e}")
            return False

    def apply_continuous_pulse(self) -> bool:
        """
        Apply continuous pulse sequence.
        Checks self.use_pulse dynamically and stops pulsing if it becomes False.
        """
        if not self.is_running:
            return True # Exit if protocol stopped externally

        # This function is entered when the main protocol loop decides pulsing should happen.
        # It needs to handle the case where self.use_pulse becomes False while running.
        try:
            # Check if pulsing is actually enabled *now*
            if not self.use_pulse:
                print(f"Protocol {self.protocol} ({time.time()}): apply_continuous_pulse called, but self.use_pulse is False. Skipping.")
                return True # Not an error, just nothing to pulse.

            print(f"Protocol {self.protocol} ({time.time()}): Starting continuous pulse sequence (self.use_pulse={self.use_pulse})...")
            self.signals.progress.emit(">>Pulsing...")

            if not self._start_pulse(): return False # Command to start pulsing
            print(f"Protocol {self.protocol} ({time.time()}): Sent 'J' (start pulse) to Arduino.")
            pulse_command_active_j = True # Flag to track if "J" was sent

            last_keepalive_time = time.time()
            keepalive_interval = 30  # seconds
            check_interval = 0.2 # How often to check conditions in this loop

            while self.is_running and self.use_pulse: # *** KEY: Check self.use_pulse in loop condition ***
                current_time = time.time()

                # Pause holds static: pause() already sent 'JS'; wait here, then
                # re-arm the pulse on resume so the hold continues cleanly.
                if self.is_paused:
                    self._wait_while_paused()
                    if not (self.is_running and self.use_pulse):
                        break
                    if not self._start_pulse():
                        return False
                    last_keepalive_time = time.time()
                    continue

                # Check overall protocol duration
                if not self.check_duration():
                    print(f"Protocol {self.protocol} ({time.time()}): Duration ended during pulse operation.")
                    break # Exit loop if duration is over

                # Send keepalive periodically
                if current_time - last_keepalive_time > keepalive_interval:
                    if self.arduino: self.arduino.send("T")
                    last_keepalive_time = current_time

                time.sleep(check_interval) # Main loop pause

            # Loop exited. Reasons: not self.is_running OR self.use_pulse became False OR duration ended.
            print(f"Protocol {self.protocol} ({time.time()}): Exiting apply_continuous_pulse loop. Conditions: is_running={self.is_running}, use_pulse={self.use_pulse}, elapsed_time={self.elapsed_time:.1f}/{self.duration}")

            # Always send stop pulse command ('JS') if start command ('J') was sent, to ensure it stops.
            if pulse_command_active_j and self.arduino:
                if not self._send_pulse_stop(): print("Warning: Failed to send JS command")
                print(f"Protocol {self.protocol} ({time.time()}): Sent 'JS' (stop pulse) to Arduino.")

            return True

        except Exception as e:
            print(f"Error during pulse sequence: {e}")
            # Try to send stop command on error too
            self._send_pulse_stop()
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

    def _fail(self, reason: str, reset_needed: bool = False):
        """Common failure exit: log, optionally request recovery, emit."""
        print(f"Protocol {self.protocol} failed: {reason}")
        self.is_running = False
        self.signals.finished.emit(False)
        if reset_needed:
            self.signals.reset_needed.emit()
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
                    if not self.arduino.send("T"):
                        return self._fail("keepalive failed")
                    last_keepalive_time = time.time()
                time.sleep(0.2)
        finally:
            self._live_phase = False
            if pulse_active and self.arduino and not self._send_pulse_stop():
                self.logger.error("Could not stop pulse while leaving hold phase")
                self.signals.reset_needed.emit()
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
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)
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
                    if not self.arduino.send("T"):
                        self._fail("keepalive failed")
                        return
                    last_keepalive_time = current_time
                time.sleep(0.1)
        finally:
            self._live_phase = False
            self._active_lateral_side = None
            if pulse_active and self.arduino and not self._send_pulse_stop():
                self.logger.error("Could not stop pulse while leaving protocol 4")
                self.signals.reset_needed.emit()
                pulse_stop_failed = True
        if pulse_stop_failed:
            self._fail("could not stop final pulsing")
            return
        self._release(center_first=True)

    def run(self):
        """Execute the selected protocol."""
        try:
            print("Starting protocol execution...")
            self.is_running = True
            self.start_time = time.time()
            if not self.arduino.send("HF1"):
                print("Failed to enable high-frequency status updates")
                self.is_running = False
                self.signals.finished.emit(False)
                return
            time.sleep(0.1)

            if self.protocol == "1":
                self.protocol_1()
            elif self.protocol == "2":
                self.protocol_2()
            elif self.protocol == "3":
                self.protocol_3()
            elif self.protocol == "4":
                self.protocol_4()
            else:
                print(f"Unknown protocol: {self.protocol}")
                self.signals.finished.emit(False)
            
            if not self.arduino.send("HF0"):
                print("Warning: Failed to disable high-frequency status updates")
            time.sleep(0.1)
            self.is_running = False
            
        except Exception as e:
            print(f"Critical error executing protocol: {e}")
            if self.arduino:
                self.arduino.send("HF0")
            time.sleep(0.1)
            self.is_running = False
            self.signals.finished.emit(False)
        finally:
            # This run is over: stop being invoked on every status frame
            self._disconnect_status()

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
        self.is_running = False
        self._disconnect_status()

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
