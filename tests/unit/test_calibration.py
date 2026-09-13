"""Guided calibration: measured data, serial lifecycle, UI and atomic saving."""

import configparser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QMainWindow, QMessageBox, QPushButton

from config.config import Configuration
from controllers.calibration_controller import CalibrationController
from controllers.connection_manager import ConnectionManager
from controllers.protocol_controller import ProtocolController
from helpers.arduino import CommandHandle
from helpers.calibration import CalibrationDraft, distance_factor
from ui.app_shell import AppShell

pytestmark = pytest.mark.unit


@pytest.fixture
def config(tmp_path):
    result = Configuration(str(tmp_path / "device.cfg"))
    result._set_default_a_marks()
    result._set_default_b_marks()
    result._set_default_c_marks()
    result.calibration = -28369
    result._write_default_config()
    result.get_config()
    return result


def test_factor_uses_measured_distance_and_preserves_direction():
    assert distance_factor(100, 1340, 2) == 3720
    assert distance_factor(1340, 100, 2) == 3720


@pytest.mark.parametrize("inches", [0, -1, float("nan"), float("inf")])
def test_bad_distance_rejected(inches):
    with pytest.raises(ValueError):
        distance_factor(100, 1340, inches)


def test_stationary_anchors_rejected():
    with pytest.raises(ValueError):
        distance_factor(100, 101, 2)


def test_save_roundtrip_replaces_key_and_preserves_other_sections(config):
    config.config["Unrelated"] = {"keep": "yes"}
    config._atomic_write()
    original = Path(config.configFile).read_bytes()
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    draft.record("lateral", 0, 1690)
    draft.factors["horizontal"] = 3720
    assert config.BMarks["0"] == 1900  # not changed until Save
    backup = draft.save(config)
    assert Path(backup).read_bytes() == original
    assert not draft.dirty
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.BMarks["0.0"] == 1910
    assert "0" not in loaded.BMarks
    assert loaded.CMarks["0.0"] == 1690
    assert loaded.b_factor == 3720
    assert loaded.calibration == -28369
    assert loaded.AMarks == config.AMarks
    assert loaded.config["Unrelated"]["keep"] == "yes"
    loaded.update_config()
    parser = configparser.ConfigParser()
    parser.read(config.configFile)
    assert parser["BMarks"]["0.0"] == "1910"


def test_failed_save_preserves_live_config_and_original_file(config, monkeypatch):
    original = Path(config.configFile).read_bytes()
    parser = config.config
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    monkeypatch.setattr(config, "_atomic_write", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        draft.save(config)
    assert config.config is parser
    assert config.BMarks["0"] == 1900
    assert Path(config.configFile).read_bytes() == original
    assert draft.dirty


@pytest.mark.parametrize("change", ["missing_endpoint", "out_of_order", "out_of_range"])
def test_invalid_table_cannot_replace_file(config, change):
    original = Path(config.configFile).read_bytes()
    draft = CalibrationDraft(config)
    if change == "missing_endpoint":
        draft.marks["horizontal"].pop("-25.0")
    elif change == "out_of_order":
        draft.marks["horizontal"]["0.0"] = 100
    else:
        draft.marks["horizontal"]["5.0"] = 4501
    with pytest.raises(ValueError):
        draft.save(config)
    assert Path(config.configFile).read_bytes() == original


def test_factor_only_save_does_not_rewrite_existing_cmarks(config):
    config.CMarks = {"0": 10, "-10": 30, "10": 20}
    config.config["CMarks"] = {k: str(v) for k, v in config.CMarks.items()}
    draft = CalibrationDraft(config)
    draft.factors["horizontal"] = 3720
    draft.save(config)
    assert config.CMarks == {"0": 10, "-10": 30, "10": 20}
    assert dict(config.config["CMarks"]) == {"0": "10", "-10": "30", "10": "20"}


def test_bc_edits_do_not_certify_fallback_axial_data(config):
    config.calibration_errors.append("AMarks section missing; defaults in use")
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    draft.save(config)
    assert not config.marks_valid


class CalibrationArduino(QObject):
    status_emit = pyqtSignal(int, int, int, float)
    done_emit = pyqtSignal()
    error_emit = pyqtSignal(str)
    warning_emit = pyqtSignal(str)
    connection_lost = pyqtSignal()
    ready_to_go_emit = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.connected = True
        self.protocol_v2 = False
        self.commands = []
        self.allow_send = True

    def send(self, command):
        self.commands.append(command)
        return self.allow_send

    def send_tracked(self, command):
        if not self.send(command):
            return None
        handle = CommandHandle(command)
        handle.written.set()
        return handle


@pytest.fixture
def session(qtbot, config, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(
        "controllers.calibration_controller.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    window = QMainWindow()
    qtbot.addWidget(window)
    window.current_user = {"username": "Technician"}
    window.config = config
    window.arduino = CalibrationArduino()
    window.protocol_state = "idle"
    window.protocol_running = False
    window.reset_in_progress = False
    window.actuator_command_in_progress = False
    window.initial_setup_complete = True
    window._physical_stop_active = False
    window._closing = False
    window.disable_actuator_controls = MagicMock()
    window.enable_actuator_controls = MagicMock()
    window._show_timed_error = MagicMock()
    window.set_protocol_state = lambda state: setattr(window, "protocol_state", state)
    controller = CalibrationController(window)
    controller.open()
    controller.timer.stop()  # tests drive the monotonic clock explicitly

    def feed(b=1900, c=1688, count=4):
        for _ in range(count):
            clock[0] += 0.15
            window.arduino.status_emit.emit(0, b, c, 0.0)

    yield controller, window, clock, feed
    controller.shutdown()


def test_profile_keeps_calibration_hidden_after_login(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert not shell.profile._calibration.isEnabled()
    assert shell.profile._calibration.isHidden()
    shell.login_succeeded("Technician", goto="profile")
    assert shell.profile._calibration.isHidden()


def test_record_requires_fresh_settled_feedback_and_never_moves(session):
    controller, window, clock, feed = session
    d = controller.dialog
    d.angle.setValue(0)
    assert not d.capture_button.isEnabled()
    feed(b=1910)
    assert d.capture_button.isEnabled()
    d.capture_button.click()
    assert controller.draft.marks["horizontal"]["0.0"] == 1910
    assert window.config.BMarks["0"] == 1900
    assert window.arduino.commands == ["HF1"]
    clock[0] += 3
    controller.tick()
    assert not d.capture_button.isEnabled()
    assert not d.jog_buttons[0].isEnabled()


@pytest.mark.parametrize("axis,command", [(0, "I131950"), (1, "K1738")])
def test_jog_routes_correct_axis_and_waits_for_ack_and_settle(session, axis, command):
    controller, window, _, feed = session
    d = controller.dialog
    d.axis.setCurrentIndex(axis)
    feed()
    d.jog_buttons[2].click()
    assert window.arduino.commands[-1] == command
    assert not d.capture_button.isEnabled()
    assert not d.axis.isEnabled()
    feed(b=1950 if axis == 0 else 1900, c=1738 if axis == 1 else 1688)
    assert controller.handle is not None  # arrival alone is insufficient
    window.arduino.done_emit.emit()
    controller.tick()
    assert controller.handle is None
    assert d.capture_button.isEnabled()


def test_done_without_arrival_does_not_enable_capture(session):
    controller, window, _, feed = session
    feed()
    controller.jog(200)
    window.arduino.done_emit.emit()
    feed()
    assert controller.handle is not None
    assert not controller.dialog.capture_button.isEnabled()


def test_v2_unrelated_done_does_not_complete_move(session):
    controller, window, _, feed = session
    window.arduino.protocol_v2 = True
    feed()
    controller.jog(50)
    window.arduino.done_emit.emit()
    feed(b=1950)
    assert controller.handle is not None
    controller.handle.result = "DONE"
    controller.handle.completed.set()
    controller.tick()
    assert controller.handle is None


@pytest.mark.parametrize("failure", ["stale", "timeout", "error", "disconnect", "close", "stall"])
def test_failed_or_closed_move_sends_stop_and_requires_reset(session, failure):
    controller, window, clock, feed = session
    feed()
    controller.jog(200)
    if failure == "stale":
        clock[0] += 3
        controller.tick()
    elif failure == "timeout":
        clock[0] += 16
        controller.last_status = clock[0]
        controller.tick()
    elif failure == "error":
        window.arduino.error_emit.emit("BUSY")
    elif failure == "disconnect":
        window.arduino.connected = False
        window.arduino.connection_lost.emit()
    elif failure == "stall":
        window.arduino.warning_emit.emit("Motor stalled")
    else:
        controller.dialog.reject()
    assert "X" in window.arduino.commands
    assert window.protocol_state == "fault"
    assert not window.initial_setup_complete
    assert controller.aborted


def test_physical_stop_does_not_restart_firmware_release(session):
    controller, window, _, feed = session
    feed()
    controller.jog(200)
    window._physical_stop_active = True
    controller.tick()
    assert "X" not in window.arduino.commands
    assert controller.aborted


def test_jog_limits_and_failed_enqueue_do_not_fabricate_movement(session):
    controller, window, _, feed = session
    feed(b=0)
    controller.jog(-50)
    assert window.arduino.commands == ["HF1"]
    assert controller.handle is None
    window.arduino.allow_send = False
    controller.jog(50)
    assert controller.handle is None
    assert "could not be sent" in controller.dialog.message.text()


def test_factor_buttons_and_save_apply_only_selected_axis(session):
    controller, window, _, feed = session
    d = controller.dialog
    feed(b=100)
    d.anchor_buttons[0].click()
    feed(b=1340)
    d.anchor_buttons[1].click()
    d.distance.setValue(2)
    d.calculate_button.click()
    assert d.factor.value() == 3720
    assert window.config.b_factor == 1900
    d.apply_factor_button.click()
    d.save_button.click()
    assert window.config.b_factor == 3720
    assert window.config.c_factor == 1900
    assert not controller.draft.dirty
    d.axis.setCurrentIndex(1)
    assert "—" in d.anchors_label.text()


def test_discard_leaves_device_file_untouched(session, monkeypatch):
    controller, window, _, feed = session
    original = Path(window.config.configFile).read_bytes()
    feed(b=1910)
    controller.capture()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Discard)
    controller.dialog.reject()
    assert Path(window.config.configFile).read_bytes() == original
    assert not window._calibration_active


def test_session_excludes_treatment_and_reset(session):
    _, window, _, _ = session
    assert ProtocolController(window).start_protocol() is False
    ConnectionManager(window).reset_arduino()
    assert not window.reset_in_progress
    assert window._show_timed_error.call_count == 2


def test_angle_touch_buttons_and_enter_never_jog(session, qtbot):
    controller, window, _, feed = session
    feed()
    d = controller.dialog
    plus = next(b for b in d.angle.parent().findChildren(QPushButton) if b.text() == "+")
    minus = next(b for b in d.angle.parent().findChildren(QPushButton) if b.text() == "−")
    plus.click()
    assert d.angle.value() == 5
    minus.click()
    assert d.angle.value() == 0
    d.angle.setFocus()
    qtbot.keyClick(d.angle, Qt.Key_Return)
    assert window.arduino.commands == ["HF1"]


def test_failed_save_reports_error_and_retains_draft(session, monkeypatch):
    controller, window, _, feed = session
    feed(b=1910)
    controller.capture()
    monkeypatch.setattr(
        window.config, "_atomic_write", MagicMock(side_effect=OSError("disk full"))
    )
    controller.dialog.save_button.click()
    assert "not saved" in controller.dialog.message.text()
    assert "disk full" in controller.dialog.message.text()
    assert controller.draft.dirty
    assert window.config.BMarks["0"] == 1900


def test_moving_feedback_cannot_be_recorded(session):
    controller, _, _, feed = session
    for position in (1900, 1920, 1940, 1960):
        feed(b=position, count=1)
    controller.capture()
    assert not controller.draft.dirty
    assert not controller.dialog.capture_button.isEnabled()
