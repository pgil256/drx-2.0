from datetime import datetime
import time
import threading
import logging
from utils.logging import setup_logger
from typing import Optional
from PyQt5 import QtCore
from helpers import worker_signals

# Constants
DEGREES0 = 0  # Center/neutral position
MIN_PRESSURE = 10  # Minimum starting pressure in lbs
MAX_SAFE_PRESSURE = 100  # Maximum safe pressure in lbs
HOLD_TIME_SHORT = 1
HOLD_TIME_LONG = 5  # Default hold duration in seconds
PRESSURE_INCREMENT = 5  # Standard pressure increase step
ANGLE_INCREMENT = 2.5  # Standard angle adjustment step


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
        self.signals = worker_signals.WorkerSignals()

        # Protocol parameters
        self.protocol = protocol
        self.max_pressure = max_pressure
        self.max_left = -abs(max_left)  # Ensure negative for left
        self.max_right = abs(max_right)  # Ensure positive for right
        self.duration = duration * 60  # Convert to seconds
        self.use_pulse = use_pulse

        # State tracking
        self.is_running = False
        self.I2Cstatus = 0
        self.exit_flag = threading.Event()
        self.start_time = None
        self.elapsed_time = 0
        self.current_pressure = 0
        self.angle_set = False  # Flag to track if angle is set

        # Connect signals if arduino is provided
        if ser is not None and hasattr(ser, "status_emit"):
            ser.status_emit.connect(self.update_status)

        print(f"Protocols class initialized with use_pulse={use_pulse}")

    def update_status(self, pos_a, pos_b, pos_c, pressure):
        """Update current status values from Arduino feedback."""
        self.current_pressure = pressure
        # Forward pressure to UI if needed
        self.signals.pressure_emit.emit(float(pressure))

    def apply_continuous_pulse(self) -> bool:
        """Apply continuous pulse sequence until duration expires."""
        if not self.is_running or not self.use_pulse:
            return True

        try:
            print("Starting continuous pulse sequence...")
            self.signals.progress.emit(">>Starting continuous pulsing")

            # Send initial jerking command to Arduino
            print("Sending jerk command")
            self.arduino.send("J")
            self.signals.progress.emit(">>Pulsing")

            # Monitor until protocol completes or is stopped
            while self.is_running and self.check_duration():
                # Brief check interval without disrupting Arduino
                time.sleep(0.5)

                # Check if we should continue
                if not self.check_duration() or not self.is_running:
                    break

            # Stop jerking when done
            if self.is_running:
                print("Pulse sequence complete due to time expiration")
            else:
                print("Pulse sequence stopped by user")

            # Send stop command
            self.arduino.send("JS")  # Stop jerking
            time.sleep(1)  # Increased wait time after stopping pulse

            return True

        except Exception as e:
            from utils.exceptions import ProtocolExecutionError
            error = ProtocolExecutionError(f"Error during pulse sequence: {e}")
            print(f"Error during pulse sequence: {error}")
            self.arduino.send("JS")  # Try to stop jerking even on error
            return False

    def run(self):
        """Implementation of QRunnable's run method to execute in thread pool."""
        try:
            self.is_running = True
            self.start_time = time.time()

            # Execute the right protocol based on protocol number
            if self.protocol == "1":
                self.protocol_1()
            elif self.protocol == "2":
                self.protocol_2()
            elif self.protocol == "3":
                self.protocol_3()
            else:
                from utils.exceptions import ProtocolValidationError
                error = ProtocolValidationError(f"Unknown protocol: {self.protocol}")
                print(f"Error: {error}")
                self.signals.finished.emit(False)
        except Exception as e:
            from utils.exceptions import ProtocolExecutionError
            error = ProtocolExecutionError(f"Error executing protocol: {str(e)}")
            print(f"Error executing protocol: {error}")
            self.is_running = False
            self.signals.finished.emit(False)

    def stop(self):
        """Safely stop a running protocol."""
        print("Stopping protocol")
        self.is_running = False
        self.exit_flag.set()  # Signal threads to exit

        # Send stop command to Arduino
        if self.arduino:
            self.arduino.send("X")  # Emergency stop command

        # Notify UI of completion
        self.signals.stopped.emit(True)

    def check_duration(self):
        """Check if protocol duration has expired.

        Returns:
            bool: True if should continue, False if time expired
        """
        if not self.start_time:
            return False

        self.elapsed_time = time.time() - self.start_time
        return self.elapsed_time < self.duration

    def set_to_angle(self, degrees):
        """Set lateral flexion to specified angle."""
        try:
            if not self.is_running:
                return False

            print(f"Setting angle to {degrees}°")
            self.angle_set = False  # Reset angle flag

            # Format for dictionary lookup with one decimal place
            degree_key = "{:.1f}".format(degrees)

            # Get position value from CMarks dictionary
            if degree_key in self.config.CMarks:
                position = self.config.CMarks[degree_key]
                print(f"Position value for {degrees}° is {position}")

                # Send command to Arduino
                self.arduino.send(f"K{position}")
                self.signals.progress.emit(f">>Setting angle to {degrees}°")

                # Use a fixed delay instead of waiting for I2Cstatus
                time.sleep(3)  # Increased wait time for angle setting

                # Get a status update to ensure position is set
                self.arduino.send("S")
                time.sleep(1)

                self.I2Cstatus = 1  # Force status to 1
                self.angle_set = True  # Mark angle as set
                print(f"Angle set to {degrees}° completed")

                return True
            else:
                from utils.exceptions import ProtocolValidationError
                error = ProtocolValidationError(f"No position defined for angle {degrees}°")
                print(f"Error: {error}")
                return False

        except Exception as e:
            from utils.exceptions import ActuatorException
            error = ActuatorException(f"Error setting angle: {str(e)}")
            print(f"Error setting angle: {error}")
            return False

    def set_to_pressure(self, pressure):
        """Set axial pressure to specified value."""
        try:
            if not self.is_running:
                return False

            print(f"Setting pressure to {pressure} lbs")

            # Validate pressure is within safe limits
            if pressure < 0 or pressure > MAX_SAFE_PRESSURE:
                from utils.exceptions import SafetyLimitException
                error = SafetyLimitException(
                    f"Pressure {pressure} outside safe range (0-{MAX_SAFE_PRESSURE})",
                    severity="HIGH",
                    limit_type="pressure",
                    current_value=pressure,
                    limit_value=MAX_SAFE_PRESSURE
                )
                print(f"Error: {error}")
                return False

            # Send command to Arduino
            self.arduino.send(f"P{pressure}")
            self.signals.progress.emit(f">>Setting pressure to {pressure} lbs")
            self.signals.pressure_emit.emit(float(pressure))

            # Wait for pressure to be applied with timeout
            wait_start = time.time()
            max_wait = 5  # Maximum wait time in seconds

            while (time.time() - wait_start) < max_wait:
                # Check if target pressure reached within tolerance (±2 lbs)
                if abs(self.current_pressure - pressure) <= 2:
                    print(
                        f"Target pressure {pressure} reached at {self.current_pressure}"
                    )
                    self.I2Cstatus = 1
                    return True

                # Request status update to get latest pressure
                if (time.time() - wait_start) > 1:  # Don't spam requests
                    self.arduino.send("S")

                time.sleep(0.5)

            from utils.exceptions import ArduinoTimeoutError
            timeout_warning = ArduinoTimeoutError(
                f"Pressure set operation timed out. Current: {self.current_pressure}, Target: {pressure}"
            )
            print(f"Warning: {timeout_warning}")
            self.I2Cstatus = 1  # Force status to continue
            return True

        except Exception as e:
            from utils.exceptions import ActuatorException
            error = ActuatorException(f"Error setting pressure: {str(e)}")
            print(f"Error setting pressure: {error}")
            return False

    def update_I2Cstatus(self):
        """Update I2C status flag."""
        self.I2Cstatus = 1

    def reset_actuators(self):
        """Reset all actuators to safe positions."""
        try:
            print("Performing final reset sequence...")

            # First ensure jerking/pulsing is stopped
            self.arduino.send("JS")
            time.sleep(1)

            # Then return to neutral angle
            degree_key = "{:.1f}".format(0)
            if degree_key in self.config.CMarks:
                position = self.config.CMarks[degree_key]
                self.arduino.send(f"K{position}")
                time.sleep(3)  # Wait for movement to complete

            # Then set pressure to zero
            self.arduino.send("P0")
            time.sleep(2)

            # Final status check
            self.arduino.send("S")
            time.sleep(1)

            print("Reset sequence completed")
            return True
        except Exception as e:
            from utils.exceptions import ActuatorException
            error = ActuatorException(f"Error during reset sequence: {e}", requires_reset=True)
            print(f"Error during reset sequence: {error}")
            return False

    def protocol_1(self):
        """Axial protocol - pressure only."""
        print("Running protocol 1...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting axial protocol")

        # Start with minimal pressure
        current_pressure = MIN_PRESSURE
        if not self.set_to_pressure(current_pressure):
            return

        self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

        # Gradually increase to max pressure
        while (
            current_pressure < self.max_pressure
            and self.is_running
            and self.check_duration()
        ):
            current_pressure = min(
                current_pressure + PRESSURE_INCREMENT, self.max_pressure
            )
            print(f"Increasing pressure to {current_pressure} lbs.")

            if not self.set_to_pressure(current_pressure):
                return

            self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

            # Request status update to get latest pressure
            self.arduino.send("S")
            time.sleep(0.5)

        # Ensure we're at max pressure before pulsing
        if self.current_pressure < (self.max_pressure - 3):
            print(
                f"Adjusting final pressure from {self.current_pressure} to {self.max_pressure}"
            )
            if not self.set_to_pressure(self.max_pressure):
                return

            # Extra wait to ensure pressure stabilizes
            self.exit_flag.wait(timeout=2.0)

            # Request status update to get latest pressure
            self.arduino.send("S")
            time.sleep(0.5)

        # At max pressure, either pulse continuously or hold until time expires
        if self.is_running and self.use_pulse:
            # Regardless of exact pressure, apply pulse if pulse mode is enabled
            print(f"Applying continuous pulses at pressure {self.current_pressure}")
            if not self.apply_continuous_pulse():
                return
        elif self.is_running:
            # Hold at max pressure until time expires
            print("Holding at max pressure until time expires.")
            while self.is_running and self.check_duration():
                self.exit_flag.wait(timeout=HOLD_TIME_LONG)

                # Periodic status check
                if self.is_running and self.check_duration():
                    self.arduino.send("S")
                    time.sleep(0.1)

        # Reset actuators after protocol completes
        self.signals.reset_needed.emit()

        print("Protocol 1 complete.")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_2(self):
        """Axial with left lateral movement."""
        print("Running protocol 2...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting left lateral protocol")

        # First reset to ensure we're starting from a known state
        self.signals.reset_needed.emit()
        time.sleep(1)

        # Start with pressure before moving to angle
        current_pressure = MIN_PRESSURE
        if not self.set_to_pressure(current_pressure):
            self.signals.finished.emit(False)
            return

        self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

        # Gradually increase to max pressure
        while (
            current_pressure < self.max_pressure
            and self.is_running
            and self.check_duration()
        ):
            current_pressure = min(
                current_pressure + PRESSURE_INCREMENT, self.max_pressure
            )
            print(f"Increasing pressure to {current_pressure} lbs.")

            if not self.set_to_pressure(current_pressure):
                self.signals.finished.emit(False)
                return

            self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

            # Request status update to get latest pressure
            self.arduino.send("S")
            time.sleep(0.5)

        # Ensure we're at max pressure
        if self.current_pressure < (self.max_pressure - 3):
            print(
                f"Adjusting final pressure from {self.current_pressure} to {self.max_pressure}"
            )
            if not self.set_to_pressure(self.max_pressure):
                self.signals.finished.emit(False)
                return

            # Extra wait to ensure pressure stabilizes
            self.exit_flag.wait(timeout=2.0)

        if self.is_running:
            # IMPORTANT: Move to angle position FIRST before any pulsing
            print(f"Moving to left {self.max_left}°.")
            if not self.set_to_angle(self.max_left):
                self.signals.finished.emit(False)
                return

            # Additional delay to ensure position is stable
            time.sleep(3)

            # Verify angle has been set
            if not self.angle_set:
                print("Warning: Angle may not be properly set. Continuing anyway.")

            # Now that angle is set, apply pulsing if enabled
            if self.use_pulse:
                print("Angle set complete. Now applying continuous pulses.")
                if not self.apply_continuous_pulse():
                    self.signals.reset_needed.emit()
                    self.signals.finished.emit(False)
                    return
            else:
                # Hold at position until time expires
                print("Holding at position until time expires.")
                while self.is_running and self.check_duration():
                    self.exit_flag.wait(timeout=HOLD_TIME_LONG)
                    # Periodic status check
                    if self.is_running and self.check_duration():
                        self.arduino.send("S")
                        time.sleep(0.5)

        # Ensure reset happens regardless of how we exit the protocol
        self.signals.reset_needed.emit()

        print("Protocol 2 complete.")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)

    def protocol_3(self):
        """Axial with right lateral movement."""
        print("Running protocol 3...")
        if not self.check_duration():
            return

        self.signals.progress.emit(">>Starting right lateral protocol")

        # First reset to ensure we're starting from a known state
        self.signals.reset_needed.emit()
        time.sleep(1)

        # Start with pressure before moving to angle
        current_pressure = MIN_PRESSURE
        if not self.set_to_pressure(current_pressure):
            self.signals.finished.emit(False)
            return

        self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

        # Gradually increase to max pressure
        while (
            current_pressure < self.max_pressure
            and self.is_running
            and self.check_duration()
        ):
            current_pressure = min(
                current_pressure + PRESSURE_INCREMENT, self.max_pressure
            )
            print(f"Increasing pressure to {current_pressure} lbs.")

            if not self.set_to_pressure(current_pressure):
                self.signals.finished.emit(False)
                return

            self.exit_flag.wait(timeout=HOLD_TIME_SHORT)

            # Request status update to get latest pressure
            self.arduino.send("S")
            time.sleep(0.5)

        # Ensure we're at max pressure
        if self.current_pressure < (self.max_pressure - 3):
            print(
                f"Adjusting final pressure from {self.current_pressure} to {self.max_pressure}"
            )
            if not self.set_to_pressure(self.max_pressure):
                self.signals.finished.emit(False)
                return

            # Extra wait to ensure pressure stabilizes
            self.exit_flag.wait(timeout=2.0)

        if self.is_running:
            # IMPORTANT: Move to angle position FIRST before any pulsing
            print(f"Moving to right {self.max_right}°.")
            if not self.set_to_angle(self.max_right):
                self.signals.finished.emit(False)
                return

            # Additional delay to ensure position is stable
            time.sleep(3)

            # Verify angle has been set
            if not self.angle_set:
                print("Warning: Angle may not be properly set. Continuing anyway.")

            # Now that angle is set, apply pulsing if enabled
            if self.use_pulse:
                print("Angle set complete. Now applying continuous pulses.")
                if not self.apply_continuous_pulse():
                    self.signals.reset_needed.emit()
                    self.signals.finished.emit(False)
                    return
            else:
                # Hold at position until time expires
                print("Holding at position until time expires.")
                while self.is_running and self.check_duration():
                    self.exit_flag.wait(timeout=HOLD_TIME_LONG)
                    # Periodic status check
                    if self.is_running and self.check_duration():
                        self.arduino.send("S")
                        time.sleep(0.5)

        # Ensure reset happens regardless of how we exit the protocol
        self.signals.reset_needed.emit()

        print("Protocol 3 complete.")
        self.signals.progress.emit("Protocol complete")
        self.signals.finished.emit(True)
        
