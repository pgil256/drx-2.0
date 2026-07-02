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
    # angle = i*2.5 - 20, pos = round(500 + 1900*i/16): -20->500, -17.5->619,
    # -15->738, -10->975, 0->1450, 17.5->2281, 20->2400.
    return cfg.CMarks


def test_empty_table_returns_zero():
    assert pos_c_to_angle(1234, {}) == 0.0


def test_exact_center_mark():
    assert pos_c_to_angle(1450, default_cmarks()) == pytest.approx(0.0)


def test_exact_min_mark():
    assert pos_c_to_angle(500, default_cmarks()) == pytest.approx(-20.0)


def test_exact_max_mark():
    assert pos_c_to_angle(2400, default_cmarks()) == pytest.approx(20.0)


def test_below_min_clamps_to_min_angle():
    assert pos_c_to_angle(100, default_cmarks()) == pytest.approx(-20.0)


def test_above_max_clamps_to_max_angle():
    assert pos_c_to_angle(9999, default_cmarks()) == pytest.approx(20.0)


def test_interpolates_between_marks():
    # 600 sits between 500 (-20.0) and 619 (-17.5).
    # ratio = (600-500)/(619-500) = 0.840; angle = -20 + 2.5*0.840 = -17.90
    assert pos_c_to_angle(600, default_cmarks()) == pytest.approx(-17.90, abs=0.05)


def test_garbage_input_returns_zero():
    assert pos_c_to_angle("not-a-number", default_cmarks()) == 0.0
