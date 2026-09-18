"""Lateral-angle approximation from raw encoder position (Phase 3.5 §15.3).

The Arduino reports the lateral actuator as a raw encoder count (``pos_c``). The
forward map degrees→position lives in ``config.CMarks`` (a ``"{:.1f}"``-degree →
position table). This is its inverse: a piecewise-linear interpolation of
``pos_c`` back to an approximate angle for the Treatment "Lateral Angle" readout.

It is intentionally an APPROXIMATION — the forward map truncates with ``int()``
and the marks are non-uniformly spaced — so the result is interpolated per
segment (against positions sorted ascending) rather than over the whole range.
"""


def pos_c_to_angle(pos_c, cmarks):
    """Approximate the lateral angle (degrees) for a raw ``pos_c`` reading.

    Args:
        pos_c: raw lateral encoder count from the Arduino status frame.
        cmarks: the ``config.CMarks`` dict — ``{"<deg>": <position int>}``.

    Returns:
        float degrees, clamped to the calibrated mark range. Returns 0.0 when
        the table is empty or unusable.
    """
    if not cmarks:
        return 0.0

    try:
        pos_c = float(pos_c)
        # (position, degrees) pairs sorted by position (ascending).
        pairs = sorted((float(p), float(d)) for d, p in cmarks.items())
    except (ValueError, TypeError):
        return 0.0

    if not pairs:
        return 0.0

    # Below / above the calibrated range clamps to the nearest endpoint angle.
    if pos_c <= pairs[0][0]:
        return pairs[0][1]
    if pos_c >= pairs[-1][0]:
        return pairs[-1][1]

    for i in range(len(pairs) - 1):
        p1, d1 = pairs[i]
        p2, d2 = pairs[i + 1]
        if p1 <= pos_c <= p2:
            if p2 == p1:
                return d1
            ratio = (pos_c - p1) / (p2 - p1)
            return d1 + (d2 - d1) * ratio

    return pairs[-1][1]
