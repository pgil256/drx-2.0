"""Distance readout factors derived from measured actuator travel."""

import pytest

from helpers.calibration import distance_factor

pytestmark = pytest.mark.unit


def test_factor_uses_measured_distance_and_preserves_direction():
    assert distance_factor(100, 1340, 2) == 3720
    assert distance_factor(1340, 100, 2) == 3720


@pytest.mark.parametrize("inches", [0, -1, float("nan"), float("inf")])
def test_bad_distance_rejected(inches):
    with pytest.raises(ValueError):
        distance_factor(100, 1340, inches)


def test_stationary_anchors_rejected():
    with pytest.raises(ValueError):
        distance_factor(100, 101, 2)
