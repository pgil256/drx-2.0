"""Unit tests for helpers.angles.pos_c_to_angle (Phase 3.5 §15.3).

The lateral-angle approximation inverse-interpolates a raw encoder count back to
degrees over config.CMarks. These pin the exact endpoints, an exact mark hit, a
between-mark interpolation, and the empty/garbage guards.
"""

import pytest

from helpers.angles import pos_c_to_angle
from config.config import Configuration

pytestmark = pytest.mark.unit


def default_cmarks():
    cfg = Configuration()
    cfg._set_default_c_marks()
    return cfg.CMarks


def test_empty_table_returns_zero():
    assert pos_c_to_angle(1234, {}) == 0.0


def test_exact_center_mark():
    marks = default_cmarks()
    assert pos_c_to_angle(marks["0.0"], marks) == pytest.approx(0.0)


def test_exact_min_mark():
    marks = default_cmarks()
    assert pos_c_to_angle(marks["-20.0"], marks) == pytest.approx(-20.0)


def test_exact_max_mark():
    marks = default_cmarks()
    assert pos_c_to_angle(marks["20.0"], marks) == pytest.approx(20.0)


def test_below_min_clamps_to_min_angle():
    marks = default_cmarks()
    assert pos_c_to_angle(min(marks.values()) - 1, marks) == pytest.approx(-20.0)


def test_above_max_clamps_to_max_angle():
    marks = default_cmarks()
    assert pos_c_to_angle(max(marks.values()) + 1, marks) == pytest.approx(20.0)


def test_interpolates_between_marks():
    marks = default_cmarks()
    midpoint = (marks["-20.0"] + marks["-17.5"]) / 2
    assert pos_c_to_angle(midpoint, marks) == pytest.approx(-18.75)


def test_garbage_input_returns_zero():
    assert pos_c_to_angle("not-a-number", default_cmarks()) == 0.0
