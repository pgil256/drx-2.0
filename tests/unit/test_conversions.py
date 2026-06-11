# tests/unit/test_conversions.py
import pytest

from helpers.conversions import lateral_degrees_to_position

CMARKS = {
    "-20.0": 500,
    "-17.5": 619,
    "0.0": 1450,
    "17.5": 2281,
    "20.0": 2400,
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
