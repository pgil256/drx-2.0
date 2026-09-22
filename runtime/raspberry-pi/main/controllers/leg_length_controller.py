"""Boot homing and command-based position estimates for the open-loop FIT axis."""

import math
import time
from typing import Callable, Optional

import RPi.GPIO as GPIO
from PyQt5.QtCore import QObject, QTimer

from main.config.constants import EXTRABACKWARD, EXTRAFORWARD, LEG_LENGTH_MAX, LEG_LENGTH_MIN
from helpers.logging import setup_logger


# Production firmware runs F+/F- for 0.5 s and FF/FR for 6 s at the same
# drive speed. Preserve the existing 0.25/3 inch command calibration.
MOVES = {"F+": (0.25, 0.5), "F-": (-0.25, 0.5), "FF": (3.0, 6.0), "FR": (-3.0, 6.0)}


class LegLengthController(QObject):
    """Publish estimates only after timed movement and its completion reply.

    There is no encoder or home switch. A full-travel retract establishes the
    mechanical reference; cancelled or unacknowledged moves require rehoming.
    All state and GPIO changes run on the GUI thread.
    """

    def __init__(self, window: object) -> None:
        super().__init__()
        self.window = window
        self.logger = setup_logger(component="LegLength")
        self.boot_home_pending = True
        self.active = False
        self.position: Optional[float] = None
        self._connections = []
        self._callback: Optional[Callable[[bool], None]] = None
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._poll)
        self._display("Zero required")

    def _display(self, reason: str = "From retracted zero") -> None:
        self.window.shell.setup.set_leg_length_estimate(self.position, reason)

    def invalidate(self) -> None:
        """Forget the reference after untracked service movement."""
        self.position = None
        self.window._service_leg_position_unknown = True
        self._display("Zero required")

    def move(self, command: str) -> bool:
        """Execute a jog within the travel range relative to retracted zero."""
        if (self.position is None
                or getattr(self.window, "_service_leg_position_unknown", False) is True):
            self.window._show_timed_error("Use the leg-length Return control to establish zero.")
            return False
        delta, _ = MOVES[command]
        target = self.position + delta
        if not LEG_LENGTH_MIN <= target <= LEG_LENGTH_MAX:
            self.window._show_timed_error(
                f"Leg length is limited to {LEG_LENGTH_MIN:g}–{LEG_LENGTH_MAX:g} inches."
            )
            return False
        return self._start(command, target, 1)

    def home(self, callback: Optional[Callable[[bool], None]] = None) -> bool:
        """Retract through the entire possible travel before assigning zero."""
        strokes = math.ceil((LEG_LENGTH_MAX - LEG_LENGTH_MIN) / abs(MOVES["FR"][0]))
        return self._start("FR", 0.0, strokes, callback, homing=True)

    def move_to(self, target: float) -> bool:
        """Reach a selected estimate using acknowledged quarter-inch jogs."""
        if (self.position is None
                or getattr(self.window, "_service_leg_position_unknown", False) is True):
            self.window._show_timed_error("Use the leg-length Return control to establish zero.")
            return False
        if not math.isfinite(target) or not LEG_LENGTH_MIN <= target <= LEG_LENGTH_MAX:
            self.window._show_timed_error(
                f"Leg length is limited to {LEG_LENGTH_MIN:g}–{LEG_LENGTH_MAX:g} inches."
            )
            return False
        delta = target - self.position
        steps = abs(delta) / MOVES["F+"][0]
        if not math.isclose(steps, round(steps), abs_tol=1e-8):
            self.window._show_timed_error("Choose a leg-length target in 0.25-inch steps.")
            return False
        if steps == 0:
            return not self.active
        return self._start("F+" if delta > 0 else "F-", target, round(steps))

    def _start(self, command: str, target: float, strokes: int,
               callback: Optional[Callable[[bool], None]] = None,
               homing: bool = False) -> bool:
        w = self.window
        if self.active or any(getattr(w, flag, False) is True for flag in (
            "_closing", "_physical_stop_active", "_no_automatic_recovery", "_device_maintenance_active", "_calibration_active",
            "protocol_running",
        )):
            return False
        if callback is None and any(getattr(w, flag, False) is True for flag in (
            "reset_in_progress", "actuator_command_in_progress",
        )):
            return False
        self.arduino = w.arduino
        if self.arduino is None:
            w._show_timed_error("Leg movement was not sent. Check the Arduino connection.")
            return False
        self.command, self.target, self.remaining = command, target, strokes
        self.homing, self._callback = homing, callback
        self.active = True
        self._connections = [
            (self.arduino.done_emit, self._done),
            (self.arduino.error_emit, self._error),
            (self.arduino.command_rejected, self._rejected),
            (self.arduino.fault_emit, self._fault),
            (self.arduino.connection_lost, self.cancel),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)
        w.disable_actuator_controls()
        w.loading_spinner.show()
        if homing:
            self.invalidate()
        self._display("Retracting to zero…" if homing else "Moving…")
        if not self._queue():
            self._finish(False, "Leg movement was not sent.")
            return False
        self.timer.start()
        return True

    def _queue(self) -> bool:
        self._written_at = None
        self._legacy_done = False
        self._queued_at = time.monotonic()
        try:
            self.handle = self.arduino.send_tracked(self.command)
        except Exception:
            self.logger.exception("Could not queue leg command %s", self.command)
            self.handle = None
        return self.handle is not None

    def _drive(self, forward: Optional[bool]) -> None:
        GPIO.output(EXTRAFORWARD, GPIO.HIGH if forward is True else GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH if forward is False else GPIO.LOW)

    def _done(self) -> None:
        if not self.active or not self.handle.written.is_set():
            return
        if self._written_at is None:
            self._finish(False, "Leg command ended before the local drive could start.")
            return
        if time.monotonic() - self._written_at >= MOVES[self.command][1] - 0.1:
            self._legacy_done = True

    def _error(self, reason: str) -> None:
        if self.active:
            self._finish(False, "Leg movement failed: " + reason)

    def _rejected(self, result: dict) -> None:
        if self.active and self.command.startswith(result["command"]):
            self._error(result["reason"])

    def _fault(self, result: dict) -> None:
        self._error(result["reason"])

    def _poll(self) -> None:
        if not self.active:
            return
        if any(getattr(self.window, flag, False) is True for flag in (
            "_closing", "_physical_stop_active", "_no_automatic_recovery", "_device_maintenance_active",
        )):
            self.cancel()
            return
        now = time.monotonic()
        duration = MOVES[self.command][1]
        if self.handle.completed.is_set() and self.handle.result != "DONE":
            self._error(self.handle.result or "Command interrupted")
            return
        if self.handle.written.is_set() and self._written_at is None:
            if self.handle.completed.is_set():
                self._finish(False, "Leg command ended before the local drive could start.")
                return
            # Never energize the Pi driver while serial delivery is still queued.
            self._written_at = now
            self._drive(MOVES[self.command][0] > 0)
        elapsed = now - self._written_at if self._written_at is not None else 0.0
        if elapsed >= duration:
            self._drive(None)
        acknowledged = (self.handle.completed.is_set() and self.handle.result == "DONE"
                        if self.arduino.protocol_v2 else self._legacy_done)
        if acknowledged and elapsed >= duration:
            self.remaining -= 1
            if self.remaining:
                if not self._queue():
                    self._finish(False, "Leg movement was not sent.")
            else:
                self._finish(True)
        elif now - self._queued_at > duration + 3.0:
            self._finish(False, "Leg movement timed out. Return the leg to zero before jogging.")

    def cancel(self) -> None:
        """Cancel without allowing a late DONE/timer to establish a false zero."""
        if self.active:
            self._finish(False)

    def _finish(self, success: bool, error: str = "") -> None:
        self.active = False
        self.timer.stop()
        self._drive(None)
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections = []
        if success:
            self.position = self.target
            self.window.leg_length = self.position
            self.window._service_leg_position_unknown = False
            if self.homing:
                self.boot_home_pending = False
            self._display()
        else:
            # Invalidate even a queued command: it may have reached the wire
            # just before cancellation. X discards pending motion before stopping.
            self.invalidate()
            if getattr(self.window, "_physical_stop_active", False) is not True:
                try:
                    self.arduino.send("X")
                except Exception:
                    self.logger.exception("Could not stop interrupted leg movement")
        if error:
            self.logger.error(error)
            self.window._show_timed_error(error)
        callback, self._callback = self._callback, None
        if callback is not None:
            callback(success)
        else:
            self.window.loading_spinner.hide()
            self.window.enable_actuator_controls()
