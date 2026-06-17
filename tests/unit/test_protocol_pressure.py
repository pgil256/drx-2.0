# tests/unit/test_protocol_pressure.py
"""Unit tests for Protocols pressure ramp, emergency stop, and cached state.

These tests are Windows-runnable: the Arduino is a MagicMock (no pty/FakeArduino),
methods are called directly (no real QThreadPool), and pressure ramps are driven by
seeding the cached pressure state so the device-feedback loops terminate quickly.
"""
import threading
import time
from unittest.mock import MagicMock

import pytest

from helpers.protocols import (
    Protocols,
    MAX_SAFE_PRESSURE,
    PRESSURE_INCREMENT,
)
from config.config import Configuration


def make_protocol(**kwargs):
    """Create a Protocols instance with a mocked Arduino and sane defaults."""
    defaults = dict(
        a_factor=1900,
        protocol="1",
        max_pressure=50,
        max_left=10.0,
        max_right=10.0,
        duration=1,  # 1 minute
        use_pulse=False,
        ser=MagicMock(),
        config=None,
    )
    defaults.update(kwargs)

    if defaults["config"] is None:
        config = Configuration()
        config._set_default_c_marks()
        config._set_default_a_marks()
        config._set_default_b_marks()
        defaults["config"] = config

    p = Protocols(**defaults)
    # MagicMock.send returns a truthy Mock by default; make it an explicit bool
    # so the "command failed" branches behave like the real Arduino (True = ok).
    p.arduino.send = MagicMock(return_value=True)
    return p


@pytest.mark.unit
class TestRunPressureSequence:
    """Tests for run_pressure_sequence ramp toward a target pressure."""

    def test_rejects_negative_target(self):
        """A negative target pressure is outside the safe range and aborts."""
        p = make_protocol()
        p.is_running = True
        assert p.run_pressure_sequence(10, -5) is False

    def test_rejects_over_max_safe_target(self):
        """A target above MAX_SAFE_PRESSURE is rejected before any command."""
        p = make_protocol()
        p.is_running = True
        result = p.run_pressure_sequence(10, MAX_SAFE_PRESSURE + 1)
        assert result is False
        p.arduino.send.assert_not_called()

    def test_returns_true_when_target_reached(self):
        """When status already reports the target, the sequence completes True."""
        p = make_protocol()
        p.is_running = True
        # Seed the cached pressure at the target so every wait loop breaks at once.
        p.current_pressure = 50
        result = p.run_pressure_sequence(50, 50)
        assert result is True

    def test_sends_initial_pressure_command(self):
        """The first command sent is the starting pressure P-command."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50
        p.run_pressure_sequence(50, 50)
        first_call = p.arduino.send.call_args_list[0][0][0]
        assert first_call == "P50"

    def test_sends_final_target_pressure_command(self):
        """The final target pressure P-command is sent before returning True."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50
        result = p.run_pressure_sequence(50, 50)
        assert result is True
        # Every command should be a pressure command; the target must appear.
        sent = [c[0][0] for c in p.arduino.send.call_args_list]
        assert all(cmd.startswith("P") for cmd in sent)
        assert "P50" in sent

    def test_ramps_through_increments_toward_target(self):
        """Ramping from start to a higher target sends increasing P-commands."""
        p = make_protocol()
        p.is_running = True
        # Seed at the highest value so each increment's stabilization check passes
        # immediately (abs(current - command) <= tolerance is satisfied).
        p.current_pressure = 50
        start = 50 - PRESSURE_INCREMENT  # one increment below target
        result = p.run_pressure_sequence(start, 50)
        assert result is True
        sent = [c[0][0] for c in p.arduino.send.call_args_list]
        # Both the starting and the target pressure commands must have been sent.
        assert f"P{start}" in sent
        assert "P50" in sent

    def test_returns_false_when_initial_pressure_command_fails(self):
        """If the Arduino rejects the initial P-command, the sequence aborts."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50
        p.arduino.send = MagicMock(return_value=False)
        assert p.run_pressure_sequence(50, 50) is False

    def test_aborts_when_status_never_reaches_target(self):
        """If status never reports reaching pressure, the build times out -> False."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 0  # never reaches target
        result = p.run_pressure_sequence(50, 50)
        assert result is False

    def test_aborts_immediately_when_not_running(self):
        """An emergency stop during the initial build aborts the sequence."""
        p = make_protocol()
        p.is_running = False  # simulates stop() having cleared the flag
        p.current_pressure = 0
        result = p.run_pressure_sequence(50, 50)
        assert result is False


@pytest.mark.unit
class TestStop:
    """Tests for the emergency-stop path."""

    def test_clears_is_running(self):
        """stop() must clear the is_running flag so all loops terminate."""
        p = make_protocol()
        p.is_running = True
        p.stop()
        assert p.is_running is False

    def test_sends_emergency_stop_command(self):
        """stop() sends the 'X' emergency-stop command to the Arduino."""
        p = make_protocol()
        p.is_running = True
        p.stop()
        sent = [c[0][0] for c in p.arduino.send.call_args_list]
        assert "X" in sent

    def test_disables_high_frequency_before_emergency_stop(self):
        """'HF0' is sent before 'X' so updates are quiet during the stop."""
        p = make_protocol()
        p.is_running = True
        p.stop()
        sent = [c[0][0] for c in p.arduino.send.call_args_list]
        assert "HF0" in sent and "X" in sent
        assert sent.index("HF0") < sent.index("X")

    def test_emits_stopped_signal(self):
        """stop() emits the stopped(True) signal on success."""
        p = make_protocol()
        p.is_running = True
        handler = MagicMock()
        p.signals.stopped.connect(handler)
        p.stop()
        handler.assert_called_once_with(True)

    def test_handles_missing_arduino(self):
        """With no Arduino, stop() still clears state and emits stopped(True)."""
        p = make_protocol()
        p.is_running = True
        p.arduino = None
        handler = MagicMock()
        p.signals.stopped.connect(handler)
        p.stop()
        assert p.is_running is False
        handler.assert_called_once_with(True)


@pytest.mark.unit
class TestCachedStateProperties:
    """Tests for the thread-safe current_pressure / current_pos_c properties."""

    def test_current_pressure_round_trips(self):
        """Setting current_pressure stores a float that reads back equal."""
        p = make_protocol()
        p.current_pressure = 42.5
        assert p.current_pressure == 42.5
        assert isinstance(p.current_pressure, float)

    def test_current_pressure_coerces_to_float(self):
        """An int assigned to current_pressure is stored as a float."""
        p = make_protocol()
        p.current_pressure = 30
        assert p.current_pressure == 30.0
        assert isinstance(p.current_pressure, float)

    def test_current_pos_c_round_trips(self):
        """Setting current_pos_c stores an int that reads back equal."""
        p = make_protocol()
        p.current_pos_c = 1450
        assert p.current_pos_c == 1450
        assert isinstance(p.current_pos_c, int)

    def test_current_pos_c_coerces_to_int(self):
        """A float assigned to current_pos_c is truncated to an int."""
        p = make_protocol()
        p.current_pos_c = 1450.9
        assert p.current_pos_c == 1450
        assert isinstance(p.current_pos_c, int)

    def test_initial_cached_state_is_zero(self):
        """A freshly built protocol caches zeroed state."""
        p = make_protocol()
        assert p.current_pressure == 0.0
        assert p.current_pos_c == 0

    def test_concurrent_writes_leave_consistent_value(self):
        """Concurrent writes are serialized by the state lock (no torn state)."""
        p = make_protocol()

        def writer(value):
            for _ in range(200):
                p.current_pressure = value

        threads = [threading.Thread(target=writer, args=(v,)) for v in (10.0, 20.0, 30.0)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Final value must be exactly one of the written values, never a partial.
        assert p.current_pressure in (10.0, 20.0, 30.0)


@pytest.mark.unit
class TestUpdateStatus:
    """Tests for update_status caching device feedback."""

    def test_updates_cached_pressure_and_pos_c(self):
        """update_status caches the reported pressure and C position."""
        p = make_protocol()
        p.update_status(pos_a=100, pos_b=200, pos_c=1450, pressure=37.5)
        assert p.current_pressure == 37.5
        assert p.current_pos_c == 1450

    def test_coerces_reported_types(self):
        """update_status coerces pressure to float and pos_c to int."""
        p = make_protocol()
        p.update_status(pos_a=0, pos_b=0, pos_c=999, pressure=12)
        assert isinstance(p.current_pressure, float)
        assert isinstance(p.current_pos_c, int)
        assert p.current_pressure == 12.0
        assert p.current_pos_c == 999

    def test_emits_pressure_signal(self):
        """update_status emits pressure_emit with the reported pressure."""
        p = make_protocol()
        handler = MagicMock()
        p.signals.pressure_emit.connect(handler)
        p.update_status(pos_a=0, pos_b=0, pos_c=0, pressure=25.0)
        handler.assert_called_once_with(25.0)

    def test_emits_full_status_signal(self):
        """update_status emits status_emit with all four feedback values."""
        p = make_protocol()
        handler = MagicMock()
        p.signals.status_emit.connect(handler)
        p.update_status(pos_a=5, pos_b=6, pos_c=7, pressure=8.0)
        handler.assert_called_once_with(5, 6, 7, 8.0)

    def test_drives_pressure_loop_to_completion(self):
        """update_status feeding the target lets run_pressure_sequence finish True."""
        p = make_protocol()
        p.is_running = True

        def feed():
            # Give the build loop a moment, then report the device at target.
            time.sleep(0.05)
            p.update_status(pos_a=0, pos_b=0, pos_c=0, pressure=50.0)

        feeder = threading.Thread(target=feed)
        feeder.start()
        result = p.run_pressure_sequence(50, 50)
        feeder.join()
        assert result is True
