# tests/unit/test_reset_worker_logic.py
"""Windows-runnable unit tests for ResetWorker logic.

These tests drive ResetWorker with fully mocked Arduino / config / main_window
objects and call its methods directly (no QThreadPool, no pty). They complement
the POSIX/pty-gated integration tests in tests/integration/test_reset_worker.py.

Conventions:
- Import via `from helpers.reset_worker import ...` (conftest puts main/ on path).
- time.sleep is patched out so timeout/retry paths run fast.
- Per the tests-only fix policy, these assert CURRENT behavior of the device
  logic. Suspected bugs are marked xfail rather than changing safety logic.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from helpers.reset_worker import ResetWorker, ResetWorkerSignals


def make_main_window(use_event=True):
    """Build a mocked main_window with the attributes ResetWorker inspects.

    A real ``threading.Event`` is used for I2Cstatus_event so the event-based
    code path in _wait_for_done exercises real wait/clear semantics. ``worker``
    is set to None so the run() safety check treats no protocol as running.
    """
    mw = MagicMock()
    mw.I2Cstatus = 0
    if use_event:
        mw.I2Cstatus_event = threading.Event()
    else:
        # Remove the attribute so hasattr(...) is False -> polling path.
        del mw.I2Cstatus_event
    mw.worker = None
    return mw


def make_config():
    """Build a mocked config with the marks/calibration ResetWorker reads."""
    config = MagicMock()
    config.AMarks = {"0.0": 0, "0": 0}
    config.BMarks = {"0.0": 1900, "0": 1900}
    # run() reads CMarks["{:.1f}".format(0)] == CMarks["0.0"]
    config.CMarks = {"0.0": 1450}
    config.calibration = 1.0
    return config


def make_worker(arduino=None, config=None, main_window=None, use_event=True):
    """Construct a ResetWorker with mocked collaborators."""
    if arduino is None:
        arduino = MagicMock()
        arduino.send.return_value = True
    if config is None:
        config = make_config()
    if main_window is None:
        main_window = make_main_window(use_event=use_event)
    return ResetWorker(arduino, config, main_window)


@pytest.mark.unit
class TestResetWorkerInit:
    """Tests for ResetWorker construction."""

    def test_stores_collaborators(self):
        arduino = MagicMock()
        config = make_config()
        mw = make_main_window()
        worker = ResetWorker(arduino, config, mw)
        assert worker.arduino is arduino
        assert worker.config is config
        assert worker.main_window is mw

    def test_creates_signals(self):
        worker = make_worker()
        assert isinstance(worker.signals, ResetWorkerSignals)

    def test_step_times_starts_empty(self):
        worker = make_worker()
        assert worker.step_times == []


@pytest.mark.unit
class TestWaitForDone:
    """Tests for _wait_for_done timeout and completion handling."""

    def test_returns_false_on_timeout_event_path(self):
        """Event never set within timeout -> returns False (event path)."""
        worker = make_worker(use_event=True)
        # Event is never set, so a short timeout should elapse and return False.
        result = worker._wait_for_done(timeout=0.05, operation_name="op")
        assert result is False

    def test_resets_i2cstatus_on_timeout_event_path(self):
        """I2Cstatus is forced back to 0 after a timeout."""
        worker = make_worker(use_event=True)
        worker.main_window.I2Cstatus = 1  # stale value
        worker._wait_for_done(timeout=0.05, operation_name="op")
        assert worker.main_window.I2Cstatus == 0

    def test_returns_true_when_event_set(self):
        """When the event is set, _wait_for_done returns True and clears it."""
        worker = make_worker(use_event=True)
        worker.main_window.I2Cstatus_event.set()
        result = worker._wait_for_done(timeout=1.0, operation_name="op")
        assert result is True
        # Event should be cleared and flag reset for next use.
        assert worker.main_window.I2Cstatus_event.is_set() is False
        assert worker.main_window.I2Cstatus == 0

    def test_returns_false_on_timeout_polling_path(self):
        """No event attribute -> polling path returns False on timeout."""
        worker = make_worker(use_event=False)
        worker.main_window.I2Cstatus = 0  # never becomes 1
        result = worker._wait_for_done(timeout=0.1, operation_name="op")
        assert result is False
        assert worker.main_window.I2Cstatus == 0

    def test_returns_true_polling_path_when_flag_set(self):
        """Polling path returns True when I2Cstatus is already 1."""
        worker = make_worker(use_event=False)
        worker.main_window.I2Cstatus = 1
        result = worker._wait_for_done(timeout=1.0, operation_name="op")
        assert result is True
        assert worker.main_window.I2Cstatus == 0


@pytest.mark.unit
class TestTryCommandWithRetry:
    """Tests for _try_command_with_retry: send, success, and DTR retry."""

    def test_sends_command_via_arduino(self):
        """The command is sent through the mocked arduino."""
        arduino = MagicMock()
        mw = make_main_window(use_event=True)

        def send_and_ack(cmd):
            # _try_command_with_retry clears the event before send; the Arduino
            # "completing" sets it so the subsequent _wait_for_done succeeds.
            mw.I2Cstatus_event.set()
            return True

        arduino.send.side_effect = send_and_ack
        worker = ResetWorker(arduino, make_config(), mw)
        result = worker._try_command_with_retry("L01.0", "Calibration", timeout=1.0)
        assert result is True
        arduino.send.assert_called_once_with("L01.0")

    def test_clears_stale_event_before_send(self):
        """A stale (pre-set) ack event must be cleared before sending.

        Discriminating test for the clear-before-send guard (reset_worker.py:83):
        the event is pre-set (a stale ack from a prior command), but ``send``
        succeeds WITHOUT acking the current command, and ``reset_dtr`` is
        unavailable so there is no retry. With the guard, the stale event is
        cleared, the non-acking command times out, and the result is False. If
        the guard were removed, the stale event would make ``_wait_for_done``
        return True immediately and this would (wrongly) return True -- so this
        test fails if the guard regresses, unlike a side_effect that re-sets it.
        """
        arduino = MagicMock(spec=["send"])  # no reset_dtr -> clean timeout, no retry
        arduino.send.return_value = True     # send "succeeds" but never acks
        mw = make_main_window(use_event=True)
        mw.I2Cstatus_event.set()             # stale ack from a prior command
        worker = ResetWorker(arduino, make_config(), mw)

        with patch("helpers.reset_worker.time.sleep"):
            result = worker._try_command_with_retry("X", "op", timeout=0.05)

        assert result is False               # would be True if clear() were removed
        arduino.send.assert_called_once_with("X")

    def test_dtr_reset_retry_on_send_failure(self):
        """First send fails -> reset_dtr is called and command is re-sent."""
        arduino = MagicMock()
        arduino.reset_dtr = MagicMock()
        mw = make_main_window(use_event=True)

        calls = {"n": 0}

        def send_side_effect(cmd):
            calls["n"] += 1
            if calls["n"] == 1:
                return False  # first attempt fails -> triggers DTR retry
            # Second attempt (after DTR reset) succeeds and acks completion.
            mw.I2Cstatus_event.set()
            return True

        arduino.send.side_effect = send_side_effect
        worker = ResetWorker(arduino, make_config(), mw)

        with patch("helpers.reset_worker.time.sleep"):
            result = worker._try_command_with_retry("Z", "op", timeout=1.0)

        assert result is True
        arduino.reset_dtr.assert_called_once()
        assert arduino.send.call_count == 2

    def test_returns_false_when_send_fails_and_no_dtr(self):
        """Send fails and reset_dtr unavailable -> returns False, no retry."""
        arduino = MagicMock(spec=["send"])  # no reset_dtr attribute
        arduino.send.return_value = False
        worker = make_worker(arduino=arduino, use_event=True)
        with patch("helpers.reset_worker.time.sleep"):
            result = worker._try_command_with_retry("Z", "op", timeout=0.1)
        assert result is False
        arduino.send.assert_called_once()

    def test_dtr_retry_on_timeout(self):
        """Send succeeds but completion times out -> DTR reset and retry."""
        arduino = MagicMock()
        arduino.send.return_value = True
        arduino.reset_dtr = MagicMock()
        mw = make_main_window(use_event=True)
        # Event never gets set -> _wait_for_done times out both times.
        worker = ResetWorker(arduino, make_config(), mw)

        with patch("helpers.reset_worker.time.sleep"):
            result = worker._try_command_with_retry("Z", "op", timeout=0.05)

        # Final wait also times out so overall result is False, but the timeout
        # DTR-retry path was exercised: reset_dtr called, command sent twice.
        assert result is False
        arduino.reset_dtr.assert_called_once()
        assert arduino.send.call_count == 2

    def test_returns_false_on_timeout_without_dtr(self):
        """Completion times out and reset_dtr unavailable -> returns False."""
        arduino = MagicMock(spec=["send"])  # no reset_dtr
        arduino.send.return_value = True
        worker = make_worker(arduino=arduino, use_event=True)
        # Event never set -> first wait times out, no DTR available -> False.
        with patch("helpers.reset_worker.time.sleep"):
            result = worker._try_command_with_retry("Z", "op", timeout=0.05)
        assert result is False
        arduino.send.assert_called_once()


@pytest.mark.unit
class TestRunProtocolGuard:
    """Tests for the run() safety guard that refuses while a protocol runs."""

    def test_refuses_when_protocol_running(self):
        """run() must NOT issue any reset command if a protocol is running."""
        arduino = MagicMock()
        arduino.send.return_value = True
        mw = make_main_window(use_event=True)
        # Simulate a running protocol on the main window.
        mw.worker = MagicMock()
        mw.worker.is_running = True
        worker = ResetWorker(arduino, make_config(), mw)

        finished = []
        errors = []
        worker.signals.finished.connect(finished.append)
        worker.signals.error.connect(errors.append)

        with patch("helpers.reset_worker.time.sleep"):
            worker.run()

        # No reset commands should have been sent.
        arduino.send.assert_not_called()
        # finished(False) and an error should be emitted.
        assert finished == [False]
        assert errors and "running" in errors[0].lower()

    def test_proceeds_when_no_protocol_running(self):
        """run() proceeds (sends Y) when worker is present but not running."""
        arduino = MagicMock()
        arduino.send.return_value = True
        mw = make_main_window(use_event=True)
        mw.worker = MagicMock()
        mw.worker.is_running = False
        # Auto-ack: set the event on each send so waits pass quickly.
        mw.I2Cstatus_event = threading.Event()

        def send_and_ack(cmd):
            mw.I2Cstatus_event.set()
            return True

        arduino.send.side_effect = send_and_ack
        worker = ResetWorker(arduino, make_config(), mw)

        with patch("helpers.reset_worker.time.sleep"):
            worker.run()

        sent = [c.args[0] for c in arduino.send.call_args_list]
        assert sent[0] == "Y"


@pytest.mark.unit
class TestRunSequenceOrdering:
    """Tests for the ordered reset steps issued on the success path."""

    def _run_success(self):
        """Run a full successful reset and return the list of sent commands."""
        arduino = MagicMock()
        mw = make_main_window(use_event=True)
        mw.worker = None  # no protocol running

        def send_and_ack(cmd):
            # Each command immediately "completes" by setting the event so
            # _wait_for_done returns True on the next wait.
            mw.I2Cstatus_event.set()
            return True

        arduino.send.side_effect = send_and_ack
        worker = ResetWorker(arduino, make_config(), mw)

        finished = []
        worker.signals.finished.connect(finished.append)

        with patch("helpers.reset_worker.time.sleep"):
            worker.run()

        sent = [c.args[0] for c in arduino.send.call_args_list]
        return sent, finished

    def test_first_command_is_y(self):
        """Step 1 issues the 'Y' reset command first."""
        sent, _ = self._run_success()
        assert sent[0] == "Y"

    def test_zero_mark_before_actuators(self):
        """Step 2 issues the 'L5' zero mark before any actuator step."""
        sent, _ = self._run_success()
        # 'Y' first, then an 'L5...' command before the I14/A13/I12 actuators.
        l5_index = next(i for i, c in enumerate(sent) if c.startswith("L5"))
        i14_index = next(i for i, c in enumerate(sent) if c.startswith("I14"))
        assert l5_index < i14_index

    def test_actuator_step_ordering(self):
        """Actuators C ('I14'), B ('A13'), A ('I12') are issued in order."""
        sent, _ = self._run_success()
        i14 = next(i for i, c in enumerate(sent) if c.startswith("I14"))
        a13 = next(i for i, c in enumerate(sent) if c.startswith("A13"))
        i12 = next(i for i, c in enumerate(sent) if c.startswith("I12"))
        assert i14 < a13 < i12

    def test_calibration_is_last(self):
        """Step 6 issues the 'L0' calibration command last."""
        sent, _ = self._run_success()
        l0_index = next(i for i, c in enumerate(sent) if c.startswith("L0"))
        assert l0_index == len(sent) - 1

    def test_full_command_sequence(self):
        """The full ordered sequence matches Y, L5, I14, A13, I12, L0."""
        sent, _ = self._run_success()
        prefixes = []
        for cmd in sent:
            for pfx in ("Y", "L5", "I14", "A13", "I12", "L0"):
                if cmd == pfx or cmd.startswith(pfx):
                    prefixes.append(pfx)
                    break
        assert prefixes == ["Y", "L5", "I14", "A13", "I12", "L0"]

    def test_actuator_c_uses_cmarks_zero_position(self):
        """Actuator C command embeds the CMarks['0.0'] position (1450)."""
        sent, _ = self._run_success()
        i14_cmd = next(c for c in sent if c.startswith("I14"))
        assert i14_cmd == "I141450"

    def test_calibration_embeds_config_value(self):
        """Calibration command embeds config.calibration."""
        sent, _ = self._run_success()
        l0_cmd = next(c for c in sent if c.startswith("L0"))
        assert l0_cmd == "L01.0"

    def test_success_emits_finished_true(self):
        """A fully successful run emits finished(True)."""
        _, finished = self._run_success()
        assert finished == [True]
