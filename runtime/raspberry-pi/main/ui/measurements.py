"""Display-only conversions; never clamp feedback to a commanded target."""

import math
from typing import Mapping, Optional


def calibrated_reading(position: float, marks: Mapping) -> Optional[float]:
    """Interpolate within a valid monotonic calibration table, otherwise return None."""
    try:
        value = float(position)
        points = sorted((float(raw), float(unit)) for unit, raw in marks.items())
        if len(points) < 2 or not math.isfinite(value):
            return None
        if not all(math.isfinite(raw) and math.isfinite(unit) for raw, unit in points):
            return None
        differences = [b[1] - a[1] for a, b in zip(points, points[1:])]
        if not (all(d > 0 for d in differences) or all(d < 0 for d in differences)):
            return None
        if any(a[0] == b[0] for a, b in zip(points, points[1:])):
            return None
        if not points[0][0] <= value <= points[-1][0]:
            return None
        for left, right in zip(points, points[1:]):
            if left[0] <= value <= right[0]:
                fraction = (value - left[0]) / (right[0] - left[0])
                return left[1] + fraction * (right[1] - left[1])
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    return None
