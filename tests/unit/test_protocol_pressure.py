# tests/unit/test_protocol_pressure.py
"""Unit tests for Protocols pressure ramp, emergency stop, and cached state.

These tests are Windows-runnable: the Arduino is a MagicMock (no pty/FakeArduino),
methods are called directly (no real QThreadPool), and pressure ramps use explicit
acknowledgements and simulated time for feedback, timeout, and cancellation checks.
"""
from functools import partial
import threading
from unittest.mock import MagicMock

import pytest

from fixtures.protocol_clock import ProtocolClock
from fixtures.protocols import make_protocol as build_protocol
from helpers.protocols import (
    Protocols,
    MAX_SAFE_PRESSURE,
    PRESSURE_INCREMENT,
)
from main.config.constants import PRESSURE_BUILD_TIMEOUT_S


make_protocol = partial(build_protocol, acknowledge=True)


@pytest.mark.unit
@pytest.mark.usefixtures("protocol_clock")
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

        def send(command: str) -> bool:
            p.current_pressure = float(command[1:])
            p._on_firmware_done()
            return True

        p.arduino.send.side_effect = send
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

    def test_aborts_when_status_never_reaches_target(self, protocol_clock: ProtocolClock) -> None:
        """If status never reports reaching pressure, the build times out -> False."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 0  # never reaches target
        result = p.run_pressure_sequence(50, 50)
        assert result is False
        p.arduino.send.assert_called_once_with("P50")
        assert PRESSURE_BUILD_TIMEOUT_S <= protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S + 1

    @pytest.mark.parametrize("rejected_send", [2, 3], ids=["increment", "final"])
    def test_aborts_when_later_pressure_command_is_rejected(self, rejected_send: int) -> None:
        """Rejected increments and final commands must not report success."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50

        def send(command: str) -> bool:
            p._on_firmware_done()
            return p.arduino.send.call_count != rejected_send

        p.arduino.send.side_effect = send
        assert p.run_pressure_sequence(40, 50) is False
        assert p.arduino.send.call_count == rejected_send

    def test_aborts_when_increment_never_stabilizes(self, protocol_clock: ProtocolClock) -> None:
        """A verified initial pressure cannot stand in for the next increment."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 40
        assert p.run_pressure_sequence(40, 50) is False
        assert [c.args[0] for c in p.arduino.send.call_args_list] == ["P40", "P50"]
        assert PRESSURE_BUILD_TIMEOUT_S <= protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S + 1

    def test_aborts_after_final_pressure_retries_exhausted(self, protocol_clock: ProtocolClock) -> None:
        """Final verification retains its bounded retries when pressure drops."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50

        def send(command: str) -> bool:
            p._on_firmware_done()
            if p.arduino.send.call_count > 1:
                p.current_pressure = 0
            return True

        p.arduino.send.side_effect = send
        assert p.run_pressure_sequence(50, 50) is False
        assert [c.args[0] for c in p.arduino.send.call_args_list] == ["P50"] + ["P50.0"] * 5
        assert 5 * PRESSURE_BUILD_TIMEOUT_S <= protocol_clock.elapsed
        assert protocol_clock.elapsed < 5 * (PRESSURE_BUILD_TIMEOUT_S + 1)

    @pytest.mark.parametrize("during_ack", [False, True], ids=["pressure", "ack"])
    def test_cancellation_during_wait_aborts_without_escalating(
        self, protocol_clock: ProtocolClock, during_ack: bool,
    ) -> None:
        """Cancellation interrupts both pressure feedback and DONE waits."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 40 if during_ack else 0
        p.arduino.send.side_effect = None
        p.arduino.send.return_value = True
        protocol_clock.on_sleep = p.cancel

        assert p.run_pressure_sequence(40, 50) is False
        p.arduino.send.assert_called_once_with("P40")
        assert p.is_running is False
        assert protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S

    def test_aborts_immediately_when_not_running(self):
        """An emergency stop during the initial build aborts the sequence."""
        p = make_protocol()
        p.is_running = False  # simulates stop() having cleared the flag
        p.current_pressure = 0
        result = p.run_pressure_sequence(50, 50)
        assert result is False


@pytest.mark.unit
class TestPressureTolerance:
    @pytest.mark.parametrize("stage", ["initial", "increment", "final", "direct"])
    @pytest.mark.parametrize(
        "offset, expected, waits_for_settling",
        [(-2.01, False, True), (-2, True, False), (0, True, False),
         (2, True, False), (2.01, True, True), (10, True, True), (10.01, False, True)],
    )
    def test_control_goal_and_overshoot_allowance(
        self, protocol_clock: ProtocolClock, stage: str, offset: float,
        expected: bool, waits_for_settling: bool,
    ) -> None:
        """Every pressure wait aims for +/-2, then permits at most +10 lbs."""
        p = make_protocol()
        p.is_running = True

        def send(command: str) -> bool:
            target = float(command[1:])
            command_index = p.arduino.send.call_count
            apply_offset = (
                stage == "direct"
                or (stage == "initial" and command_index == 1)
                or (stage == "increment" and command_index == 2)
                or (stage == "final" and command_index >= 2)
            )
            p.current_pressure = target + (offset if apply_offset else 0)
            p._on_firmware_done()
            return True

        p.arduino.send.side_effect = send
        if stage == "direct":
            result = p.set_to_pressure(50)
        else:
            result = p.run_pressure_sequence(40 if stage == "increment" else 50, 50)

        assert result is expected
        assert (protocol_clock.elapsed >= PRESSURE_BUILD_TIMEOUT_S) is waits_for_settling
        assert all(float(c.args[0][1:]) <= 50 for c in p.arduino.send.call_args_list)

    def test_waits_for_correction_into_control_band(self, protocol_clock: ProtocolClock) -> None:
        """A +3 lb reading is not accepted immediately as the control goal."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 53

        def settle() -> None:
            p.current_pressure = 52

        protocol_clock.on_sleep = settle
        assert p.set_to_pressure(50) is True
        assert 0 < protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S
        assert p.current_pressure == 52


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

    def test_stop_order_x_then_release_then_hf0(self):
        """stop() sends X first (jumps the rate-limit queue), then P0 to
        release pressure, then HF0 last so telemetry stays live during the
        release."""
        p = make_protocol()
        p.is_running = True
        p.stop()
        sent = [c[0][0] for c in p.arduino.send.call_args_list]
        assert sent == ["X", "P0", "HF0"]

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

    def test_drives_pressure_loop_to_completion(self, protocol_clock: ProtocolClock) -> None:
        """update_status feeding the target lets run_pressure_sequence finish True."""
        p = make_protocol()
        p.is_running = True

        def feed() -> None:
            # Deliver feedback during the initial build's simulated wait.
            p.update_status(pos_a=0, pos_b=0, pos_c=0, pressure=50.0)

        protocol_clock.on_sleep = feed
        result = p.run_pressure_sequence(50, 50)
        assert result is True
        assert protocol_clock.sleeps
