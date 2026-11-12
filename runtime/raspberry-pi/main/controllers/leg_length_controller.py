"""Timed moves for the leg-length (FIT) actuator.

Nothing measures this actuator. The firmware runs it for a fixed time per
command (F+/F- 0.5 s, FF/FR 6 s), and there is no encoder, limit switch or
home switch. So the app keeps no leg-length position, shows none and applies
no software travel limit: staff set leg length by watching the leg. drx-demo
made the same change on 12 November 2026.
"""

import time
from typing import Optional

import RPi.GPIO as GPIO
from PyQt5.QtCore import QObject, QTimer

from config.constants import EXTRABACKWARD, EXTRAFORWARD
from helpers.logging import setup_logger
from helpers.stop_commands import PHYSICAL_STOP_MESSAGES


# Production firmware runs F+/F- for 0.5 s and FF/FR for 6 s at the same
# drive speed: (direction, seconds).
MOVES = {"F+": (1, 0.5), "F-": (-1, 0.5), "FF": (1, 6.0), "FR": (-1, 6.0)}

# The Return control runs FR this many times back to back: 12 s of retract,
# the same full-retract time as before. drx-demo's Return also sends FR twice.
RETURN_STROKES = 2


class LegLengthController(QObject):
    """Run one timed leg move at a time with the Pi drive pins in step.

    The Pi's direction pins are energized only after the command is on the
    wire and are dropped when its time is up, whether or not DONE arrives.
    An interrupted or failed move sends X, except after the device's stop
    button. All state and GPIO changes run on the GUI thread.
    """

    def __init__(self, window: object) -> None:
        super().__init__()
        self.window = window
        self.logger = setup_logger(component="LegLength")
        self.active = False
        self._connections = []
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._poll)

    def move(self, command: str) -> bool:
        """Run one timed jog: F+, F-, FF or FR."""
        return self._start(command, 1)

    def retract(self) -> bool:
        """The Return control: run FR RETURN_STROKES times back to back."""
        return self._start("FR", RETURN_STROKES)

    def _start(self, command: str, strokes: int) -> bool:
        w = self.window
        if self.active or any(getattr(w, flag, False) is True for flag in (
            "_closing", "_physical_stop_active", "_no_automatic_recovery", "_device_maintenance_active", "_calibration_active",
            "protocol_running", "reset_in_progress", "actuator_command_in_progress",
        )):
            return False
        self.arduino = w.arduino
        if self.arduino is None:
            w._show_timed_error("Leg movement was not sent. Check the Arduino connection.")
            return False
        self.command, self.remaining = command, strokes
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
            # The firmware stopped the leg motor itself at the device's stop
            # button and is releasing the load; an X would end that release.
            # This slot can run before the window latches the physical stop.
            self._finish(False, "Leg movement failed: " + reason,
                         send_stop=reason not in PHYSICAL_STOP_MESSAGES)

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
            self._finish(False, "Leg movement timed out.")

    def cancel(self) -> None:
        """Stop following the move; a late DONE or timer tick then does nothing."""
        if self.active:
            self._finish(False)

    def _finish(self, success: bool, error: str = "", send_stop: bool = True) -> None:
        self.active = False
        self.timer.stop()
        self._drive(None)
        for signal, slot in self._connections:
            signal.disconnect(slot)
        self._connections = []
        if (not success and send_stop
                and getattr(self.window, "_physical_stop_active", False) is not True):
            # Even a queued command may have reached the wire just before
            # cancellation. X discards pending motion before stopping.
            try:
                self.arduino.send("X")
            except Exception:
                self.logger.exception("Could not stop interrupted leg movement")
        if error:
            self.logger.error(error)
            self.window._show_timed_error(error)
        self.window.loading_spinner.hide()
        self.window.enable_actuator_controls()
