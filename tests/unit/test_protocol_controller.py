# tests/unit/test_protocol_controller.py
"""Safety-gate tests for the protocol start/stop state machine.

ProtocolController owns the gates between a touch on START and traction
being applied to a patient: the confirmation dialog, the login check,
the calibration check, the Arduino-readiness check, and the
idle/starting/running/stopping/fault transitions. These are the tests
the audit called out as missing (Phase D, "tests for the safety gates").

The shared window facade has explicit state and bounded collaborator APIs;
no Qt window or Arduino is constructed. Constructor coverage lives in Gate W.
"""
from functools import partial
from unittest.mock import MagicMock, call

import pytest
from PyQt5.QtCore import QObject, pyqtSignal
from pytestqt.qtbot import QtBot

from controllers.protocol_controller import ProtocolController
from controllers.safety_monitor import SafetyMonitor
from helpers import protocols as protocols_module
from kneespa import KneeSpa
from fixtures.controllers import make_window, make_worker_double
from ui.widgets.treatment_status_panel import TreatmentStatusPanel

pytestmark = pytest.mark.unit


class _RetiredDialog:
    """Inert legacy dialog, matching the removed application's placeholder."""

    def isVisible(self) -> bool:
        return False

    def update_pressure(self, pressure: float) -> None:
        pass


class _StatusSource(QObject):
    """Real Qt status signal without a serial connection or reader thread."""

    status_emit = pyqtSignal(int, int, int, float)


@pytest.fixture
def controller(qtbot):
    window = make_window()
    return ProtocolController(window), window


@pytest.mark.parametrize("recovering", [False, True])
def test_late_treatment_failure_cannot_cancel_operator_reset(controller, recovering):
    pc, window = controller
    session = object()
    pc._session = session
    window.safety = MagicMock(spec_set=SafetyMonitor)
    window.reset_in_progress = recovering

    pc._on_operation_failed("Pressure sensor timeout", session)

    if recovering:
        window.safety.on_controller_fault.assert_not_called()
    else:
        window.safety.on_controller_fault.assert_called_once_with(
            {"reason": "Pressure sensor timeout"}
        )


# ----- set_state: single source of truth -----
class TestSetState:
    @pytest.mark.parametrize("state,running", [
        ("idle", False),
        ("starting", True),
        ("running", True),
        ("stopping", True),
        ("fault", False),
    ])
    def test_protocol_running_tracks_state(self, controller, state, running):
        pc, w = controller
        pc.set_state(state)
        assert w.protocol_state == state
        assert w.protocol_running is running

    def test_starting_disables_start_button(self, controller):
        """No double-start: the button is dead while a start is in flight."""
        pc, w = controller
        pc.set_state("starting")
        w.shell.treatment.set_busy.assert_called_with(True)

    def test_idle_shows_idle_banner(self, controller):
        pc, w = controller
        pc.set_state("idle")
        w.treatment_panel.set_idle.assert_called_once()

    def test_stopping_shows_stopping_banner(self, controller):
        pc, w = controller
        pc.set_state("stopping")
        w.treatment_panel.set_stopping.assert_called_once()


# ----- navigation gating -----
class TestBlockNav:
    @pytest.mark.parametrize("state", ["starting", "running", "stopping"])
    def test_blocks_while_active(self, controller, state):
        pc, w = controller
        w.protocol_state = state
        assert pc.block_nav() is True
        w._show_timed_error.assert_called_once()

    @pytest.mark.parametrize("state", ["idle", "fault"])
    def test_allows_when_inactive(self, controller, state):
        pc, w = controller
        w.protocol_state = state
        assert pc.block_nav() is False


# ----- start_or_stop: the gate chain -----
class TestStartGates:
    def test_declined_confirmation_stays_idle(self, controller, monkeypatch):
        """Cancel on the confirm dialog must not touch the connection or
        the protocol; the button comes back."""
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: False)
        pc.start_or_stop()
        assert w.protocol_state == "idle"
        w.ensure_arduino_connection.assert_not_called()
        w.shell.treatment.set_busy.assert_called_with(False)
        w.protocol_timer.start.assert_not_called()

    def test_connection_failure_returns_to_idle(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = False
        worker_cls = MagicMock(return_value=make_worker_double())
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)
        pc.start_or_stop()
        assert w.protocol_state == "idle"
        worker_cls.assert_not_called()
        w.threadpool.start.assert_not_called()
        w.protocol_timer.start.assert_not_called()
        w._show_timed_error.assert_called_once()

    def test_start_protocol_failure_returns_to_idle(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = True
        monkeypatch.setattr(pc, "start_protocol", lambda: False)
        pc.start_or_stop()
        assert w.protocol_state == "idle"

    def test_successful_start_reaches_running(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = True
        worker_cls = MagicMock(return_value=make_worker_double())
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)
        pc.start_or_stop()
        assert w.protocol_state == "running"
        assert w.protocol_running is True
        w.ensure_arduino_connection.assert_called_once()
        w.threadpool.start.assert_called_once_with(worker_cls.return_value)

    def test_fault_state_requires_recovery_before_restart(self, controller, monkeypatch):
        pc, w = controller
        w.protocol_state = "fault"
        confirmed = []
        monkeypatch.setattr(
            pc, "confirm_start", lambda: confirmed.append(1) or False
        )
        pc.start_or_stop()
        assert not confirmed
        assert w.protocol_state == "fault"
        w._show_timed_error.assert_called_once()

    def test_active_state_routes_to_stop(self, controller, monkeypatch):
        pc, w = controller
        w.protocol_state = "running"
        stopped = []
        monkeypatch.setattr(pc, "stop_protocol", lambda: stopped.append(1))
        pc.start_or_stop()
        assert stopped

    @pytest.mark.parametrize("answer,expected", [("No", False), ("Yes", True)])
    def test_confirm_start_honors_dialog_answer(
        self, controller, monkeypatch, answer, expected
    ):
        """confirm_start itself: only an explicit Yes lets the start pass."""
        pc, w = controller
        from controllers import protocol_controller as pc_module

        class StubMessageBox:
            Yes = 0x4000   # ints so QMessageBox.Yes | QMessageBox.No works
            No = 0x10000

            @classmethod
            def question(cls, *args, **kwargs):
                return getattr(cls, answer)

        monkeypatch.setattr(pc_module, "QMessageBox", StubMessageBox)
        assert pc.confirm_start() is expected


# ----- start_protocol: the last line of defense -----
class TestStartProtocolGates:
    def test_denied_when_not_logged_in(self, controller):
        pc, w = controller
        w.current_user = None
        assert pc.start_protocol() is False
        w._show_timed_error.assert_called_once()
        w.protocol_timer.start.assert_not_called()

    def test_refused_when_uncalibrated(self, controller):
        """Generated default geometry or a default scale factor must never
        treat a patient."""
        pc, w = controller
        w.config.calibrated = False
        assert pc.start_protocol() is False
        w._warn_uncalibrated.assert_called_once()
        w.threadpool.start.assert_not_called()
        w.protocol_timer.start.assert_not_called()

    @pytest.mark.parametrize("bad", ["0", "5", "9", "", "abc"])
    def test_invalid_protocol_number_rejected(self, controller, bad):
        pc, w = controller
        w.protocol_value = bad
        assert pc.start_protocol() is False
        w._show_timed_error.assert_called_once()
        w.threadpool.start.assert_not_called()
        w.protocol_timer.start.assert_not_called()

    def test_successful_start_builds_worker_with_seeded_limits(
        self, controller, monkeypatch
    ):
        """The worker receives the clamp-relevant parameters exactly as
        seeded (max_left negated for the worker convention)."""
        pc, w = controller
        worker_cls = MagicMock(return_value=make_worker_double())
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)

        assert pc.start_protocol() is True

        worker_cls.assert_called_once_with(
            1900, "2", 50, -10, 10, 12, True,
            ser=w.arduino, config=w.config, pulse_rate=2.4,
            motor_speeds=w.shell.treatment.settings_values(),
        )
        w.threadpool.start.assert_called_once_with(worker_cls.return_value)
        # Banner shows the run: max pressure + duration in seconds.
        w.treatment_panel.set_running.assert_called_once_with(50, 720)

    def test_worker_failure_signal_wired_to_fault(self, controller, monkeypatch):
        """protocols 2/3 emit reset_needed after a failed pulse phase; it
        must be connected (it used to go nowhere)."""
        pc, w = controller
        worker_cls = MagicMock(return_value=make_worker_double())
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)
        pc.start_protocol()
        worker = worker_cls.return_value
        failure = worker.signals.operation_failed.connect.call_args.args[0]
        finished = worker.signals.finished.connect.call_args.args[0]
        assert failure.func == pc._on_operation_failed
        worker.signals.reset_needed.connect.assert_not_called()
        assert finished.func == pc.protocol_completed
        assert failure.keywords["session"] is pc._session
        assert finished.keywords["session"] is pc._session


class TestTreatmentWiring:
    def test_worker_construction_failure_does_not_start_timer(
        self, controller: tuple, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failure before worker setup cannot start the countdown or dispatch."""
        pc, w = controller
        worker_cls = MagicMock(side_effect=RuntimeError("worker setup failed"))
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)

        assert pc.start_protocol() is False

        w.protocol_timer.start.assert_not_called()
        w.threadpool.start.assert_not_called()
        w._show_timed_error.assert_called_once_with("Protocol Error: worker setup failed")

    @pytest.mark.parametrize("legacy_dialogs", [False, True])
    def test_timer_waits_for_prepared_signal(self, controller, monkeypatch, legacy_dialogs):
        pc, w = controller
        if legacy_dialogs:
            w.timer_dialog = _RetiredDialog()
        worker = make_worker_double()
        monkeypatch.setattr(protocols_module, "Protocols", lambda *a, **kw: worker)
        assert pc.start_protocol()
        w.protocol_timer.start.assert_not_called()
        w.threadpool.start.assert_called_once_with(worker)
        prepared = worker.signals.prepared.connect.call_args.args[0]
        prepared(1000, 2000)
        w.protocol_timer.start.assert_called_once()
        assert w.protocol_start_time == 1000

    def test_repeated_starts_preserve_only_active_pressure_receivers(
        self, controller: tuple, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
    ) -> None:
        """Starts keep public worker signals and the live safety route intact."""
        pc, w = controller
        w.pressure_dialog = _RetiredDialog()
        w.arduino = _StatusSource()
        w.config.CMarks = {"0.0": 100, "10.0": 200, "20.0": 300}
        w.config.BMarks = {"0.0": 0, "10.0": 100}
        w.initial_setup_complete = True
        w.safety = SafetyMonitor(w)
        w.treatment_panel = TreatmentStatusPanel()
        qtbot.addWidget(w.treatment_panel)
        w.arduino.status_emit.connect(partial(KneeSpa.status_emit, w))
        workers = []
        pressures = []

        def construct_worker(*args: object, **kwargs: object) -> MagicMock:
            worker = make_worker_double()
            worker.signals = protocols_module.WorkerSignals()
            worker.signals.pressure_emit.connect(pressures.append)
            workers.append(worker)
            return worker

        monkeypatch.setattr(protocols_module, "Protocols", construct_worker)
        for pressure in (42.0, 43.0, 44.0):
            assert pc.start_protocol() is True
            worker = workers[-1]
            assert worker.signals.receivers(worker.signals.pressure_emit) == 1
            assert w.arduino.receivers(w.arduino.status_emit) == 1
            worker.signals.pressure_emit.emit(pressure)
            w.arduino.status_emit.emit(500, 0, 150, pressure)
            assert w.last_measured_pressure == pressure
            w.shell.treatment.set_pressure.assert_called_with(pressure)
            w.shell.treatment.set_angle.assert_called_with(pytest.approx(5.0))
            assert w.treatment_panel.pressure_label.text() == f"{pressure:.1f} lbs"
            worker.signals.finished.emit(True)
            assert w.protocol_state == "idle"
            assert w.arduino.receivers(w.arduino.status_emit) == 1

        assert pressures == [42.0, 43.0, 44.0]
        assert w.shell.treatment.set_pressure.call_count == 3
        # The same live route still runs SafetyMonitor's limit handling.
        w.arduino.status_emit.emit(500, 0, 150, 200.0)
        w._show_safety_alert.assert_called_once()
        assert "Pressure warning threshold exceeded" in w.treatment_panel.phase_label.text()

    @pytest.mark.parametrize("elapsed,remaining", [(1, 719), (720, 0), (900, 0)])
    def test_countdown_updates_banner_without_legacy_dialog(
        self, controller: tuple, monkeypatch: pytest.MonkeyPatch,
        qtbot: QtBot, elapsed: int, remaining: int,
    ) -> None:
        """Countdown keeps its clamping and expiry behavior after dialog removal."""
        pc, w = controller
        w.protocol_start_time = 1000
        w.protocol_duration = 720
        w.treatment_panel = TreatmentStatusPanel()
        qtbot.addWidget(w.treatment_panel)
        monkeypatch.setattr(
            "controllers.protocol_controller.time.time", lambda: 1000 + elapsed
        )

        pc.update_protocol_time()

        assert w.treatment_panel.time_label.text() == (
            f"{remaining // 60}:{remaining % 60:02d} left"
        )
        if remaining == 0:
            w.protocol_timer.stop.assert_called_once()
            assert w.protocol_start_time is None
        else:
            w.protocol_timer.stop.assert_not_called()
            assert w.protocol_start_time == 1000


# ----- start gate re-check after the confirm dialog -----
class TestStartRecheck:
    def test_declining_after_fault_does_not_enable_start(self, controller, monkeypatch):
        pc, w = controller

        def decline_with_fault():
            pc.set_state("fault")
            return False

        monkeypatch.setattr(pc, "confirm_start", decline_with_fault)
        pc.start_or_stop()

        assert w.protocol_state == "fault"
        w.shell.treatment.set_busy.assert_called_with(True)

    @pytest.mark.parametrize("connected", [False, True])
    def test_fault_during_connection_check_is_preserved(
        self, controller, monkeypatch, connected
    ):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        start = MagicMock(return_value=True)
        monkeypatch.setattr(pc, "start_protocol", start)

        def verify_with_fault():
            pc.set_state("fault")
            return connected

        w.ensure_arduino_connection.side_effect = verify_with_fault
        pc.start_or_stop()

        start.assert_not_called()
        assert w.protocol_state == "fault"
        w.shell.treatment.set_busy.assert_called_with(True)

    def test_initial_progress_is_not_lost_or_overwritten(self, controller, monkeypatch):
        pc, w = controller
        worker = make_worker_double()
        worker.signals = protocols_module.WorkerSignals()
        monkeypatch.setattr(protocols_module, "Protocols", lambda *a, **kw: worker)

        def dispatch(_worker):
            worker.signals.progress.emit("Pressure ramp")

        w.threadpool.start.side_effect = dispatch
        assert pc.start_protocol() is True
        w.treatment_panel.set_phase.assert_called_with("PRESSURE RAMP")
        w.treatment_panel.set_phase.assert_called_with("PRESSURE RAMP")

    def test_connection_exception_does_not_clear_fault(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)

        def verify_with_fault():
            pc.set_state("fault")
            raise RuntimeError("connection interrupted")

        w.ensure_arduino_connection.side_effect = verify_with_fault
        pc.start_or_stop()

        assert w.protocol_state == "fault"
        w.shell.treatment.set_busy.assert_called_with(True)

    def test_reset_during_connection_check_keeps_start_disabled(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        start = MagicMock(return_value=True)
        monkeypatch.setattr(pc, "start_protocol", start)

        def verify_with_reset():
            w.reset_in_progress = True
            return True

        w.ensure_arduino_connection.side_effect = verify_with_reset
        pc.start_or_stop()

        start.assert_not_called()
        assert w.protocol_state == "idle"
        w.shell.treatment.set_busy.assert_called_with(True)

    def test_fault_during_confirm_aborts_start(self, controller, monkeypatch):
        """A firmware fault that lands while the confirm dialog's nested event
        loop runs must not be overridden by the 'starting' transition."""
        pc, w = controller
        w.reset_in_progress = False

        def confirm_with_fault():
            w.protocol_state = "fault"
            return True

        monkeypatch.setattr(pc, "confirm_start", confirm_with_fault)
        started = []
        monkeypatch.setattr(pc, "start_protocol", lambda: started.append(1) or True)

        pc.start_or_stop()

        assert started == []
        assert w.protocol_state == "fault"

    def test_reset_during_confirm_aborts_start(self, controller, monkeypatch):
        pc, w = controller
        w.reset_in_progress = False

        def confirm_with_reset():
            w.reset_in_progress = True
            return True

        monkeypatch.setattr(pc, "confirm_start", confirm_with_reset)
        started = []
        monkeypatch.setattr(pc, "start_protocol", lambda: started.append(1) or True)

        pc.start_or_stop()

        assert started == []
        assert w.protocol_state == "idle"

    def test_running_not_forced_after_immediate_worker_failure(
        self, controller, monkeypatch
    ):
        """start_protocol pumps events; if the worker's finished(False) is
        processed inside it the machine is already idle and must stay idle."""
        pc, w = controller
        w.reset_in_progress = False
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = True

        def start_then_fail():
            pc.set_state("idle")
            return True

        monkeypatch.setattr(pc, "start_protocol", start_then_fail)

        pc.start_or_stop()

        assert w.protocol_state == "idle"

    def test_clean_start_reaches_running(self, controller, monkeypatch):
        pc, w = controller
        w.reset_in_progress = False
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = True
        monkeypatch.setattr(pc, "start_protocol", lambda: True)

        pc.start_or_stop()

        assert w.protocol_state == "running"


# ----- release before the recovery reset -----
class TestReleaseBeforeReset:
    def test_reset_waits_while_load_present(self, controller):
        pc, w = controller
        w.last_measured_pressure = 30.0
        pc._stop_phase3()
        w.reset_arduino.assert_not_called()

    def test_reset_runs_once_load_cleared(self, controller):
        pc, w = controller
        w.last_measured_pressure = 1.0
        pc._stop_phase3()
        w.reset_arduino.assert_called_once()

    def test_reset_runs_immediately_without_telemetry(self, controller):
        pc, w = controller
        w.last_measured_pressure = None  # no status frame ever arrived
        pc._stop_phase3()
        w.reset_arduino.assert_called_once()

    def test_reset_runs_after_bounded_wait(self, controller):
        import time as _time

        pc, w = controller
        w.last_measured_pressure = 30.0
        pc._reset_after_release(started=_time.time() - pc.RELEASE_WAIT_S - 1)
        w.reset_arduino.assert_called_once()

    def test_emergency_stop_phase3_also_waits(self, controller):
        pc, w = controller
        w.last_measured_pressure = 30.0
        pc._emergency_stop_phase3()
        w.reset_arduino.assert_not_called()


# ----- UI pause anchor lifecycle -----
class TestPauseAnchor:
    def test_emergency_stop_clears_pause_anchor(self, controller):
        pc, w = controller
        w._paused_at = 1234.0
        pc.emergency_stop_clicked(None)
        assert w._paused_at is None

    def test_completion_clears_pause_anchor(self, controller):
        pc, w = controller
        w._paused_at = 1234.0
        pc.protocol_completed(True)
        assert w._paused_at is None


# ----- panel stop -----
class TestPanelStop:
    @pytest.mark.parametrize(
        "state", ["idle", "starting", "running", "stopping", "fault"]
    )
    def test_panel_stop_always_uses_emergency_stop(
        self, controller, monkeypatch, state
    ):
        pc, w = controller
        w.protocol_state = state
        events = []
        monkeypatch.setattr(
            pc,
            "emergency_stop_clicked",
            lambda event: events.append(event),
        )

        pc.panel_stop_requested()

        assert events == [None]


class TestStopProtocol:
    def test_stop_sets_stopping_and_stops_actuators(self, controller):
        pc, w = controller
        pc.stop_protocol()
        assert w.protocol_state == "stopping"
        w.stop_actuators.assert_called_once()


class TestCompletionOutcomes:
    def test_existing_safety_fault_is_not_cleared_or_duplicated(self, controller):
        pc, w = controller
        w.protocol_state = "fault"

        pc.protocol_completed(False)

        assert w.protocol_state == "fault"
        w.treatment_panel.set_idle.assert_not_called()
        w._show_timed_error.assert_not_called()
        w._show_safety_alert.assert_not_called()

    def test_worker_failure_remains_faulted(self, controller):
        pc, w = controller
        w.protocol_state = "running"
        pc.protocol_completed(False)
        assert w.protocol_state == "fault"
        w.treatment_panel.set_idle.assert_not_called()
        w._show_timed_error.assert_not_called()
        w._show_safety_alert.assert_not_called()
        assert not w.initial_setup_complete

    @pytest.mark.parametrize("success", [False, True])
    def test_user_stop_stays_gated_until_reset_without_fault_alert(self, controller, success):
        pc, w = controller
        w.protocol_state = "stopping"
        w.protocol_stop_requested = True
        from helpers.treatment_session import TreatmentSession
        pc._session = TreatmentSession("test-patient", 2, 720)
        pc.protocol_completed(success)
        assert w.protocol_state == "stopping"
        assert w.protocol_stop_requested is True
        w._show_safety_alert.assert_not_called()
        record = w.cloud_client.post_treatment_async.call_args.args[0]
        assert record["outcome"] == "stopped"

    def test_start_exception_recovers_state(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.side_effect = RuntimeError("boom")
        pc.start_or_stop()
        assert w.protocol_state == "idle"
        assert w.protocol_running is False
        assert w.worker is None
