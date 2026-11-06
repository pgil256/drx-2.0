"""L1: a failing UI update is logged and never propagates."""

from unittest.mock import MagicMock

import pytest

import kneespa
import ui.presentation as presentation
from controllers.protocol_controller import ProtocolController
from fixtures.controllers import make_stub, make_window
from kneespa import KneeSpa
from ui.presentation import present

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def fresh_failures():
    presentation._failing.clear()
    yield
    presentation._failing.clear()


def broken():
    raise RuntimeError("widget gone")


def logged_targets(logger):
    return [c[0][1] for c in logger.exception.call_args_list]


class TestPresent:
    def test_success_runs_the_update(self):
        logger, calls = MagicMock(), []
        assert present(logger, "badge", lambda: calls.append(1)) is True
        assert calls == [1]
        logger.exception.assert_not_called()

    def test_failure_is_logged_and_swallowed(self):
        logger = MagicMock()
        assert present(logger, "badge", broken) is False
        logger.exception.assert_called_once_with("Could not update %s", "badge")

    def test_missing_widget_attribute_is_caught(self):
        logger, shell = MagicMock(), object()
        assert present(logger, "phase", lambda: shell.treatment.set_phase("x")) is False
        assert logged_targets(logger) == ["phase"]

    def test_a_repeating_failure_logs_once_until_it_recovers(self):
        logger = MagicMock()
        for _ in range(5):
            present(logger, "progress", broken)
        assert logged_targets(logger) == ["progress"]
        present(logger, "progress", lambda: None)
        present(logger, "progress", broken)
        assert logged_targets(logger) == ["progress", "progress"]

    def test_targets_are_tracked_separately(self):
        logger = MagicMock()
        present(logger, "progress", broken)
        present(logger, "phase", broken)
        assert logged_targets(logger) == ["progress", "phase"]


class TestProtocolControllerPresentation:
    def test_busy_state_failure_is_logged(self, qtbot):
        window = make_window()
        window.shell.treatment.set_busy.side_effect = RuntimeError("busy")
        ProtocolController(window).set_busy(True)
        assert "treatment busy state" in logged_targets(window.logger)

    def test_stop_from_view_presents_phase_even_if_run_state_fails(
            self, qtbot, monkeypatch):
        window = make_window("running")
        controller = ProtocolController(window)
        monkeypatch.setattr(controller, "emergency_stop_clicked", MagicMock())
        window.shell.treatment.set_run_state.side_effect = RuntimeError("run state")
        controller.stop_from_view()
        controller.emergency_stop_clicked.assert_called_once()
        window.shell.treatment.set_phase.assert_called_with("stopped")
        assert "treatment run state" in logged_targets(window.logger)

    def test_pause_still_pauses_the_worker_when_the_view_fails(self, qtbot):
        window = make_window("running")
        window.protocol_running = True
        window.shell.treatment.set_phase.side_effect = RuntimeError("phase")
        ProtocolController(window).pause()
        window.worker.pause.assert_called_once()
        assert window._paused_at is not None
        assert "treatment phase" in logged_targets(window.logger)


class TestWindowPresentation:
    def test_progress_failure_does_not_stop_the_countdown(self):
        stub = make_stub()
        stub.protocol_start_time = 1.0
        stub.shell.treatment.set_progress.side_effect = RuntimeError("ring")
        KneeSpa.update_protocol_time(stub)
        stub.protocol.update_protocol_time.assert_called_once()
        assert logged_targets(stub.logger) == ["treatment progress"]

    def test_badge_failure_still_refreshes_device_status(self):
        stub = make_stub()
        stub.shell.setup.set_arduino_connected.side_effect = RuntimeError("badge")
        stub._refresh_device_presentation = MagicMock()
        KneeSpa._set_badge(stub, True)
        stub._refresh_device_presentation.assert_called_once()
        assert logged_targets(stub.logger) == ["Setup connection badge"]

    def test_logout_logs_a_failed_unlink_and_still_logs_out(self, monkeypatch):
        stub = make_stub()
        stub.current_user = {"username": "Dr"}
        monkeypatch.setattr(kneespa, "unlink_patient", MagicMock(side_effect=RuntimeError("x")))
        KneeSpa._on_logout(stub)
        stub.logger.exception.assert_called_once_with("Could not unlink the patient at logout")
        stub.shell.logout.assert_called_once()
        assert stub.current_user is None

    def test_unreadable_protocol_choice_is_logged_and_kept(self):
        stub = make_stub()
        stub.protocol_value = "3"
        stub.shell.treatment.selected_protocol.side_effect = RuntimeError("picker")
        KneeSpa._seed_modern_run_inputs(stub)
        assert stub.protocol_value == "3"
        assert stub.logger.exception.call_args[0][0].startswith(
            "Could not read the selected protocol")

    def test_unreadable_settings_are_logged(self):
        stub = make_stub()
        stub.shell.treatment.settings_values.side_effect = RuntimeError("sliders")
        KneeSpa._seed_modern_run_inputs(stub)
        stub.logger.exception.assert_called_once_with("Could not read the Treatment settings")
