# tests/unit/test_conversions.py
"""Conversion tests: the extracted lateral_degrees_to_position helper (base)
plus the GUI line's window-method tests for KneeSpa.set_to_distance /
set_to_c_distance, called UNBOUND against lightweight stubs.

FROZEN-CONVENTION POLICY: these pin CURRENT behavior (A-command format,
half-degree snapping, integer-truncating interpolation) as regression guards,
not as a statement that the numbers are "correct"."""
import types
from unittest.mock import MagicMock

import pytest

from helpers.conversions import (
    lateral_degrees_to_position,
    horizontal_degrees_to_position,
)
from kneespa import KneeSpa
from config.config import Configuration

CMARKS = {
    "-20.0": 500,
    "-17.5": 619,
    "0.0": 1450,
    "17.5": 2281,
    "20.0": 2400,
}

# Default BMarks (config._set_default_b_marks); integer-degree string keys.
BMARKS = {
    "-25": 0,
    "-20": 380,
    "-15": 760,
    "-10": 1140,
    "-5": 1520,
    "0": 1900,
    "5": 2280,
}


@pytest.mark.unit
class TestLateralDegreesToPosition:
    def test_exact_key(self):
        position, degrees = lateral_degrees_to_position(CMARKS, 0.0)
        assert position == 1450
        assert degrees == 0.0

    def test_interpolates_between_marks(self):
        # -19.0 lies between -20.0 (500) and -17.5 (619)
        position, degrees = lateral_degrees_to_position(CMARKS, -19.0)
        assert degrees == -19.0
        assert 540 <= position <= 555

    def test_snaps_to_half_degree(self):
        position, degrees = lateral_degrees_to_position(CMARKS, -18.75)
        assert degrees == -19.0

    def test_clamps_out_of_range_input(self):
        position, degrees = lateral_degrees_to_position(CMARKS, 35.0)
        assert degrees == 20.0
        assert position == 2400

    def test_duplicate_degree_marks_no_crash(self):
        marks = {"-20": "500", "-20.00": "505", "20.0": "2400"}
        position, degrees = lateral_degrees_to_position(marks, -20.0)
        assert position == 500

    def test_outside_table_raises(self):
        sparse = {"-5.0": 1200, "5.0": 1700}
        with pytest.raises(ValueError):
            lateral_degrees_to_position(sparse, -10.0)

    def test_string_values_accepted(self):
        # configparser yields strings
        marks = {k: str(v) for k, v in CMARKS.items()}
        position, _ = lateral_degrees_to_position(marks, 17.5)
        assert position == 2281


@pytest.mark.unit
class TestHorizontalDegreesToPosition:
    """The calibrated horizontal (B actuator) degrees->position map used to
    home the reset. Unlike the frozen A13<inches> jog path, this reads BMarks."""

    def test_home_minus_10_hits_exact_mark(self):
        """-10 deg -> BMarks['-10'] == 1140 (the reset home position)."""
        assert horizontal_degrees_to_position(BMARKS, -10) == 1140

    def test_zero_degrees_exact_mark(self):
        assert horizontal_degrees_to_position(BMARKS, 0) == 1900

    def test_float_input_matches_integer_key(self):
        """A float like -15.0 still resolves the integer-string key '-15'."""
        assert horizontal_degrees_to_position(BMARKS, -15.0) == 760

    def test_float_style_key_tolerated(self):
        """A table written with '-15.0' keys still resolves."""
        marks = {"-20.0": 380, "-15.0": 760, "0.0": 1900}
        assert horizontal_degrees_to_position(marks, -15) == 760

    def test_interpolates_between_marks(self):
        # -12.5 lies halfway between -15(760) and -10(1140): 760 + 380*0.5 = 950
        assert horizontal_degrees_to_position(BMARKS, -12.5) == 950

    def test_clamps_below_range(self):
        """Below the smallest mark clamps to its position, never extrapolates."""
        assert horizontal_degrees_to_position(BMARKS, -40) == 0

    def test_clamps_above_range(self):
        assert horizontal_degrees_to_position(BMARKS, 30) == 2280

    def test_string_values_accepted(self):
        # configparser yields strings for both keys and values.
        marks = {k: str(v) for k, v in BMARKS.items()}
        assert horizontal_degrees_to_position(marks, -15) == 760

    def test_empty_table_raises(self):
        with pytest.raises(ValueError):
            horizontal_degrees_to_position({}, -15)


# ---------------------------------------------------------------------------
# Window-method tests (GUI line, adapted to the FAILSAFE base: the methods no
# longer touch I2CStatus, and the lateral path routes through the helper).
# ---------------------------------------------------------------------------
def make_config_with_defaults():
    """Build a Configuration populated with the default mark tables."""
    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    return config


def make_c_stub(config=None):
    """Lightweight stub carrying only what KneeSpa.set_to_c_distance reads."""
    if config is None:
        config = make_config_with_defaults()
    return types.SimpleNamespace(
        loading_spinner=MagicMock(),
        disable_actuator_controls=MagicMock(),
        enable_actuator_controls=MagicMock(),
        config=config,
        arduino=MagicMock(),
        I2Cstatus_event=MagicMock(),
    )


def make_distance_stub():
    """Lightweight stub carrying only what KneeSpa.set_to_distance reads."""
    return types.SimpleNamespace(
        arduino=MagicMock(),
        I2Cstatus_event=MagicMock(),
        enable_actuator_controls=MagicMock(),
    )


def sent_command(stub):
    """Return the last command string passed to the stub's arduino.send."""
    return stub.arduino.send.call_args[0][0]


@pytest.mark.unit
class TestSetToDistance:
    """Tests for the axial A-command formatting (set_to_distance)."""

    def test_sends_a_command_with_actuator_and_inches(self):
        """Command is 'A<actuator><inches:.1f>' per the frozen format."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 3.0, "A", 1900)
        stub.arduino.send.assert_called_once_with("AA3.0")

    def test_inches_formatted_to_one_decimal(self):
        """Inches always render with exactly one decimal place."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 2, "A", 1900)
        assert sent_command(stub) == "AA2.0"

    def test_fractional_inches_preserved(self):
        """A fractional input keeps its one-decimal representation."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 1.5, "A", 1900)
        assert sent_command(stub) == "AA1.5"

    def test_zero_inches(self):
        """Zero inches is sent as the literal 'A<actuator>0.0'."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 0, "A", 1900)
        assert sent_command(stub) == "AA0.0"

    def test_actuator_letter_is_embedded(self):
        """The actuator identifier is placed between the 'A' prefix and value."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 4.0, "B", 1900)
        assert sent_command(stub) == "AB4.0"

    def test_factor_does_not_change_sent_command(self):
        """FROZEN: the internal 'position' uses factor, but the SENT command
        is driven only by inches/actuator. Two factors -> identical command."""
        stub_a = make_distance_stub()
        stub_b = make_distance_stub()
        KneeSpa.set_to_distance(stub_a, 2.0, "A", 1900)
        KneeSpa.set_to_distance(stub_b, 2.0, "A", 8)
        assert sent_command(stub_a) == sent_command(stub_b) == "AA2.0"

    def test_clears_status_event(self):
        """Side effect: the thread-safe DONE event is cleared for the next
        command (the legacy I2CStatus flag write was retired on the base)."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 1.0, "A", 1900)
        stub.I2Cstatus_event.clear.assert_called_once()

    def test_keeps_controls_locked_until_firmware_done(self):
        """Queue acceptance is not physical completion; DONE unlocks later."""
        stub = make_distance_stub()
        KneeSpa.set_to_distance(stub, 1.0, "A", 1900)
        stub.enable_actuator_controls.assert_not_called()


@pytest.mark.unit
class TestSetToCDistanceExactMarks:
    """Exact-mark lookups in set_to_c_distance."""

    def test_zero_degrees_hits_exact_mark(self):
        """Zero degrees uses the configured CMarks center position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["0.0"])
        result = KneeSpa.set_to_c_distance(stub, 0.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_min_mark_lookup(self):
        """The minimum angle uses its configured CMarks position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["-20.0"])
        result = KneeSpa.set_to_c_distance(stub, -20.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_max_mark_lookup(self):
        """The maximum angle uses its configured CMarks position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["20.0"])
        result = KneeSpa.set_to_c_distance(stub, 20.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_positive_mark_lookup(self):
        """A positive angle uses its configured CMarks position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["17.5"])
        result = KneeSpa.set_to_c_distance(stub, 17.5)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_rounds_to_nearest_half_degree(self):
        """Input is rounded to the nearest configured half-degree mark."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["0.0"])
        result = KneeSpa.set_to_c_distance(stub, 0.1)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_accepts_string_degrees(self):
        """Degrees are coerced via float(); a numeric string works."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["0.0"])
        result = KneeSpa.set_to_c_distance(stub, "0.0")
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")


@pytest.mark.unit
class TestSetToCDistanceInterpolation:
    """Between-mark linear interpolation in set_to_c_distance."""

    def test_interpolates_between_marks(self):
        """An angle between marks uses the configured table's interpolation."""
        stub = make_c_stub()
        expected_position, _ = lateral_degrees_to_position(
            stub.config.CMarks, -16.0
        )
        result = KneeSpa.set_to_c_distance(stub, -16.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_interpolation_uses_integer_truncation(self):
        """FROZEN: interpolation uses int() truncation of the delta, not rounding.

        Expected output is calculated from the live configured table so a
        calibration update does not require changing this regression test.
        """
        stub = make_c_stub()
        expected_position, _ = lateral_degrees_to_position(
            stub.config.CMarks, 14.0
        )
        result = KneeSpa.set_to_c_distance(stub, 14.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_interpolated_command_has_k_prefix(self):
        """An interpolated command still carries the 'K' prefix."""
        stub = make_c_stub()
        expected_position, _ = lateral_degrees_to_position(
            stub.config.CMarks, -16.0
        )
        KneeSpa.set_to_c_distance(stub, -16.0)
        call_arg = sent_command(stub)
        assert call_arg.startswith("K")
        assert int(call_arg[1:]) == expected_position


@pytest.mark.unit
class TestSetToCDistanceClamping:
    """Range-end clamping in set_to_c_distance (bounds are [-20.0, 20.0])."""

    def test_clamps_below_minimum(self):
        """Degrees below -20 use the configured -20-degree position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["-20.0"])
        result = KneeSpa.set_to_c_distance(stub, -25.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_clamps_above_maximum(self):
        """Degrees above 20 use the configured 20-degree position."""
        stub = make_c_stub()
        expected_position = int(stub.config.CMarks["20.0"])
        result = KneeSpa.set_to_c_distance(stub, 25.0)
        assert result is True
        stub.arduino.send.assert_called_with(f"K{expected_position}")

    def test_clamp_matches_exact_mark_at_boundary(self):
        """The clamped boundary value resolves through the exact-mark path."""
        stub_clamped = make_c_stub()
        stub_exact = make_c_stub()
        KneeSpa.set_to_c_distance(stub_clamped, 100.0)
        KneeSpa.set_to_c_distance(stub_exact, 20.0)
        assert sent_command(stub_clamped) == sent_command(stub_exact)


@pytest.mark.unit
class TestSetToCDistanceSideEffects:
    """Spinner / control / event side effects of set_to_c_distance."""

    def test_clears_status_event_on_success(self):
        stub = make_c_stub()
        KneeSpa.set_to_c_distance(stub, 0.0)
        stub.I2Cstatus_event.clear.assert_called_once()

    def test_toggles_loading_spinner(self):
        """Spinner shows on entry and hides before the successful return."""
        stub = make_c_stub()
        KneeSpa.set_to_c_distance(stub, 0.0)
        stub.loading_spinner.show.assert_called_once()
        stub.loading_spinner.hide.assert_called_once()

    def test_disables_until_firmware_done(self):
        stub = make_c_stub()
        KneeSpa.set_to_c_distance(stub, 0.0)
        stub.disable_actuator_controls.assert_called_once()
        stub.enable_actuator_controls.assert_not_called()

    def test_returns_false_and_hides_spinner_on_bad_input(self):
        """FROZEN: non-numeric degrees raise inside the try; the method swallows
        the error, hides the spinner, and returns False (no command sent)."""
        stub = make_c_stub()
        result = KneeSpa.set_to_c_distance(stub, "not-a-number")
        assert result is False
        stub.arduino.send.assert_not_called()
        stub.loading_spinner.hide.assert_called_once()
