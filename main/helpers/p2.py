# protocols.py
from datetime import datetime
import time
import threading
import logging
from helpers.logging import setup_logger
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtCore import QUrl, Qt, QObject

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
        max_left: float, # Already negative from KneeSpa
        max_right: float, # Already positive from KneeSpa
        duration: int,
        use_pulse: bool,
        ser=None,
        config=None,
    ):
        """Initialize protocol handler."""
        super().__init__()
        print("Initializing Protocols class...")

        # System setup
        self.logger = setup_logger(component="Protocols")
        self.arduino = ser
        self.a_factor = a_factor
        self.config = config
        self.signals = WorkerSignals()

        # Protocol parameters (directly use values passed, KneeSpa ensures correctness)
        self.protocol = protocol
        self.max_pressure = max_pressure
        self.max_left = max_left
        self.max_right = max_right
        self.duration = duration * 60      # Convert to seconds
        self.use_pulse = use_pulse         # This can be changed mid-protocol

        # State tracking
        self.is_running = False
        self.start_time = None
        self.elapsed_time = 0
        self.current_pressure = 0
        self.current_pos_c = 0
        self.target_pos_c = None
        self.angle_set = False

        # Connect signals if arduino is provided
        if ser is not None and hasattr(ser, "status_emit"):
            try:
                ser.status_emit.disconnect(self.update_status)
            except TypeError: # Disconnect raises TypeError if not connected
                pass
            ser.status_emit.connect(self.update_status)
            print("Protocol: Connected Arduino status_emit signal to update_status method")
        else:
            print("WARNING: Arduino object missing status_emit signal - status updates won't work!")

        print(f"Protocols class initialized with use_pulse={self.use_pulse}")

    # --- update_status, check_duration, run_pressure_sequence, set_to_pressure, set_to_c_distance remain the same ---
    # (Keep your existing implementations for these)
    def update_status(self, pos_a, pos_b, pos_c, pressure):
        """Update current status values from Arduino feedback."""
        # print(f"Protocol update_status received: A={pos_a}, B={pos_b}, C={pos_c}, Pressure={pressure}") # Verbose

        # Store values with explicit type conversion
        self.current_pressure = float(pressure)
        self.current_pos_c = int(pos_c)

        # Emit separate pressure signal for dialogs and UI updates
        # Make sure to use float for pressure to avoid type conversion issues
        # print(f"Protocol emitting pressure_emit with pressure={float(pressure)}") # Verbose
        self.signals.pressure_emit.emit(float(pressure))

        # Also emit the full status update for other components
        # print(f"Protocol emitting status_emit with all values") # Verbose
        self.signals.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))

    def check_duration(self) -> bool:
        """Check if protocol duration has expired."""
        if not self.start_time:
            print("Warning: No start time set for duration check")
            return False

        self.elapsed_time = time.time() - self.start_time

        # Only print status every 15 seconds
        if int(self.elapsed_time) % 15 == 0 and int(self.elapsed_time) > 0: # Avoid printing at 0.0s
             # Add a small delay or check if the second has changed to avoid multiple prints per second
             if not hasattr(self, '_last_print_second') or int(self.elapsed_time) != self._last_print_second:
                print(f"Duration check - Elapsed: {self.elapsed_time:.1f}s / Total: {self.duration}s")
                self._last_print_second = int(self.elapsed_time)


        return self.elapsed_time < self.duration

    def run_pressure_sequence(self, starting_pressure: float, target_pressure: float) -> bool:
            """Run a sequence of pressure increases from start to target."""
            # Use self.max_pressure as the dynamic target
            dynamic_target_pressure = self.max_pressure
            print(f"Running pressure sequence from {starting_pressure} towards {dynamic_target_pressure} lbs")

            current_command = starting_pressure
            pressure_tolerance = 3  # Acceptable pressure difference in lbs
            max_wait_time = 5  # Increased max time to wait for pressure (seconds)
            max_retries = 5    # Increased max retries
            check_interval = 0.5  # Time between pressure checks in seconds
            last_check_time = 0  # Track when we last printed a status update

            # Initial pressure command
            print(f"Increasing pressure to: {current_command} lbs")
            if not self.arduino.send(f"P{current_command}"): return False

            # Wait for initial pressure to build
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time and self.is_running:
                if self.current_pressure >= current_command - pressure_tolerance:
                    break
                current_time = time.time()
                if current_time - last_check_time >= check_interval:
                    last_check_time = current_time
                    # print(f"Initial pressure build - Target: {current_command}, Current: {self.current_pressure}") # Verbose
                time.sleep(0.1) # Shorter sleep

            # Step through pressure increments
            while current_command < (self.max_pressure - PRESSURE_INCREMENT/2) and self.is_running:
                current_command += PRESSURE_INCREMENT
                # Ensure we don't exceed the potentially updated max_pressure
                current_command = min(current_command, self.max_pressure)
                print(f"Increasing pressure to: {current_command} lbs (Current Max: {self.max_pressure})")
                if not self.arduino.send(f"P{current_command}"): return False

                increment_start = time.time()
                increment_stable = False
                while time.time() - increment_start < max_wait_time and self.is_running:
                    if abs(self.current_pressure - current_command) <= pressure_tolerance:
                        print(f"Pressure increment stabilized near {self.current_pressure} lbs")
                        increment_stable = True
                        break
                    time.sleep(0.1)

                if not increment_stable:
                    print(f"Warning: Pressure increment {current_command} not fully stabilized")

                if not self.is_running: break # Exit if stopped during increment
                time.sleep(1.0) # Smaller delay between increments

            if not self.is_running: return False # Check again before final step

            # Send final pressure command (use current self.max_pressure)
            print(f"Setting final pressure: {self.max_pressure} lbs")
            final_attempt_start = time.time()
            if not self.arduino.send(f"P{self.max_pressure}"): return False

            # Wait and verify final pressure
            retry_count = 0
            final_stabilized = False
            max_final_wait_time = 15  # Longer wait for final pressure

            while retry_count < max_retries and not final_stabilized and self.is_running:
                wait_start = time.time()
                last_check_time = 0
                while time.time() - wait_start < max_wait_time and self.is_running:
                    final_diff = abs(self.max_pressure - self.current_pressure)
                    current_time = time.time()
                    if current_time - last_check_time >= check_interval:
                        last_check_time = current_time
                        # print(f"Pressure check - Target: {self.max_pressure}, Current: {self.current_pressure}, Difference: {final_diff} lbs") # Verbose
                    if final_diff <= pressure_tolerance:
                        print(f"Pressure within tolerance! Achieved {self.current_pressure} lbs")
                        final_stabilized = True
                        break
                    if time.time() - final_attempt_start > max_final_wait_time and final_diff < 5:
                        print(f"Pressure close enough after extended attempts: {self.current_pressure}/{self.max_pressure} lbs")
                        final_stabilized = True
                        break
                    time.sleep(0.1)

                if final_stabilized or not self.is_running: break

                retry_count += 1
                if retry_count < max_retries:
                    print(f"Retrying final pressure command (attempt {retry_count + 1}/{max_retries})")
                    if not self.arduino.send(f"P{self.max_pressure}"): return False
                else:
                    print(f"Warning: Final pressure of {self.current_pressure} lbs not reaching target {self.max_pressure} lbs")

            if not self.is_running: return False
            time.sleep(1) # Final stabilization pause
            print(f"Pressure sequence complete. Final pressure: {self.current_pressure} lbs")
            return True

    def set_to_pressure(self, target_pressure: float) -> bool:
        """Set axial pressure directly."""
        pressure_tolerance = 2  # Acceptable pressure difference in lbs
        max_wait_time = 5  # Maximum time to wait for pressure to stabilize (seconds)

        try:
            if not self.is_running:
                print("Cannot set pressure - protocol not running")
                return False
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                print(f"Error: Pressure {target_pressure} outside safe range (0-{MAX_SAFE_PRESSURE})")
                return False

            print(f"Setting pressure directly to: {target_pressure} lbs")
            if not self.arduino.send(f"P{target_pressure}"): return False

            # Wait for pressure to reach target
            if target_pressure > 0:  # Only wait if target is non-zero
                wait_start = time.time()
                while time.time() - wait_start < max_wait_time and self.is_running:
                    diff = abs(target_pressure - self.current_pressure)
                    if diff <= pressure_tolerance:
                        print(f"Direct pressure set stabilized at {self.current_pressure} lbs")
                        return True # Success
                    time.sleep(0.1)
                # If loop finishes without reaching target
                print(f"Warning: Direct pressure set timed out. Current: {self.current_pressure}, Target: {target_pressure}")
                return False # Indicate it didn't stabilize
            else:
                time.sleep(0.5) # Short delay for P0 command
                return True # Assume P0 works quickly

        except Exception as e:
            print(f"Error setting pressure: {e}")
            return False

    def set_to_c_distance(self, degrees: float) -> bool:
        """Set the C actuator position based on degrees."""
        position_tolerance = 25  # Acceptable position difference
        max_wait_time = 5  # Maximum time to wait for position to be reached (seconds)

        try:
            print(f"Setting C actuator dynamically to {degrees} degrees")
            # Use the current instance attributes self.max_left or self.max_right
            # The 'degrees' argument passed here *is* the target based on the current self.max_left/right
            target_degrees = float(degrees)
            target_degrees = round(target_degrees * 2) / 2
            target_degrees = max(-20.0, min(20.0, target_degrees))
            degree_key = "{:.1f}".format(target_degrees)

            # Look up or interpolate position
            if degree_key in self.config.CMarks:
                position = int(self.config.CMarks[degree_key])
            else:
                # (Interpolation logic remains the same)
                marks = sorted((float(k), int(v)) for k, v in self.config.CMarks.items())
                for i in range(len(marks) - 1):
                    if marks[i][0] <= target_degrees <= marks[i + 1][0]:
                        deg1, pos1 = marks[i]
                        deg2, pos2 = marks[i + 1]
                        ratio = (target_degrees - deg1) / (deg2 - deg1)
                        position = pos1 + int((pos2 - pos1) * ratio)
                        break
                else:
                    raise ValueError(f"Degree value {target_degrees} outside valid range")

            self.angle_set = False
            self.target_pos_c = position
            print(f"Sending command K{position} for {target_degrees} degrees")
            if not self.arduino.send(f"K{position}"): return False

            # Wait for position to be reached
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time and self.is_running:
                current_diff = abs(self.current_pos_c - position)
                # print(f"Position check - Target: {position}, Current: {self.current_pos_c}, Difference: {current_diff}") # Verbose
                if current_diff <= position_tolerance:
                    print(f"Position reached within tolerance (Current: {self.current_pos_c})")
                    self.angle_set = True
                    break
                time.sleep(0.1)

            if not self.angle_set:
                print("Warning: Angle position not verified within timeout")
            return True # Return True even if not verified, maybe just delayed

        except Exception as e:
            print(f"Error in set_to_c_distance: {e}")
            return False

    # --- MODIFIED apply_continuous_pulse ---
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

            if not self.arduino.send("J"): return False # Command to start pulsing
            print(f"Protocol {self.protocol} ({time.time()}): Sent 'J' (start pulse) to Arduino.")
            pulse_command_active_j = True # Flag to track if "J" was sent

            last_keepalive_time = time.time()
            keepalive_interval = 30  # seconds
            check_interval = 0.2 # How often to check conditions in this loop

            while self.is_running and self.use_pulse: # *** KEY: Check self.use_pulse in loop condition ***
                current_time = time.time()

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

    # --- MODIFIED Protocol Methods ---
    def protocol_1(self):
        """Axial protocol - pressure only."""
        print("Running protocol 1...")
        if not self.check_duration(): return False

        self.signals.progress.emit(">>Starting axial protocol")

        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20: # Use dynamic self.max_pressure
            initial_pressure = max(20.0, MIN_PRESSURE)
        if not self.set_to_pressure(initial_pressure): return False
        if not self.run_pressure_sequence(MIN_PRESSURE, self.max_pressure): return False # Target is dynamic self.max_pressure

        # Final phase: pulse or hold, responsive to changes in self.use_pulse
        if self.is_running:
            main_phase_loop_active = True
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop. Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    # If we enter here, we intend to pulse.
                    # apply_continuous_pulse will run its own loop based on duration
                    # and will also internally check self.use_pulse to stop early if it changes.
                    print(f"Protocol {self.protocol} ({time.time()}): Loop decides to pulse. Calling apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        # Error during pulse
                        return False # Signal protocol failure
                    # apply_continuous_pulse completed (either by duration, stop, or self.use_pulse becoming False)
                    # The function handles the timed part. We break the outer loop now.
                    main_phase_loop_active = False
                else:
                    # Hold mode
                    # print(f"Protocol {self.protocol} ({time.time()}): Loop decides to hold.") # Verbose
                    time.sleep(0.5) # Check frequently if state changes back to pulse or duration ends

            # Ensure pulse is stopped if loop exited for any reason
            if hasattr(self.arduino, 'send') and self.arduino:
                 if not self.arduino.send("JS"): print("Warning: Failed sending final JS in P1")
                 print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")

        if not self.set_to_pressure(0): print("Warning: Failed to reset pressure at end of P1")
        print(f"Protocol {self.protocol} ({time.time()}): complete")
        return True # Signal success

    def protocol_2(self):
        """Axial with left lateral movement."""
        print("Running protocol 2...")
        if not self.check_duration(): return False

        self.signals.progress.emit(">>Starting left lateral protocol")

        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20: # Use dynamic self.max_pressure
             initial_pressure = max(20.0, MIN_PRESSURE)
        if not self.set_to_pressure(initial_pressure): return False
        if not self.run_pressure_sequence(MIN_PRESSURE, self.max_pressure): return False # Target is dynamic self.max_pressure

        if self.is_running:
            print(f"Moving to left {self.max_left}°") # Use dynamic self.max_left
            if not self.set_to_c_distance(self.max_left): return False # Use dynamic self.max_left

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop. Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    print(f"Protocol {self.protocol} ({time.time()}): Loop decides to pulse. Calling apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        return False # Error during pulse
                    main_phase_loop_active = False
                else:
                    # print(f"Protocol {self.protocol} ({time.time()}): Loop decides to hold.") # Verbose
                    time.sleep(0.5)

            if hasattr(self.arduino, 'send') and self.arduino:
                 if not self.arduino.send("JS"): print("Warning: Failed sending final JS in P2")
                 print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")

        # Reset
        if not self.set_to_c_distance(0): print("Warning: Failed setting C angle to 0 at end of P2")
        time.sleep(0.5) # Small delay for angle reset
        if not self.set_to_pressure(0): print("Warning: Failed resetting pressure at end of P2")
        print(f"Protocol {self.protocol} ({time.time()}): complete")
        return True # Signal success

    def protocol_3(self):
        """Axial with right lateral movement."""
        print("Running protocol 3...")
        if not self.check_duration(): return False

        self.signals.progress.emit(">>Starting right lateral protocol")

        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20: # Use dynamic self.max_pressure
            initial_pressure = max(20.0, MIN_PRESSURE)
        if not self.set_to_pressure(initial_pressure): return False
        if not self.run_pressure_sequence(MIN_PRESSURE, self.max_pressure): return False # Target is dynamic self.max_pressure

        if self.is_running:
            print(f"Moving to right {self.max_right}°") # Use dynamic self.max_right
            if not self.set_to_c_distance(self.max_right): return False # Use dynamic self.max_right

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop. Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    print(f"Protocol {self.protocol} ({time.time()}): Loop decides to pulse. Calling apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        return False # Error during pulse
                    main_phase_loop_active = False
                else:
                    # print(f"Protocol {self.protocol} ({time.time()}): Loop decides to hold.") # Verbose
                    time.sleep(0.5)

            if hasattr(self.arduino, 'send') and self.arduino:
                 if not self.arduino.send("JS"): print("Warning: Failed sending final JS in P3")
                 print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")

        # Reset
        if not self.set_to_c_distance(0): print("Warning: Failed setting C angle to 0 at end of P3")
        time.sleep(0.5) # Small delay for angle reset
        if not self.set_to_pressure(0): print("Warning: Failed resetting pressure at end of P3")
        print(f"Protocol {self.protocol} ({time.time()}): complete")
        return True # Signal success

    # --- MODIFIED run Method ---
    @QtCore.pyqtSlot() # Add pyqtSlot decorator
    def run(self):
        """Execute the selected protocol."""
        protocol_success = False # Track if protocol ran without error
        try:
            print("Starting protocol execution in thread...")
            self.is_running = True
            self.start_time = time.time()
            # Enable high-frequency status updates from Arduino
            if not self.arduino.send("HF1"):
                 raise ConnectionError("Failed to enable HF status updates.")
            time.sleep(0.1) # Allow command to process

            if self.protocol == "1":
                protocol_success = self.protocol_1()
            elif self.protocol == "2":
                protocol_success = self.protocol_2()
            elif self.protocol == "3":
                protocol_success = self.protocol_3()
            else:
                print(f"Unknown protocol: {self.protocol}")
                protocol_success = False # Unknown protocol is failure

            if protocol_success:
                 self.signals.progress.emit("Protocol complete")
            else:
                 self.signals.progress.emit("Protocol failed or stopped early.")
                 # Optional: emit a specific error signal if needed

        except Exception as e:
            print(f"Critical error executing protocol {self.protocol}: {e}")
            import traceback
            traceback.print_exc() # Log full traceback
            protocol_success = False
            self.signals.error.emit((e, traceback.format_exc())) # Emit error signal

        finally:
            print(f"Protocol {self.protocol} thread finishing. Success: {protocol_success}")
            self.is_running = False # Ensure flag is cleared
            # Always try to turn off high-frequency updates, even on error
            if self.arduino:
                if not self.arduino.send("HF0"): print("Warning: Failed sending HF0.")
                time.sleep(0.1)
            # Emit the finished signal with the success status
            self.signals.finished.emit(protocol_success)

    # --- stop and _start_keepalive_thread remain the same ---
    # (Keep your existing implementations)
    def stop(self):
        """Safely stop a running protocol."""
        print("Initiating protocol stop sequence...")
        self.is_running = False # Signal loops to stop

        # Ensure we have a valid Arduino connection
        if not self.arduino:
            print("Warning: No Arduino connection available for stop sequence")
            self.signals.stopped.emit(True) # Signal stop anyway
            return

        try:
            # Stop pulsing if active
            if hasattr(self, 'use_pulse') and self.use_pulse:
                 if not self.arduino.send("JS"): print("Warning: Failed sending JS on stop.")
                 time.sleep(0.1)

            # Turn off high-frequency status first
            if not self.arduino.send("HF0"): print("Warning: Failed sending HF0 on stop.")
            print(f"High frequency status turned off during stop.")
            time.sleep(0.5)  # Brief pause

            # Send emergency stop command
            if not self.arduino.send("X"): print("Warning: Failed sending X on stop.")
            print(f"Emergency stop command sent during stop.")
            time.sleep(0.5)

            # Send test command to verify connection is still active
            if not self.arduino.send("T"): print("Warning: Failed sending T on stop.")
            print(f"Test command sent during stop.")

            # Start a keepalive thread
            self._start_keepalive_thread()

            # Signal that the protocol was stopped
            self.signals.stopped.emit(True)

        except Exception as e:
            print(f"Error during protocol stop: {e}")
            self.signals.stopped.emit(False) # Signal stop failed

    def _start_keepalive_thread(self):
        """Start a separate thread to send periodic keepalive signals to Arduino."""
        def keepalive_worker():
            print("Starting keepalive worker thread")
            # Run for 60 seconds
            end_time = time.time() + 60
            keepalive_interval = 3
            last_keepalive = 0
            reconnect_attempts = 0
            max_reconnect_attempts = 3

            while time.time() < end_time:
                try:
                    current_time = time.time()
                    if current_time - last_keepalive >= keepalive_interval:
                        if self.arduino and hasattr(self.arduino, "send"):
                            success = False
                            if hasattr(self.arduino, "verify_connection"):
                                try:
                                    # Reduce verification frequency or timeout here if needed
                                    success = self.arduino.verify_connection(tries=1, timeout_s=1.0)
                                except Exception as ve:
                                    print(f"Error verifying connection in keepalive: {ve}")

                            if not success:
                                success = self.arduino.send("T")

                            if success:
                                if reconnect_attempts > 0 or last_keepalive == 0:
                                    print("Sent keepalive after protocol stop")
                                last_keepalive = current_time
                                reconnect_attempts = 0
                            else:
                                reconnect_attempts += 1
                                if reconnect_attempts <= max_reconnect_attempts:
                                    print(f"Keepalive failed, trying reconnect ({reconnect_attempts}/{max_reconnect_attempts})...")
                                    if hasattr(self.arduino, "reconnect"):
                                         # Use a shorter retry here?
                                        self.arduino.reconnect(max_retries=1)
                                else:
                                    print("Maximum reconnect attempts reached, stopping keepalive")
                                    break
                        else:
                             print("Keepalive: Arduino object invalid or missing.")
                             break # Stop if arduino object is gone

                except Exception as e:
                    print(f"Error in keepalive thread: {e}")
                    reconnect_attempts += 1
                    if reconnect_attempts > max_reconnect_attempts:
                        print("Too many errors in keepalive thread, stopping")
                        break

                time.sleep(1) # Check every second

            print("Keepalive thread finished")

        # Start background thread
        keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
        keepalive_thread.start()
        print("Keepalive thread started")