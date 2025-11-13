import time
import threading
from helpers.logging import (
    setup_logger, debug, debug_protocol, debug_state_change,
    debug_timing, debug_error, debug_thread, debug_signal
)

from PyQt5.QtCore import QObject, pyqtSignal, QRunnable

from config.constants import (
    PRESSURE_MAX,
    AXIAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
    PROTOCOL_DEFAULT_SETTINGS
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
    finished = pyqtSignal(bool)
    stopped = pyqtSignal(bool)
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(str)
    pressure_emit = pyqtSignal(float)
    status_emit = pyqtSignal(int, int, int, float)
    reset_needed = pyqtSignal()

class Protocols(QRunnable):
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
    ):
        """Initialize protocol handler."""
        super().__init__()
        debug("Initializing Protocols class", component="Protocol", level="INFO")

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

        # State tracking
        self.is_running = False
        self.start_time = None
        self.elapsed_time = 0
        self.current_pressure = 0
        self.current_pos_c = 0
        self.target_pos_c = None
        self.angle_set = False
        self.keepalive_thread_active = False  # Track if keepalive thread is running

        # Connect signals if arduino is provided
        if ser is not None and hasattr(ser, "status_emit"):
            # First disconnect any existing connections to avoid duplicates
            try:
                ser.status_emit.disconnect(self.update_status)
                debug("Disconnected existing status_emit signal", component="Protocol")
            except Exception:
                pass  # Ignore if not previously connected

            # Now connect the signal
            ser.status_emit.connect(self.update_status)
            debug_signal("Connected Arduino status_emit to update_status",
                        signal_name="status_emit", data="update_status method")
        else:
            debug("WARNING: Arduino object missing status_emit signal",
                 component="Protocol", level="WARNING")

        debug_protocol("Protocols initialized", state={
            "protocol": protocol,
            "max_pressure": max_pressure,
            "max_left": self.max_left,
            "max_right": self.max_right,
            "duration": self.duration,
            "use_pulse": use_pulse
        })

    def update_status(self, pos_a, pos_b, pos_c, pressure):
        """Update current status values from Arduino feedback."""
        # Store old values for state change tracking
        old_pressure = self.current_pressure
        old_pos_c = self.current_pos_c

        # Store values with explicit type conversion
        self.current_pressure = float(pressure)
        self.current_pos_c = int(pos_c)

        # Only log significant changes to reduce noise
        if abs(old_pressure - self.current_pressure) > 0.5:
            debug_state_change("Protocol.current_pressure", old_pressure, self.current_pressure,
                              f"Status update from Arduino")
        if old_pos_c != self.current_pos_c:
            debug_state_change("Protocol.current_pos_c", old_pos_c, self.current_pos_c,
                              f"Status update from Arduino")

        # Emit separate pressure signal for dialogs and UI updates
        debug_signal("Emitting pressure_emit", signal_name="pressure_emit",
                    data=float(pressure))
        self.signals.pressure_emit.emit(float(pressure))

        # Also emit the full status update for other components
        debug_signal("Emitting status_emit", signal_name="status_emit",
                    data={"pos_a": int(pos_a), "pos_b": int(pos_b),
                          "pos_c": int(pos_c), "pressure": float(pressure)})
        self.signals.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))

    def check_duration(self) -> bool:
        """Check if protocol duration has expired."""
        if not self.start_time:
            debug("No start time set for duration check", component="Protocol", level="WARNING")
            return False

        self.elapsed_time = time.time() - self.start_time

        # Only print status every 15 seconds
        if int(self.elapsed_time) % 15 == 0:
            remaining = self.duration - self.elapsed_time
            debug_protocol(f"Duration check", state={
                "elapsed": f"{self.elapsed_time:.1f}s",
                "total": f"{self.duration}s",
                "remaining": f"{remaining:.1f}s"
            })

        return self.elapsed_time < self.duration

    def interruptible_sleep(self, duration):
        """Sleep for the specified duration but check for stop flag frequently."""
        if duration <= 0:
            return self.is_running

        check_interval = 0.1  # Check every 100ms
        elapsed = 0
        start_time = time.time()

        while elapsed < duration and self.is_running:
            sleep_time = min(check_interval, duration - elapsed)
            time.sleep(sleep_time)
            elapsed += sleep_time

        if not self.is_running:
            debug("Interruptible sleep interrupted", component="Protocol",
                  elapsed=f"{elapsed:.1f}s", target=f"{duration}s")

        return self.is_running  # Return False if interrupted

    def run_pressure_sequence(self, starting_pressure: float, target_pressure: float) -> bool:
            """Run a sequence of pressure increases from start to target."""
            current_command = starting_pressure
            pressure_tolerance = 5  # Acceptable pressure difference in lbs
            max_wait_time = 10  # Increased max time to wait for pressure (seconds)
            max_retries = 5    # Increased max retries
            check_interval = 0.5  # Time between pressure checks in seconds
            last_check_time = 0  # Track when we last printed a status update

            debug_protocol("Starting pressure sequence", state={
                "start_pressure": starting_pressure,
                "target_pressure": target_pressure,
                "tolerance": pressure_tolerance
            })

            # Initial pressure command
            debug(f"Setting initial pressure", component="Protocol",
                  command=current_command, unit="lbs")
            self.arduino.send(f"P{current_command}")

            # Wait for initial pressure to build with less frequent status checks
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time and self.is_running:
                if self.current_pressure >= current_command - pressure_tolerance:
                    debug(f"Initial pressure reached", component="Protocol",
                          target=current_command, actual=self.current_pressure)
                    break
                # Avoid excessive status printing
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    last_check_time = current_time
                    debug_protocol("Building initial pressure", state={
                        "target": current_command,
                        "current": self.current_pressure,
                        "elapsed": f"{current_time - wait_start:.1f}s"
                    })
                time.sleep(1)  # Longer sleep to reduce polling

            # Check if protocol was stopped
            if not self.is_running:
                debug("Protocol stopped during initial pressure build",
                     component="Protocol", level="WARNING")
                return False

            # Step through pressure increments with reduced monitoring
            increment_count = 0
            while current_command < (target_pressure - PRESSURE_INCREMENT/2) and self.is_running:
                current_command += PRESSURE_INCREMENT
                increment_count += 1

                debug_protocol(f"Pressure increment {increment_count}", state={
                    "new_command": current_command,
                    "current": self.current_pressure
                })
                self.arduino.send(f"P{current_command}")

                # Wait for current increment to stabilize before next increment
                increment_start = time.time()
                increment_stable = False

                while time.time() - increment_start < max_wait_time and self.is_running:
                    # Check if this increment is stable before moving to next
                    if abs(self.current_pressure - current_command) <= pressure_tolerance:
                        debug_timing(f"Pressure increment {increment_count} stabilized",
                                   start_time=increment_start, component="Protocol",
                                   pressure=self.current_pressure)
                        increment_stable = True
                        break
                    time.sleep(0.2)

                # Check if protocol was stopped
                if not self.is_running:
                    debug("Protocol stopped during pressure increment",
                         component="Protocol", level="WARNING")
                    return False

                if not increment_stable:
                    debug(f"Pressure increment {increment_count} not fully stabilized",
                         component="Protocol", level="WARNING",
                         command=current_command, actual=self.current_pressure)

                # Small delay between increments
                time.sleep(2.0)

            # Send final pressure command
            debug_protocol("Setting final pressure", state={
                "target": target_pressure,
                "current": self.current_pressure
            })
            final_attempt_start = time.time()
            self.arduino.send(f"P{target_pressure}")

            # Wait and verify with extended monitoring for final pressure
            retry_count = 0
            final_stabilized = False
            max_final_wait_time = 15  # Longer wait for final pressure to stabilize

            while retry_count < max_retries and not final_stabilized:
                wait_start = time.time()
                last_check_time = 0

                # Give pressure time to stabilize
                while time.time() - wait_start < max_wait_time and self.is_running:
                    final_diff = abs(target_pressure - self.current_pressure)

                    # Only print status updates periodically
                    current_time = time.time()
                    if current_time - last_check_time >= check_interval:
                        last_check_time = current_time
                        debug_protocol("Final pressure check", state={
                            "target": target_pressure,
                            "current": self.current_pressure,
                            "difference": f"{final_diff:.1f}",
                            "retry": retry_count,
                            "elapsed": f"{current_time - wait_start:.1f}s"
                        })

                    if final_diff <= pressure_tolerance:
                        debug_timing("Final pressure reached within tolerance",
                                   start_time=final_attempt_start, component="Protocol",
                                   achieved=self.current_pressure, target=target_pressure)
                        final_stabilized = True
                        break

                    # Check if we've spent too long on final pressure - if we're close, consider it good enough
                    if time.time() - final_attempt_start > max_final_wait_time and final_diff < 5:
                        debug("Accepting close-enough pressure after extended time",
                             component="Protocol", level="WARNING",
                             current=self.current_pressure, target=target_pressure,
                             difference=final_diff)
                        final_stabilized = True
                        break

                    time.sleep(0.2)  # Longer sleep to reduce polling

                if final_stabilized:
                    break
                else:
                    retry_count += 1
                    if retry_count < max_retries:
                        debug(f"Retrying final pressure command",
                             component="Protocol", level="WARNING",
                             attempt=f"{retry_count + 1}/{max_retries}")
                        self.arduino.send(f"P{target_pressure}")
                    else:
                        debug(f"Final pressure not reached after max retries",
                             component="Protocol", level="ERROR",
                             current=self.current_pressure, target=target_pressure)

            # Give one final moment to stabilize before continuing
            time.sleep(3)

            # Leave high-frequency updates on for next command
            debug_protocol("Pressure sequence complete", state={
                "final_pressure": self.current_pressure,
                "target": target_pressure,
                "stabilized": final_stabilized
            })
            return True

    def set_to_pressure(self, target_pressure: float) -> bool:
        """Set axial pressure directly."""
        pressure_tolerance = 2  # Acceptable pressure difference in lbs
        max_wait_time = 5  # Maximum time to wait for pressure to stabilize (seconds)

        try:
            if not self.is_running:
                debug("Cannot set pressure - protocol not running",
                     component="Protocol", level="WARNING")
                return False
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                debug(f"Pressure outside safe range", component="Protocol", level="ERROR",
                     target=target_pressure, range=f"0-{MAX_SAFE_PRESSURE}")
                return False

            debug(f"Setting direct pressure", component="Protocol",
                 target=target_pressure, current=self.current_pressure)
            self.arduino.send(f"P{target_pressure}")

            # Wait for pressure to reach target with live monitoring
            if target_pressure > 0:  # Only wait if we're increasing pressure
                wait_start = time.time()
                while time.time() - wait_start < max_wait_time and self.is_running:
                    diff = abs(target_pressure - self.current_pressure)
                    if diff <= pressure_tolerance:
                        debug_timing(f"Pressure stabilized", start_time=wait_start,
                                   component="Protocol", pressure=self.current_pressure)
                        break
                    time.sleep(0.1)  # Small sleep to prevent CPU hogging

            return True
        except Exception as e:
            debug_error("Error setting pressure", exception=e, component="Protocol")
            return False

    def set_to_c_distance(self, degrees: float) -> bool:
        """Set the C actuator position based on degrees."""
        position_tolerance = 50  # Increased tolerance for position verification
        max_wait_time = 10  # Increased wait time for motor to reach position (seconds)

        try:
            debug_protocol(f"Setting C actuator position", state={
                "degrees": degrees,
                "current_pos": self.current_pos_c
            })

            degrees = float(degrees)
            degrees = round(degrees * 2) / 2
            degrees = max(-20.0, min(20.0, degrees))
            degree_key = "{:.1f}".format(degrees)

            # Look up or interpolate position
            if degree_key in self.config.CMarks:
                position = int(self.config.CMarks[degree_key])
                debug(f"Using exact CMarks position", component="Protocol",
                     degrees=degree_key, position=position)
            else:
                marks = sorted((float(k), int(v)) for k, v in self.config.CMarks.items())
                for i in range(len(marks) - 1):
                    if marks[i][0] <= degrees <= marks[i + 1][0]:
                        deg1, pos1 = marks[i]
                        deg2, pos2 = marks[i + 1]
                        # Prevent division by zero
                        if deg2 - deg1 != 0:
                            ratio = (degrees - deg1) / (deg2 - deg1)
                            position = pos1 + int((pos2 - pos1) * ratio)
                            debug(f"Interpolated position", component="Protocol",
                                 degrees=degrees, position=position,
                                 between=f"[{deg1},{deg2}]")
                        else:
                            # If degree marks are identical, use the first position
                            position = pos1
                            debug(f"Using first position (identical marks)",
                                 component="Protocol", position=pos1)
                        break
                else:
                    raise ValueError(f"Degree value {degrees} outside valid range")

            # Send command and ensure high-frequency status updates for position monitoring
            self.angle_set = False
            self.target_pos_c = position
            debug_state_change("Protocol.target_pos_c", None, position, f"Moving to {degrees} degrees")
            self.arduino.send(f"K{position}")

            # Wait for position to be reached with live monitoring
            wait_start = time.time()
            last_log_time = 0
            while time.time() - wait_start < max_wait_time and self.is_running:
                current_diff = abs(self.current_pos_c - position)

                # Log position check periodically
                current_time = time.time()
                if current_time - last_log_time > 0.5:  # Log every 0.5s
                    last_log_time = current_time
                    debug_protocol("Position tracking", state={
                        "target": position,
                        "current": self.current_pos_c,
                        "difference": current_diff,
                        "elapsed": f"{current_time - wait_start:.1f}s"
                    })

                if current_diff <= position_tolerance:
                    debug_timing("Position reached within tolerance", start_time=wait_start,
                               component="Protocol", position=self.current_pos_c)
                    self.angle_set = True
                    # Allow motor to fully settle at position
                    time.sleep(0.5)
                    break
                time.sleep(0.1)  # Small sleep to prevent CPU hogging

            # Check if we stopped due to protocol termination
            if not self.is_running:
                debug("Protocol stopped - aborting position check",
                     component="Protocol", level="WARNING")
                return False

            if not self.angle_set:
                debug("Position not verified within timeout - continuing anyway",
                     component="Protocol", level="WARNING",
                     target=position, current=self.current_pos_c,
                     difference=abs(self.current_pos_c - position))
                # Continue anyway - position verification timeout shouldn't stop the protocol
                return True  # Changed from False - allow protocol to continue

            return True

        except Exception as e:
            debug_error("Error in set_to_c_distance", exception=e, component="Protocol")
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
                debug_protocol("apply_continuous_pulse called but use_pulse is False",
                             state={"use_pulse": self.use_pulse})
                return True # Not an error, just nothing to pulse.

            debug_protocol("Starting continuous pulse sequence",
                         state={"use_pulse": self.use_pulse, "protocol": self.protocol})
            self.signals.progress.emit(">>Pulsing...")

            if not self.arduino.send("J"):
                debug("Failed to send pulse start command", component="Protocol", level="ERROR")
                return False

            debug("Sent 'J' (start pulse) to Arduino", component="Protocol")
            pulse_command_active_j = True # Flag to track if "J" was sent

            last_keepalive_time = time.time()
            keepalive_interval = 30  # seconds
            check_interval = 0.2 # How often to check conditions in this loop
            pulse_start_time = time.time()

            while self.is_running and self.use_pulse: # *** KEY: Check self.use_pulse in loop condition ***
                current_time = time.time()

                # Check overall protocol duration
                if not self.check_duration():
                    debug("Duration ended during pulse operation", component="Protocol")
                    break # Exit loop if duration is over

                # Send keepalive periodically (but not during emergency stops)
                if current_time - last_keepalive_time > keepalive_interval:
                    # Check if this is still a valid operation (not emergency stopped)
                    if self.arduino and self.is_running:
                        self.arduino.send("T")
                        debug("Sent keepalive during pulse", component="Protocol")
                    last_keepalive_time = current_time

                time.sleep(check_interval) # Main loop pause

            # Loop exited. Reasons: not self.is_running OR self.use_pulse became False OR duration ended.
            pulse_duration = time.time() - pulse_start_time
            debug_protocol("Exiting pulse loop", state={
                "is_running": self.is_running,
                "use_pulse": self.use_pulse,
                "elapsed_time": f"{self.elapsed_time:.1f}s",
                "duration": f"{self.duration}s",
                "pulse_duration": f"{pulse_duration:.1f}s"
            })

            # Always send stop pulse command ('JS') if start command ('J') was sent, to ensure it stops.
            if pulse_command_active_j and self.arduino:
                if not self.arduino.send("JS"):
                    debug("Failed to send JS (stop pulse) command", component="Protocol", level="WARNING")
                else:
                    debug("Sent 'JS' (stop pulse) to Arduino", component="Protocol")

            return True

        except Exception as e:
            debug_error("Error during pulse sequence", exception=e, component="Protocol")
            # Try to send stop command on error too
            if self.arduino:
                self.arduino.send("JS")
                debug("Sent emergency JS stop on error", component="Protocol", level="ERROR")
            return False

    def protocol_1(self):
        """Axial protocol - pressure only."""
        debug_protocol("Starting protocol 1 (Axial)", state={
            "max_pressure": self.max_pressure,
            "duration": self.duration,
            "use_pulse": self.use_pulse
        })

        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting axial protocol")

        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            debug(f"Using higher initial pressure", component="Protocol",
                 initial=initial_pressure, max_pressure=self.max_pressure)

        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        # Run pressure sequence
        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Final phase: pulse or hold, responsive to changes in self.use_pulse
        if self.is_running:
            main_phase_loop_active = True
            debug_protocol("Entering final phase loop", state={
                "use_pulse": self.use_pulse,
                "protocol": self.protocol
            })

            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    debug_state_change("Protocol.use_pulse", False, True,
                                     "Entering pulse mode in final phase")
                    if not self.apply_continuous_pulse():
                        # Error during pulse
                        return False # Signal protocol failure
                    # apply_continuous_pulse completed
                    main_phase_loop_active = False
                else:
                    # Hold mode - check less frequently to reduce log spam
                    time.sleep(0.5)

            # Ensure pulse is stopped if loop exited for any reason
            if hasattr(self.arduino, 'send') and self.arduino:
                 if not self.arduino.send("JS"):
                     debug("Failed sending final JS in Protocol 1", component="Protocol", level="WARNING")
                 else:
                     debug("Sent final 'JS' after main phase loop", component="Protocol")

        # Reset
        self.set_to_pressure(0)
        debug("Protocol 1 complete", component="Protocol", level="INFO")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_2(self):
        """Axial with left lateral movement."""
        debug_protocol("Starting protocol 2 (Left Lateral)", state={
            "max_pressure": self.max_pressure,
            "max_left": self.max_left,
            "duration": self.duration,
            "use_pulse": self.use_pulse
        })

        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting left lateral protocol")

        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            debug(f"Using higher initial pressure", component="Protocol",
                 initial=initial_pressure, max_pressure=self.max_pressure)

        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Move to left position
        if self.is_running:
            debug(f"Moving to left position", component="Protocol", degrees=self.max_left)
            if not self.set_to_c_distance(self.max_left):
                self.signals.finished.emit(False)
                return

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            debug_protocol("Entering final phase loop", state={
                "use_pulse": self.use_pulse,
                "protocol": self.protocol
            })

            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    debug("Attempting pulse mode", component="Protocol")
                    if not self.apply_continuous_pulse():
                        self.signals.reset_needed.emit()
                        self.signals.finished.emit(False)
                        return
                    main_phase_loop_active = False
                else:
                    time.sleep(0.5)

            if hasattr(self.arduino, 'send') and self.arduino:
                 self.arduino.send("JS")
                 debug("Sent final 'JS' after main phase loop", component="Protocol")

        # Reset
        self.set_to_c_distance(0)
        self.set_to_pressure(0)
        debug("Protocol 2 complete", component="Protocol", level="INFO")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_3(self):
        """Axial with right lateral movement."""
        debug_protocol("Starting protocol 3 (Right Lateral)", state={
            "max_pressure": self.max_pressure,
            "max_right": self.max_right,
            "duration": self.duration,
            "use_pulse": self.use_pulse
        })

        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting right lateral protocol")

        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            debug(f"Using higher initial pressure", component="Protocol",
                 initial=initial_pressure, max_pressure=self.max_pressure)

        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(MIN_PRESSURE, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Move to right position
        if self.is_running:
            debug(f"Moving to right position", component="Protocol", degrees=self.max_right)
            if not self.set_to_c_distance(self.max_right):
                self.signals.finished.emit(False)
                return

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            debug_protocol("Entering final phase loop", state={
                "use_pulse": self.use_pulse,
                "protocol": self.protocol
            })

            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    debug("Attempting pulse mode", component="Protocol")
                    if not self.apply_continuous_pulse():
                        self.signals.reset_needed.emit()
                        self.signals.finished.emit(False)
                        return
                    main_phase_loop_active = False
                else:
                    time.sleep(0.5)

            if hasattr(self.arduino, 'send') and self.arduino:
                 self.arduino.send("JS")
                 debug("Sent final 'JS' after main phase loop", component="Protocol")

        # Reset
        self.set_to_c_distance(0)

        # Simple wait for returning to center position
        time.sleep(1)

        self.set_to_pressure(0)
        debug("Protocol 3 complete", component="Protocol", level="INFO")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_4(self):
        """Axial with oscillating lateral movement between left and right."""
        debug_protocol("Starting protocol 4 (Oscillating)", state={
            "max_pressure": self.max_pressure,
            "max_left": self.max_left,
            "max_right": self.max_right,
            "duration": self.duration,
            "use_pulse": self.use_pulse
        })

        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting oscillating lateral protocol")

        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            debug(f"Using higher initial pressure", component="Protocol",
                 initial=initial_pressure, max_pressure=self.max_pressure)

        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(MIN_PRESSURE, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Oscillation parameters
        oscillation_period = 30  # Total time for one complete cycle (left->right->left) in seconds
        hold_at_extreme = 2      # Time to hold at each extreme position

        # Main oscillation loop
        if self.is_running:
            debug_protocol("Starting oscillation", state={
                "left": self.max_left,
                "right": self.max_right,
                "period": oscillation_period,
                "hold": hold_at_extreme
            })

            oscillation_start_time = time.time()
            position_at_left = True  # Start at left position
            last_position_change = oscillation_start_time
            pulse_active = False
            oscillation_count = 0

            # Move to initial left position
            if not self.set_to_c_distance(self.max_left):
                self.signals.finished.emit(False)
                return

            # Start pulsing if enabled
            if self.use_pulse and self.arduino:
                if not self.arduino.send("J"):
                    debug("Failed to start pulse", component="Protocol", level="WARNING")
                else:
                    pulse_active = True
                    debug_state_change("Protocol4.pulse_active", False, True, "Initial pulse start")

            while self.is_running and self.check_duration():
                current_time = time.time()
                time_since_position_change = current_time - last_position_change

                # Check if it's time to switch positions
                if time_since_position_change >= (oscillation_period / 2):
                    oscillation_count += 1
                    # Switch position
                    if position_at_left:
                        # Move to right
                        debug_protocol(f"Oscillation {oscillation_count}: Moving right",
                                     state={"target": self.max_right})
                        self.signals.progress.emit(f">>Moving to right {self.max_right}°")
                        if not self.set_to_c_distance(self.max_right):
                            break
                        position_at_left = False
                    else:
                        # Move to left
                        debug_protocol(f"Oscillation {oscillation_count}: Moving left",
                                     state={"target": self.max_left})
                        self.signals.progress.emit(f">>Moving to left {self.max_left}°")
                        if not self.set_to_c_distance(self.max_left):
                            break
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
                    if not self.arduino.send("J"):
                        debug("Failed to restart pulse", component="Protocol", level="WARNING")
                    else:
                        pulse_active = True
                        debug_state_change("Protocol4.pulse_active", False, True, "Pulse restarted")
                elif not self.use_pulse and pulse_active and self.arduino:
                    # Pulse was turned off
                    if not self.arduino.send("JS"):
                        debug("Failed to stop pulse", component="Protocol", level="WARNING")
                    else:
                        pulse_active = False
                        debug_state_change("Protocol4.pulse_active", True, False, "Pulse stopped")

                # Send periodic keepalive (but not during emergency stops)
                if int(current_time) % 30 == 0:
                    if self.arduino and self.is_running:
                        self.arduino.send("T")

                time.sleep(0.1)  # Main loop sleep

            # Stop pulsing if it was active
            if pulse_active and self.arduino:
                self.arduino.send("JS")
                debug("Stopped final pulsing", component="Protocol")

        # Reset
        self.set_to_c_distance(0)
        time.sleep(1)  # Wait for return to center
        self.set_to_pressure(0)
        debug("Protocol 4 complete", component="Protocol", level="INFO",
             oscillations=oscillation_count)
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def run(self):
        """Execute the selected protocol."""
        try:
            debug_thread("Protocol execution starting", thread_name="Protocol.run", state="STARTING")
            debug_state_change("Protocol.is_running", False, True, "Protocol execution started")
            self.is_running = True
            self.start_time = time.time()

            # Enable high-frequency status updates
            self.arduino.send("HF1")
            debug("Enabled high-frequency status updates (HF1)", component="Protocol")
            time.sleep(0.1)

            # Execute the selected protocol
            debug(f"Executing protocol {self.protocol}", component="Protocol", level="INFO")
            if self.protocol == "1":
                self.protocol_1()
            elif self.protocol == "2":
                self.protocol_2()
            elif self.protocol == "3":
                self.protocol_3()
            elif self.protocol == "4":
                self.protocol_4()
            else:
                debug(f"Unknown protocol", component="Protocol", level="ERROR",
                     protocol=self.protocol)
                self.signals.finished.emit(False)

            # Disable high-frequency status updates
            self.arduino.send("HF0")
            debug("Disabled high-frequency status updates (HF0)", component="Protocol")
            time.sleep(0.1)

            debug_thread("Protocol execution completed", thread_name="Protocol.run", state="COMPLETED")

        except Exception as e:
            debug_error("Critical error executing protocol", exception=e, component="Protocol")
            self.arduino.send("HF0")
            time.sleep(0.1)
            self.is_running = False
            self.signals.finished.emit(False)

    def stop(self, emergency=False):
        """Safely stop a running protocol.

        Args:
            emergency: If True, sends the emergency stop command 'X'.
                      If False (default), performs a gentle stop without 'X'.
        """
        debug_protocol(f"Initiating protocol stop", state={
            "emergency": emergency,
            "is_running": self.is_running,
            "use_pulse": self.use_pulse
        })

        old_is_running = self.is_running
        self.is_running = False
        if old_is_running:
            debug_state_change("Protocol.is_running", True, False,
                             f"{'Emergency' if emergency else 'Normal'} stop initiated")

        # Also set flags to interrupt any ongoing pulse or movement
        old_use_pulse = self.use_pulse
        self.use_pulse = False  # Stop any continuous pulse immediately
        if old_use_pulse:
            debug_state_change("Protocol.use_pulse", True, False, "Pulse disabled by stop")

        # For emergency stops, also terminate any keepalive thread
        if emergency:
            old_keepalive = self.keepalive_thread_active
            self.keepalive_thread_active = False
            if old_keepalive:
                debug_state_change("Protocol.keepalive_thread_active", True, False,
                                 "Keepalive terminated by emergency stop")

        # Ensure we have a valid Arduino connection
        if not self.arduino:
            debug("No Arduino connection available for stop sequence",
                 component="Protocol", level="WARNING")
            self.signals.stopped.emit(True)
            return

        try:
            # Turn off high-frequency status first
            success = self.arduino.send("HF0")
            debug(f"High frequency status turned off", component="Protocol",
                 success=success)
            time.sleep(0.5)  # Brief pause before next command

            # Only send emergency stop command if this is an emergency or user-initiated stop
            if emergency:
                success = self.arduino.send("X")
                debug(f"Emergency stop command 'X' sent", component="Protocol",
                     level="WARNING", success=success)
                # For emergency stops, do NOT start keepalive thread
            else:
                # For normal stops, send test command and start keepalive
                time.sleep(0.5)  # Increased wait time

                # Send test command to verify connection is still active
                success = self.arduino.send("T")
                debug(f"Test command sent for normal stop", component="Protocol",
                     success=success)

                # Start a keepalive thread that continues even after worker is "stopped"
                # This prevents connection timeouts for normal stops only
                debug("Starting keepalive thread for normal stop", component="Protocol")
                self._start_keepalive_thread()

            # Signal that the protocol was stopped
            debug_signal("Emitting stopped signal", signal_name="stopped", data=True)
            self.signals.stopped.emit(True)

        except Exception as e:
            debug_error("Error during protocol stop", exception=e, component="Protocol")
            self.signals.stopped.emit(False)

    def _start_keepalive_thread(self):
        """Start a separate thread to send periodic keepalive signals to Arduino."""
        def keepalive_worker():
            debug_thread("Keepalive worker starting", thread_name="keepalive_worker", state="STARTING")

            # Run for 60 seconds to ensure Arduino connection is maintained
            end_time = time.time() + 60  # Extended duration to 60 seconds
            keepalive_interval = 3  # More frequent - every 3 seconds
            last_keepalive = 0
            reconnect_attempts = 0
            max_reconnect_attempts = 3

            # Set flag to indicate thread is active
            self.keepalive_thread_active = True

            while time.time() < end_time and self.keepalive_thread_active:
                try:
                    current_time = time.time()
                    if current_time - last_keepalive >= keepalive_interval:
                        if self.arduino and hasattr(self.arduino, "send"):
                            # Try to verify connection first
                            success = False
                            if hasattr(self.arduino, "verify_connection"):
                                try:
                                    success = self.arduino.verify_connection(tries=3, timeout_s=5.0)
                                    if success:
                                        debug("Keepalive connection verified", component="Protocol")
                                except Exception as ve:
                                    debug_error("Error verifying connection", exception=ve, component="Protocol")

                            # If verification fails or unavailable, try basic send
                            if not success:
                                success = self.arduino.send("T")  # Test command as keepalive

                            if success:
                                # Only print keepalive message on first success or after failures
                                if reconnect_attempts > 0 or last_keepalive == 0:
                                    debug("Keepalive sent successfully", component="Protocol",
                                         after_failures=reconnect_attempts > 0)
                                last_keepalive = current_time
                                reconnect_attempts = 0  # Reset counter on success
                            else:
                                # Try reconnecting if connection seems lost
                                reconnect_attempts += 1
                                if reconnect_attempts <= max_reconnect_attempts:
                                    debug(f"Keepalive failed, attempting reconnect",
                                         component="Protocol", level="WARNING",
                                         attempt=f"{reconnect_attempts}/{max_reconnect_attempts}")
                                    if hasattr(self.arduino, "reconnect"):
                                        self.arduino.reconnect(max_retries=1)
                                else:
                                    debug("Maximum reconnect attempts reached, stopping keepalive",
                                         component="Protocol", level="ERROR")
                                    break
                except Exception as e:
                    debug_error("Error in keepalive thread", exception=e, component="Protocol")
                    reconnect_attempts += 1
                    if reconnect_attempts > max_reconnect_attempts:
                        debug("Too many errors in keepalive thread, stopping",
                             component="Protocol", level="ERROR")
                        break

                time.sleep(1)

            # Clean up and check why thread ended
            was_emergency = not self.keepalive_thread_active  # If False, it was terminated
            self.keepalive_thread_active = False

            if was_emergency:
                debug_thread("Keepalive thread terminated by emergency stop",
                           thread_name="keepalive_worker", state="TERMINATED")
            else:
                debug_thread("Keepalive thread finished normally",
                           thread_name="keepalive_worker", state="COMPLETED")

        # Start background thread
        keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
        keepalive_thread.start()
        debug("Keepalive thread started", component="Protocol")