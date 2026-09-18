# tests/unit/test_connection_manager.py
"""Tests for the extracted Arduino connection lifecycle."""
import threading
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock

from controllers.connection_manager import ConnectionManager
from fixtures.controllers import ConnectionWindow as StubWindow


@pytest.fixture
def manager(qtbot):
    window = StubWindow()
    return ConnectionManager(window), window


@pytest.mark.unit
class TestResetGating:
    def test_reset_waits_for_cancelled_treatment_cleanup(self, manager, monkeypatch):
        cm, w = manager
        w.worker = SimpleNamespace(is_running=False, completed=threading.Event())
        w._no_automatic_recovery = True
        w._physical_stop_active = True
        scheduled = []
        monkeypatch.setattr(
            "controllers.connection_manager.QTimer.singleShot",
            lambda ms, callback: scheduled.append(callback),
        )

        cm.reset_arduino()

        w.threadpool.start.assert_not_called()
        assert not w.reset_in_progress
        assert w._no_automatic_recovery and w._physical_stop_active
        assert len(scheduled) == 1

        w.worker.completed.set()
        scheduled.pop()()

        w.threadpool.start.assert_called_once()
        assert w.reset_in_progress
        assert not w._no_automatic_recovery and not w._physical_stop_active
        cm._on_reset_finished(True, cm.reset_worker)
        assert w.initial_setup_complete and not w.reset_in_progress

    def test_reset_refuses_running_treatment(self, manager):
        cm, w = manager
        w.worker = SimpleNamespace(is_running=True, completed=threading.Event())

        cm.reset_arduino()

        w.threadpool.start.assert_not_called()
        assert not w.reset_in_progress
        assert w.errors == ["Stop treatment before resetting Arduino."]

    def test_deferred_reset_cannot_start_after_close(self, manager, monkeypatch):
        cm, w = manager
        w.worker = SimpleNamespace(is_running=False, completed=threading.Event())
        scheduled = []
        monkeypatch.setattr(
            "controllers.connection_manager.QTimer.singleShot",
            lambda ms, callback: scheduled.append(callback),
        )
        cm.reset_arduino()
        w.worker.completed.set()
        w._closing = True

        scheduled.pop()()

        w.threadpool.start.assert_not_called()
        assert not w.reset_in_progress

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
        w.shell.treatment.set_busy.assert_called_with(False)

    def test_reset_finished_failure_keeps_start_disabled(self, manager):
        cm, w = manager
        w.reset_in_progress = True
        cm._on_reset_finished(False)
        assert w.reset_in_progress is False
        assert w.initial_setup_complete is False
        w.shell.treatment.set_busy.assert_called_with(True)
        assert any("failed" in e.lower() for e in w.errors)


@pytest.mark.unit
class TestReadyToGo:
    def test_boot_banner_does_not_fake_a_done(self, manager):
        """ResetWorker waits for the banner on Arduino.ready_event; setting the
        DONE event here as well could satisfy the NEXT step's wait early and
        shift every later DONE by one homing step."""
        cm, w = manager
        w.I2Cstatus = 0
        w.I2Cstatus_event = MagicMock()
        cm.ready_to_go()
        w.I2Cstatus_event.set.assert_not_called()
        assert w.I2Cstatus == 0


@pytest.mark.unit
class TestLateConnect:
    def test_late_connect_schedules_reset(self, manager, monkeypatch):
        """A connection that comes up after setup_arduino() stopped waiting
        still owes the device its reset / zero-mark / calibration sequence."""
        cm, w = manager
        scheduled = []
        monkeypatch.setattr(
            "controllers.connection_manager.QTimer.singleShot",
            lambda ms, fn: scheduled.append((ms, fn)),
        )
        cm._on_late_connect()
        assert scheduled == [(0, cm._automatic_reset)]

    def test_calibration_pushes_tolerate_missing_transport(self, manager):
        cm, w = manager
        w.arduino = None
        cm.send_zero_mark()      # must not raise
        cm.send_calibration()
        assert w.logger.error.called


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
class TestThreadTeardown:
    def test_teardown_disconnects_quits_waits_and_clears_references(self, manager):
        cm, w = manager
        arduino = w.arduino
        arduino.disconnect.return_value = True
        w.arduino_thread = MagicMock()
        w.arduino_thread.wait.return_value = True
        thread = w.arduino_thread

        assert cm.teardown_arduino(drain_timeout=1.5) is True

        arduino.disconnect.assert_called_once_with(drain_timeout=1.5)
        thread.quit.assert_called_once()
        thread.wait.assert_called_once_with(3000)
        thread.deleteLater.assert_called_once()
        assert w.arduino is None
        assert w.arduino_thread is None

    def test_teardown_ignores_inherited_qobject_thread_method(self, manager):
        """A fresh QMainWindow has thread(), but no owned Arduino QThread."""
        cm, w = manager
        w.arduino = None
        w.thread = lambda: "qt-affinity-thread"

        assert cm.teardown_arduino() is True
        assert w.arduino is None
        assert w.arduino_thread is None


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
        old_arduino = w.arduino
        w.setup_gpio = lambda: setattr(w, "gpio_reset", True)
        def fake_setup(auto_reset):
            w.arduino = MagicMock()
            return True
        monkeypatch.setattr(cm, "setup_arduino", fake_setup)

        assert cm.ensure_arduino_connection() is False

        old_arduino.disconnect.assert_called_once()
        assert w.gpio_reset
        sent = [c.args[0] for c in w.arduino.send.call_args_list]
        assert sent == []
        assert w.reset_in_progress
        w.threadpool.start.assert_called_once()

    def test_no_arduino_object_reconnects(self, manager, monkeypatch):
        cm, w = manager
        w.arduino = None
        w.setup_gpio = lambda: None

        def fake_setup(auto_reset):
            # the real setup_arduino installs a fresh Arduino on the window
            w.arduino = MagicMock()
            return True

        monkeypatch.setattr(cm, "setup_arduino", fake_setup)
        assert cm.ensure_arduino_connection() is False

    def test_failed_reconnect_returns_false_and_alerts(self, manager, monkeypatch):
        """A start must NOT proceed on a dead link; the operator is told."""
        cm, w = manager
        w.arduino.connected = False
        old_arduino = w.arduino
        w.setup_gpio = lambda: None
        monkeypatch.setattr(cm, "setup_arduino", lambda auto_reset: False)

        assert cm.ensure_arduino_connection() is False
        assert w.errors, "operator was not shown a connection error"
        # No calibration pushed onto a link that never came up.
        assert not old_arduino.send.called

    def test_reconnect_skips_auto_reset(self, manager, monkeypatch):
        """The re-setup must use auto_reset=False: ensure_arduino_connection
        runs inside the start path and an automatic reset would race it."""
        cm, w = manager
        w.arduino.connected = False
        w.setup_gpio = lambda: None
        seen = []
        def fake_setup(auto_reset):
            seen.append(auto_reset)
            w.arduino = MagicMock()
            return True
        monkeypatch.setattr(
            cm, "setup_arduino",
            fake_setup,
        )
        cm.ensure_arduino_connection()
        assert seen == [False]
