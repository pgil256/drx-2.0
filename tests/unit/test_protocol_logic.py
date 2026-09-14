# tests/unit/test_protocol_logic.py
import time
from unittest.mock import patch

import pytest

from fixtures.protocol_clock import ProtocolClock
from fixtures.protocols import make_protocol
from helpers.conversions import lateral_degrees_to_position
from helpers.protocols import (
    MAX_SAFE_PRESSURE,
    MIN_PRESSURE,
    PRESSURE_INCREMENT,
)
from main.config.constants import LATERAL_MOVE_TIMEOUT_S, PRESSURE_BUILD_TIMEOUT_S


@pytest.mark.unit
class TestCheckDuration:
    """Tests for protocol duration checking."""

    def test_returns_true_within_duration(self):
        p = make_protocol(duration=1)  # 1 minute = 60 seconds
        p.start_time = time.time()
        assert p.check_duration() is True

    def test_returns_false_after_duration(self):
        p = make_protocol(duration=1)
        p.start_time = time.time() - 120  # 2 minutes ago
        assert p.check_duration() is False

    def test_returns_false_without_start_time(self):
        p = make_protocol()
        p.start_time = None
        assert p.check_duration() is False

    def test_updates_elapsed_time(self):
        p = make_protocol(duration=1)
        p.start_time = time.time() - 30  # 30 seconds ago
        p.check_duration()
        assert 29 <= p.elapsed_time <= 31


@pytest.mark.unit
class TestSetToCDistance:
    """Tests for C actuator position calculation and interpolation."""

    def test_rejected_send_does_not_claim_arrival(self) -> None:
        """Even cached arrival cannot make a rejected command succeed."""
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = int(p.config.CMarks["0.0"])
        p.arduino.send.return_value = False
        assert p.set_to_c_distance(0) is False
        p.arduino.send.assert_called_once_with(f"K{p.current_pos_c}")
        assert p.angle_set is False

    def test_unverified_position_times_out(self, protocol_clock: ProtocolClock) -> None:
        """Neither a stale DONE nor unchanged telemetry verifies a new move."""
        p = make_protocol()
        p.is_running = True
        p.arduino.send.return_value = True
        p._on_firmware_done()
        assert p.set_to_c_distance(0) is False
        assert p.angle_set is False
        assert p.arduino.send.call_count == 1
        assert LATERAL_MOVE_TIMEOUT_S <= protocol_clock.elapsed < LATERAL_MOVE_TIMEOUT_S + 1

    def test_cancellation_interrupts_position_wait(self, protocol_clock: ProtocolClock) -> None:
        """Cancellation ends the wait without claiming arrival or resending."""
        p = make_protocol()
        p.is_running = True
        p.arduino.send.return_value = True
        protocol_clock.on_sleep = p.cancel
        assert p.set_to_c_distance(0) is False
        assert p.angle_set is False
        assert p.arduino.send.call_count == 1
        assert protocol_clock.elapsed < LATERAL_MOVE_TIMEOUT_S

    def test_exact_mark_lookup(self):
        p = make_protocol()
        p.is_running = True
        expected_position = int(p.config.CMarks["0.0"])
        p.current_pos_c = expected_position  # Already at target to avoid timeout

        result = p.set_to_c_distance(0.0)
        assert result is True
        p.arduino.send.assert_called_with(f"K{expected_position}")

    def test_negative_degree(self):
        p = make_protocol()
        p.is_running = True
        expected_position = int(p.config.CMarks["-20.0"])
        p.current_pos_c = expected_position  # At target

        result = p.set_to_c_distance(-20.0)
        assert result is True
        p.arduino.send.assert_called_with(f"K{expected_position}")

    def test_positive_degree(self):
        p = make_protocol()
        p.is_running = True
        expected_position = int(p.config.CMarks["17.5"])
        p.current_pos_c = expected_position  # At target

        result = p.set_to_c_distance(17.5)
        assert result is True
        p.arduino.send.assert_called_with(f"K{expected_position}")

    def test_interpolation_between_marks(self):
        """Degrees between marks should interpolate position linearly."""
        p = make_protocol()
        p.is_running = True
        expected_position, _ = lateral_degrees_to_position(
            p.config.CMarks, -18.75
        )
        p.current_pos_c = expected_position

        result = p.set_to_c_distance(-18.75)
        assert result is True
        # The command should have a K prefix with an interpolated value
        call_arg = p.arduino.send.call_args[0][0]
        assert call_arg.startswith("K")
        position = int(call_arg[1:])
        assert position == expected_position

    def test_clamps_below_minus_20(self):
        p = make_protocol()
        p.is_running = True
        expected_position = int(p.config.CMarks["-20.0"])
        p.current_pos_c = expected_position

        result = p.set_to_c_distance(-25.0)  # Should clamp to -20
        assert result is True
        p.arduino.send.assert_called_with(f"K{expected_position}")

    def test_clamps_above_max_mark(self):
        """Values above 20 clamp to 20.0."""
        p = make_protocol()
        p.is_running = True
        expected_position = int(p.config.CMarks["20.0"])
        p.current_pos_c = expected_position

        result = p.set_to_c_distance(25.0)  # Clamps to 20.0
        assert result is True
        p.arduino.send.assert_called_with(f"K{expected_position}")

    def test_duplicate_degree_marks_no_division_error(self):
        """Regression: duplicate-degree CMarks keys (e.g. "-20" and "-20.00"
        from a hand-edited config) both float to the same degree value but
        miss the exact "{:.1f}" lookup, producing a zero-width interpolation
        bracket. Must use the first mark, not raise ZeroDivisionError."""
        p = make_protocol()
        p.config.CMarks = {"-20": "500", "-20.00": "505", "20.0": "2400"}
        p.is_running = True
        p.current_pos_c = 500  # Already at target to avoid timeout

        result = p.set_to_c_distance(-20.0)
        assert result is True
        p.arduino.send.assert_called_with("K500")


@pytest.mark.unit
class TestProtocolInit:
    """Tests for protocol initialization logic."""

    def test_max_left_forced_negative(self):
        p = make_protocol(max_left=15.0)
        assert p.max_left == -15.0

    def test_max_right_forced_positive(self):
        p = make_protocol(max_right=-10.0)
        assert p.max_right == 10.0

    def test_duration_converted_to_seconds(self):
        p = make_protocol(duration=5)  # 5 minutes
        assert p.duration == 300

    def test_initial_state(self):
        p = make_protocol()
        assert p.is_running is False
        assert p.current_pressure == 0
        assert p.current_pos_c == 0


@pytest.mark.unit
class TestSetToPressure:
    """Tests for direct pressure setting."""

    def test_rejected_send_returns_false(self) -> None:
        """Pressure already at target does not excuse a rejected send."""
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50
        p.arduino.send.return_value = False
        assert p.set_to_pressure(50) is False
        p.arduino.send.assert_called_once_with("P50")

    def test_unverified_pressure_times_out(self, protocol_clock: ProtocolClock) -> None:
        """A successful enqueue alone does not verify measured pressure."""
        p = make_protocol()
        p.is_running = True
        p.arduino.send.return_value = True
        assert p.set_to_pressure(50) is False
        p.arduino.send.assert_called_once_with("P50")
        assert PRESSURE_BUILD_TIMEOUT_S <= protocol_clock.elapsed < PRESSURE_BUILD_TIMEOUT_S + 1

    def test_rejects_negative_pressure(self):
        p = make_protocol()
        p.is_running = True
        result = p.set_to_pressure(-10)
        assert result is False

    def test_rejects_over_max_pressure(self):
        p = make_protocol()
        p.is_running = True
        result = p.set_to_pressure(MAX_SAFE_PRESSURE + 1)
        assert result is False

    def test_rejects_when_not_running(self):
        p = make_protocol()
        p.is_running = False
        result = p.set_to_pressure(50)
        assert result is False

    def test_sends_pressure_command(self):
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50  # Already at target
        # The device acks the move; the worker waits for that DONE
        p.arduino.send.side_effect = lambda cmd: (p._on_firmware_done(), True)[1]
        result = p.set_to_pressure(50)
        assert result is True
        p.arduino.send.assert_called_with("P50")


@pytest.mark.unit
class TestProtocolConstants:
    """Tests for protocol-level constants."""

    def test_min_pressure(self):
        assert MIN_PRESSURE == 10

    def test_max_safe_pressure(self):
        assert MAX_SAFE_PRESSURE == 80

    def test_pressure_increment(self):
        assert PRESSURE_INCREMENT == 10
