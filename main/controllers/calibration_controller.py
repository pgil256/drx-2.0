"""Nonblocking, single-connection guided calibration for B and C actuators."""

import time
from collections import deque
from statistics import median
from typing import Optional

from PyQt5.QtCore import QTimer

from helpers.calibration import CalibrationDraft, distance_factor
from helpers.logging import setup_logger
from ui.modals.calibration_dialog import CalibrationDialog

try:
    from main.config.constants import (
        CALIBRATION_AXES, CALIBRATION_MOVE_TIMEOUT_S, CALIBRATION_POSITION_TOLERANCE,
        CALIBRATION_SETTLE_COUNTS, CALIBRATION_STATUS_MAX_AGE_S,
    )
except ModuleNotFoundError:  # Direct script entry point
    from config.constants import (
        CALIBRATION_AXES, CALIBRATION_MOVE_TIMEOUT_S, CALIBRATION_POSITION_TOLERANCE,
        CALIBRATION_SETTLE_COUNTS, CALIBRATION_STATUS_MAX_AGE_S,
    )


class CalibrationController:
    """Own a modal service session and stop incomplete moves on failure/exit."""

    def __init__(self, window: object) -> None:
        self.window = window
        self.logger = setup_logger(component="Calibration")
        self.dialog: Optional[CalibrationDialog] = None

    def open(self) -> None:
        """Open the profile action without creating a second serial connection."""
        w = self.window
        if self.dialog is not None:
            self.dialog.raise_()
            return
        if not w.current_user:
            w._show_timed_error("Log in to calibrate the actuators.")
            return
        if w.protocol_state != "idle" or w.protocol_running or w.reset_in_progress:
            w._show_timed_error("Finish treatment or reset before opening calibration.")
            return
        if w.actuator_command_in_progress:
            w._show_timed_error("Wait for the current actuator movement to finish.")
            return
        try:
            self.draft = CalibrationDraft(w.config)
        except (ValueError, TypeError) as exc:
            self.logger.exception("Cannot load calibration draft")
            w._show_timed_error(f"Could not load calibration: {exc}")
            return
        self.arduino = w.arduino
        self.samples = deque(maxlen=4)
        self.last_status = 0.0
        self.started = time.monotonic()
        self.handle = None
        self.target = None
        self.done = False
        self.aborted = False
        self.anchors = {axis: {} for axis in CALIBRATION_AXES}
        self.connections = []
        self.dialog = CalibrationDialog(self.draft, w)
        d = self.dialog
        d.jog_requested.connect(self.jog)
        d.capture_requested.connect(self.capture)
        d.move_requested.connect(self.move_selected)
        d.anchor_requested.connect(self.capture_anchor)
        d.factor_requested.connect(self.calculate_factor)
        d.save_requested.connect(self.save)
        d.stop_requested.connect(lambda: self.abort("Stopped by operator."))
        d.leaving.connect(self.stop_before_close)
        d.axis_changed.connect(self.refresh_anchors)
        d.finished.connect(self.close)
        w._calibration_active = True
        w.disable_actuator_controls()
        if self.arduino is not None:
            for signal, slot in (
                (self.arduino.status_emit, self.on_status),
                (self.arduino.done_emit, self.on_done),
                (self.arduino.error_emit, self.on_error),
                (self.arduino.warning_emit, self.on_warning),
                (self.arduino.connection_lost, self.on_disconnect),
                (self.arduino.ready_to_go_emit, self.on_reboot),
            ):
                signal.connect(slot)
                self.connections.append((signal, slot))
            if not self.arduino.send("HF1"):
                d.show_message("Arduino disconnected. Reopen calibration after connecting.", True)
        else:
            d.show_message("Arduino disconnected. Reopen calibration after connecting.", True)
        self.timer = QTimer(d)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        d.open()

    def blocked(self) -> bool:
        """Check live session ownership and device lifecycle before every action."""
        w = self.window
        return (
            self.aborted or not w.current_user or w.protocol_running
            or w.protocol_state != "idle" or w.reset_in_progress
            or getattr(w, "_physical_stop_active", False)
            or getattr(w, "_closing", False)
            or self.arduino is None or w.arduino is not self.arduino
            or not self.arduino.connected
        )

    def stable(self) -> bool:
        """Require several fresh readings; a cached value is never a capture."""
        if (
            len(self.samples) < 3
            or time.monotonic() - self.last_status > CALIBRATION_STATUS_MAX_AGE_S
        ):
            return False
        if self.samples[-1][0] - self.samples[0][0] < 0.2:
            return False
        return all(
            max(s[i] for s in self.samples) - min(s[i] for s in self.samples)
            <= CALIBRATION_SETTLE_COUNTS for i in (1, 2)
        )

    def ready(self) -> bool:
        """Whether a settled position can be captured or used as a jog origin."""
        return not self.blocked() and self.handle is None and self.stable()

    def position(self) -> int:
        """Average the settled sample window for the selected axis."""
        index = 1 if self.dialog.current_axis() == "horizontal" else 2
        return round(median(s[index] for s in self.samples))

    def on_status(self, a: int, b: int, c: int, pressure: float) -> None:
        """Update measured feedback without using the existing angle conversion."""
        if self.dialog is None:
            return
        now = time.monotonic()
        self.last_status = now
        if self.handle is None or self.handle.written.is_set():
            self.samples.append((now, b, c))
        self.dialog.live.setText(f"Horizontal: {b} counts    Lateral: {c} counts")
        self.tick()

    def on_done(self) -> None:
        """Legacy DONE is accepted only after write and still requires arrival."""
        if self.handle is not None and self.handle.written.is_set():
            if not self.arduino.protocol_v2:
                self.done = True

    def tick(self) -> None:
        """Supervise queued moves without sleeping or blocking the Qt event loop."""
        if self.dialog is None:
            return
        now = time.monotonic()
        if self.handle is not None:
            if self.blocked():
                self.abort("Calibration interrupted by a device state change.")
                return
            if now - self.last_status > CALIBRATION_STATUS_MAX_AGE_S:
                self.abort("Position feedback stopped during movement.")
                return
            if now - self.move_started > CALIBRATION_MOVE_TIMEOUT_S:
                self.abort("The actuator did not finish its move in time.")
                return
            if self.handle.completed.is_set() and self.handle.result not in ("DONE", "WRITTEN"):
                self.abort(f"Movement failed: {self.handle.reason or self.handle.result}")
                return
            acknowledged = self.done or (
                self.arduino.protocol_v2 and self.handle.completed.is_set()
                and self.handle.result == "DONE"
            )
            if acknowledged and self.stable():
                if abs(self.position() - self.target) <= CALIBRATION_POSITION_TOLERANCE:
                    self.handle = None
                    self.dialog.show_message("Position settled. Measure the angle, then record it.")
        self.dialog.set_available(self.ready(), self.handle is not None)
        if (
            not self.aborted
            and now - max(self.started, self.last_status) > CALIBRATION_STATUS_MAX_AGE_S
        ):
            self.dialog.live.setText("No fresh position readings — movement and recording disabled")

    def jog(self, delta: int) -> None:
        """Move a fixed raw-count step within the firmware envelope."""
        if not self.ready():
            return
        self.move(self.position() + delta)

    def move(self, target: int) -> None:
        """Send one tracked movement; all further movement waits for arrival."""
        if not self.ready():
            return
        spec = CALIBRATION_AXES[self.dialog.current_axis()]
        low, high = spec["position_limits"]
        if not low <= target <= high:
            self.dialog.show_message(f"Move exceeds the {low}–{high} count travel limits.", True)
            return
        self.handle = self.arduino.send_tracked(f"{spec['prefix']}{target}")
        if self.handle is None:
            self.dialog.show_message("Movement could not be sent. Check the connection.", True)
            return
        self.target = target
        self.move_started = time.monotonic()
        self.done = False
        self.samples.clear()
        self.logger.info("Calibration %s move to %s counts", self.dialog.current_axis(), target)
        self.dialog.show_message("Moving… STOP remains available.")
        self.dialog.set_available(False, True)

    def move_selected(self) -> None:
        """Move only when the operator explicitly taps Go to selected mark."""
        key = self.dialog.selected_mark()
        if key is not None:
            self.move(self.draft.marks[self.dialog.current_axis()][key])

    def capture(self) -> None:
        """Record measured angle and fresh, settled raw feedback in the draft."""
        if not self.ready():
            return
        try:
            self.draft.record(
                self.dialog.current_axis(), self.dialog.angle.value(), self.position()
            )
        except ValueError as exc:
            self.dialog.show_message(str(exc), True)
            return
        self.dialog.refresh_table()
        self.dialog.show_message("Angle recorded in the draft. Measure the next angle or save.")

    def capture_anchor(self, name: str) -> None:
        """Store a start/end distance measurement, separately for each actuator."""
        if self.ready():
            self.anchors[self.dialog.current_axis()][name] = self.position()
            self.refresh_anchors()

    def refresh_anchors(self) -> None:
        """Reflect the selected actuator's distance reference points."""
        anchors = self.anchors[self.dialog.current_axis()]
        self.dialog.anchors_label.setText(
            f"Start: {anchors.get('start', '—')}    End: {anchors.get('end', '—')} counts"
        )

    def calculate_factor(self) -> None:
        """Preview the factor; the operator chooses Use this factor to stage it."""
        anchors = self.anchors[self.dialog.current_axis()]
        try:
            factor = distance_factor(anchors["start"], anchors["end"], self.dialog.distance.value())
        except KeyError:
            self.dialog.show_message("Record both start and end positions first.", True)
            return
        except ValueError as exc:
            self.dialog.show_message(str(exc), True)
            return
        self.dialog.factor.setValue(factor)
        self.dialog.show_message("Calculated. Select Use this factor to add it to the draft.")

    def save(self) -> None:
        """Commit only reviewed draft changes and report any persistence failure."""
        if (
            self.handle is not None or not self.window.current_user
            or self.window.reset_in_progress or self.window.protocol_running
        ):
            return
        if not self.draft.dirty:
            self.dialog.show_message("No calibration changes to save.")
            return
        try:
            backup = self.draft.save(self.window.config)
        except (OSError, ValueError) as exc:
            self.logger.exception("Calibration save failed")
            self.dialog.show_message(f"Calibration was not saved: {exc}", True)
            return
        self.logger.info("Calibration saved; previous configuration backup: %s", backup)
        self.dialog.refresh_table()
        message = "Calibration saved."
        if backup is not None:
            message += " The previous configuration was backed up."
        self.dialog.show_message(message)

    def abort(self, reason: str) -> None:
        """Send the firmware's priority stop and require reset before further motion."""
        if self.aborted:
            return
        self.aborted = True
        # A physical stop already owns the firmware's autonomous release.
        # Sending another X would interrupt and restart that release.
        firmware_stopped = getattr(self.window, "_physical_stop_active", False) is True
        sent = firmware_stopped or bool(self.arduino and self.arduino.send("X"))
        self.handle = None
        self.samples.clear()
        self.window.initial_setup_complete = False
        self.window.set_protocol_state("fault")
        self.logger.error("Calibration stopped: %s (stop queued=%s)", reason, sent)
        advice = "Close calibration and reset Arduino in Setup before moving again."
        if not sent:
            advice = "STOP could not be sent. Use the physical emergency stop."
        self.dialog.show_message(f"{reason} {advice}", True)
        self.dialog.set_available(False, False)

    def on_error(self, reason: str) -> None:
        """Never treat a rejected or failed calibration move as success."""
        if self.handle is not None:
            self.abort(reason)

    def on_warning(self, reason: str) -> None:
        """A stalled calibration move must not keep driving against an endpoint."""
        if self.handle is not None and "stall" in reason.lower():
            self.abort(reason)

    def on_disconnect(self) -> None:
        """Invalidate the session across reconnection, including cached samples."""
        self.abort("Arduino connection lost.")

    def on_reboot(self) -> None:
        """Firmware reboot invalidates every outstanding capture and movement."""
        self.abort("Arduino restarted during calibration.")

    def stop_before_close(self) -> None:
        """Closing a moving session always requests a priority stop first."""
        if self.handle is not None:
            self.abort("Calibration closed during movement.")

    def close(self, result: int = 0) -> None:
        """Release session signals and restore the application's control gating."""
        if self.dialog is None:
            return
        self.timer.stop()
        for signal, slot in self.connections:
            signal.disconnect(slot)
        if self.arduino is not None:
            self.arduino.send("HF0")
        self.window._calibration_active = False
        self.window.actuator_command_in_progress = False
        self.window.enable_actuator_controls()
        self.dialog.deleteLater()
        self.dialog = None

    def shutdown(self) -> None:
        """Stop and detach before application teardown closes the serial port."""
        if self.dialog is not None:
            self.stop_before_close()
            self.dialog.done(CalibrationDialog.Rejected)
