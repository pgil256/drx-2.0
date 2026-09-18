"""Gate W: real KneeSpa construction and treatment signals with offline boundaries.

Only hardware/network execution and the worker scheduler are controlled. The
window, configuration, CSV/auth, shell, controllers, wiring and timers are real.
Queued single shots are delivered explicitly to simulate nested/late events.
"""

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PyQt5.QtCore import QEvent, QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox
from pytestqt.qtbot import QtBot

import kneespa
from config.config import Configuration
from config.constants import DATA_PATHS
from controllers import connection_manager, protocol_controller
from helpers.arduino import Arduino
from helpers.protocols import WorkerSignals
from helpers.reset_worker import ResetWorkerSignals
from ui.screens.content import PHASES

pytestmark = pytest.mark.integration
_QT_SINGLE_SHOT = QTimer.singleShot


def test_operator_login_opens_distinct_patient_modal(window_run: SimpleNamespace) -> None:
    run = window_run
    run.window.cloud_patient = {"patient_id": str(uuid4())}
    run.window.update_ui_after_login()
    assert run.window.shell.login_modal.isHidden()
    assert run.window.shell.patient_modal.isVisible()
    assert run.window.cloud_patient is None
    assert run.window.current_user["username"] == "Test operator"
    run.window.shell.patient_modal.close_overlay()
    assert run.window.cloud_patient is None
    assert not run.window._patient_lookup_pending
    assert "No patient linked" in run.view._patient_label.text()


def test_modal_patient_pin_and_cancel_invalidate_late_result(
    window_run: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = window_run
    run.cloud.enabled = True
    jobs = []
    monkeypatch.setattr(kneespa.threading, "Thread", lambda **kw: SimpleNamespace(
        start=lambda: jobs.append(kw["target"])
    ))
    response = {"patient_id": str(uuid4()), "display_name": "Test Patient", "settings": {
        "protocol_number": 4, "duration_min": 12, "max_pressure_lb": "50.0",
        "max_left_deg": "0.0", "max_right_deg": "20.0", "pulse_rate_hz": "2.4",
    }}
    run.cloud.lookup_pin.return_value = response
    run.window._show_patient_modal()
    modal = run.window.shell.patient_modal
    for digit in "0123":
        modal._keypad._press(digit)
    assert run.window._patient_lookup_pending
    assert not run.view._start_btn.isEnabled()
    modal.close_overlay()
    jobs.pop()()
    run.cloud.lookup_pin.assert_called_once_with("0123")
    assert run.window.cloud_patient is None
    assert run.view._start_btn.isEnabled()


def test_modal_patient_success_applies_whole_plan(window_run: SimpleNamespace) -> None:
    run = window_run
    run.window._show_patient_modal()
    response = {"patient_id": str(uuid4()), "display_name": None, "external_ref": "TEST-001",
                "settings": {"protocol_number": 3, "duration_min": 15, "max_pressure_lb": "60",
                             "max_left_deg": "0", "max_right_deg": "20", "pulse_rate_hz": "0"}}
    run.window._on_cloud_lookup_done(run.window._patient_lookup_id, response)
    assert run.window.shell.patient_modal.isHidden()
    assert run.view._patient_label.text() == "TEST-001"
    assert run.view.selected_protocol() == 3
    assert run.window.protocol_value == "3"
    assert run.view.settings_values()["pulse_rate"] == 0
    start(run)
    assert run.workers[-1][1][6] is False  # Zero pulses/sec disables pulsing.


def test_motor_speed_settings_reach_worker(window_run: SimpleNamespace) -> None:
    run = window_run
    speeds = {"axial_speed": 75, "lateral_speed": 90, "pulse_speed": 60}
    run.view.set_settings(speeds)
    start(run)
    worker, _args, kwargs = run.workers[-1]
    assert all(kwargs["motor_speeds"][key] == value for key, value in speeds.items())
    assert all(not run.view._settings[key].isEnabled() for key in speeds)
    worker.signals.motor_speed_failed.emit("Motor speed setup failed")
    run.notices.assert_called_with("Motor speed setup failed")


def nested_event(callback: Callable[[], None]) -> None:
    """Deliver an event inside a real nested Qt loop without a native dialog."""
    loop = QEventLoop()

    def deliver() -> None:
        try:
            callback()
        finally:
            loop.quit()

    _QT_SINGLE_SHOT(0, deliver)
    loop.exec_()


@pytest.fixture
def window_run(themed_app: QApplication, tmp_path: Path,
               monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    """Construct the real window without operator data, serial or network I/O."""
    cfg_path = tmp_path / "kneespa.cfg"
    config = Configuration(str(cfg_path))
    config._set_default_a_marks()
    config._set_default_b_marks()
    config._set_default_c_marks()
    for section in ("AMarks", "BMarks", "CMarks"):
        config._set_section(section, getattr(config, section))
    config.calibration = -28369
    config.update_config()
    for key in ("USER_PINS", "AUTH_STATE", "PENDING_UPLOADS"):
        monkeypatch.setitem(DATA_PATHS, key, str(tmp_path / key.lower()))
    (tmp_path / "user_pins").write_text("pin_hash,username,email,status\n", encoding="utf-8")
    for key in ("ADMIN_PIN", "ADMIN_PIN_HASH", "USER_PIN", "USER_PIN_HASH"):
        monkeypatch.delenv(key, raising=False)

    cloud = MagicMock(enabled=False)
    monkeypatch.setattr(kneespa, "CloudClient", lambda **kwargs: cloud)
    smtp = MagicMock(side_effect=AssertionError("Unexpected SMTP connection"))
    monkeypatch.setattr(kneespa.smtplib, "SMTP_SSL", smtp)
    arduino = MagicMock(spec=Arduino)
    arduino._connect_cancel = threading.Event()
    arduino._io_thread = None
    arduino.wait_for_drain.return_value = True
    arduino.connected = True
    arduino.send.return_value = True
    arduino.verify_connection.return_value = True
    arduino.disconnect.return_value = True
    events, pending, timers, workers = [], [], [], []

    def connect(manager: connection_manager.ConnectionManager,
                auto_reset: bool = True) -> bool:
        manager.window.arduino = arduino
        manager.window.initial_setup_complete = True
        return True

    monkeypatch.setattr(connection_manager.ConnectionManager, "setup_arduino", connect)
    monkeypatch.setattr(QTimer, "singleShot", lambda delay, callback: pending.append(
        (delay, callback)
    ))

    class RecordedTimer(QTimer):
        def __init__(self, *args: object) -> None:
            super().__init__(*args)
            timers.append(self)

        def start(self, *args: object) -> None:
            events.append("timer")
            super().start(*args)

    monkeypatch.setattr(kneespa, "QTimer", RecordedTimer)
    window = kneespa.KneeSpa(debug_mode=True, config_path=str(cfg_path))
    assert window.config.calibrated
    assert window.arduino is None
    startup = next(callback for delay, callback in pending if delay == 100)
    startup()
    pending.clear()
    window.current_user = {"username": "Test operator", "status": "admin"}
    window.shell.login_succeeded("Test operator", "admin")
    window.shell.navigate("protocols")
    window.resize(1366, 768)
    window.show()
    notices = MagicMock()
    monkeypatch.setattr(window, "_show_timed_error", notices)
    # Native message-box rendering is a separate UI contract; keep alerts
    # observable without opening platform dialogs inside simulated races.
    monkeypatch.setattr(window, "_show_safety_alert", MagicMock())
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)

    def construct(*args: object, **kwargs: object) -> MagicMock:
        events.append("worker")
        worker = MagicMock()
        worker.signals = WorkerSignals()
        worker.cancel.side_effect = lambda **kw: events.append("cancel")
        worker.stop.side_effect = lambda: events.append("worker.stop")
        workers.append((worker, args, kwargs))
        return worker

    monkeypatch.setattr(protocol_controller.protocols, "Protocols", construct)
    pool = MagicMock()
    pool.activeThreadCount.return_value = 0
    window.threadpool = pool

    def dispatch(worker: object) -> None:
        events.append("dispatch")
        assert not window.protocol_timer.isActive()
        assert worker.signals.receivers(worker.signals.finished) == 1
        assert worker.signals.receivers(worker.signals.progress) == 1
        assert worker.signals.receivers(worker.signals.reset_needed) == 0
        worker.signals.prepared.emit(time.time(), time.monotonic())

    pool.start.side_effect = dispatch
    run = SimpleNamespace(window=window, view=window.shell.treatment, arduino=arduino,
                          cloud=cloud, events=events, pending=pending, timers=timers,
                          workers=workers, pool=pool, notices=notices, dispatch=dispatch)
    events.clear()
    real_thread = threading.Thread
    yield run
    monkeypatch.setattr(threading, "Thread", real_thread)
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.close()
    window._cloud_close_thread.join(timeout=1)
    window.close()
    assert window._cleanup_complete
    assert not window.protocol_timer.isActive()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    pending.clear()
    smtp.assert_not_called()


@pytest.mark.parametrize("page", ["setup", "profile"])
def test_calibration_button_opens_shared_session(
    window_run: SimpleNamespace, page: str, qtbot: QtBot,
) -> None:
    """Both visible entry points open the real controller without requesting motion."""
    w = window_run.window
    w.shell.navigate(page)
    button = getattr(w.shell, page)._calibration
    assert button.isVisible()
    assert button.isEnabled()
    window_run.arduino.send.reset_mock()

    button.click()

    controller = w.calibration_controller
    assert controller.dialog.isVisible()
    assert w._calibration_active
    assert not controller.dialog.capture_button.isEnabled()
    window_run.arduino.send.assert_called_once_with("HF1")
    assert not w.shell.setup._rows["horizontal"].motion_buttons[0].isEnabled()

    controller.dialog.close_button.click()

    assert controller.dialog is None
    assert not w._calibration_active
    qtbot.waitUntil(w.shell.setup._rows["horizontal"].motion_buttons[0].isEnabled)


@pytest.mark.parametrize("page", ["setup", "profile"])
@pytest.mark.parametrize("busy_flag", [
    "protocol_running", "reset_in_progress", "actuator_command_in_progress",
])
def test_calibration_entry_refuses_busy_device(
    window_run: SimpleNamespace, page: str, busy_flag: str,
) -> None:
    """Exposing calibration preserves the controller's existing device ownership guards."""
    w = window_run.window
    w.shell.navigate(page)
    setattr(w, busy_flag, True)
    window_run.arduino.send.reset_mock()
    try:
        getattr(w.shell, page)._calibration.click()

        assert w.calibration_controller.dialog is None
        assert not w._calibration_active
        window_run.notices.assert_called_once()
        window_run.arduino.send.assert_not_called()
    finally:
        setattr(w, busy_flag, False)


def phase(run: SimpleNamespace) -> str:
    """Read the badge text displayed to the operator."""
    return run.view._phase_badge._label.text()


def start(run: SimpleNamespace) -> MagicMock:
    """Click the actual START control connected by KneeSpa._connect_shell."""
    run.view._start_btn.click()
    return run.workers[-1][0]


def test_constructor_timer_wiring_and_cleanup(window_run: SimpleNamespace,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    run = window_run
    w = run.window
    assert len(run.timers) == 3
    assert w._cloud_retry_timer in run.timers
    assert not w._cloud_retry_timer.isActive()  # Cloud disabled in this offline fixture.
    assert w.protocol_timer in run.timers
    assert w.protocol_timer.parent() is w
    assert w.protocol_timer.interval() == 1000
    assert w.protocol_timer.receivers(w.protocol_timer.timeout) == 1
    assert not w.protocol_timer.isActive()
    run.view.set_settings({"duration": 12})
    start(run)
    assert run.events[:3] == ["worker", "dispatch", "timer"]
    assert w.protocol_state == "running"
    assert run.view._start_btn.isVisible() and not run.view._start_btn.isEnabled()
    assert run.view._pause_btn.isEnabled()
    assert not run.view._settings["duration"].isEnabled()
    assert phase(run) == PHASES["ramping"][0]
    anchor = w.protocol_start_time
    monkeypatch.setattr(protocol_controller.time, "time", lambda: anchor + 5)
    w.protocol_timer.timeout.emit()
    assert w.treatment_panel.time_label.text() == "11:55 left"
    assert run.view._progress_fraction == pytest.approx(5 / 720)
    w.close()
    assert w._closing and not w.protocol_timer.isActive()
    assert [c.args[0] for c in run.arduino.send.call_args_list][-3:] == ["X", "P0", "HF0"]


@pytest.mark.parametrize("answer", [QMessageBox.No, QMessageBox.Yes])
@pytest.mark.parametrize("during", ["confirmation", "connection"])
def test_confirmation_reads_inputs_after_nested_edits(window_run: SimpleNamespace,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      answer: int, during: str) -> None:
    run = window_run
    summaries = []

    def edit() -> None:
        run.view.set_settings({"max_pressure": 63, "max_left": 13,
                               "max_right": 17, "duration": 18})
        run.view.select_protocol(3)

    def confirm(*args: object) -> int:
        summaries.append(args[2])
        if during == "confirmation":
            nested_event(edit)
        return answer

    monkeypatch.setattr(QMessageBox, "question", confirm)
    if during == "connection":
        run.arduino.verify_connection.side_effect = lambda: nested_event(edit) or True
    run.view._start_btn.click()
    assert "Max pressure: 40" in summaries[0]
    if answer == QMessageBox.No:
        assert not run.workers and not run.window.protocol_timer.isActive()
        assert run.view._start_btn.isEnabled()
    else:
        assert run.workers[0][1][1:6] == ("3", 63, -13, 17, 18)


@pytest.mark.parametrize("during", ["confirmation", "connection"])
@pytest.mark.parametrize("event", ["fault", "reset", "stop"])
def test_nested_state_change_prevents_dispatch(window_run: SimpleNamespace,
                                               monkeypatch: pytest.MonkeyPatch,
                                               during: str, event: str) -> None:
    run = window_run
    w = run.window

    def change() -> None:
        if event == "fault":
            w.safety.on_physical_stop()
        elif event == "reset":
            w.reset_in_progress = True
        else:
            w.protocol.stop_protocol()

    if during == "confirmation":
        monkeypatch.setattr(
            QMessageBox, "question", lambda *args: nested_event(change) or QMessageBox.Yes
        )
    else:
        run.arduino.verify_connection.side_effect = lambda: nested_event(change) or True
    run.view._start_btn.click()
    assert not run.workers and not w.protocol_timer.isActive()
    assert not run.view._start_btn.isEnabled()
    assert w.protocol_state == {"fault": "fault", "reset": "idle", "stop": "stopping"}[event]


@pytest.mark.parametrize("success", [True, False])
def test_immediate_completion_cannot_be_promoted_to_running(window_run: SimpleNamespace,
                                                          success: bool) -> None:
    run = window_run

    def finish(worker: MagicMock) -> None:
        run.dispatch(worker)
        worker.signals.progress.emit(">Oscillating limb")
        assert phase(run) == PHASES["oscillating"][0]
        worker.signals.finished.emit(success)

    run.pool.start.side_effect = finish
    start(run)
    assert run.window.protocol_state == ("idle" if success else "fault")
    assert not run.window.protocol_timer.isActive()
    assert run.view._start_btn.isEnabled() == success
    assert not run.view._pause_btn.isEnabled()
    assert phase(run) == PHASES["complete" if success else "stopped"][0]


@pytest.mark.parametrize("pulse,expected", [(True, "pulsing"), (False, "holding")])
def test_pause_resume_clock_and_live_cancel(window_run: SimpleNamespace,
                                           monkeypatch: pytest.MonkeyPatch,
                                           pulse: bool, expected: str) -> None:
    run = window_run
    worker = start(run)
    w = run.window
    anchor = w.protocol_start_time
    monkeypatch.setattr(protocol_controller.time, "time", lambda: anchor + 5)
    run.view._pause_btn.click()
    worker.pause.assert_called_once()
    assert run.view._start_btn.text() == "RESUME" and run.view._start_btn.isEnabled()
    assert phase(run) == PHASES["paused"][0]
    assert not w.protocol_timer.isActive()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.Cancel)
    run.view.set_settings({"max_pressure": 70})
    run.view.setting_changed.emit("max_pressure", 70)
    assert run.view.settings_values()["max_pressure"] == 40
    worker.request_live_pressure.assert_not_called()
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.Ok)
    run.view.set_settings({"max_pressure": 61})
    run.view.setting_changed.emit("max_pressure", 61)
    worker.request_live_pressure.assert_called_once_with(61)
    w.current_use_pulse_setting = pulse
    monkeypatch.setattr(protocol_controller.time, "time", lambda: anchor + 25)
    run.view._start_btn.click()
    worker.resume.assert_called_once()
    assert w.protocol_start_time == anchor + 20
    assert w.protocol_timer.isActive() and w.protocol_timer.interval() == 1000
    assert phase(run) == PHASES[expected][0]


@pytest.mark.parametrize("success", [True, False])
def test_stop_completion_race_and_recovery(window_run: SimpleNamespace,
                                          success: bool) -> None:
    run = window_run
    worker = start(run)
    run.arduino.send.side_effect = lambda command: run.events.append(command) or True
    run.view.estop_requested.emit()
    assert run.events.index("cancel") < run.events.index("X")
    assert phase(run) == PHASES["stopped"][0]
    assert not run.window.protocol_timer.isActive()
    worker.signals.finished.emit(success)
    assert run.window.protocol_state == "stopping"
    assert not run.view._start_btn.isEnabled()
    run.window.connection._on_reset_finished(True)
    assert run.window.protocol_state == "idle" and run.view._start_btn.isEnabled()
    assert run.view._settings["duration"].isEnabled()


@pytest.mark.parametrize("result", ["success", "failure", "error"])
def test_reset_signals_drive_real_controls(window_run: SimpleNamespace,
                                           monkeypatch: pytest.MonkeyPatch,
                                           result: str) -> None:
    run = window_run
    reset = MagicMock(signals=ResetWorkerSignals())
    monkeypatch.setattr(connection_manager, "ResetWorker", lambda *args: reset)
    run.pool.start.side_effect = None
    run.window.reset_arduino()
    assert run.window.reset_in_progress and not run.view._start_btn.isEnabled()
    if result == "error":
        reset.signals.error.emit("reset test failure")
        assert run.window.reset_in_progress
        reset.signals.finished.emit(False)
    else:
        reset.signals.finished.emit(result == "success")
    assert not run.window.reset_in_progress
    assert run.window.protocol_state == ("idle" if result == "success" else "fault")
    assert run.view._start_btn.isEnabled() == (result == "success")


def test_fault_survives_completion_and_stale_callbacks_after_close(
    window_run: SimpleNamespace,
) -> None:
    run = window_run
    worker = start(run)
    run.window.safety.on_physical_stop()
    worker.signals.finished.emit(True)
    assert run.window.protocol_state == "fault"
    assert not run.view._start_btn.isEnabled()
    assert not run.window.protocol_timer.isActive()
    run.window.connection._on_reset_finished(True)
    assert run.window.protocol_state == "fault"
    assert not run.view._start_btn.isEnabled()
    run.window.close()
    run.window.protocol._stop_phase2()
    run.window.protocol._emergency_stop_phase2()
    run.window.connection._on_reset_finished(True)
    worker.signals.finished.emit(True)
    assert run.window.protocol_state == "fault"
    assert not run.window.protocol_timer.isActive()


def test_upload_uses_live_end_settings_and_frozen_patient(window_run: SimpleNamespace) -> None:
    run = window_run
    run.cloud.enabled = True
    run.window.cloud_patient = {"patient_id": 7}
    worker = start(run)
    run.window.cloud_patient = {"patient_id": 8}
    run.view.set_settings({"max_pressure": 67, "max_left": 12, "max_right": 16})
    worker.signals.finished.emit(True)
    record = run.cloud.post_treatment_async.call_args.args[0]
    assert record["patient_id"] == "7"
    assert record["outcome"] == "completed"
    assert record["settings_at_end"] == {
        "max_pressure_lb": 67, "max_left_deg": 12, "max_right_deg": 16, "pulse_rate_hz": 2,
    }


@pytest.mark.parametrize("text,expected", [
    (">>PULSING oscillating moving to complete stopped pressure", "pulsing"),
    ("Oscillating moving to complete stopped pressure", "oscillating"),
    ("Moving to complete stopped pressure", "positioning"),
    ("Complete stopped pressure", "complete"),
    ("Stopped pressure", "stopped"),
    ("Protocol Started", "ramping"),
    (">Pressure ramp", "ramping"),
    (">>unknown diagnostic", "holding"),
    ("  >>unknown diagnostic", "holding"),
])
def test_worker_progress_phase_precedence_and_full_banner(window_run: SimpleNamespace,
                                                         text: str, expected: str) -> None:
    run = window_run
    worker = start(run)
    run.view.set_phase("holding")
    worker.signals.progress.emit(text)
    assert phase(run) == PHASES[expected][0]
    assert run.window.treatment_panel.phase_label.text() == text.lstrip(">").upper()


def test_progress_view_error_still_updates_banner(window_run: SimpleNamespace,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    run = window_run
    monkeypatch.setattr(run.view, "set_phase", MagicMock(side_effect=RuntimeError("view")))
    run.window.protocol.update_status_label(">>Pressure ramp")
    assert run.window.treatment_panel.phase_label.text() == "PRESSURE RAMP"


@pytest.mark.parametrize("action", ["Dismiss", "Stop"])
def test_pressure_notice_actions_keep_recovery_explicit(window_run, action, qtbot):
    run = window_run
    worker = start(run)
    run.arduino.send.reset_mock()
    run.window.on_pressure_progress_notice({"travel_counts": 2150, "rise_lb": 1.5})
    notice = run.window._pressure_notice
    assert notice.isVisible()
    (notice.dismiss_button if action == "Dismiss" else notice.stop_button).click()
    if action == "Dismiss":
        run.arduino.send.assert_not_called()
        worker.cancel.assert_not_called()
    else:
        assert [c.args[0] for c in run.arduino.send.call_args_list] == ["X", "X", "HF1"]
        worker.cancel.assert_called_once_with(firmware_stopped=True)
        assert run.window._no_automatic_recovery
        run.window.protocol._stop_phase2()
        run.window.connection._automatic_reset()
        assert [c.args[0] for c in run.arduino.send.call_args_list] == ["X", "X", "HF1"]


def test_restart_button_requests_cleanup_once(window_run):
    run = window_run
    run.window.shell.navigate("profile")
    run.window.shell.profile._restart.click()
    assert run.window.restart_requested and run.window._closing
    run.window._on_restart_app()
    assert [c.args[0] for c in run.arduino.send.call_args_list] == ["X", "P0", "HF0"]


def test_pressure_caption_and_decimal_render_in_existing_panel(window_run, tmp_path):
    run = window_run
    run.window.on_sensor_diagnostics({"valid": True, "age_ms": 0})
    run.window.on_baseline_changed(True)
    run.view.set_pressure(40.25)
    assert run.view._pressure_stat._value == "40.2"
    assert run.view._pressure_stat.grab().save(str(tmp_path / "pressure-panel.png"))
