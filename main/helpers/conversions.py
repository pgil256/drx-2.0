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


def horizontal_degrees_to_position(
    bmarks: Dict[str, Number], degrees: float
) -> int:
    """Map horizontal (B actuator) degrees to a raw position via calibrated BMarks.

    BMarks is the measured degree->position table for the horizontal actuator.
    The ``A13<inches>`` jog path (position = ``BFULLINCH * inches``) is an
    UNCALIBRATED approximation whose slope disagrees with BMarks -- homing
    through it lands the actuator at the wrong angle -- so absolute homing must
    go through this table instead.

    Uses an exact key when present (BMarks keys are integer-degree strings like
    ``"-15"``; ``"-15.0"`` is tolerated too), otherwise interpolates linearly
    between the bracketing marks and clamps to the table's endpoints.

    Returns:
        int raw_position

    Raises:
        ValueError: if the table is empty or its entries are non-numeric.
    """
    degrees = float(degrees)

    # Exact-key fast path across the plausible spellings of the angle.
    candidates = []
    if degrees.is_integer():
        candidates.append(str(int(degrees)))  # "-15"
    candidates.append("{:.1f}".format(degrees))  # "-15.0"
    candidates.append(str(degrees))  # "-15" or "-15.0"
    for key in candidates:
        if key in bmarks:
            return int(bmarks[key])

    try:
        marks = sorted((float(k), int(v)) for k, v in bmarks.items())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"BMarks table is unusable ({exc})")
    if not marks:
        raise ValueError("BMarks table is empty")

    # Clamp to the calibrated endpoints rather than extrapolating past them.
    if degrees <= marks[0][0]:
        return marks[0][1]
    if degrees >= marks[-1][0]:
        return marks[-1][1]

    for (deg1, pos1), (deg2, pos2) in zip(marks, marks[1:]):
        if deg1 <= degrees <= deg2:
            if deg2 - deg1 == 0:
                return pos1
            ratio = (degrees - deg1) / (deg2 - deg1)
            return pos1 + int((pos2 - pos1) * ratio)

    raise ValueError(f"Degree value {degrees} outside calibrated BMarks range")
