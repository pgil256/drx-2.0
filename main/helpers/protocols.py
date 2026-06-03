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
        max_left: float,
        max_right: float,
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
        self._state_lock = threading.Lock()
        self._current_pressure = 0.0
        self._current_pos_c = 0
        self.target_pos_c = None
        self.angle_set = False

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
        print(f"Protocol update_status received: A={pos_a}, B={pos_b}, C={pos_c}, Pressure={pressure}")
        
        # Store values with explicit type conversion
        self.current_pressure = float(pressure)
        self.current_pos_c = int(pos_c)
        
        # Emit separate pressure signal for dialogs and UI updates
        # Make sure to use float for pressure to avoid type conversion issues
        print(f"Protocol emitting pressure_emit with pressure={float(pressure)}")
        self.signals.pressure_emit.emit(float(pressure))
        
        # Also emit the full status update for other components
        print(f"Protocol emitting status_emit with all values")
        self.signals.status_emit.emit(int(pos_a), int(pos_b), int(pos_c), float(pressure))

    def check_duration(self) -> bool:
        """Check if protocol duration has expired."""
        if not self.start_time:
            print("Warning: No start time set for duration check")
            return False
        
        self.elapsed_time = time.time() - self.start_time
        
        # Only print status every 15 seconds
        if int(self.elapsed_time) % 15 == 0:
            print(f"Duration check - Elapsed: {self.elapsed_time:.1f}s / Total: {self.duration}s")
            
        return self.elapsed_time < self.duration

    def run_pressure_sequence(self, starting_pressure: float, target_pressure: float) -> bool:
            """Run a sequence of pressure increases from start to target."""
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                print(f"Error: Pressure {target_pressure} outside safe range (0-{MAX_SAFE_PRESSURE})")
                return False

            current_command = starting_pressure
            pressure_tolerance = 3  # Acceptable pressure difference in lbs
            max_wait_time = 5  # Increased max time to wait for pressure (seconds)
            max_retries = 5    # Increased max retries
            check_interval = 0.5  # Time between pressure checks in seconds
            last_check_time = 0  # Track when we last printed a status update
            
            # Initial pressure command 
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

            # Step through pressure increments with reduced monitoring
            while current_command < (target_pressure - PRESSURE_INCREMENT/2):
                if not self.is_running:
                    print("Emergency stop during pressure ramp")
                    return False
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

            # Send final pressure command
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
        max_wait_time = 5  # Maximum time to wait for pressure to stabilize (seconds)
        
        try:
            if not self.is_running:
                print("Cannot set pressure - protocol not running")
                return False
            if target_pressure < 0 or target_pressure > MAX_SAFE_PRESSURE:
                print(f"Error: Pressure {target_pressure} outside safe range (0-{MAX_SAFE_PRESSURE})")
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
            degrees = float(degrees)
            degrees = round(degrees * 2) / 2
            degrees = max(-20.0, min(20.0, degrees))
            degree_key = "{:.1f}".format(degrees)

            # Look up or interpolate position
            if degree_key in self.config.CMarks:
                position = int(self.config.CMarks[degree_key])
            else:
                marks = sorted((float(k), int(v)) for k, v in self.config.CMarks.items())
                for i in range(len(marks) - 1):
                    if marks[i][0] <= degrees <= marks[i + 1][0]:
                        deg1, pos1 = marks[i]
                        deg2, pos2 = marks[i + 1]
                        ratio = (degrees - deg1) / (deg2 - deg1)
                        position = pos1 + int((pos2 - pos1) * ratio)
                        break
                else:
                    raise ValueError(f"Degree value {degrees} outside valid range")

            # Send command and ensure high-frequency status updates for position monitoring
            self.angle_set = False
            self.target_pos_c = position
            if not self.arduino.send(f"K{position}"):
                print(f"Failed to send C actuator command K{position}")
                return False
            
            # Wait for position to be reached with live monitoring
            wait_start = time.time()
            while time.time() - wait_start < max_wait_time:
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

    def protocol_1(self):
        """Axial protocol - pressure only."""
        print("Running protocol 1...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting axial protocol")

        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            print(f"Setting higher initial pressure of {initial_pressure} lbs for max_pressure={self.max_pressure}")

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
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop. Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    # If we enter here, we intend to pulse.
                    # apply_continuous_pulse will run its own loop based on duration
                    # and will also internally check self.use_pulse to stop early if it changes.
                    print(f"Protocol {self.protocol} ({time.time()}): Loop decides to pulse. Calling apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        # Error during pulse - emit signal and return
                        self.signals.finished.emit(False)
                        return
                    # apply_continuous_pulse completed (either by duration, stop, or self.use_pulse becoming False)
                    # The function handles the timed part. We break the outer loop now.
                    main_phase_loop_active = False
                else:
                    # Hold mode
                    # print(f"Protocol {self.protocol} ({time.time()}): Loop decides to hold.") # Verbose
                    time.sleep(0.5) # Check frequently if state changes back to pulse or duration ends

            # Ensure pulse is stopped if loop exited for any reason
            if hasattr(self.arduino, 'send') and self.arduino:
                 if not self.arduino.send("JS"):
                     self.signals.finished.emit(False)
                     return
                 print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")
        
        # Reset
        if not self.set_to_pressure(0):
            self.signals.finished.emit(False)
            return
        print("Protocol 1 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_2(self):
        """Axial with left lateral movement."""
        print("Running protocol 2...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting left lateral protocol")
        
        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            print(f"Setting higher initial pressure of {initial_pressure} lbs for max_pressure={self.max_pressure}")
    
        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Move to left position
        if self.is_running:
            print(f"Moving to left {self.max_left}°")
            if not self.set_to_c_distance(self.max_left):
                self.signals.finished.emit(False)
                return

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop (pulse/hold). Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    print(f"Protocol {self.protocol} ({time.time()}): self.use_pulse is True, attempting to run apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        self.signals.reset_needed.emit()
                        self.signals.finished.emit(False)
                        return
                    main_phase_loop_active = False 
                else:
                    print(f"Protocol {self.protocol} ({time.time()}): self.use_pulse is False, in hold mode.")
                    time.sleep(0.5)
            
            if hasattr(self.arduino, 'send') and self.arduino:
                  if not self.arduino.send("JS"):
                      self.signals.finished.emit(False)
                      return
                  print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")

        # Reset
        if not self.set_to_c_distance(0):
            self.signals.finished.emit(False)
            return
        if not self.set_to_pressure(0):
            self.signals.finished.emit(False)
            return
        print("Protocol 2 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_3(self):
        """Axial with right lateral movement."""
        print("Running protocol 3...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting right lateral protocol")
        
        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            print(f"Setting higher initial pressure of {initial_pressure} lbs for max_pressure={self.max_pressure}")
    
        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            self.signals.finished.emit(False)
            return

        # Move to right position
        if self.is_running:
            print(f"Moving to right {self.max_right}°")
            if not self.set_to_c_distance(self.max_right):
                self.signals.finished.emit(False)
                return

            # Final phase: pulse or hold, responsive to changes in self.use_pulse
            main_phase_loop_active = True
            print(f"Protocol {self.protocol} ({time.time()}): Entering final phase loop (pulse/hold). Initial self.use_pulse={self.use_pulse}")
            while main_phase_loop_active and self.is_running and self.check_duration():
                if self.use_pulse:
                    print(f"Protocol {self.protocol} ({time.time()}): self.use_pulse is True, attempting to run apply_continuous_pulse.")
                    if not self.apply_continuous_pulse():
                        self.signals.reset_needed.emit()
                        self.signals.finished.emit(False)
                        return
                    main_phase_loop_active = False 
                else:
                    print(f"Protocol {self.protocol} ({time.time()}): self.use_pulse is False, in hold mode.")
                    time.sleep(0.5)
            
            if hasattr(self.arduino, 'send') and self.arduino:
                  if not self.arduino.send("JS"):
                      self.signals.finished.emit(False)
                      return
                  print(f"Protocol {self.protocol} ({time.time()}): Sent final 'JS' after main phase loop.")

        # Reset
        if not self.set_to_c_distance(0):
            self.signals.finished.emit(False)
            return
        
        # Simple wait for returning to center position
        time.sleep(1)
            
        if not self.set_to_pressure(0):
            self.signals.finished.emit(False)
            return
        print("Protocol 3 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_4(self):
        """Axial with oscillating lateral movement between left and right."""
        print("Running protocol 4...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting oscillating lateral protocol")
        
        # Determine initial pressure based on max pressure
        initial_pressure = MIN_PRESSURE
        if self.max_pressure > 20:
            initial_pressure = max(20.0, MIN_PRESSURE)
            print(f"Setting higher initial pressure of {initial_pressure} lbs for max_pressure={self.max_pressure}")
    
        # Initial pressure setting
        if not self.set_to_pressure(initial_pressure):
            self.signals.finished.emit(False)
            return

        if not self.run_pressure_sequence(initial_pressure, self.max_pressure):
            self.signals.finished.emit(False)
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
                self.signals.finished.emit(False)
                return
            
            # Start pulsing if enabled
            if self.use_pulse and self.arduino:
                if not self.arduino.send("J"):
                    self.signals.finished.emit(False)
                    return
                pulse_active = True
                print(f"Protocol 4: Started continuous pulsing")
            
            while self.is_running and self.check_duration():
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
                            self.signals.finished.emit(False)
                            return
                        position_at_left = False
                    else:
                        # Move to left
                        print(f"Oscillating to left {self.max_left}°")
                        self.signals.progress.emit(f">>Moving to left {self.max_left}°")
                        if not self.set_to_c_distance(self.max_left):
                            self.signals.finished.emit(False)
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
                    if not self.arduino.send("J"):
                        self.signals.finished.emit(False)
                        return
                    pulse_active = True
                    print(f"Protocol 4: Restarted pulsing")
                elif not self.use_pulse and pulse_active and self.arduino:
                    # Pulse was turned off
                    if not self.arduino.send("JS"):
                        self.signals.finished.emit(False)
                        return
                    pulse_active = False
                    print(f"Protocol 4: Stopped pulsing")
                
                # Send periodic keepalive
                if int(current_time) % 30 == 0:
                    if self.arduino:
                        if not self.arduino.send("T"):
                            self.signals.finished.emit(False)
                            return
                
                time.sleep(0.1)  # Main loop sleep
            
            # Stop pulsing if it was active
            if pulse_active and self.arduino:
                if not self.arduino.send("JS"):
                    self.signals.finished.emit(False)
                    return
                print(f"Protocol 4: Stopped final pulsing")

        # Reset
        if not self.set_to_c_distance(0):
            self.signals.finished.emit(False)
            return
        time.sleep(1)  # Wait for return to center
        if not self.set_to_pressure(0):
            self.signals.finished.emit(False)
            return
        print("Protocol 4 complete")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

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
        """Safely stop a running protocol."""
        print("Initiating protocol stop sequence...")
        self.is_running = False
        
        # Ensure we have a valid Arduino connection
        if not self.arduino:
            print("Warning: No Arduino connection available for stop sequence")
            self.signals.stopped.emit(True)
            return
        
        try:
            # Turn off high-frequency status first (more reliable before emergency stop)
            success = self.arduino.send("HF0")
            print(f"High frequency status turned off: {'Success' if success else 'Failed'}")
            time.sleep(0.5)  # Brief pause before next command
            
            # Send emergency stop command
            success = self.arduino.send("X")
            print(f"Emergency stop command sent: {'Success' if success else 'Failed'}")
            
            # Wait for a moment to let the stop command process
            time.sleep(0.5)  # Increased wait time
            
            # Send test command to verify connection is still active
            success = self.arduino.send("T")
            print(f"Test command sent: {'Success' if success else 'Failed'}")
            
            # Start a keepalive thread that continues even after worker is "stopped"
            # This prevents connection timeouts
            self._start_keepalive_thread()
            
            # Signal that the protocol was stopped
            self.signals.stopped.emit(True)
            
        except Exception as e:
            print(f"Error during protocol stop: {e}")
            self.signals.stopped.emit(False)
    
    def _start_keepalive_thread(self):
        """Start a separate thread to send periodic keepalive signals to Arduino."""
        def keepalive_worker():
            print("Starting keepalive worker thread")
            # Run for 60 seconds to ensure Arduino connection is maintained
            # even after the QRunnable is removed from the threadpool
            end_time = time.time() + 60  # Extended duration to 60 seconds
            keepalive_interval = 3  # More frequent - every 3 seconds
            last_keepalive = 0
            reconnect_attempts = 0
            max_reconnect_attempts = 3
            
            while time.time() < end_time:
                try:
                    current_time = time.time()
                    if current_time - last_keepalive >= keepalive_interval:
                        if self.arduino and hasattr(self.arduino, "send"):
                            # Try to verify connection first
                            success = False
                            if hasattr(self.arduino, "verify_connection"):
                                try:
                                    success = self.arduino.verify_connection(tries=3, timeout_s=5.0)
                                except Exception as ve:
                                    print(f"Error verifying connection: {ve}")
                            
                            # If verification fails or unavailable, try basic send
                            if not success:
                                success = self.arduino.send("T")  # Test command as keepalive
                            
                            if success:
                                # Only print keepalive message on first success or after failures
                                if reconnect_attempts > 0 or last_keepalive == 0:
                                    print("Sent keepalive after protocol stop")
                                last_keepalive = current_time
                                reconnect_attempts = 0  # Reset counter on success
                            else:
                                # Try reconnecting if connection seems lost
                                reconnect_attempts += 1
                                if reconnect_attempts <= max_reconnect_attempts:
                                    print(f"Keepalive failed, trying reconnect ({reconnect_attempts}/{max_reconnect_attempts})...")
                                    if hasattr(self.arduino, "reconnect"):
                                        self.arduino.reconnect(max_retries=1)
                                else:
                                    print("Maximum reconnect attempts reached, stopping keepalive")
                                    break
                except Exception as e:
                    print(f"Error in keepalive thread: {e}")
                    reconnect_attempts += 1
                    if reconnect_attempts > max_reconnect_attempts:
                        print("Too many errors in keepalive thread, stopping")
                        break
                    
                time.sleep(1)
            
            print("Keepalive thread finished")
        
        # Start background thread
        keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
        keepalive_thread.start()
        print("Keepalive thread started")
