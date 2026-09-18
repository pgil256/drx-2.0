"""Pressure commands require typed, stopped-motor evidence with no blind resends."""
import threading
from unittest.mock import MagicMock
import pytest
from fixtures.protocols import make_protocol
from main.config.constants import PRESSURE_BUILD_TIMEOUT_S

pytestmark = pytest.mark.unit

@pytest.mark.parametrize("target", [-1, 81, float("nan"), float("inf")])
def test_invalid_target_never_sent(target):
    worker = make_protocol()
    worker.is_running = True
    assert not worker.set_to_pressure(target)
    worker.arduino.send.assert_not_called()

@pytest.mark.parametrize("start,target,commands", [
    (20, 50, ["P30|50", "P40|50", "P50|50"]),
    (40, 40, []), (50, 30, ["P30|30"]),
])
def test_ramp_does_not_repeat_completed_waypoints(start, target, commands):
    worker = make_protocol(acknowledge=True, max_pressure=target)
    worker.is_running = True
    assert worker.run_pressure_sequence(start, target)
    assert [c.args[0] for c in worker.arduino.send.call_args_list] == commands

@pytest.mark.parametrize("reply", ["none", "done", "typed", "wrong_kind", "wrong_target"])
def test_pressure_cannot_complete_without_matching_evidence_and_ack(protocol_clock, reply):
    worker = make_protocol()
    worker.is_running = True
    worker.current_pressure = 50
    def receive():
        if reply in ("typed", "wrong_kind", "wrong_target"):
            worker.arduino.motion_done.emit("K" if reply == "wrong_kind" else "P",
                                           40 if reply == "wrong_target" else 50, 50)
        if reply not in ("none", "typed"):
            worker.arduino.done_emit.emit()
    protocol_clock.on_sleep = receive
    assert not worker.set_to_pressure(50)
    worker.arduino.send.assert_called_once_with("P50|50")
    assert PRESSURE_BUILD_TIMEOUT_S <= protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S + 1

def test_cancellation_prevents_later_waypoint(protocol_clock):
    worker = make_protocol()
    worker.is_running = True
    protocol_clock.on_sleep = worker.cancel
    assert not worker.run_pressure_sequence(20, 50)
    worker.arduino.send.assert_called_once_with("P30|50")
    assert protocol_clock.elapsed < 1

def test_rejected_send_ends_ramp_immediately(protocol_clock):
    worker = make_protocol()
    worker.is_running = True
    worker.arduino.send.return_value = False
    assert not worker.run_pressure_sequence(20, 50)
    assert protocol_clock.elapsed == 0

@pytest.mark.parametrize("signal,result", [
    ("fault_emit", {"reason": "PRESSURE_LIMIT"}),
    ("command_rejected", {"command": "P", "reason": "TARE_REQUIRED"}),
])
def test_fault_or_rejection_cancels_even_during_hold(signal, result):
    worker = make_protocol()
    worker.is_running = True
    getattr(worker.arduino, signal).emit(result)
    assert not worker.is_running
    assert not worker._send_command("P50")

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
