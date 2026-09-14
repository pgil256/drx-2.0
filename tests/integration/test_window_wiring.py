"""Gate W: real KneeSpa construction and treatment signals with offline boundaries.

Only hardware/network execution and the worker scheduler are controlled. The
window, configuration, CSV/auth, shell, controllers, wiring and timers are real.
Queued single shots are delivered explicitly to simulate nested/late events.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterator
from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import QEvent, QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox

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
    monkeypatch.setattr(kneespa, "CloudClient", lambda: cloud)
    smtp = MagicMock(side_effect=AssertionError("Unexpected SMTP connection"))
    monkeypatch.setattr(kneespa.smtplib, "SMTP_SSL", smtp)
    arduino = MagicMock(spec=Arduino)
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
    window.threadpool = pool

    def dispatch(worker: object) -> None:
        events.append("dispatch")
        assert window.protocol_timer.isActive()
        assert worker.signals.receivers(worker.signals.finished) == 1
        assert worker.signals.receivers(worker.signals.progress) == 1
        assert worker.signals.receivers(worker.signals.reset_needed) == 1

    pool.start.side_effect = dispatch
    run = SimpleNamespace(window=window, view=window.shell.treatment, arduino=arduino,
                          cloud=cloud, events=events, pending=pending, timers=timers,
                          workers=workers, pool=pool, notices=notices, dispatch=dispatch)
    yield run
    for timer in window.findChildren(QTimer):
        timer.stop()
    window.close()
    assert not window.protocol_timer.isActive()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    pending.clear()
    smtp.assert_not_called()


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
    assert len(run.timers) == 1
    assert w.protocol_timer is run.timers[-1]
    assert w.protocol_timer.parent() is w
    assert w.protocol_timer.interval() == 1000
    assert w.protocol_timer.receivers(w.protocol_timer.timeout) == 1
    assert not w.protocol_timer.isActive()
    run.view.set_settings({"duration": 12})
    start(run)
    assert run.events[:3] == ["worker", "timer", "dispatch"]
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
    assert run.window.protocol_state == "idle"
    assert not run.window.protocol_timer.isActive()
    assert run.view._start_btn.isEnabled() and not run.view._pause_btn.isEnabled()
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
