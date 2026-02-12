# tests/unit/test_protocol_logic.py
import pytest
import time
from unittest.mock import MagicMock, patch

from helpers.protocols import Protocols, MIN_PRESSURE, MAX_SAFE_PRESSURE, PRESSURE_INCREMENT
from config.config import Configuration


def make_protocol(**kwargs):
    """Create a Protocols instance with mocked Arduino and sane defaults."""
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

    # Build config with defaults
    if defaults["config"] is None:
        config = Configuration()
        config._set_default_c_marks()
        config._set_default_a_marks()
        config._set_default_b_marks()
        defaults["config"] = config

    return Protocols(**defaults)


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

    def test_exact_mark_lookup(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 1858  # Already at target to avoid timeout

        result = p.set_to_c_distance(0.0)
        assert result is True
        # Should have sent K command with position from CMarks["0.0"]
        p.arduino.send.assert_called_with("K1858")

    def test_negative_degree(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 98  # At target

        result = p.set_to_c_distance(-20.0)
        assert result is True
        p.arduino.send.assert_called_with("K98")

    def test_positive_degree(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 3398  # At target

        result = p.set_to_c_distance(17.5)
        assert result is True
        p.arduino.send.assert_called_with("K3398")

    def test_interpolation_between_marks(self):
        """Degrees between marks should interpolate position linearly."""
        p = make_protocol()
        p.is_running = True
        # Input -18.75 rounds to -19.0 (nearest 0.5)
        # -20.0 -> 98, -17.5 -> 318
        # ratio = (-19 - (-20)) / (-17.5 - (-20)) = 1/2.5 = 0.4
        # position = 98 + (220 * 0.4) = 186
        p.current_pos_c = 186

        result = p.set_to_c_distance(-18.75)
        assert result is True
        # The command should have a K prefix with an interpolated value
        call_arg = p.arduino.send.call_args[0][0]
        assert call_arg.startswith("K")
        position = int(call_arg[1:])
        assert 180 <= position <= 195

    def test_clamps_below_minus_20(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 98

        result = p.set_to_c_distance(-25.0)  # Should clamp to -20
        assert result is True
        p.arduino.send.assert_called_with("K98")

    def test_clamps_above_max_mark(self):
        """Values above 20 clamp to 20.0, which is outside CMarks range.
        The code raises ValueError since 20.0 is not in CMarks (max is 17.5).
        This is expected behavior - the set_to_c_distance returns False."""
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 3398

        result = p.set_to_c_distance(25.0)  # Clamps to 20.0, outside CMarks range
        assert result is False  # ValueError caught internally


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
