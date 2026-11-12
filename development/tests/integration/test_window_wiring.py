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
from controllers import (
    connection_manager, device_controller, hardware_service_controller, protocol_controller,
)
from helpers.arduino import Arduino
from helpers.protocols import WorkerSignals
from helpers.reset_worker import ResetWorkerSignals
from helpers.service_auth import ServiceAccess
from ui.screens.content import PHASES

pytestmark = pytest.mark.integration
_QT_SINGLE_SHOT = QTimer.singleShot


def test_device_uses_cloud_dashboard_device_id(window_run: SimpleNamespace) -> None:
    assert window_run.window.config.device_id != window_run.cloud.device_id
    assert window_run.window.shell.device._device_id.text() == (
        "Device ID: drx-test-device-01"
    )


def test_operator_login_leaves_patient_entry_to_the_operator(window_run: SimpleNamespace) -> None:
    run = window_run
    run.window.cloud_patient = {"patient_id": str(uuid4())}
    run.window.update_ui_after_login()
    assert run.window.shell.login_modal.isHidden()
    assert run.window.shell.patient_modal.isHidden()
    assert run.window.cloud_patient is None
    assert run.window.current_user["username"] == "Test operator"
    run.window.shell.nav_rail.navigate.emit("home")
    run.window.shell.nav_rail.navigate.emit("protocols")
    assert run.window.shell._current == "protocols"
    assert run.window.shell.patient_modal.isHidden()
    run.view._patient_button.click()
    assert run.window.shell.patient_modal.isVisible()
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


class _UnstartableThread:
    """A thread the OS refuses to start (Thread.start raises RuntimeError)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def start(self) -> None:
        raise RuntimeError("can't start new thread")


def test_patient_lookup_that_cannot_start_is_not_left_pending(
    window_run: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = window_run
    run.cloud.enabled = True
    run.window._show_patient_modal()
    with monkeypatch.context() as patch:
        patch.setattr(threading, "Thread", _UnstartableThread)
        for digit in "0123":
            run.window.shell.patient_modal._keypad._press(digit)
    assert not run.window._patient_lookup_pending
    assert run.window.cloud_patient is None
    assert run.view._start_btn.isEnabled()
    run.cloud.lookup_pin.assert_not_called()


def test_patient_cloud_operation_that_cannot_start_is_not_left_pending(
    window_run: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = window_run.window.patients
    with monkeypatch.context() as patch:
        patch.setattr(threading, "Thread", _UnstartableThread)
        controller._login("test@example.com", "not-a-real-password")
    assert not controller._pending
    assert not window_run.window._patient_lookup_pending


def test_machine_sign_in_that_cannot_start_is_not_left_busy(
    window_run: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = window_run.window
    window.current_user = None
    controller = window.machine_sign_in
    controller.timer.stop()
    with monkeypatch.context() as patch:
        patch.setattr(threading, "Thread", _UnstartableThread)
        controller.begin()
    assert not controller._busy
    assert not controller._request


def test_logout_during_patient_lookup_releases_the_start_gate(
    window_run: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = window_run
    run.cloud.enabled = True
    jobs = []
    monkeypatch.setattr(kneespa.threading, "Thread", lambda **kw: SimpleNamespace(
        start=lambda: jobs.append(kw["target"])
    ))
    run.window._show_patient_modal()
    for digit in "0123":
        run.window.shell.patient_modal._keypad._press(digit)
    assert run.view._patient_pending
    run.window._on_logout()
    assert not run.window._patient_lookup_pending
    assert not run.view._patient_pending  # The abandoned lookup must not gate Start.
    jobs.pop()()
    assert run.window.cloud_patient is None


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
    speeds = {"motor_speed": 75}
    run.view.set_settings(speeds)
    start(run)
    _worker, _args, kwargs = run.workers[-1]
    assert all(kwargs["motor_speeds"][key] == value for key, value in speeds.items())
    assert all(not run.view._settings[key].isEnabled() for key in speeds)


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
               monkeypatch: pytest.MonkeyPatch, qtbot: QtBot) -> Iterator[SimpleNamespace]:
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
    monkeypatch.delenv("KNEESPA_SERVICE_PIN_HASH", raising=False)
    monkeypatch.setattr(hardware_service_controller, "DEVICE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(device_controller, "DEVICE_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(device_controller.DeviceSettings, "read",
                        lambda self, key: (None, "Unavailable in tests"))
    monkeypatch.setattr(device_controller.DeviceSystem, "network", lambda self: {})
    monkeypatch.setattr(device_controller.DeviceSystem, "clock", lambda self: {})
    monkeypatch.setattr(hardware_service_controller, "ServiceAccess", lambda: ServiceAccess(
        str(tmp_path / "service-pin.json")
    ))

    cloud = MagicMock(enabled=False)
    cloud.cloud_url = "https://cloud.example"
    cloud.sync_summary.return_value = {"pending": 0, "blocked": 0,
                                       "last_sync": "Not recorded yet", "message": "Test cloud"}
    cloud.device_id = "drx-test-device-01"
    monkeypatch.setattr(kneespa, "CloudClient", lambda **kwargs: cloud)
    smtp = MagicMock(side_effect=AssertionError("Unexpected SMTP connection"))
    monkeypatch.setattr(kneespa.smtplib, "SMTP_SSL", smtp)
    arduino = MagicMock(spec=Arduino)
    arduino._connect_cancel = threading.Event()
    arduino._io_thread = None
    arduino.wait_for_drain.return_value = True
    arduino.connected = True
    arduino.firmware_version = "service-test"
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
    monkeypatch.setattr(protocol_controller.TreatmentReviewDialog, "confirm", lambda *args: True)

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

    def finish_cleanup() -> bool:
        # Single-shot callbacks are held by this fixture; retry close explicitly
        # while cloud/device workers finish and Qt delivers their completions.
        window.close()
        return getattr(window, "_cleanup_complete", False)

    qtbot.waitUntil(finish_cleanup, timeout=3000)
    assert window._cleanup_complete
    assert not window.protocol_timer.isActive()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    pending.clear()
    smtp.assert_not_called()


@pytest.mark.parametrize("page", ["device"])
def test_calibration_button_opens_shared_session(
    window_run: SimpleNamespace, page: str, qtbot: QtBot,
) -> None:
    """The calibration entry point demands the separate PIN before acquiring the shared link."""
    w = window_run.window
    w.shell.navigate(page)
    w.hardware_service.access.provision("654321", "654321", is_admin=True)
    w.shell.device._select_section(2)
    assert w.device_controller._auth_dialog.isVisible()
    w.device_controller._auth_dialog.submit("111111")
    assert not w.shell.device.service_unlocked
    w.device_controller._auth_dialog.submit("654321")
    assert w.shell.device.service_unlocked
    button = getattr(w.shell, page).calibration_button
    assert button.isVisible()
    assert button.isEnabled()
    window_run.arduino.send.reset_mock()
    controller = w.hardware_service

    button.click()

    assert controller.dialog.isVisible()
    assert w._calibration_active
    assert not controller.ready()
    assert [call[0][0] for call in window_run.arduino.send.call_args_list] == ["HF1", "T"]
    assert not w.shell.setup._rows["horizontal"].motion_buttons[0].isEnabled()

    controller.dialog.close_button.click()

    assert controller.dialog is None
    assert not w._calibration_active
    qtbot.waitUntil(w.shell.setup._rows["horizontal"].motion_buttons[0].isEnabled)


@pytest.mark.parametrize("page", ["device"])
@pytest.mark.parametrize("busy_flag", [
    "protocol_running", "reset_in_progress", "actuator_command_in_progress",
    "_device_maintenance_active",
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
        getattr(w.shell, page).calibration_button.click()

        assert w.hardware_service.dialog is None
        assert not w._calibration_active
        window_run.notices.assert_called_once()
        window_run.arduino.send.assert_not_called()
    finally:
        setattr(w, busy_flag, False)


def phase(run: SimpleNamespace) -> str:
    """Read the badge text displayed to the operator."""
    return run.view._phase_badge._label.text()


def test_protected_device_work_blocks_treatment_reset_and_manual_motion(window_run):
    run = window_run
    w = run.window
    w._device_maintenance_active = True
    run.arduino.send.reset_mock()
    try:
        w.protocol.start_protocol()
        w.connection.reset_arduino()
        assert not w.motion.send_motion_command("K1200", "test device guard")
        assert not run.workers
        run.arduino.send.assert_not_called()
    finally:
        w._device_maintenance_active = False


def test_motion_state_lives_on_the_motion_controller(window_run):
    """The window's old motion names reach MotionController (checklist A3):
    the connection manager's reset writes the positions, and the shutdown
    stop stops the two timers by name."""
    w = window_run.window
    assert w.motion.state is w.device_state
    w.axial_flexion_position = 2.5
    assert w.motion.axial_flexion_position == 2.5
    w.disable_actuator_controls()
    w.motion.state.initial_setup_complete = True
    w.enable_actuator_controls()
    assert w.controls_enable_timer is w.motion.controls_enable_timer is not None
    w.controls_enable_timer.stop()


def test_calibration_restore_requires_explicit_recovery(window_run, monkeypatch, tmp_path):
    w = window_run.window
    monkeypatch.setattr(w.device_controller, "_queue", MagicMock())
    w.device_controller._restore_done(tmp_path / "previous-calibration.json")
    assert not w.initial_setup_complete
    assert w._no_automatic_recovery
    assert w.protocol_state == "fault"
    w.protocol.start_protocol()
    assert not window_run.workers


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
    assert [c[0][0] for c in run.arduino.send.call_args_list][-3:] == ["X", "P0", "HF0"]


@pytest.mark.parametrize("answer", [False, True])
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

    monkeypatch.setattr(protocol_controller.TreatmentReviewDialog, "confirm", confirm)
    if during == "connection":
        run.arduino.verify_connection.side_effect = lambda: nested_event(edit) or True
    run.view._start_btn.click()
    assert summaries[0]["max_pressure"] == 40
    if not answer:
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
            protocol_controller.TreatmentReviewDialog, "confirm",
            lambda *args: nested_event(change) or True
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
    assert phase(run) == PHASES["complete" if success else "fault"][0]


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


@pytest.mark.parametrize("answer", ["not now", "re-home", "setup reset"])
def test_stop_waits_for_the_operator_to_rehome(window_run: SimpleNamespace,
                                               monkeypatch: pytest.MonkeyPatch,
                                               answer: str) -> None:
    """S2: after the release, nothing homes until the operator asks."""
    run = window_run
    w = run.window
    worker = start(run)
    run.view.estop_requested.emit()
    worker.signals.finished.emit(False)
    reset = MagicMock(signals=ResetWorkerSignals())
    monkeypatch.setattr(connection_manager, "ResetWorker", lambda *args: reset)
    run.pool.start.side_effect = None
    w.last_measured_pressure = 0.0
    w.protocol.stops._stop_phase3()
    prompt = w._rehome_prompt
    assert prompt.isVisible()
    assert w.protocol_state == "fault" and not w.initial_setup_complete
    assert not w.reset_in_progress and not run.view._start_btn.isEnabled()
    assert w.shell.setup._reset_btn.isEnabled()
    assert not any(button.isEnabled() for row in w.shell.setup._rows.values()
                   for button in row.motion_buttons)
    w.protocol.stops._stop_phase3()  # a repeat does not stack a second prompt
    assert w._rehome_prompt is prompt
    if answer == "not now":
        prompt.later_button.click()
        assert not prompt.isVisible() and not w.reset_in_progress
        assert w.protocol_state == "fault" and w.shell.setup._reset_btn.isEnabled()
        return
    if answer == "re-home":
        prompt.rehome_button.click()
    else:
        w.shell.setup._reset_btn.click()
    assert w.reset_in_progress and not prompt.isVisible()
    reset.signals.finished.emit(True)
    assert w.protocol_state == "idle" and run.view._start_btn.isEnabled()


def test_rehome_prompt_defers_to_a_later_safety_stop(window_run: SimpleNamespace) -> None:
    run = window_run
    w = run.window
    w.protocol.stop_from_view()  # Setup-screen Stop with nothing running
    w.last_measured_pressure = 0.0
    w.protocol.stops._stop_phase3()
    prompt = w._rehome_prompt
    w._no_automatic_recovery = True  # e.g. a firmware fault after the prompt opened
    errors = []
    w._show_timed_error = errors.append
    prompt.rehome_button.click()
    assert not w.reset_in_progress
    assert errors and "Reset in Setup" in errors[0]


def test_window_flags_live_in_device_state(window_run: SimpleNamespace,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """A1: the window's flags are its DeviceState, and the guards read it."""
    run = window_run
    w = run.window
    reset = MagicMock(signals=ResetWorkerSignals())
    monkeypatch.setattr(connection_manager, "ResetWorker", lambda *args: reset)
    run.pool.start.side_effect = None
    w.reset_arduino()
    assert w.device_state.reset_in_progress is True
    assert not w.device_state.can_exit() and not w.device_state.can_move()
    assert w._block_active_treatment_exit() is True
    reset.signals.finished.emit(True)
    assert w.device_state.reset_in_progress is False
    assert w.device_state.initial_setup_complete is True
    assert w.device_state.protocol_state == "idle"
    assert w.device_state.can_exit() and w.device_state.can_move()


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
    run.window.protocol.stops._stop_phase2()
    run.window.protocol.stops._emergency_stop_phase2()
    run.window.connection._on_reset_finished(True)
    worker.signals.finished.emit(True)
    assert run.window.protocol_state == "fault"
    assert not run.window.protocol_timer.isActive()


@pytest.mark.parametrize("ending", [
    "completed", "failed", "controller fault", "command rejected", "physical stop",
    "stop after command rejected",
])
def test_treatment_owns_setup_motion_until_it_ends(window_run: SimpleNamespace,
                                                   qtbot: QtBot, ending: str) -> None:
    """Setup motion is locked and refused for the whole treatment; Stop is not.

    Only a normal completion hands the motion controls back. A fault keeps
    them locked. Reset is the way out of a fault, so it is never locked.
    """
    run = window_run
    w = run.window
    setup = w.shell.setup
    motion = [button for row in setup._rows.values() for button in row.motion_buttons]
    stops = [button for row in setup._rows.values() for button in row.safety_buttons]
    reset = setup._reset_btn
    assert all(button.isEnabled() for button in motion + [reset])
    worker = start(run)
    assert w.protocol_state == "running"
    assert not any(button.isEnabled() for button in motion)
    assert all(button.isEnabled() for button in stops + [setup._estop_btn, reset])
    run.arduino.send.reset_mock()
    setup.go_requested.emit("pressure")
    setup.go_requested.emit("lateral")
    setup.jog_requested.emit("axial", "fwd")
    setup.jog_requested.emit("horizontal", "reset")
    run.arduino.send.assert_not_called()
    setup.stop_requested.emit("axial")
    run.arduino.send.assert_called_once_with("X")
    if ending == "controller fault":
        w.safety.on_controller_fault({"reason": "PRESSURE_SENSOR_TIMEOUT"})
    elif ending.endswith("command rejected"):
        w.safety.on_firmware_error("Invalid P value")
        if ending.startswith("stop"):
            # STOP before the cancelled worker reports. The rejection's fault
            # stays latched, and nothing on this path touches Reset.
            run.view.estop_requested.emit()
    elif ending == "physical stop":
        w.safety.on_physical_stop()
    worker.signals.finished.emit(ending == "completed")
    if ending == "completed":
        assert w.protocol_state == "idle"
        qtbot.waitUntil(lambda: all(button.isEnabled() for button in motion + [reset]),
                        timeout=2000)
        assert not w.actuator_command_in_progress
        return
    assert w.protocol_state == "fault"
    qtbot.wait(300)  # longer than the 200 ms enable debounce
    assert not any(button.isEnabled() for button in motion)
    assert reset.isEnabled()


@pytest.mark.parametrize("ending", [
    "failed", "controller fault", "controller restart", "command rejected", "physical stop",
])
@pytest.mark.parametrize("then", ["nothing", "screen stop", "banner stop"])
def test_a_faulted_treatment_can_be_left(window_run: SimpleNamespace,
                                         ending: str, then: str) -> None:
    """After a fault, Exit, Restart and Logout work, Stop tapped again or not.

    Reset is the recovery, and it cannot succeed while the controller is
    faulted or unplugged. The operator must still be able to restart the app.
    """
    run = window_run
    w = run.window
    worker = start(run)
    if ending == "controller fault":
        w.safety.on_controller_fault({"reason": "PRESSURE_SENSOR_TIMEOUT"})
    elif ending == "controller restart":
        w.safety.on_controller_restart()
    elif ending == "command rejected":
        w.safety.on_firmware_error("Invalid P value")
    elif ending == "physical stop":
        w.safety.on_physical_stop()
    else:
        worker.signals.finished.emit(False)
    assert w.protocol_state == "fault"
    if then == "screen stop":
        run.view.estop_requested.emit()
    elif then == "banner stop":
        w.panel_stop_requested()
    worker.signals.finished.emit(False)
    w.last_measured_pressure = 0.0
    for _ in range(10):  # the stop's later phases, each scheduled by the one before
        scheduled, run.pending[:] = list(run.pending), []
        for _, callback in scheduled:
            callback()
    run.notices.reset_mock()

    assert w.protocol_state == "fault"
    assert w._block_active_treatment_exit() is False
    run.notices.assert_not_called()


def test_upload_uses_live_end_settings_and_frozen_patient(window_run: SimpleNamespace) -> None:
    run = window_run
    run.cloud.enabled = True
    run.window.cloud_patient = {"patient_id": 7}
    worker = start(run)
    run.window.cloud_patient = {"patient_id": 8}
    run.view.set_settings({"max_pressure": 67, "max_left": 12, "max_right": 16})
    worker.signals.finished.emit(True)
    record = run.cloud.post_treatment_async.call_args[0][0]
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
    # The 250 ms measurement refresh also calls set_phase. If it fires while
    # set_phase is broken (pytest-qt processes events after the test; a slow
    # runner leaves the timer due), the failure lands in the Qt event loop.
    # This test is about the progress path only.
    run.window._pressure_state_timer.stop()
    monkeypatch.setattr(run.view, "set_phase", MagicMock(side_effect=RuntimeError("view")))
    run.window.protocol.update_status_label(">>Pressure ramp")
    assert run.window.treatment_panel.phase_label.text() == "PRESSURE RAMP"


def test_firmware_stall_timeout_faults_the_running_treatment(window_run):
    """F4: the firmware stopped a jammed move; the Pi must not treat it as advisory."""
    run = window_run
    w = run.window
    worker = start(run)
    run.arduino.send.reset_mock()
    w.handle_firmware_error("Motor stall timeout 14")
    assert w.protocol_state == "fault" and w._no_automatic_recovery
    assert not w.initial_setup_complete
    worker.cancel.assert_called_once_with(firmware_stopped=True)
    assert "X" in [c[0][0] for c in run.arduino.send.call_args_list]
    assert not run.view._start_btn.isEnabled()
    assert w.treatment_panel.phase_label.text() == "SAFETY STOP: Motor stall timeout 14"
    w._show_safety_alert.assert_called_once_with("CONTROLLER FAULT: Motor stall timeout 14")


def test_controller_restart_faults_the_running_treatment(window_run):
    """The Mega rebooted mid-treatment: its tare is gone, so the readout is not live."""
    run = window_run
    w = run.window
    worker = start(run)
    w.status_emit(700, 1900, 1450, 42.0)
    w.on_baseline_changed(True)
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0})
    assert run.view._pressure_caption == "Pressure live"
    run.arduino.send.reset_mock()

    w.safety.on_controller_restart()
    w.status_emit(700, 1900, 1450, 137.5)  # the un-tared, default-factor value

    assert w.protocol_state == "fault" and w._no_automatic_recovery
    assert not w.initial_setup_complete
    worker.cancel.assert_called_once_with(firmware_stopped=True)
    worker.stop.assert_not_called()
    assert [c[0][0] for c in run.arduino.send.call_args_list] == ["X", "X", "HF1"]
    assert run.view._pressure_caption == "Controller fault — last reading stale"
    assert not run.view._start_btn.isEnabled()
    w._show_safety_alert.assert_called_once()
    alert = w._show_safety_alert.call_args[0][0]
    assert alert.startswith("CONTROLLER FAULT: ") and "Reset" in alert


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
        assert [c[0][0] for c in run.arduino.send.call_args_list] == ["X", "X", "HF1"]
        worker.cancel.assert_called_once_with(firmware_stopped=True)
        assert run.window._no_automatic_recovery
        run.window.protocol.stops._stop_phase2()
        run.window.connection._automatic_reset()
        assert [c[0][0] for c in run.arduino.send.call_args_list] == ["X", "X", "HF1"]


def test_restart_button_requests_cleanup_once(window_run, monkeypatch):
    run = window_run
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    run.window.shell.navigate("profile")
    run.window.shell.profile._restart.click()
    assert run.window.restart_requested and run.window._closing
    run.window._on_restart_app()
    assert [c[0][0] for c in run.arduino.send.call_args_list] == ["X", "P0", "HF0"]


def test_restart_button_stops_a_running_treatment(window_run, monkeypatch):
    """Restart App is available mid-treatment and runs the shutdown stop."""
    run = window_run
    worker = start(run)
    assert run.window.protocol_state == "running"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    run.arduino.send.reset_mock()
    run.notices.reset_mock()
    run.window.shell.profile._restart.click()
    assert run.window.restart_requested and run.window._closing
    worker.cancel.assert_called_once_with(firmware_stopped=False)
    assert [c[0][0] for c in run.arduino.send.call_args_list] == ["X", "P0", "HF0"]
    run.notices.assert_not_called()


def test_pressure_caption_and_decimal_render_in_existing_panel(window_run, tmp_path):
    run = window_run
    run.window.on_sensor_diagnostics({"valid": True, "age_ms": 0})
    run.window.on_baseline_changed(True)
    run.window.status_emit(0, 0, 1200, 40.25)
    run.window._refresh_measurement_display()
    assert run.view._pressure_stat._value == "40.2"
    assert run.view._pressure_stat.grab().save(str(tmp_path / "pressure-panel.png"))


def test_next_treatment_requires_recovery_and_an_explicit_patient_choice(window_run):
    run = window_run
    run.window.cloud_patient = {"patient_id": str(uuid4()), "display_name": "Previous patient"}
    run.view.set_outcome("completed", 720)
    run.view.set_cloud_status("Upload failed · record retained")
    run.view.set_busy(True)
    assert not run.view._next_button.isEnabled()
    run.view._next_button.click()
    assert run.window.cloud_patient is not None
    run.view.set_busy(False)
    run.window._refresh_device_presentation()
    run.view._next_button.click()
    assert run.window.shell.patient_modal.isVisible()
    assert run.window.cloud_patient is None
    assert run.view._outcome is None
    assert "Upload failed" in run.view._cloud_status.text()


def test_start_closes_login_but_keeps_video_with_its_stop_strip(window_run):
    run = window_run
    shell = run.window.shell
    shell.login_modal.open_over(shell)
    run.window.set_protocol_state("starting")
    assert shell.login_modal.isHidden()
    assert run.view._estop_btn.isEnabled()


def test_video_during_a_treatment_shows_live_strip_and_stop_uses_screen_stop(
    window_run, monkeypatch,
):
    run = window_run
    shell = run.window.shell
    stops = []
    monkeypatch.setattr(run.window.protocol, "stop_from_view", lambda: stops.append(True))
    run.window.set_protocol_state("running")
    shell.show_video()
    modal = shell.video_modal
    assert modal.isVisible()
    assert run.notices.call_count == 0
    assert modal._treatment_bar.isVisible()
    run.window.set_protocol_state("running")
    assert modal.isVisible(), "a later lifecycle update must not close the video"
    modal._treatment_stop.click()
    assert stops == [True]
    assert modal.isHidden()


def test_fault_closes_an_open_video(window_run):
    run = window_run
    shell = run.window.shell
    run.window.set_protocol_state("running")
    shell.show_video()
    assert shell.video_modal.isVisible()
    run.window.set_protocol_state("stopping")
    assert shell.video_modal.isVisible(), "a stop keeps the STOP strip available"
    run.window.set_protocol_state("fault")
    assert shell.video_modal.isHidden()


def test_upload_failure_opens_nonblocking_window_and_sync_clears_it(window_run):
    run = window_run
    run.window._cloud_bridge.upload_failed.emit("Saved on this device; retrying automatically", False)
    dialog = run.window._upload_error_dialog
    assert dialog.isVisible() and not dialog.isModal()
    assert dialog._retry.isHidden()
    assert run.view._upload_error_button.isVisible()
    dialog.close()
    run.view._upload_error_button.click()
    assert dialog.isVisible()
    run.window._cloud_bridge.status_changed.emit("Treatments synced")
    assert not dialog.isVisible()
    assert not run.view._upload_error_button.isVisible()


def test_permanent_upload_failure_can_retry_from_error_window(window_run):
    run = window_run
    run.window._cloud_bridge.upload_failed.emit("Correct cloud credentials, then retry", True)
    run.window._upload_error_dialog._retry.click()
    run.cloud.retry_pending_async.assert_called_with(DATA_PATHS["PENDING_UPLOADS"], retry_blocked=True)


@pytest.fixture
def patient_flow(window_run, monkeypatch):
    """Run the real dialogs/controller with synthetic staff and device transports."""
    from controllers import patient_controller
    from helpers.staff_client import StaffError

    run = window_run
    run.cloud.enabled = True
    jobs = []
    monkeypatch.setattr(kneespa.threading, "Thread", lambda **kw: SimpleNamespace(
        start=lambda: jobs.append(kw["target"])
    ))
    identity, clinic_id = str(uuid4()), str(uuid4())
    context = {"email": "test@example.com", "clinic": {"id": clinic_id, "name": "Test Clinic"},
               "clinics": [{"id": clinic_id, "name": "Test Clinic"}],
               "permissions": ["patients.edit", "plans.approve"]}
    staff = MagicMock(context={}, cookies=[])
    staff.login.return_value = {"mfa_required": True}
    staff.verify_mfa.return_value = context
    staff.check_context.return_value = context

    def select(clinic):
        assert clinic == clinic_id
        staff.context = context
        return context

    staff.select_clinic.side_effect = select
    staff.request.return_value = {"id": identity, "display_name": "Test Patient",
                                  "status": "active", "version": 3, "plan": {"current": None}}
    monkeypatch.setattr(patient_controller, "StaffClient", lambda _url: staff)
    monkeypatch.delenv("KNEESPA_PATIENT_PORTAL_URL", raising=False)
    response = {"patient_id": identity, "display_name": "Test Patient", "settings": {
        "protocol_number": 4, "duration_min": 12, "max_pressure_lb": 60,
        "max_left_deg": 10, "max_right_deg": 0, "pulse_rate_hz": 2.4,
    }}
    run.cloud.lookup_pin.return_value = response
    controller = run.window.patients
    run.window._show_patient_modal()
    modal = run.window.shell.patient_modal
    assert modal._add.y() < modal._manual.y()
    modal._add.click()
    assert controller.portal.isVisible() and not controller.editor.isVisible()
    assert controller.portal._address.text() == "https://cloud.example/patients/new"
    assert run.window.cloud_patient is None and not jobs
    controller.portal._back.click()
    for digit in "0123":
        modal._keypad._press(digit)
    jobs.pop(0)()
    run.cloud.lookup_pin.assert_called_once_with("0123")
    assert run.window.cloud_patient["patient_id"] == identity
    staff.request.assert_not_called()
    run.view._edit_patient_button.click()
    editor = controller.editor
    assert not editor._save.isEnabled()
    editor._name.setText("Test Patient")
    editor._sign_in.click()
    login = controller.login
    login._email.setText("test@example.com")
    login._password.setText("test-password")
    login._next.click()
    assert not login._password.text()
    jobs.pop(0)()
    assert login._stage == "mfa"
    login._code.setText("123456")
    login._next.click()
    jobs.pop(0)()
    assert login._stage == "clinic"
    assert login._clinics.currentData() is None
    login._clinics.setCurrentIndex(1)
    login._next.click()
    jobs.pop(0)()
    jobs.pop(0)()  # Load the existing cloud profile after clinic selection.
    assert editor._save.isEnabled() and login.isHidden()
    return SimpleNamespace(run=run, controller=controller, editor=editor, login=login,
                           staff=staff, jobs=jobs, response=response, error=StaffError)


def test_qr_registration_pin_lookup_then_staff_mfa_edit_and_cancel(patient_flow):
    flow = patient_flow
    editor, run, staff = flow.editor, flow.run, flow.staff
    assert run.window.cloud_patient["patient_id"] == flow.response["patient_id"]
    assert run.view._patient_label.text() == "Test Patient"
    assert run.view._patient_detail.text() == "Patient linked"
    staff.request.assert_called_once()
    assert staff.request.call_args[0][0] == "GET"
    editor._name.setText("Cancelled edit")
    editor.reject()
    assert run.window.cloud_patient["display_name"] == "Test Patient"
    run.view._edit_patient_button.click()
    flow.jobs.pop(0)()
    editor._name.setText("Updated Patient")
    editor._settings["max_pressure"].set_value(65)
    staff.request.return_value = {"ok": True, "version": 4}
    editor._save.click()
    editor._save.click()
    assert len(flow.jobs) == 1 and not run.view._start_btn.isEnabled()
    flow.jobs.pop(0)()
    assert run.window.cloud_patient["display_name"] == "Updated Patient"
    assert run.view.settings_values()["max_pressure"] == 65
    start(run)
    assert not run.view._edit_patient_button.isEnabled()


def test_uncertain_profile_edit_requires_reload_before_retry(patient_flow):
    flow = patient_flow
    flow.editor._name.setText("Updated Patient")
    flow.staff.request.side_effect = flow.error("unavailable", "Lost response", uncertain=True)
    flow.editor._save.click()
    flow.jobs.pop(0)()
    assert flow.controller.flow.needs_reload
    assert not flow.editor._save.isEnabled()
    assert flow.editor._reload.isVisible()
    flow.staff.request.side_effect = None
    flow.editor._reload.click()
    flow.jobs.pop(0)()
    assert flow.editor._save.isEnabled()
    assert [call[0][0] for call in flow.staff.request.call_args_list] == ["GET", "PATCH", "GET"]


def test_unapproved_cloud_patient_stays_unlinked_after_qr_handoff(patient_flow):
    flow = patient_flow
    flow.editor.reject()
    flow.run.window._show_patient_modal()
    modal = flow.run.window.shell.patient_modal
    modal._add.click()
    flow.controller.portal._back.click()
    flow.staff.request.reset_mock()
    flow.run.cloud.lookup_pin.return_value = {
        "error": "settings_not_supported", "reason": "plan_review_required",
    }
    for _ in range(2):
        for digit in "0123":
            modal._keypad._press(digit)
        flow.jobs.pop(0)()
        assert modal.isVisible()
        assert "correction" in modal._status.text()
    flow.staff.request.assert_not_called()
    assert flow.run.window.cloud_patient is None


def test_logout_discards_staff_session_and_late_patient_result(patient_flow):
    flow = patient_flow
    flow.editor._save.click()
    flow.run.window._on_logout()
    flow.jobs.pop(0)()
    assert flow.run.window.cloud_patient is None
    assert flow.editor.isHidden()
    assert flow.run.window.current_user is None


def test_push_on_the_footplate_reads_negative_on_every_pressure_display(window_run):
    run = window_run
    w = run.window
    w.on_baseline_changed(True)
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0, "signed_lb": -24.5})
    w.status_emit(0, 0, 1200, 24.5)
    w._refresh_measurement_display()
    assert run.view._pressure_stat._value == "−24.5"
    assert w.shell.setup._pos["pressure"]._value.text() == "−24.5 lbs"
    assert w.treatment_panel.pressure_label.text() == "−24.5 lbs"
    # Display only: the stop sequence and the safety checks keep the magnitude.
    assert w.last_measured_pressure == 24.5

    # The signed sample follows its status frame. A change of direction
    # redraws the magnitude already on screen.
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0, "signed_lb": 24.5})
    assert run.view._pressure_stat._value == "24.5"
    assert w.shell.setup._pos["pressure"]._value.text() == "24.5 lbs"
    assert w.treatment_panel.pressure_label.text() == "24.5 lbs"


def test_reading_inside_the_deadband_shows_an_unsigned_zero(window_run):
    run = window_run
    w = run.window
    w.on_baseline_changed(True)
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0, "signed_lb": -0.6})
    w.status_emit(0, 0, 1200, 0.0)
    w._refresh_measurement_display()
    assert run.view._pressure_stat._value == "0.0"
    assert w.shell.setup._pos["pressure"]._value.text() == "0 lbs"


def test_pressure_warning_goes_by_size_whatever_the_direction(window_run):
    run = window_run
    w = run.window
    w.on_baseline_changed(True)
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0, "signed_lb": -110.0})
    w.status_emit(700, 1900, 1450, 110.0)
    assert "Pressure warning threshold exceeded" in w.treatment_panel.phase_label.text()
    assert w.treatment_panel.pressure_label.text() == "−110.0 lbs"


def show_live_pressure(run: SimpleNamespace, pounds: float = 12.0) -> None:
    w = run.window
    w.on_baseline_changed(True)
    w.on_sensor_diagnostics({"valid": True, "age_ms": 0, "signed_lb": pounds})
    w.status_emit(0, 0, 1200, abs(pounds))
    w._refresh_measurement_display()


def pressure_window(run: SimpleNamespace) -> tuple:
    stat = run.view._pressure_stat
    return stat._caption.text(), stat._value


WAITING = ("WAITING FOR PROTOCOL START", "—")
MEASURED = ("MEASURED PRESSURE", "12.0")


def test_idle_window_waits_for_start_only_once_the_release_is_confirmed(window_run):
    run = window_run
    w = run.window
    show_live_pressure(run)
    assert pressure_window(run) == MEASURED  # nothing has confirmed a release yet
    w.connection._on_reset_finished(True)
    show_live_pressure(run)
    assert pressure_window(run) == WAITING
    # Setup keeps its own measured reading: that is where pressure is set by hand.
    assert w.shell.setup._pos["pressure"]._value.text() == "12 lbs"

    worker = start(run)  # the number appears with Start and stays through the release
    assert w.protocol_state == "running" and pressure_window(run) == MEASURED
    worker.signals.finished.emit(True)  # retracted and zeroed by the worker
    assert w.protocol_state == "idle" and pressure_window(run) == WAITING


@pytest.mark.parametrize("ending", ["operator stop", "no-progress stop", "failed run"])
def test_reading_stays_after_a_stop_or_failure_until_the_reset_completes(
        window_run, monkeypatch, ending):
    """A run that ended without a verified release can still hold a load."""
    run = window_run
    w = run.window
    w.connection._on_reset_finished(True)
    worker = start(run)
    show_live_pressure(run)
    if ending == "operator stop":
        run.view.estop_requested.emit()
    elif ending == "no-progress stop":
        w.protocol.stop_without_recovery("Pressure-progress Stop")
    worker.signals.finished.emit(False)
    show_live_pressure(run)
    if ending == "no-progress stop":
        # That stop also drops the zero, and its caption keeps priority.
        assert pressure_window(run) == ("PRESSURE ZERO REQUIRED", "—")
    else:
        assert pressure_window(run) == MEASURED

    reset = MagicMock(signals=ResetWorkerSignals())
    monkeypatch.setattr(connection_manager, "ResetWorker", lambda *args: reset)
    run.pool.start.side_effect = None
    w.reset_arduino()
    assert w.reset_in_progress
    show_live_pressure(run)
    assert pressure_window(run) == MEASURED  # still unconfirmed while the reset runs
    reset.signals.finished.emit(True)
    show_live_pressure(run)
    assert w.protocol_state == "idle" and pressure_window(run) == WAITING


def test_fault_zero_required_and_offline_captions_outrank_the_waiting_text(window_run):
    run = window_run
    w = run.window
    w.connection._on_reset_finished(True)
    show_live_pressure(run)
    assert pressure_window(run) == WAITING
    w.on_baseline_changed(False)
    assert pressure_window(run) == ("PRESSURE ZERO REQUIRED", "—")
    w.on_baseline_changed(True)
    w._measurement_fault = "PRESSURE_LIMIT"
    w._refresh_pressure_state()
    assert "FAULT" in pressure_window(run)[0]
    w._measurement_fault = None
    w.arduino.connected = False
    w._refresh_pressure_state()
    assert pressure_window(run) == ("WAITING FOR CONTROLLER", "—")


def test_setup_pressure_keeps_the_reading_on_the_protocols_page(window_run):
    run = window_run
    w = run.window
    w.connection._on_reset_finished(True)
    show_live_pressure(run)
    assert pressure_window(run) == WAITING
    w.shell.setup._rows["pressure"].slider.set_value(10)
    assert w._on_setup_go("pressure")
    show_live_pressure(run)
    assert pressure_window(run) == MEASURED


def leg_buttons(run: SimpleNamespace) -> tuple:
    """Unlock the Protocols page's leg-length buttons; no reference is needed."""
    buttons = run.view.leg_length_buttons()
    for button in buttons:
        button.setEnabled(True)
    return buttons


def test_protocols_page_leg_length_buttons_send_one_slow_step_each(window_run):
    run = window_run
    w = run.window
    reverse, forward = leg_buttons(run)
    # Nothing measures the leg-length actuator, so no position is shown.
    assert not hasattr(run.view, "_leg_value")
    assert not hasattr(run.view, "set_leg_length_estimate")
    w.leg.move = MagicMock(return_value=True)
    forward.click()
    reverse.click()
    assert [call[0][0] for call in w.leg.move.call_args_list] == ["F+", "F-"]


def test_protocols_page_leg_length_buttons_lock_with_the_setup_controls(window_run):
    run = window_run
    w = run.window
    buttons = leg_buttons(run)
    assert all(button in w.actuator_controls for button in buttons)
    start(run)
    assert w.protocol_state == "running"
    assert not any(button.isEnabled() for button in buttons)
    # A step requested anyway is refused by the leg controller itself.
    run.arduino.send_tracked.reset_mock()
    w._on_treatment_leg_step("fwd")
    run.arduino.send_tracked.assert_not_called()
    assert not w.leg.active


def test_leg_length_step_in_flight_holds_start(window_run):
    """A run never zeroes the load cell while the leg-length actuator moves."""
    run = window_run
    w = run.window
    leg_buttons(run)
    w._on_treatment_leg_step("fwd")
    assert w.leg.active and run.arduino.send_tracked.call_args[0][0] == "F+"
    try:
        run.view._start_btn.setEnabled(True)
        run.view._start_btn.click()
        assert not run.workers and w.protocol_state == "idle"
    finally:
        w.leg.cancel()


@pytest.mark.parametrize("role", ["patient", "service_technician"])
def test_leg_length_steps_are_withheld_by_role(window_run, role):
    run = window_run
    w = run.window
    buttons = leg_buttons(run)
    w.leg.move = MagicMock(return_value=True)
    run.view.set_access_role(role)
    assert not any(button.isEnabled() for button in buttons)
    w.current_user = {"username": "Someone", "status": role}
    w._on_treatment_leg_step("fwd")
    w.leg.move.assert_not_called()
