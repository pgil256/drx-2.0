# tests/unit/test_protocol_controller.py
"""Safety-gate tests for the protocol start/stop state machine.

ProtocolController owns the gates between a touch on START and traction
being applied to a patient: the confirmation dialog, the login check,
the calibration check, the Arduino-readiness check, and the
idle/starting/running/stopping/fault transitions. These are the tests
the audit called out as missing (Phase D, "tests for the safety gates").

Stub-window pattern: a MagicMock window with real values only where the
controller branches on them; no Qt window or Arduino is constructed.
"""
from unittest.mock import MagicMock

import pytest

from controllers.protocol_controller import ProtocolController
from helpers import protocols as protocols_module

pytestmark = pytest.mark.unit


def make_window(state="idle"):
    window = MagicMock()
    window.protocol_state = state
    window.protocol_running = False
    window.current_user = {"username": "Dr", "status": "user"}
    window.config.calibrated = True
    window.config.a_factor = 1900
    window.protocol_number_field.text.return_value = "2"
    window.time_edit.value.return_value = 12
    window.max_pressure_edit.value.return_value = 50
    window.max_left_edit.value.return_value = 10
    window.max_right_edit.value.return_value = 10
    window.current_use_pulse_setting = True
    window.current_pulse_rate = 2.5
    window.protocol_stop_requested = False
    return window


@pytest.fixture
def controller(qtbot):
    window = make_window()
    return ProtocolController(window), window


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
        w.ui.start_button.setEnabled.assert_called_with(False)

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
        w.ui.start_button.setEnabled.assert_called_with(True)

    def test_connection_failure_returns_to_idle(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.return_value = False
        started = []
        monkeypatch.setattr(pc, "start_protocol", lambda: started.append(1))
        pc.start_or_stop()
        assert w.protocol_state == "idle"
        assert not started
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
        monkeypatch.setattr(pc, "start_protocol", lambda: True)
        pc.start_or_stop()
        assert w.protocol_state == "running"
        assert w.protocol_running is True

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

    def test_refused_when_uncalibrated(self, controller):
        """Generated default geometry or a default scale factor must never
        treat a patient."""
        pc, w = controller
        w.config.calibrated = False
        assert pc.start_protocol() is False
        w._warn_uncalibrated.assert_called_once()
        w.threadpool.start.assert_not_called()

    @pytest.mark.parametrize("bad", ["0", "5", "9", "", "abc"])
    def test_invalid_protocol_number_rejected(self, controller, bad):
        pc, w = controller
        w.protocol_number_field.text.return_value = bad
        assert pc.start_protocol() is False
        w._show_timed_error.assert_called_once()
        w.threadpool.start.assert_not_called()

    def test_successful_start_builds_worker_with_seeded_limits(
        self, controller, monkeypatch
    ):
        """The worker receives the clamp-relevant parameters exactly as
        seeded (max_left negated for the worker convention) and rollback
        seeds are initialized before the worker starts."""
        pc, w = controller
        worker_cls = MagicMock()
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)

        assert pc.start_protocol() is True

        worker_cls.assert_called_once_with(
            1900, "2", 50, -10, 10, 12, True,
            ser=w.arduino, config=w.config, pulse_rate=2.5,
        )
        w.threadpool.start.assert_called_once_with(worker_cls.return_value)
        # Mid-protocol-change rollback seeds (Cancel used to TypeError).
        assert w._prev_pressure == 50
        assert w._prev_left == 10
        assert w._prev_right == 10
        # Banner shows the run: max pressure + duration in seconds.
        w.treatment_panel.set_running.assert_called_once_with(50, 720)

    def test_worker_failure_signal_wired_to_reset(self, controller, monkeypatch):
        """protocols 2/3 emit reset_needed after a failed pulse phase; it
        must be connected (it used to go nowhere)."""
        pc, w = controller
        worker_cls = MagicMock()
        monkeypatch.setattr(protocols_module, "Protocols", worker_cls)
        pc.start_protocol()
        worker = worker_cls.return_value
        worker.signals.reset_needed.connect.assert_called_once_with(
            w.reset_arduino
        )
        worker.signals.finished.connect.assert_called_once_with(
            pc.protocol_completed
        )


# ----- start gate re-check after the confirm dialog -----
class TestStartRecheck:
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

    def test_worker_failure_logs_and_returns_to_idle(self, controller):
        pc, w = controller
        w.protocol_state = "running"
        pc.protocol_completed(False)
        assert w.protocol_state == "idle"
        w.treatment_panel.set_idle.assert_called_once()
        w._show_timed_error.assert_not_called()
        w._show_safety_alert.assert_not_called()
        w.logger.warning.assert_called_once_with(
            "Treatment ended early; returning to idle"
        )

    def test_user_stop_stays_gated_until_reset_without_fault_alert(self, controller):
        pc, w = controller
        w.protocol_state = "stopping"
        w.protocol_stop_requested = True
        pc.protocol_completed(False)
        assert w.protocol_state == "stopping"
        assert w.protocol_stop_requested is True
        w._show_safety_alert.assert_not_called()

    def test_start_exception_recovers_state(self, controller, monkeypatch):
        pc, w = controller
        monkeypatch.setattr(pc, "confirm_start", lambda: True)
        w.ensure_arduino_connection.side_effect = RuntimeError("boom")
        pc.start_or_stop()
        assert w.protocol_state == "idle"
        assert w.protocol_running is False
        assert w.worker is None
