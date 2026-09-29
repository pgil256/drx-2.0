"""Distance readout factors for the hardware service panel."""

import math

from config.constants import CALIBRATION_DISTANCE_REFERENCE_INCHES


def distance_factor(start: int, end: int, inches: float) -> int:
    """Calculate the legacy six-inch factor from measured actuator travel."""
    if not math.isfinite(inches) or inches <= 0:
        raise ValueError("Enter a positive measured travel distance in inches.")
    if abs(end - start) <= 25:
        raise ValueError("The two positions must be more than 25 counts apart.")
    factor = round(abs(end - start) / inches * CALIBRATION_DISTANCE_REFERENCE_INCHES)
    if not 1 <= factor <= 1000000:
        raise ValueError("The calculated factor is outside the supported range.")
    return factor
