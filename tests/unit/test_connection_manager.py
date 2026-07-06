# tests/unit/test_connection_manager.py
"""Tests for the extracted Arduino connection lifecycle."""
import pytest
from unittest.mock import MagicMock

from controllers.connection_manager import ConnectionManager


class StubWindow:
    def __init__(self):
        self.arduino = MagicMock()
        self.config = MagicMock()
        self.config.AMarks = {"0.0": 160}
        self.config.BMarks = {"0.0": 1900}
        self.config.calibration = -28369.0
        self.config.scale_calibrated = True
        self.reset_in_progress = False
        self.initial_setup_complete = False
        self.loading_spinner = MagicMock()
        self.start_button = MagicMock()
        self.threadpool = MagicMock()
        self.logger = MagicMock()
        self.errors = []
        self.reset_readings = 0
        self.leg_resets = 0

    def _show_timed_error(self, message):
        self.errors.append(message)

    def disable_actuator_controls(self):
        pass

    def reset_setup_readings(self):
        self.reset_readings += 1

    def reset_extra_button_clicked(self):
        self.leg_resets += 1


@pytest.fixture
def manager(qtbot):
    window = StubWindow()
    return ConnectionManager(window), window


@pytest.mark.unit
class TestResetGating:
    def test_overlapping_reset_ignored(self, manager):
        cm, w = manager
        w.reset_in_progress = True
        cm.reset_arduino()
        assert not w.threadpool.start.called

    def test_reset_without_arduino_fails_cleanly(self, manager):
        cm, w = manager
        w.arduino = None
        cm.reset_arduino()
        assert w.reset_in_progress is False
        assert any("not initialized" in e for e in w.errors)

    def test_reset_starts_worker_and_sets_flags(self, manager):
        cm, w = manager
        cm.reset_arduino()
        assert w.reset_in_progress is True
        assert w.initial_setup_complete is False
        assert w.threadpool.start.called
        assert w.reset_readings == 1

    def test_reset_finished_success(self, manager):
        cm, w = manager
        w.reset_in_progress = True
        cm._on_reset_finished(True)
        assert w.reset_in_progress is False
        assert w.initial_setup_complete is True
        w.start_button.setEnabled.assert_called_with(True)

    def test_reset_finished_failure_reenables_start(self, manager):
        cm, w = manager
        w.reset_in_progress = True
        cm._on_reset_finished(False)
        assert w.reset_in_progress is False
        assert w.initial_setup_complete is False
        w.start_button.setEnabled.assert_called_with(True)
        assert any("failed" in e.lower() for e in w.errors)


@pytest.mark.unit
class TestCalibrationPushes:
    def test_zero_mark_uses_delimited_form(self, manager):
        """Regression: this copy still sent the legacy fixed-width L5,
        which truncates 4-digit marks (1900 -> 190)."""
        cm, w = manager
        cm.send_zero_mark()
        w.arduino.send.assert_called_once_with("L5|160|1900")

    def test_calibration_sent_when_plausible(self, manager):
        cm, w = manager
        cm.send_calibration()
        w.arduino.send.assert_called_once_with("L0-28369.0")

    def test_implausible_factor_refused(self, manager):
        cm, w = manager
        w.config.scale_calibrated = False
        w.config.calibration = 1.0
        cm.send_calibration()
        assert not w.arduino.send.called


@pytest.mark.unit
class TestEnsureConnection:
    """The readiness gate every protocol start must pass (Phase D
    safety-gate tests). The slow paths stub out setup_arduino and
    time.sleep so no real port or 1.5 s of settling is involved."""

    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        import controllers.connection_manager as cm_module

        monkeypatch.setattr(cm_module.time, "sleep", lambda s: None)

    def test_verified_connection_passes_without_reset(self, manager):
        cm, w = manager
        w.arduino.connected = True
        w.arduino.verify_connection.return_value = True
        assert cm.ensure_arduino_connection() is True
        w.arduino.disconnect.assert_not_called()

    def test_unresponsive_connection_reconnects(self, manager, monkeypatch):
        """connected but not answering: disconnect, GPIO to safe state,
        reconnect, then re-push zero marks + calibration."""
        cm, w = manager
        w.arduino.connected = True
        w.arduino.verify_connection.return_value = False
        w.setup_gpio = lambda: setattr(w, "gpio_reset", True)
        monkeypatch.setattr(cm, "setup_arduino", lambda auto_reset: True)

        assert cm.ensure_arduino_connection() is True

        w.arduino.disconnect.assert_called_once()
        assert w.gpio_reset
        sent = [c.args[0] for c in w.arduino.send.call_args_list]
        assert sent == ["L5|160|1900", "L0-28369.0"]

    def test_no_arduino_object_reconnects(self, manager, monkeypatch):
        cm, w = manager
        w.arduino = None
        w.setup_gpio = lambda: None

        def fake_setup(auto_reset):
            # the real setup_arduino installs a fresh Arduino on the window
            w.arduino = MagicMock()
            return True

        monkeypatch.setattr(cm, "setup_arduino", fake_setup)
        assert cm.ensure_arduino_connection() is True

    def test_failed_reconnect_returns_false_and_alerts(self, manager, monkeypatch):
        """A start must NOT proceed on a dead link; the operator is told."""
        cm, w = manager
        w.arduino.connected = False
        w.setup_gpio = lambda: None
        monkeypatch.setattr(cm, "setup_arduino", lambda auto_reset: False)

        assert cm.ensure_arduino_connection() is False
        assert w.errors, "operator was not shown a connection error"
        # No calibration pushed onto a link that never came up.
        assert not w.arduino.send.called

    def test_reconnect_skips_auto_reset(self, manager, monkeypatch):
        """The re-setup must use auto_reset=False: ensure_arduino_connection
        runs inside the start path and an automatic reset would race it."""
        cm, w = manager
        w.arduino.connected = False
        w.setup_gpio = lambda: None
        seen = []
        monkeypatch.setattr(
            cm, "setup_arduino",
            lambda auto_reset: seen.append(auto_reset) or True,
        )
        cm.ensure_arduino_connection()
        assert seen == [False]
