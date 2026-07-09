from datetime import datetime
import time
import threading
import logging
from helpers.logging import setup_logger
from helpers.conversions import lateral_degrees_to_position
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import QUrl, Qt, QObject

from config.constants import (
    PRESSURE_MAX,
    AXIAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
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
                self.arduino.send(f"P{max_p}")
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
        # Stop any active firmware pulse so the limb is held static (NOT 'X').
        if self.arduino:
            try:
                self.arduino.send("JS")
            except Exception as e:
                print(f"Error stopping pulse on pause: {e}")

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
        return self.arduino.send(cmd)

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
                if not self.arduino.send("JS"): print("Warning: Failed to send JS command")
                print(f"Protocol {self.protocol} ({time.time()}): Sent 'JS' (stop pulse) to Arduino.")

            return True

        except Exception as e:
            print(f"Error during pulse sequence: {e}")
            # Try to send stop command on error too
            if self.arduino: self.arduino.send("JS")
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
        """Run the treatment hold, pulsing while use_pulse is on.

        Responsive to live use_pulse changes; ends when the duration
        elapses or the protocol is stopped.
        """
        if not self.is_running:
            return True

        main_phase_loop_active = True
        print(
            f"Protocol {self.protocol}: entering pulse/hold phase "
            f"(use_pulse={self.use_pulse})"
        )
        while main_phase_loop_active and self.is_running and self.check_duration():
            if self.use_pulse:
                if not self.apply_continuous_pulse():
                    # Pulse failure leaves the machine in an unknown motion
                    # state: request the recovery reset (previously only
                    # protocols 2/3 did)
                    return self._fail("pulse sequence failed", reset_needed=True)
                main_phase_loop_active = False
            else:
                self._wait_while_paused()
                time.sleep(0.5)

        # Ensure pulse is stopped however the loop exited
        if self.arduino and hasattr(self.arduino, "send"):
            if not self.arduino.send("JS"):
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

    def _run_standard_protocol(self, banner: str, target_angle) -> None:
        """Protocols 1-3: ramp, optional lateral move, pulse/hold, release."""
        if not self._preamble(banner):
            return

        moved_lateral = False
        if self.is_running and target_angle is not None:
            print(f"Moving to {target_angle}°")
            if not self.set_to_c_distance(target_angle):
                self._fail("lateral positioning failed")
                return
            moved_lateral = True

        if not self._pulse_or_hold_phase():
            return

        self._release(center_first=moved_lateral)

    def protocol_1(self):
        """Axial protocol - pressure only."""
        print("Running protocol 1...")
        self._run_standard_protocol(">>Starting axial protocol", None)

    def protocol_2(self):
        """Axial with left lateral movement."""
        print("Running protocol 2...")
        self._run_standard_protocol(
            ">>Starting left lateral protocol", self.max_left
        )

    def protocol_3(self):
        """Axial with right lateral movement."""
        print("Running protocol 3...")
        self._run_standard_protocol(
            ">>Starting right lateral protocol", self.max_right
        )

    def protocol_4(self):
        """Axial with oscillating lateral movement between left and right."""
        print("Running protocol 4...")
        if not self._preamble(">>Starting oscillating lateral protocol"):
            return

        # Oscillation parameters
        oscillation_period = 30  # Total time for one complete cycle (left->right->left) in seconds
        hold_at_extreme = 2      # Time to hold at each extreme position

        # Main oscillation loop
        if self.is_running:
            print(f"Starting oscillation between {self.max_left}° and {self.max_right}°")
            oscillation_start_time = time.time()
            position_at_left = True  # Start at left position
            last_position_change = oscillation_start_time
            pulse_active = False

            # Move to initial left position
            if not self.set_to_c_distance(self.max_left):
                self._fail("initial lateral positioning failed")
                return

            # Start pulsing if enabled
            if self.use_pulse and self.arduino:
                if not self._start_pulse():
                    self._fail("could not start pulsing", reset_needed=True)
                    return
                pulse_active = True
                print(f"Protocol 4: Started continuous pulsing")

            while self.is_running and self.check_duration():
                # Hold on pause: pause() sent 'JS'; on resume re-arm pulsing.
                if self.is_paused:
                    self._wait_while_paused()
                    if not self.is_running:
                        break
                    if pulse_active and self.use_pulse and self.arduino:
                        if not self._start_pulse():
                            self._fail("could not restart pulsing", reset_needed=True)
                            return
                    last_position_change = time.time()
                    continue

                current_time = time.time()
                time_since_position_change = current_time - last_position_change

                # Check if it's time to switch positions
                if time_since_position_change >= (oscillation_period / 2):
                    # Switch position
                    if position_at_left:
                        # Move to right
                        print(f"Oscillating to right {self.max_right}°")
                        self.signals.progress.emit(f">>Moving to right {self.max_right}°")
                        if not self.set_to_c_distance(self.max_right):
                            self._fail("oscillation move failed")
                            return
                        position_at_left = False
                    else:
                        # Move to left
                        print(f"Oscillating to left {self.max_left}°")
                        self.signals.progress.emit(f">>Moving to left {self.max_left}°")
                        if not self.set_to_c_distance(self.max_left):
                            self._fail("oscillation move failed")
                            return
                        position_at_left = True

                    last_position_change = current_time

                    # Hold briefly at extreme position
                    if hold_at_extreme > 0:
                        hold_start = time.time()
                        while time.time() - hold_start < hold_at_extreme and self.is_running and self.check_duration():
                            time.sleep(0.1)

                # Handle pulse state changes
                if self.use_pulse and not pulse_active and self.arduino:
                    # Pulse was turned on
                    if not self._start_pulse():
                        self._fail("could not restart pulsing", reset_needed=True)
                        return
                    pulse_active = True
                    print(f"Protocol 4: Restarted pulsing")
                elif not self.use_pulse and pulse_active and self.arduino:
                    # Pulse was turned off
                    if not self.arduino.send("JS"):
                        self._fail("could not stop pulsing", reset_needed=True)
                        return
                    pulse_active = False
                    print(f"Protocol 4: Stopped pulsing")

                # Send periodic keepalive
                if int(current_time) % 30 == 0:
                    if self.arduino:
                        if not self.arduino.send("T"):
                            self._fail("keepalive failed")
                            return

                time.sleep(0.1)  # Main loop sleep

            # Stop pulsing if it was active
            if pulse_active and self.arduino:
                if not self.arduino.send("JS"):
                    self._fail("could not stop final pulsing", reset_needed=True)
                    return
                print(f"Protocol 4: Stopped final pulsing")

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

        if not self.arduino:
            print("Warning: No Arduino connection available for stop sequence")
            self.signals.stopped.emit(True)
            return

        try:
            # Emergency stop first: halts pulsing/motion immediately
            # (X jumps the transport's queue and the firmware's limiter)
            stop_sent = self.arduino.send("X")
            print(f"Emergency stop command sent: {'Success' if stop_sent else 'FAILED'}")

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
