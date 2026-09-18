"""Supervise an authenticated, operator-guided hardware service session."""

import json
import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Optional

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog

from config.paths import DEVICE_STATE_DIR
from helpers.calibration import distance_factor
from helpers.firmware_protocol import HX711_PROTOCOL_DRIVER
from helpers.hardware_service import HardwareServiceDraft, load_cell_factor
from helpers.logging import setup_logger
from helpers.service_auth import ServiceAccess
from ui.modals.hardware_service_dialog import HardwareServiceDialog
from ui.modals.service_pin_dialog import ServicePinDialog

try:
    from main.config.constants import (
        CALIBRATION_MOVE_TIMEOUT_S, CALIBRATION_POSITION_TOLERANCE,
        CALIBRATION_SETTLE_COUNTS, CALIBRATION_STATUS_MAX_AGE_S, SERVICE_AXES,
    )
except ModuleNotFoundError:
    from config.constants import (
        CALIBRATION_MOVE_TIMEOUT_S, CALIBRATION_POSITION_TOLERANCE,
        CALIBRATION_SETTLE_COUNTS, CALIBRATION_STATUS_MAX_AGE_S, SERVICE_AXES,
    )


class HardwareServiceController:
    """One modal owner of the existing serial link; never starts treatment."""

    def __init__(self, window: object) -> None:
        self.window = window
        self.logger = setup_logger(component="Hardware Service")
        self.access = ServiceAccess()
        self.dialog: Optional[HardwareServiceDialog] = None
        self.pin_dialog: Optional[ServicePinDialog] = None

    def _can_open(self) -> bool:
        w = self.window
        return bool(w.current_user) and not (
            w.protocol_running or w.reset_in_progress
            or (w.actuator_command_in_progress and w.protocol_state != "fault")
            or w.protocol_state not in ("idle", "fault") or getattr(w, "_closing", False)
            or getattr(w, "_physical_stop_active", False)
        )

    def open(self) -> None:
        """Authenticate each visit and recheck ownership after PIN entry."""
        if self.dialog is not None:
            self.dialog.raise_()
            return
        if self.pin_dialog is not None:
            self.pin_dialog.raise_()
            return
        if not self._can_open():
            self.window._show_timed_error("Log in and finish movement, treatment or reset first.")
            return
        try:
            d = ServicePinDialog(
                self.access, self.window.current_user.get("status") == "admin", self.window,
            )
        except (OSError, ValueError):
            self.logger.exception("Cannot read service credential")
            self.window._show_timed_error("Could not read the device service credential.")
            return
        self.pin_dialog = d
        d.finished.connect(self._authenticated)
        d.open()

    def _authenticated(self, result: int) -> None:
        pin_dialog = self.pin_dialog
        self.pin_dialog = None
        if pin_dialog is None:
            return
        pin_dialog.deleteLater()
        if result != QDialog.Accepted or not self._can_open():
            return
        self._start_session()

    def _start_session(self) -> None:
        """Called only after service authentication; acquire session ownership."""
        w = self.window
        try:
            self.draft = HardwareServiceDraft(w.config)
        except (ValueError, TypeError, KeyError):
            self.logger.exception("Cannot load hardware calibration draft")
            w._show_timed_error("Could not load hardware calibration settings.")
            return
        self.user = dict(w.current_user)
        self.diagnostic_only = w.protocol_state == "fault"
        self.arduino = w.arduino
        self.started = time.monotonic()
        self.last_status = self.last_hardware = self.last_poll = 0.0
        self.samples = deque(maxlen=5)
        self.raw_samples = deque(maxlen=5)
        self.hardware = {}
        self.pressure_points = {}
        self.anchors = {axis: {} for axis in SERVICE_AXES}
        self.movement_evidence = {axis: set() for axis in SERVICE_AXES}
        self.leg_evidence = set()
        self.handle = None
        self.stop_handle = None
        self.target = None
        self.move_axis = None
        self.legacy_done = False
        self.aborted = self.prepared = self.stop_armed = False
        self.physical_stop_seen = self.software_stop_written = False
        self.saved = False
        self.moved = False
        self.reference_lbs = None
        self.connections = []
        self.results = {}
        self.bench_results = {}
        self.events = []
        self.report_path = None
        self.session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.dialog = HardwareServiceDialog(self.draft, w)
        d = self.dialog
        d.action_requested.connect(self.action)
        d.stop_requested.connect(lambda: self.abort("Stopped by technician."))
        d.leaving.connect(self.stop_before_close)
        d.finished.connect(self.close)
        d.step_changed.connect(lambda _step: self.tick())
        w._calibration_active = True
        w.disable_actuator_controls()
        if self.arduino is not None:
            for name, slot in (
                ("status_emit", self.on_status), ("done_emit", self.on_done),
                ("sensor_diagnostics", self.on_sensor),
                ("hardware_diagnostics", self.on_hardware),
                ("error_emit", self.on_error), ("warning_emit", self.on_warning),
                ("command_rejected", self.on_rejected), ("fault_emit", self.on_rejected),
                ("connection_lost", self.on_disconnect),
                ("ready_to_go_emit", self.on_reboot),
            ):
                signal = getattr(self.arduino, name)
                signal.connect(slot)
                self.connections.append((signal, slot))
            self.arduino.send("HF1")
            self.arduino.send("T")
        self.timer = QTimer(d)
        self.timer.timeout.connect(self.tick)
        self.timer.start(100)
        self.event("opened", "Technician authenticated; no movement requested.")
        if self.diagnostic_only:
            d.show_message(
                "Diagnostic access after a fault: movement is locked. You may measure the "
                "load cell and save calibration, then close and reset unloaded."
            )
        d.open()

    def owns_session(self) -> bool:
        w = self.window
        return bool(w.current_user) and w.current_user == self.user and not (
            w.protocol_running or w.reset_in_progress or getattr(w, "_closing", False)
        )

    def blocked(self) -> bool:
        return (
            self.aborted or not self.owns_session() or not self.prepared
            or self.window.protocol_state != "idle"
            or getattr(self.window, "_physical_stop_active", False)
            or self.arduino is None or self.window.arduino is not self.arduino
            or not self.arduino.connected
        )

    def stable(self) -> bool:
        now = time.monotonic()
        return (
            len(self.samples) >= 3
            and now - self.last_status <= CALIBRATION_STATUS_MAX_AGE_S
            and self.samples[-1][0] - self.samples[0][0] >= 0.2
            and all(max(s[i] for s in self.samples) - min(s[i] for s in self.samples)
                    <= CALIBRATION_SETTLE_COUNTS for i in (1, 2, 3))
        )

    def hardware_ready(self) -> bool:
        return (
            time.monotonic() - self.last_hardware <= 3.0
            and all(self.hardware.get(key) is True for key in ("a_ok", "b_ok", "c_ok"))
            and self.hardware.get("stop_pressed") is False
            and self.hardware.get("fit_active") is False
        )

    def ready(self) -> bool:
        return (
            not self.blocked() and self.handle is None and self.stable() and self.hardware_ready()
        )

    def measurement_ready(self) -> bool:
        """Read-only load-cell repair remains available after failed initial setup."""
        return (
            self.owns_session() and self.prepared and not self.aborted and self.handle is None
            and self.arduino is not None and self.arduino is self.window.arduino
            and self.arduino.connected
            and self.arduino.firmware_driver == HX711_PROTOCOL_DRIVER
            and len(self.raw_samples) >= 3
            and time.monotonic() - self.raw_samples[-1][0] <= 1.5
        )

    def position(self, axis: str) -> int:
        index = SERVICE_AXES[axis]["status_index"] + 1
        return round(median(sample[index] for sample in self.samples))

    def on_status(self, a: int, b: int, c: int, pressure: float) -> None:
        if self.dialog is None:
            return
        if not all(math.isfinite(v) for v in (a, b, c, pressure)):
            self.abort("Invalid device feedback.")
            return
        now = time.monotonic()
        if now - self.last_status > CALIBRATION_STATUS_MAX_AGE_S:
            self.samples.clear()
        self.last_status = now
        if self.handle is None or self.handle.written.is_set():
            self.samples.append((now, a, b, c, pressure))
        self.dialog.set_live(
            f"Axial {a}  |  Horizontal {b}  |  Lateral {c} counts  |  Force {pressure:.2f} lb"
        )
        self.tick()

    def on_sensor(self, sample: dict) -> None:
        if self.dialog is None:
            return
        if sample.get("valid") and 0 <= sample.get("age_ms", -1) <= 500:
            if abs(sample["raw"]) < 8388607:
                self.raw_samples.append((time.monotonic(), dict(sample)))
            else:
                self.raw_samples.clear()
        else:
            self.raw_samples.clear()
        self.dialog.set_diagnostics(
            f"Load cell: raw {sample['raw']}, signed force {sample['signed_lb']:.2f} lb, "
            f"sample age {sample['age_ms']} ms; scale {sample['factor']:g}."
        )

    def on_hardware(self, result: dict) -> None:
        if self.dialog is None:
            return
        self.hardware = dict(result)
        self.last_hardware = time.monotonic()
        if result.get("stop_pressed"):
            if not self.physical_stop_seen:
                self.event("physical_stop", "Physical stop input observed pressed.")
            self.physical_stop_seen = True
            self.abort("Physical emergency-stop input observed.", physical=True)
        elif self.handle is not None and not all(result[k] for k in ("a_ok", "b_ok", "c_ok")):
            self.abort("Position sensor communication failed during movement.")

    def on_done(self) -> None:
        if self.handle is not None and self.handle.written.is_set():
            if not self.arduino.protocol_v2:
                self.legacy_done = True

    def tick(self) -> None:
        """Poll evidence and supervise motion without blocking the Qt event loop."""
        if self.dialog is None:
            return
        now = time.monotonic()
        connected = (
            self.arduino is not None and self.window.arduino is self.arduino
            and self.arduino.connected
        )
        if connected and now - self.last_poll >= 1.0:
            self.last_poll = now
            self.arduino.send("D")
        if self.handle is not None:
            if self.blocked():
                self.abort("Device state changed during the test.")
                return
            if now - self.last_status > CALIBRATION_STATUS_MAX_AGE_S:
                self.abort("Position feedback stopped during movement.")
                return
            if now - self.last_hardware > 3.0:
                self.abort("Hardware diagnostics stopped during movement.")
                return
            if now - self.move_started > CALIBRATION_MOVE_TIMEOUT_S:
                self.abort("Movement did not complete before the timeout.")
                return
            if self.handle.completed.is_set() and self.handle.result not in ("DONE", "WRITTEN"):
                self.abort(f"Movement failed: {self.handle.reason or self.handle.result}")
                return
            ack = self.legacy_done or (
                self.arduino.protocol_v2 and self.handle.completed.is_set()
                and self.handle.result == "DONE"
            )
            if (self.move_axis == "leg" and not self.leg_gpio_started
                    and self.handle.written.is_set()):
                if ack:
                    self.abort("Leg test missed the local drive window; repeat after reset.")
                    return
                try:
                    self.window._start_service_leg_gpio(self.move_direction > 0)
                except Exception:
                    self.logger.exception("Cannot start the Pi leg drive")
                    self.abort("The local leg drive could not start.")
                    return
                self.leg_gpio_started = True
            settled = self.stable() and self.hardware_ready()
            if ack and settled:
                if self.move_axis == "leg":
                    self.leg_evidence.add(self.move_direction)
                    self.finish_move(
                        "Timed leg command completed; confirm actual movement visually."
                    )
                elif abs(self.position(self.move_axis) - self.target) <= (
                    CALIBRATION_POSITION_TOLERANCE
                ):
                    displacement = self.position(self.move_axis) - self.move_origin
                    if abs(displacement) > CALIBRATION_POSITION_TOLERANCE:
                        self.movement_evidence[self.move_axis].add(1 if displacement > 0 else -1)
                    self.finish_move(
                        "Position reached and settled. Check physical direction and travel."
                    )
        if self.stop_handle is not None and self.stop_handle.written.is_set():
            self.software_stop_written = True
        if not self.owns_session() and not self.aborted:
            self.abort("Service session ownership changed.")
        self.dialog.set_available(self.ready(), self.handle is not None, self.aborted)
        self.dialog.set_measurement_available(self.measurement_ready())

    def finish_move(self, message: str) -> None:
        if self.move_axis == "leg":
            self.window._release_leg_gpio()
        self.event("movement_completed", f"{self.move_axis}: {self.target}")
        self.handle = None
        self.dialog.show_message(message)

    def action(self, name: str, value: object = None) -> None:
        """Dispatch user actions; recheck authorization and evidence at execution."""
        if self.dialog is None or not self.owns_session():
            return
        try:
            if name == "begin":
                self.prepared = True
                self.set_result("preparation", "pass", "Technician confirmed unloaded preparation.")
                self.dialog.show_message("Preparation recorded. Continue to connection checks.")
            elif name == "check_link":
                if self.hardware_ready() and self.stable():
                    self.event("diagnostics_checked", "Fresh status and all three I2C replies.")
                    self.dialog.show_message(
                        "Fresh position feedback and controller replies received. Inspect readings "
                        "and wiring, then record your observation."
                    )
                else:
                    self.dialog.show_message(
                        "Waiting for fresh feedback and hardware diagnostics. Install matching "
                        "service firmware if diagnostics remain unavailable.", True,
                    )
            elif name == "result":
                self.record_result(value)
            elif name == "bench_result":
                self.record_bench_result(value)
            elif name == "export":
                self.export_report()
            elif name == "save":
                self.save()
            elif name == "stop_check":
                self.stop_check(str(value))
            elif name == "pressure_capture":
                if not self.measurement_ready():
                    raise ValueError("Wait for fresh load-cell samples and complete preparation.")
                self.capture_pressure(str(value))
            elif name == "pressure_calculate":
                if self.handle is not None or not self.prepared:
                    return
                self.draft.scale = load_cell_factor(
                    self.pressure_points["zero"], self.pressure_points["loaded"], float(value),
                )
                self.reference_lbs = float(value)
                self.dialog.refresh_draft()
                self.dialog.show_message(
                    "Load-cell factor staged. Remove the reference load before resetting; "
                    "verify against the reference again after reset."
                )
            elif not self.ready():
                self.dialog.show_message(
                    "Fresh, stable readings and completed preparation required.", True,
                )
            elif name == "jog":
                axis = self.dialog.current_axis()
                if value not in (-200, -50, 50, 200):
                    raise ValueError("Choose a supported bounded jog.")
                self.move(axis, self.position(axis) + int(value))
            elif name == "record":
                axis = self.dialog.current_axis()
                self.draft.record(axis, float(value), self.position(axis))
                self.dialog.refresh_draft()
            elif name == "goto":
                axis = self.dialog.current_axis()
                self.move(axis, self.draft.marks[axis][str(value)])
            elif name == "remove":
                axis = self.dialog.current_axis()
                self.draft.marks[axis].pop(str(value))
                self.draft.recorded[axis].discard(str(value))
                self.dialog.refresh_draft()
            elif name == "anchor":
                axis = self.dialog.current_axis()
                self.anchors[axis][str(value)] = self.position(axis)
                points = self.anchors[axis]
                self.dialog.set_anchors(axis, points.get("start"), points.get("end"))
            elif name == "factor":
                axis = self.dialog.current_axis()
                points = self.anchors[axis]
                self.draft.factors[axis] = distance_factor(
                    points["start"], points["end"], float(value),
                )
                self.dialog.refresh_draft()
                self.dialog.show_message(
                    "Distance readout factor staged. Position marks govern movement."
                )
            elif name == "leg":
                self.move_leg(str(value))
        except (ValueError, KeyError, TypeError) as exc:
            self.dialog.show_message(f"Check the measurements and required captures: {exc}", True)
        self.tick()

    def move(self, axis: str, target: int) -> None:
        if not self.ready():
            return
        low, high = SERVICE_AXES[axis]["position_limits"]
        if axis == "axial":
            # The running firmware still uses the saved zero until deliberate reset.
            marks = self.window.config.AMarks
            low = max(low, int(marks.get("0.0", marks.get("0", 0))))
        if not low <= target <= high:
            raise ValueError(f"Move must remain within {low}–{high} counts.")
        origin = self.position(axis)
        self.start_move(f"{SERVICE_AXES[axis]['prefix']}{target}", axis, target, target - origin)

    def move_leg(self, direction: str) -> None:
        if direction not in ("+", "-"):
            raise ValueError("Choose forward or reverse.")
        self.start_move("F" + direction, "leg", None, 1 if direction == "+" else -1)

    def start_move(self, command: str, axis: str, target: Optional[int], delta: int) -> None:
        if not self.ready():
            return
        handle = self.arduino.send_tracked(command)
        if handle is None:
            self.dialog.show_message("Movement could not be queued. Check the connection.", True)
            return
        self.handle = handle
        self.moved = True
        if axis == "leg":
            self.window._service_leg_position_unknown = True
        self.move_started = time.monotonic()
        self.move_axis, self.target = axis, target
        self.move_origin = self.position(axis) if axis != "leg" else None
        self.move_direction = 1 if delta > 0 else -1
        self.leg_gpio_started = False
        self.legacy_done = False
        self.samples.clear()
        self.event("movement_requested", command)
        self.dialog.show_message("Moving. STOP remains available.")
        self.dialog.set_available(False, True)

    def capture_pressure(self, kind: str) -> None:
        if self.arduino.firmware_driver != HX711_PROTOCOL_DRIVER:
            raise ValueError("Compatible load-cell firmware is required.")
        if kind not in ("zero", "loaded"):
            raise ValueError("Choose unloaded or reference-load capture.")
        now = time.monotonic()
        if (len(self.raw_samples) < 3 or now - self.raw_samples[0][0] > 6.0
                or now - self.raw_samples[-1][0] > 1.5
                or self.raw_samples[-1][0] - self.raw_samples[0][0] < 1.0):
            raise ValueError("Wait for several fresh load-cell samples.")
        raw = [entry[1]["raw"] for entry in self.raw_samples]
        noise_limit = max(1000, abs(self.draft.original_scale) * 0.5)
        if max(raw) - min(raw) > noise_limit:
            raise ValueError("Load-cell readings are not stable; wait for the load to settle.")
        if kind == "zero":
            self.pressure_points.clear()
            self.reference_lbs = None
            self.dialog.set_pressure_capture("loaded", "not captured")
        elif "zero" not in self.pressure_points:
            raise ValueError("Capture the unloaded reading first.")
        self.pressure_points[kind] = round(median(raw))
        self.raw_samples.clear()  # next point must use entirely new samples
        self.dialog.set_pressure_capture(kind, self.pressure_points[kind])
        self.event("load_cell_capture", {"kind": kind, "raw": self.pressure_points[kind]})
        self.dialog.show_message("Raw reference captured. It does not tare or move the device.")

    def stop_check(self, kind: str) -> None:
        if self.handle is not None or not self.prepared:
            return
        if kind == "software":
            if getattr(self.window, "_physical_stop_active", False) or self.hardware.get(
                "stop_pressed", False,
            ):
                self.dialog.show_message(
                    "Release the physical stop before this stationary check.", True,
                )
                return
            if self.aborted and self.stop_handle is None:
                self.dialog.show_message(
                    "The physical stop already ended this session. Reset and perform the "
                    "software check first in a new session; this check remains incomplete.", True,
                )
                return
            self.abort("Stationary software-stop check requested.")
        elif kind == "physical":
            self.stop_armed = True
            self.dialog.show_message(
                "Press the physical emergency stop. The wizard will record its input; "
                "confirm actual stop/release behavior separately. Reset after closing."
            )

    def record_result(self, value: dict) -> None:
        step = self.dialog.current_step()
        status = value["status"]
        if status not in ("pass", "fail", "skip"):
            raise ValueError("Choose pass, fail or skip.")
        if status == "pass":
            if not self.prepared:
                raise ValueError("Complete preparation before confirming hardware checks.")
            if step == "communication" and not (self.stable() and self.hardware_ready()):
                raise ValueError("Fresh position and hardware replies are required.")
            if step in SERVICE_AXES and self.movement_evidence[step] != {-1, 1}:
                raise ValueError("Complete a bounded move in both directions before confirming.")
            if step == "leg" and self.leg_evidence != {-1, 1}:
                raise ValueError("Test both leg-length directions before confirming.")
            if step == "loadcell" and len(self.pressure_points) != 2:
                raise ValueError("Capture unloaded and known-load readings first.")
            if step == "stops" and not (
                getattr(self, "physical_stop_seen", False)
                and getattr(self, "software_stop_written", False)
            ):
                raise ValueError("Observe the physical input and transmit the software stop first.")
        self.set_result(step, status, str(value.get("notes", "")))

    def record_bench_result(self, value: dict) -> None:
        """Record named physical checks as observations, never inferred software results."""
        check = value["check"]
        status = value["status"]
        notes = str(value.get("notes", "")).strip()
        if check not in self.bench_checks() or status not in ("pass", "fail", "skip"):
            raise ValueError("Choose a listed bench check and result.")
        if status != "skip" and not notes:
            raise ValueError("Record the measured result or observed behavior in the notes.")
        self.bench_results[check] = {"status": status, "notes": notes, "at": self.timestamp()}
        self.dialog.set_bench_result(check, status, notes)
        self.event("bench_observation", {"check": check, **self.bench_results[check]})

    @staticmethod
    def bench_checks() -> tuple:
        return ("pressure_control", "pressure_accuracy", "dynamic_stops", "watchdog",
                "power_recovery", "limit_switches", "mechanical")

    def set_result(self, step: str, status: str, detail: str) -> None:
        self.results[step] = {"status": status, "detail": detail, "at": self.timestamp()}
        self.dialog.set_result(step, status, detail)
        self.event("result", {"step": step, **self.results[step]})

    def save(self) -> None:
        """Persist reviewed drafts; deliberate reset applies the firmware settings."""
        if self.handle is not None or self.dialog.current_step() != "review":
            return
        if not self.draft.dirty:
            self.dialog.show_message("No calibration changes to save.")
            return
        try:
            changes = self.draft.changes()
            backup = self.draft.save(self.window.config)
        except (ValueError, OSError) as exc:
            self.logger.exception("Service calibration save failed")
            self.dialog.show_message(f"Calibration was not saved: {exc}", True)
            return
        self.saved = True
        self.window.initial_setup_complete = False
        self.window._no_automatic_recovery = True
        self.window.set_protocol_state("fault")
        self.aborted = True  # old firmware settings and new draft must never mix during motion
        self.event("configuration_saved", {"changes": changes, "backup": backup})
        self.dialog.refresh_draft()
        self.dialog.show_message(
            "Calibration saved with a backup. Remove reference loads, close this wizard, "
            "and reset Arduino from Setup before movement. Then verify the new calibration."
        )
        self.export_report()

    def abort(self, reason: str, physical: bool = False) -> None:
        if self.dialog is None:
            return
        firmware_stopped = physical or getattr(self.window, "_physical_stop_active", False)
        if not self.aborted:
            self.aborted = True
            if firmware_stopped and self.arduino is not None:
                self.arduino.cancel_pending_commands()
            if not firmware_stopped and self.arduino is not None:
                self.stop_handle = self.arduino.send_tracked("X")
            release = getattr(self.window, "_release_leg_gpio", None)
            if release is not None:
                try:
                    release()
                except Exception:
                    self.logger.exception("Unable to release local leg GPIO during service stop")
            self.handle = None
            self.samples.clear()
            self.window.initial_setup_complete = False
            self.window._no_automatic_recovery = True
            self.window.set_protocol_state("fault")
            self.event("stopped", reason)
            self.logger.warning("Hardware service stopped: %s", reason)
        advice = "Close the wizard and reset before further movement."
        if not firmware_stopped and self.stop_handle is None:
            advice = "Software STOP unavailable. Use the physical emergency stop."
        self.dialog.show_message(f"{reason} {advice}", True)
        self.dialog.set_available(False, False, True)

    def on_error(self, reason: str) -> None:
        if "Stop button" in reason:
            self.physical_stop_seen = True
            self.abort(reason, physical=True)
        elif self.handle is not None:
            self.abort(reason)

    def on_warning(self, reason: str) -> None:
        if self.handle is not None and any(word in reason.lower() for word in (
            "stall", "heartbeat", "sensor", "i2c", "pressure",
        )):
            self.abort(reason)

    def on_rejected(self, result: dict) -> None:
        self.abort("Controller rejected operation: " + str(result.get("reason", "unknown")))

    def on_disconnect(self) -> None:
        self.abort("Arduino connection lost.")

    def on_reboot(self) -> None:
        self.abort("Arduino restarted; all captures require a new service session.")

    @staticmethod
    def timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    def event(self, kind: str, detail: object) -> None:
        self.events.append({"at": self.timestamp(), "kind": kind, "detail": detail})

    def export_report(self) -> None:
        """Write a local report; missing tests never become passes."""
        steps = ("preparation", "communication", "axial", "horizontal", "lateral", "leg",
                 "loadcell", "stops")
        report = {
            "schema": 1, "session": self.session_id, "updated_at": self.timestamp(),
            "technician": self.user.get("username", ""),
            "firmware": getattr(self.arduino, "firmware_version", None),
            "config_path": str(self.window.config.configFile),
            "configuration_saved": self.saved,
            "movement_performed": self.moved, "session_stopped": self.aborted,
            "reset_required": bool(self.moved or self.saved or self.aborted),
            "results": {step: self.results.get(step, {"status": "not_tested"}) for step in steps},
            "bench_observations": {
                check: self.bench_results.get(check, {"status": "not_tested"})
                for check in self.bench_checks()
            },
            "hardware_diagnostics": self.hardware,
            "captures": {"pressure_raw": self.pressure_points, "distance": self.anchors},
            "reference_force_lb": getattr(self, "reference_lbs", None),
            "proposed_changes": self.draft.changes(),
            "recorded_marks": {
                axis: {key: self.draft.marks[axis][key] for key in keys}
                for axis, keys in self.draft.recorded.items()
            },
            "events": self.events,
            "scope": "Bench evidence and operator observations; not a device certification. "
                     "Loaded stop/release, pressure control/pulse, watchdog, power-loss and limit "
                     "switch behavior require the documented physical bench procedure.",
        }
        directory = Path(DEVICE_STATE_DIR) / "service-reports"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"hardware-{self.session_id}.json"
            temporary = path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(report, output, indent=2, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
            self.report_path = path
            if not self.saved:
                self.dialog.show_message(f"Service report saved: {path}")
        except (OSError, ValueError):
            self.logger.exception("Could not save hardware service report")
            self.dialog.show_message(
                "Could not save the service report. Check device storage.", True,
            )

    def stop_before_close(self) -> None:
        if self.handle is not None:
            self.abort("Wizard closed during movement.")

    def close(self, result: int = 0) -> None:
        if self.dialog is None:
            return
        self.stop_before_close()
        self.timer.stop()
        self.window._release_leg_gpio()
        if self.moved:
            self.window.initial_setup_complete = False
            self.window._no_automatic_recovery = True
            self.window.set_protocol_state("fault")
            self.event("reset_required", "Service movement invalidated normal position estimates.")
        self.export_report()
        for signal, slot in self.connections:
            signal.disconnect(slot)
        if self.arduino is not None:
            self.arduino.send("HF0")
        self.window._calibration_active = False
        self.window.actuator_command_in_progress = False
        self.window.enable_actuator_controls()
        self.dialog.deleteLater()
        self.dialog = None
        needs_reset = self.moved or self.saved or self.aborted
        if needs_reset and not getattr(self.window, "_closing", False):
            message = "Remove reference loads and reset Arduino from Setup before normal movement."
            if getattr(self.window, "_service_leg_position_unknown", False):
                message += " Then use the leg-length Reset control to restore its position."
            self.window._show_timed_error(message)

    def shutdown(self) -> None:
        if self.pin_dialog is not None:
            self.pin_dialog.reject()
        if self.dialog is not None:
            self.stop_before_close()
            self.dialog.done(QDialog.Rejected)
