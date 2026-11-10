"""Setup movement, extracted from the KneeSpa window (checklist A3).

The Setup screen's jog, Go, reset and stop handlers, the commanded-position
tracking, the 200 ms enable debounce and the P2 watchdog for a DONE that never
arrives used to be KneeSpa methods that read the whole window. They live here
now, with their bodies unchanged apart from where they read state, behind
narrow collaborators instead of the window:

- ``arduino``: returns the current Arduino transport, or None;
- ``config``: returns the device configuration (marks and calibration flags);
- ``state``: the window's :class:`~controllers.device_state.DeviceState`;
- ``view``: a :class:`SetupView`, the few screen operations movement needs.

The leg-length controller, the treatment-running flag, the DONE event and the
leg GPIO release are passed in the same way. KneeSpa keeps thin methods under
the old names that delegate here, and :class:`MotionAttributes` keeps its old
position and timer attribute names working.
"""

import threading
from typing import Any, Callable, Optional

import RPi.GPIO as GPIO
from PyQt5.QtCore import QTimer

from config.constants import (
    ACTUATORS,
    AXIAL_MAX_INCHES,
    AXIAL_MIN_INCHES,
    DEFAULT_HORIZONTAL_POSITION,
    DEGREES,
    EXTRABACKWARD,
    EXTRAFORWARD,
    HORIZONTAL_MAX_DEGREES,
    HORIZONTAL_MIN_DEGREES,
    LATERAL_MAX_DEGREES,
    LATERAL_MIN_DEGREES,
    MIN_PRESSURE,
    PRESSURE_MAX,
    SETUP_MOTION_DONE_TIMEOUT_S,
)
from helpers.conversions import (
    horizontal_degrees_to_position,
    lateral_degrees_to_position,
)
from helpers.hardware_service import axial_position
from ui.presentation import present

TREATMENT_ACTIVE_MESSAGE = "Stop treatment before moving the device from Setup."


class SetupView:
    """The screen operations MotionController needs, and nothing else.

    :class:`WindowSetupView` adapts the KneeSpa window; tests use a fake.
    """

    def row_value(self, key: str) -> float:
        """The value a Setup row's slider is set to."""
        raise NotImplementedError

    def show_position(self, key: str, value) -> None:
        """Show a commanded target on its Setup row (not a measured value)."""
        raise NotImplementedError

    def set_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable the Setup motion controls as one group."""
        raise NotImplementedError

    def show_busy(self) -> None:
        raise NotImplementedError

    def hide_busy(self) -> None:
        raise NotImplementedError

    def show_error(self, message: str) -> None:
        """A timed error the operator must see."""
        raise NotImplementedError

    def warn_uncalibrated(self) -> None:
        raise NotImplementedError

    def show_link_down(self) -> None:
        """Mark the Arduino link as offline."""
        raise NotImplementedError


class WindowSetupView(SetupView):
    """The KneeSpa window's screen, as MotionController sees it."""

    def __init__(self, window) -> None:
        self._window = window

    def row_value(self, key):
        return self._window.shell.setup.row_value(key)

    def show_position(self, key, value):
        window = self._window
        present(window.logger, "Setup position",
                lambda: window.shell.setup.set_position(key, value))

    def set_controls_enabled(self, enabled):
        for w in self._window.actuator_controls:
            w.setEnabled(enabled)

    def show_busy(self):
        self._window.loading_spinner.show()

    def hide_busy(self):
        self._window.loading_spinner.hide()

    def show_error(self, message):
        self._window._show_timed_error(message)

    def warn_uncalibrated(self):
        self._window._warn_uncalibrated()

    def show_link_down(self):
        self._window._set_badge(False)


class MotionController:
    """Setup movement: jog, Go, reset and stop, and the motion-control gate."""

    def __init__(
        self,
        arduino: Callable[[], Any],
        config: Callable[[], Any],
        state,
        view: SetupView,
        *,
        logger,
        leg: Callable[[], Any] = lambda: None,
        done_event: Optional[threading.Event] = None,
        protocol_running: Callable[[], bool] = lambda: False,
        release_leg_gpio: Callable[[], None] = lambda: None,
        timer_parent=None,
    ) -> None:
        self._arduino = arduino
        self._config = config
        self.state = state
        self.view = view
        self.logger = logger
        self._leg = leg
        self.done_event = done_event if done_event is not None else threading.Event()
        self._protocol_running = protocol_running
        self._release_leg_gpio = release_leg_gpio
        self._timer_parent = timer_parent
        self.actuator_a = ACTUATORS["AXIAL"]["ID"]
        self.actuator_b = ACTUATORS["HORIZONTAL"]["ID"]
        self.actuator_c = ACTUATORS["LATERAL"]["ID"]
        # Commanded positions (legacy setup_actuator_controls defaults).
        self.axial_flexion_position = 0
        self.horizontal_flexion_position = DEFAULT_HORIZONTAL_POSITION
        self.lateral_flexion_position = 0
        self.controls_enable_timer = None  # Single pending-enable timer for all controls
        self._motion_watchdog = None  # Backstop for a Setup move whose DONE never arrives

    @property
    def arduino(self):
        return self._arduino()

    @property
    def config(self):
        return self._config()

    @property
    def leg(self):
        return self._leg()

    # ----- position commands -----

    def set_to_distance(self, inches, actuator):
        command = "A{}{:.1f}".format(actuator, inches)
        config = self.config
        if str(actuator) == "12" and getattr(config, "axial_service_calibrated", False) is True:
            try:
                command = f"I12{axial_position(config.AMarks, inches)}"
            except (ValueError, TypeError, KeyError) as exc:
                self.view.show_error(f"Axial calibration is invalid: {exc}")
                return False
        self.done_event.clear()
        if not self.send_motion_command(command, "axial movement"):
            return False
        self.logger.debug("Sent cmd %s", command.strip())
        self.logger.debug("End set to distance")
        return True

    def set_to_c_distance(self, degrees):
        """
        Set the C actuator position based on degrees with proper type handling.

        Args:
            degrees (float): Target angle in degrees
        """
        self.view.show_busy()
        self.disable_actuator_controls()
        try:
            position, degrees = lateral_degrees_to_position(
                self.config.CMarks, degrees
            )

            self.logger.debug(" positioned to %s degrees pos %s", degrees, position)
            command = f"K{position}"
            self.done_event.clear()
            if not self.send_motion_command(command, "lateral movement"):
                return False
            self.logger.debug("cmd %s", command)

            self.logger.debug("End set to c.")
            self.view.hide_busy()
            return True

        except Exception:
            self.view.hide_busy()
            self.logger.exception("Error in set_to_c_distance")
            self.logger.error("Degrees: %s, Type: %s", degrees, type(degrees))
            self.logger.error("CMarks: %s", self.config.CMarks)
            return False

    # ----- the treatment interlock -----

    def _treatment_active(self) -> bool:
        """A treatment is starting, running or stopping, so it owns the actuators.

        Either the lifecycle state or the running flag is enough; the two can
        differ briefly while a start is dispatched.
        """
        return (bool(self._protocol_running())
                or self.state.protocol_state in ("starting", "running", "stopping"))

    def _refuse_during_treatment(self) -> bool:
        """True, with the reason shown, while a treatment owns the actuators.

        The firmware takes a plain P<n> during a ramp or hold as the new
        pressure limit, and answers a position move with BUSY, which the
        treatment worker treats as a fault. Checked here, where a command
        would be sent, so it holds for every widget and signal. The stop
        paths never ask.
        """
        if not self._treatment_active():
            return False
        self.logger.warning("Setup movement refused: a treatment is active")
        self.view.show_error(TREATMENT_ACTIVE_MESSAGE)
        return True

    def send_motion_command(self, command, context):
        """Queue a Setup motion without fabricating success in the UI."""
        if self.state.closing is True:
            return False
        # F0 is the leg-length stop: it is always sent.
        if command != "F0" and self._refuse_during_treatment():
            # As for a failed send: a caller may already have taken the
            # controls. They stay locked while the treatment runs.
            self.enable_actuator_controls()
            self.view.hide_busy()
            return False
        if (self.state.calibration_active is True
                or self.state.device_maintenance_active is True):
            self.view.show_error("Finish device service before normal movement.")
            return False
        try:
            arduino = self.arduino
            queued = bool(arduino and arduino.send(command))
        except Exception:
            queued = False
            self.logger.exception("Could not queue %s command %s", context, command)
        if queued:
            # Position (A/I/K) and pressure (P) moves re-enable the controls
            # only on the firmware's DONE; F0 is a stop the leg controller owns.
            if command[:1] in ("A", "I", "K", "P"):
                self._arm_motion_watchdog()
            return True

        self.logger.error("Could not queue %s command %s", context, command)
        self.view.show_link_down()
        self.view.show_error(
            f"{context.capitalize()} was not sent. Check the Arduino connection."
        )
        self.enable_actuator_controls()
        self.view.hide_busy()
        return False

    # ----- the DONE watchdog (P2) -----

    def _arm_motion_watchdog(self):
        """Start the backstop for a queued Setup move awaiting its DONE."""
        self._stop_motion_watchdog()
        # Parent it to the window so it cannot outlive it.
        parent = self._timer_parent
        timer = QTimer(parent) if parent is not None else QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_motion_watchdog())
        timer.start(int(SETUP_MOTION_DONE_TIMEOUT_S * 1000))
        self._motion_watchdog = timer

    def _stop_motion_watchdog(self):
        timer = self._motion_watchdog
        if timer is not None:
            timer.stop()
            self._motion_watchdog = None

    def _on_motion_watchdog(self):
        """No DONE for a Setup move: hand the controls back to the operator.

        Without this a lost DONE kept actuator_command_in_progress set, which
        also blocks logout and exit. enable_actuator_controls keeps its own
        guards, so a reset, service session or fault still owns the controls.
        """
        self._motion_watchdog = None
        # This fires from a timer, where an exception would only reach the
        # excepthook and leave the controls locked.
        if (self.state.actuator_command_in_progress is not True
                or self.state.closing is True
                or self._protocol_running() is True):
            return
        self.logger.error(
            "No DONE from the device within %s s of a Setup move; re-enabling controls",
            SETUP_MOTION_DONE_TIMEOUT_S,
        )
        self.view.hide_busy()
        self.view.show_error(
            "The device did not report that the movement finished. "
            "Check the device before moving again."
        )
        self.enable_actuator_controls()

    # ----- the motion-control gate and its 200 ms debounce -----

    def disable_actuator_controls(self):
        # A new command or operation supersedes any pending move's backstop.
        self._stop_motion_watchdog()
        # Cancel any pending enable so it cannot fire mid-command and
        # re-enable controls while the MCU is still busy
        if self.controls_enable_timer is not None:
            self.controls_enable_timer.stop()
            self.controls_enable_timer = None
        self.state.actuator_command_in_progress = True
        self.view.set_controls_enabled(False)

    def enable_actuator_controls(self):
        # Completion (or an owner taking over) ends the pending move's backstop.
        self._stop_motion_watchdog()
        if getattr(self.leg, "active", False) is True:
            return
        if not self.state.can_move():
            return
        self.state.actuator_command_in_progress = False
        # "== False", as before: an unset (None) running flag schedules nothing.
        if self._protocol_running() == False:
            self.logger.debug("Scheduling controls to enable with delay...")
            # Single timer instance shared by all controls: a new enable
            # request supersedes any pending one instead of stacking
            # per-widget timers that can interleave with a later disable
            if self.controls_enable_timer is not None:
                self.controls_enable_timer.stop()
            self.controls_enable_timer = QTimer()
            self.controls_enable_timer.setSingleShot(True)
            self.controls_enable_timer.timeout.connect(
                self._apply_enable_actuator_controls
            )
            self.controls_enable_timer.start(200)

    def _apply_enable_actuator_controls(self):
        self.controls_enable_timer = None
        if getattr(self.leg, "active", False) is True:
            return
        if (self.state.calibration_active is True
                or self.state.device_maintenance_active is True):
            return
        # The state may have changed during the 200 ms debounce window.
        if (
            self.state.reset_in_progress
            or not self.state.initial_setup_complete
            or self._protocol_running()
            or self.state.protocol_state == "fault"
        ):
            return
        self.view.set_controls_enabled(True)

    # ----- Setup: go / reset / stop -----

    def _reflect_setup(self, key, value):
        """Reflect a commanded target without claiming that a sensor measured it."""
        self.view.show_position(key, value)

    def setup_reset(self, key):
        """A Setup row's reset (home) button."""
        if self._refuse_during_treatment():
            return
        if key == "axial":
            self.reset_flexion_button_clicked(self.actuator_a)
        elif key == "lateral":
            self.reset_flexion_button_clicked(self.actuator_c)
        elif key == "horizontal":
            self.reset_flexion_button_clicked(self.actuator_b)
        elif key == "leg_length":
            # Home the open-loop FIT axis, updating zero only after completion.
            self.leg.home()
        elif key == "pressure":
            self.view.show_busy()
            self.disable_actuator_controls()
            # DONE re-enables the controls via set_done. The treatment banner
            # is reserved for protocol stops: set_stopping() here had no
            # matching set_idle(), so "STOPPING - RELEASING TRACTION" stayed
            # over the top bar until the next treatment or Arduino reset.
            self.send_motion_command("P0", "pressure release")
            self.view.hide_busy()

    def setup_go(self, key):
        """Move an actuator to its row's current slider value (the legacy Go
        path), preserving the per-actuator unit conversions and clamps.

        The caller has already authorized the operator.
        """
        if self._refuse_during_treatment():
            return False
        if key in ("axial", "horizontal", "lateral") and not self.config.marks_valid:
            self.view.warn_uncalibrated()
            return False
        if key == "pressure" and not self.config.scale_calibrated:
            self.view.warn_uncalibrated()
            return False
        if key == "leg_length":
            return self.leg.move_to(self.view.row_value("leg_length"))

        self.view.show_busy()
        self.disable_actuator_controls()
        moved = False
        try:
            if key == "axial":
                inches = self.view.row_value("axial")
                inches = max(AXIAL_MIN_INCHES, min(AXIAL_MAX_INCHES, inches))
                if not self.set_to_distance(inches, self.actuator_a):
                    return False
                self.axial_flexion_position = inches
                self._reflect_setup("axial", inches)
            elif key == "horizontal":
                degrees = self.view.row_value("horizontal")
                degrees = max(HORIZONTAL_MIN_DEGREES, min(HORIZONTAL_MAX_DEGREES, degrees))
                position = horizontal_degrees_to_position(self.config.BMarks, degrees)
                if not self.send_motion_command(f"I13{position}", "horizontal movement"):
                    return False
                self.horizontal_flexion_position = degrees
                self._reflect_setup("horizontal", degrees)
            elif key == "lateral":
                degrees = self.view.row_value("lateral")
                degrees = max(LATERAL_MIN_DEGREES, min(LATERAL_MAX_DEGREES, degrees))
                if not self.set_to_c_distance(degrees):
                    return False
                self.lateral_flexion_position = degrees
                self._reflect_setup("lateral", degrees)
            elif key == "pressure":
                moved = self.apply_setup_pressure()
                return moved
            moved = True
            return True
        except Exception as e:
            self.logger.exception("Error in Setup Go")
            self.view.show_error(f"Error moving actuator: {str(e)}")
        finally:
            self.view.hide_busy()
            if not moved:
                # Nothing is moving, so no DONE will re-enable the controls.
                # Leaving them disabled also blocked logout and exit.
                self.enable_actuator_controls()

    def apply_setup_pressure(self):
        """Setup pressure Go: clamp to [MIN_PRESSURE, PRESSURE_MAX] and send P."""
        if self._refuse_during_treatment():
            return False
        if not self.config.scale_calibrated:
            self.view.warn_uncalibrated()
            return False
        pressure = self.view.row_value("pressure")
        if pressure > PRESSURE_MAX:
            pressure = PRESSURE_MAX
            self.logger.warning(f"Pressure request exceeds max {PRESSURE_MAX}, clamping")
            self.view.show_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
        elif pressure < MIN_PRESSURE:
            pressure = MIN_PRESSURE
            self.logger.warning(f"Pressure request below minimum, setting to {MIN_PRESSURE}")
        pressure = int(pressure)
        if not self.send_motion_command("P{}".format(pressure), "pressure movement"):
            return False
        self.logger.info("Pressure cmd sent P%s", pressure)
        # This is a target, not measured pressure. The live readout is updated
        # only by status_emit feedback.
        self._reflect_setup("pressure", pressure)
        return True

    def setup_stop(self, key):
        """Per-row Stop. The firmware's 'X' stops all actuators regardless of
        suffix; route through the base stop paths so a link-down failure is
        alarmed, not just logged."""
        if key == "leg_length":
            self.stop_leg_movement()
            return
        actuator = {
            "axial": self.actuator_a,
            "horizontal": self.actuator_b,
            "lateral": self.actuator_c,
            "pressure": self.actuator_a,  # pressure rides the axial channel
        }.get(key)
        if actuator is not None:
            self.stop_position_flexion_button(actuator)

    # ----- jog and home -----

    def move_actuator(self, actuator, speed_factor, direction):
        """
        Move an actuator in the specified direction.

        The position math, clamps, and emitted serial commands are FROZEN (unit
        tested). Only the UI feedback is rerouted to the modern Setup screen.
        """
        if self._refuse_during_treatment():
            return False
        if self.state.actuator_command_in_progress:
            self.logger.info("Actuator command already in progress - ignoring input")
            return
        if not self.config.marks_valid:
            # Generated default marks are fabricated geometry; jogging on
            # them moves the mechanism to unintended positions
            self.view.warn_uncalibrated()
            return
        self.logger.debug("Speed factor: %s", speed_factor)
        if actuator == self.actuator_b:  # Horizontal Flexion
            step = 10 if int(speed_factor) > 4 else 5
            new_position = self.horizontal_flexion_position + (step * direction)

            # Check position limits
            if direction >= 0 and new_position > HORIZONTAL_MAX_DEGREES:
                return
            if direction < 0 and new_position < HORIZONTAL_MIN_DEGREES:
                return

            self.view.show_busy()
            self.disable_actuator_controls()

            # Same handling as the lateral branch: invalid BMarks used to raise
            # out of this slot with the controls already disabled.
            try:
                position = horizontal_degrees_to_position(
                    self.config.BMarks, new_position
                )
            except ValueError as e:
                self.logger.error("Invalid horizontal position: %s", e)
                self.enable_actuator_controls()
                self.view.hide_busy()
                return
            command = f"I13{position}"
            if not self.send_motion_command(command, "horizontal movement"):
                return False

            self.horizontal_flexion_position = new_position
            self.logger.info("B position: %s", self.horizontal_flexion_position)

            self._reflect_setup("horizontal", self.horizontal_flexion_position)
            self.view.hide_busy()

        elif actuator == self.actuator_a:  # Axial Flexion
            step = 1 if int(speed_factor) > 4 else 0.5
            new_position = self.axial_flexion_position + (step * direction)

            if direction > 0 and new_position > AXIAL_MAX_INCHES:
                self.view.show_error(
                    f"Axial position limited to {AXIAL_MAX_INCHES} inches (max)"
                )
                return
            if direction < 0 and new_position < AXIAL_MIN_INCHES:
                return

            self.view.show_busy()
            self.disable_actuator_controls()

            # Send command to Arduino
            # Arduino expects: A[2-digit device][float value starting at position 3]
            # Format position with at least 1 decimal place to ensure proper parsing
            command = f"A12{new_position:.1f}"
            if getattr(self.config, "axial_service_calibrated", False) is True:
                try:
                    command = f"I12{axial_position(self.config.AMarks, new_position)}"
                except (ValueError, TypeError, KeyError) as exc:
                    self.view.show_error(f"Axial calibration is invalid: {exc}")
                    self.view.hide_busy()
                    self.enable_actuator_controls()
                    return False
            self.logger.info("Sending axial command: %s", command)
            if not self.send_motion_command(command, "axial movement"):
                return False
            self.axial_flexion_position = new_position
            self.logger.info("A position: %s", self.axial_flexion_position)
            self.logger.info("Axial flexion position: %s in", self.axial_flexion_position)

            # Removed problematic L5 command that was sent without proper parameters
            # This was causing malformed commands after forward axial movement

            self._reflect_setup("axial", self.axial_flexion_position)
            self.view.hide_busy()

        elif actuator == self.actuator_c:  # Lateral Flexion
            step = 5 if int(speed_factor) > 4 else 2.5  # Use 2.5 degree increments
            new_position = self.lateral_flexion_position + (step * direction)

            # Round to nearest 2.5 degree increment
            new_position = round(new_position / 2.5) * 2.5

            # Check position limits using constants
            if direction > 0 and new_position > LATERAL_MAX_DEGREES:
                self.view.show_error(
                    f"Lateral position limited to {LATERAL_MAX_DEGREES}{DEGREES} (max)"
                )
                return
            if direction < 0 and new_position < LATERAL_MIN_DEGREES:
                self.view.show_error(
                    f"Lateral position limited to {LATERAL_MIN_DEGREES}{DEGREES} (min)"
                )
                return

            self.view.show_busy()
            self.disable_actuator_controls()

            # Interpolate between marks; an exact-key-only lookup used to
            # silently no-op the button press when a 2.5-degree mark was
            # missing from the table
            try:
                position, new_position = lateral_degrees_to_position(
                    self.config.CMarks, new_position
                )
            except ValueError as e:
                self.logger.error("Invalid lateral position: %s", e)
                self.enable_actuator_controls()
                self.view.hide_busy()
                return

            self.logger.info(
                " positioned to %s degrees pos %s", new_position, position
            )

            # Send command to Arduino
            command = f"K{position}"
            if not self.send_motion_command(command, "lateral movement"):
                return False

            self.lateral_flexion_position = new_position

            self._reflect_setup("lateral", self.lateral_flexion_position)
            self.view.hide_busy()

        return True

    def reset_flexion_button_clicked(self, actuator):
        self.view.show_busy()
        self.disable_actuator_controls()
        self.logger.debug("%s", actuator)
        if actuator == self.actuator_c:
            # Tolerant lookup (same as the horizontal branch): a hand-edited
            # CMarks without an exact "0.0" key raised KeyError out of this
            # slot, which PyQt5 turns into a process abort.
            try:
                position, _ = lateral_degrees_to_position(self.config.CMarks, 0)
            except ValueError as e:
                self.logger.error("Invalid lateral position: %s", e)
                self.enable_actuator_controls()
                self.view.hide_busy()
                return
            self.logger.info(" positioned to 0 degrees pos %s", position)
            command = f"I14{position}"
            if not self.send_motion_command(command, "lateral reset"):
                return False
            self.lateral_flexion_position = 0
            self._reflect_setup("lateral", 0)
            self.view.hide_busy()

            return

        if actuator == self.actuator_b:
            # Home the horizontal actuator to the calibrated
            # DEFAULT_HORIZONTAL_POSITION via its BMarks position, the same way
            # the lateral branch above homes from CMarks. The old 'A132' inches
            # path ignored BMarks and under-shot the true angle.
            try:
                position = horizontal_degrees_to_position(
                    self.config.BMarks, DEFAULT_HORIZONTAL_POSITION
                )
            except ValueError as e:
                self.logger.error("Invalid horizontal position: %s", e)
                self.enable_actuator_controls()
                self.view.hide_busy()
                return
            command = f"I13{position}"
            if not self.send_motion_command(command, "horizontal reset"):
                return False
            self.horizontal_flexion_position = DEFAULT_HORIZONTAL_POSITION
            self._reflect_setup("horizontal", DEFAULT_HORIZONTAL_POSITION)
            self.view.hide_busy()

            return

        if actuator == self.actuator_a:
            # 'R12' was never a firmware command (parsed as Unknown); the
            # UI then showed 0 in / 0 lb while nothing moved. Home the
            # axial actuator for real, the way the reset sequence does.
            command = "I120"
            if not self.send_motion_command(command, "axial reset"):
                return False
            self.axial_flexion_position = 0
            self._reflect_setup("axial", 0)
            # Automatic reset/protocol workflows own pressure zeroing.
            self.view.hide_busy()

            return

    # ----- stop buttons -----

    def stop_position_flexion_button(self, actuator):
        # Firmware 'X' stops all actuators regardless of suffix. Guarded like
        # stop_actuators: a torn-down transport (arduino is None) must still
        # produce the STOP NOT DELIVERED alarm rather than an AttributeError.
        if self.state.physical_stop_active is True:
            # Nothing is sent after the device's stop button: an X would end
            # the firmware's own release (see KneeSpa.stop_actuators).
            self.logger.warning("Stop not sent: the device's stop button owns the release")
            return
        try:
            arduino = self.arduino
            sent = bool(arduino and arduino.send("X"))
        except Exception:
            self.logger.exception("Actuator stop raised")
            sent = False
        if not sent:
            self.logger.error("Actuator stop could not be sent - link down")
            self.view.show_error(
                "STOP NOT DELIVERED - connection down. "
                "Press the physical emergency stop immediately."
            )

    def stop_leg_movement(self):
        """Stop leg length actuator movement."""
        self.leg.cancel()
        self.view.show_busy()
        if not self.send_motion_command("F0", "leg-length stop"):
            # Local GPIO stop remains mandatory even when serial is down.
            self._release_leg_gpio()
            return False
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        # GPIO.output(EXTRAENABLE, GPIO.LOW)
        self.view.hide_busy()
        return True


# Window attributes that now live on the MotionController. The names stay.
MOTION_ATTRIBUTES = (
    "axial_flexion_position",
    "horizontal_flexion_position",
    "lateral_flexion_position",
    "controls_enable_timer",
    "_motion_watchdog",
)


def _delegate(name: str) -> property:
    def get(owner):
        return getattr(owner.motion, name)

    def set_(owner, value):
        setattr(owner.motion, name, value)

    return property(get, set_, doc=f"Delegates to MotionController.{name}.")


class MotionAttributes:
    """Mixin that keeps the window's motion attribute names working.

    The commanded positions are read by the connection manager's reset, and
    the shutdown stop stops the two timers by name.
    """


for _name in MOTION_ATTRIBUTES:
    setattr(MotionAttributes, _name, _delegate(_name))
del _name
