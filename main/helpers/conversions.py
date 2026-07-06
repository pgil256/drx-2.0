# helpers/conversions.py
"""Shared unit-conversion helpers.

The lateral degrees->raw-position mapping used to exist as three
divergent copies (kneespa.set_to_c_distance, protocols.set_to_c_distance,
and an exact-key-only variant in move_actuator); one copy lacked the
zero-width-bracket guard and another silently no-opped between marks.
"""
from typing import Dict, Tuple, Union

Number = Union[int, float, str]


def lateral_degrees_to_position(
    cmarks: Dict[str, Number], degrees: float
) -> Tuple[int, float]:
    """Map lateral degrees to a raw position via the calibrated CMarks.

    Snaps to the nearest 0.5 degrees, clamps to +/-20, uses an exact
    "{:.1f}" key when present, otherwise interpolates linearly between
    the bracketing marks.

    Returns:
        (raw_position, snapped_degrees)

    Raises:
        ValueError: if the requested angle is outside the calibrated table.
    """
    degrees = float(degrees)
    degrees = round(degrees * 2) / 2
    degrees = max(-20.0, min(20.0, degrees))
    key = "{:.1f}".format(degrees)

    if key in cmarks:
        return int(cmarks[key]), degrees

    marks = sorted((float(k), int(v)) for k, v in cmarks.items())
    for (deg1, pos1), (deg2, pos2) in zip(marks, marks[1:]):
        if deg1 <= degrees <= deg2:
            if deg2 - deg1 == 0:
                # Duplicate-degree keys (hand-edited config) collapse to
                # a zero-width bracket; use the first mark
                return pos1, degrees
            ratio = (degrees - deg1) / (deg2 - deg1)
            return pos1 + int((pos2 - pos1) * ratio), degrees

    raise ValueError(f"Degree value {degrees} outside calibrated range")
