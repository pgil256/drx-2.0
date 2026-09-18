"""Service ownership, measured evidence and stop/failure behavior without hardware."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QMainWindow, QMessageBox

from config.config import Configuration
from controllers import hardware_service_controller as module
from helpers.arduino import CommandHandle
from helpers.firmware_protocol import HX711_PROTOCOL_DRIVER
from helpers.service_auth import ServiceAccess

pytestmark = pytest.mark.unit


class ServiceArduino(QObject):
    status_emit = pyqtSignal(int, int, int, float)
    done_emit = pyqtSignal()
    sensor_diagnostics = pyqtSignal(dict)
    hardware_diagnostics = pyqtSignal(dict)
    error_emit = pyqtSignal(str)
    warning_emit = pyqtSignal(str)
    command_rejected = pyqtSignal(dict)
    fault_emit = pyqtSignal(dict)
    connection_lost = pyqtSignal()
    ready_to_go_emit = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.commands = []
        self.connected = True
        self.protocol_v2 = False
        self.firmware_driver = HX711_PROTOCOL_DRIVER
        self.firmware_version = "service-test"
        self.allow_send = True
        self.write_now = True
        self.cancel_pending_commands = MagicMock()

    def send(self, command):
        self.commands.append(command)
        return self.allow_send

    def send_tracked(self, command):
        if not self.allow_send:
            return None
        self.commands.append(command)
        handle = CommandHandle(command)
        if self.write_now:
            handle.written.set()
        return handle


@pytest.fixture
def service(qtbot, monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(module, "DEVICE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(module, "ServiceAccess", lambda: ServiceAccess(str(tmp_path / "pin.json")))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    config = Configuration(str(tmp_path / "device.cfg"))
    config._set_default_a_marks()
    config._set_default_b_marks()
    config._set_default_c_marks()
    config.calibration = -28369
    config._write_default_config()
    config.get_config()
    w = QMainWindow()
    qtbot.addWidget(w)
    w.current_user = {"username": "Service tech", "status": "admin"}
    w.config = config
    w.arduino = ServiceArduino()
    w.protocol_state = "idle"
    w.protocol_running = w.reset_in_progress = w.actuator_command_in_progress = False
    w._closing = w._physical_stop_active = w._no_automatic_recovery = False
    w.initial_setup_complete = True
    w.disable_actuator_controls = MagicMock()
    w.enable_actuator_controls = MagicMock()
    w._show_timed_error = MagicMock()
    w._release_leg_gpio = MagicMock()
    w._start_service_leg_gpio = MagicMock()
    w.set_protocol_state = lambda value: setattr(w, "protocol_state", value)
    controller = module.HardwareServiceController(w)
    controller._start_session()
    controller.timer.stop()

    def feed(a=500, b=1900, c=1688, count=4, raw=100000, stop=False):
        for _ in range(count):
            clock[0] += 0.4
            w.arduino.hardware_diagnostics.emit({
                "a_ok": True, "b_ok": True, "c_ok": True,
                "stop_pressed": stop, "fit_active": False,
            })
            w.arduino.status_emit.emit(a, b, c, 0.0)
            w.arduino.sensor_diagnostics.emit({
                "raw": raw, "offset": 100000, "factor": -28369.0,
                "signed_lb": 0.0, "age_ms": 10, "max_gap_ms": 100,
                "read_us": 20, "ready": True, "valid": True,
            })

    yield controller, w, clock, feed
    controller.shutdown()


def prepare(controller, feed):
    controller.action("begin")
    feed()


def select(controller, step):
    for row in range(controller.dialog.steps.count()):
        from PyQt5.QtCore import Qt
        if controller.dialog.steps.item(row).data(Qt.UserRole) == step:
            controller.dialog.steps.setCurrentRow(row)
            return
    raise AssertionError(step)


def test_preparation_and_fresh_hardware_required(service):
    c, w, _, feed = service
    feed()
    assert not c.ready()
    c.action("begin")
    assert c.ready()
    c.hardware["b_ok"] = False
    c.action("jog", 50)
    assert not any(command.startswith("I") for command in w.arduino.commands)
    assert not c.ready()
    assert "V" not in w.arduino.commands
    assert "L4" not in w.arduino.commands


@pytest.mark.parametrize("axis,origin,target,command", [
    ("axial", 500, 550, "I12550"), ("horizontal", 1900, 1950, "I131950"),
    ("lateral", 1688, 1738, "I141738"),
])
def test_moves_require_ack_and_measured_arrival(service, axis, origin, target, command):
    c, w, _, feed = service
    prepare(c, feed)
    select(c, axis)
    c.action("jog", 50)
    assert w.arduino.commands[-1] == command
    positions = {"axial": "a", "horizontal": "b", "lateral": "c"}
    feed(**{positions[axis]: target})
    assert c.handle is not None
    w.arduino.done_emit.emit()
    c.tick()
    assert c.handle is None
    assert c.movement_evidence[axis] == {1}


def test_v2_ack_correlation_and_noop_do_not_fabricate_direction(service):
    c, w, _, feed = service
    prepare(c, feed)
    w.arduino.protocol_v2 = True
    c.move("axial", 500)
    w.arduino.done_emit.emit()
    feed()
    assert c.handle is not None
    c.handle.result = "DONE"
    c.handle.completed.set()
    c.tick()
    assert c.handle is None
    assert not c.movement_evidence["axial"]


@pytest.mark.parametrize("failure", ["stale", "timeout", "disconnect", "reboot", "rejection", "close"])
def test_failures_stop_motion_and_require_deliberate_reset(service, failure):
    c, w, clock, feed = service
    prepare(c, feed)
    c.move("axial", 700)
    if failure == "stale":
        clock[0] += 3
        c.tick()
    elif failure == "timeout":
        clock[0] += 16
        c.last_status = c.last_hardware = clock[0]
        c.tick()
    elif failure == "disconnect":
        w.arduino.connected = False
        w.arduino.connection_lost.emit()
    elif failure == "reboot":
        w.arduino.ready_to_go_emit.emit()
    elif failure == "rejection":
        w.arduino.command_rejected.emit({"reason": "MOTION_ACTIVE"})
    else:
        c.dialog.reject()
    assert "X" in w.arduino.commands
    assert c.aborted
    assert not w.initial_setup_complete
    assert w.protocol_state == "fault"
    assert w._no_automatic_recovery
    w._release_leg_gpio.assert_called()


def test_physical_stop_cancels_queued_motion_without_restarting_release(service):
    c, w, _, feed = service
    prepare(c, feed)
    w.arduino.write_now = False
    c.move("axial", 700)
    feed(count=1, stop=True)
    assert c.aborted
    w.arduino.cancel_pending_commands.assert_called_once()
    assert "X" not in w.arduino.commands
    c.action("stop_check", "software")
    assert "X" not in w.arduino.commands


def test_leg_gpio_starts_only_after_serial_write_and_always_releases(service):
    c, w, _, feed = service
    prepare(c, feed)
    w.arduino.write_now = False
    c.move_leg("+")
    c.tick()
    w._start_service_leg_gpio.assert_not_called()
    c.handle.written.set()
    c.tick()
    w._start_service_leg_gpio.assert_called_once_with(True)
    w.arduino.done_emit.emit()
    feed()
    assert c.handle is None
    assert c.leg_evidence == {1}
    w._release_leg_gpio.assert_called()


def test_raw_reference_requires_fresh_independent_samples(service):
    c, w, _, feed = service
    prepare(c, feed)
    c.capture_pressure("zero")
    assert c.pressure_points["zero"] == 100000
    with pytest.raises(ValueError, match="fresh"):
        c.capture_pressure("loaded")
    feed(raw=-183690)
    c.capture_pressure("loaded")
    c.action("pressure_calculate", 10)
    assert c.draft.scale == -28369
    assert not any(cmd.startswith(("L0", "L1", "P")) for cmd in w.arduino.commands)
    feed(raw=-467380)
    c.capture_pressure("zero")
    assert "loaded" not in c.pressure_points


def test_save_after_stop_is_atomic_and_requires_reset_not_live_apply(service):
    c, w, _, feed = service
    prepare(c, feed)
    original = Path(w.config.configFile).read_bytes()
    c.draft.factors["horizontal"] = 3720
    c.abort("Stationary stop check")
    select(c, "review")
    c.save()
    assert w.config.b_factor == 3720
    assert list(Path(w.config.configFile).parent.glob("*.bak"))
    assert Path(w.config.configFile).read_bytes() != original
    assert w._no_automatic_recovery
    assert not w.initial_setup_complete
    assert not any(cmd.startswith(("L0", "L1", "L5")) for cmd in w.arduino.commands)
    report = json.loads(c.report_path.read_text(encoding="utf-8"))
    assert report["configuration_saved"]
    assert report["results"]["axial"]["status"] == "not_tested"
    assert report["bench_observations"]["watchdog"]["status"] == "not_tested"


def test_failed_save_retains_draft_and_runtime_config(service, monkeypatch):
    c, w, _, feed = service
    prepare(c, feed)
    c.draft.factors["horizontal"] = 3720
    select(c, "review")
    monkeypatch.setattr(w.config, "_atomic_write", MagicMock(side_effect=OSError("disk")))
    c.save()
    assert w.config.b_factor == 1900
    assert c.draft.dirty
    assert not c.saved


def test_missing_movement_and_missing_stop_evidence_cannot_pass(service):
    c, _, _, feed = service
    prepare(c, feed)
    for step in ("axial", "horizontal", "lateral", "leg", "loadcell", "stops"):
        select(c, step)
        c.action("result", {"status": "pass", "notes": "Looks fine"})
        assert step not in c.results
        c.action("result", {"status": "skip", "notes": "No reference tool"})
        assert c.results[step]["status"] == "skip"


def test_authentication_required_on_open_and_each_visit(service):
    c, w, _, _ = service
    c.shutdown()
    w.protocol_state = "idle"
    c.open()
    assert c.dialog is None
    assert c.pin_dialog is not None
    c.pin_dialog.submit("654321")
    assert c.dialog is None
    c.pin_dialog.submit("654321")
    assert c.dialog is not None
    c.timer.stop()
    c.shutdown()
    c.open()
    assert c.dialog is None
    c.pin_dialog.submit("000000")
    assert c.dialog is None
    c.pin_dialog.submit("654321")
    assert c.dialog is not None
    c.timer.stop()


def test_session_stop_evidence_does_not_survive_reopen(service):
    c, w, _, feed = service
    prepare(c, feed)
    c.physical_stop_seen = c.software_stop_written = True
    c.shutdown()
    c._start_session()
    c.timer.stop()
    assert not c.physical_stop_seen
    assert not c.software_stop_written


def test_long_feedback_gap_requires_new_settling_window(service):
    c, _, clock, feed = service
    prepare(c, feed)
    clock[0] += 10
    feed(count=1)
    assert not c.ready()
    feed()
    assert c.ready()


def test_failed_setup_allows_load_cell_repair_without_motion(service):
    c, w, _, feed = service
    c.shutdown()
    w.protocol_state = "fault"
    w.actuator_command_in_progress = True
    assert c._can_open()
    c._start_session()
    c.timer.stop()
    c.action("begin")
    feed()
    c.hardware["b_ok"] = False
    assert not c.ready()
    assert c.measurement_ready()
    select(c, "loadcell")
    c.action("pressure_capture", "zero")
    assert "zero" in c.pressure_points
    c.move("axial", 700)
    assert not any(command.startswith("I") for command in w.arduino.commands)
    feed(raw=-467380)
    c.action("pressure_capture", "loaded")
    c.action("pressure_calculate", 10)
    select(c, "review")
    c.save()
    assert w.config.calibration == -56738
    assert w.protocol_state == "fault"


def test_close_after_completed_move_requires_reset_even_without_edits(service):
    c, w, _, feed = service
    prepare(c, feed)
    c.move("axial", 550)
    w.arduino.done_emit.emit()
    feed(a=550)
    assert c.handle is None
    assert not c.draft.dirty
    c.shutdown()
    assert not w.initial_setup_complete
    assert w.protocol_state == "fault"
    assert w._no_automatic_recovery


def test_normal_motion_cannot_overlap_service_and_leg_requires_rehome(service):
    from kneespa import KneeSpa

    c, w, _, feed = service
    prepare(c, feed)
    assert not KneeSpa._send_motion_command(w, "I12550", "test")
    c.move_leg("+")
    assert w._service_leg_position_unknown
    assert not KneeSpa._move_leg(w, "F+", 0.25, 600, True)


def test_diagnostic_snapshot_does_not_automatically_pass_operator_check(service):
    c, _, _, feed = service
    prepare(c, feed)
    c.action("check_link")
    assert "communication" not in c.results


def test_report_keeps_reference_and_proposed_unsaved_settings(service):
    c, _, _, feed = service
    prepare(c, feed)
    c.capture_pressure("zero")
    feed(raw=-467380)
    c.capture_pressure("loaded")
    c.action("pressure_calculate", 10)
    c.export_report()
    report = json.loads(c.report_path.read_text(encoding="utf-8"))
    assert report["reference_force_lb"] == 10
    assert not report["configuration_saved"]
    assert any("Load-cell" in change[0] for change in report["proposed_changes"])
