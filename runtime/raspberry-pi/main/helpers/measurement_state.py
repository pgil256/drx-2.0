"""Pressure validity independently of cached numeric readings or widget visibility."""

import math
import time
from typing import Optional

# A running protocol streams status at 1 Hz; idle firmware reports every 5 s.
DIAGNOSTICS_MAX_AGE_S = 2.5
IDLE_DIAGNOSTICS_MAX_AGE_S = 7.5
# The firmware reports a load under 0.5 lb as zero, in either direction.
PRESSURE_DEADBAND_LB = 0.5


def is_push(diagnostics: Optional[dict]) -> bool:
    """True when the latest signed sample is a push on the footplate."""
    try:
        signed = diagnostics.get("signed_lb")
    except AttributeError:
        return False
    return (isinstance(signed, (int, float)) and not isinstance(signed, bool)
            and math.isfinite(signed) and signed <= -PRESSURE_DEADBAND_LB)


def signed_reading(pressure, diagnostics: Optional[dict]):
    """Give a status frame's magnitude the direction of the latest signed sample.

    Display only. Status frames and the control logic carry the magnitude; a
    foot pressing on the footplate must not read like a pull (ks-fb,
    11 November 2026). Zero stays zero.
    """
    if (is_push(diagnostics) and isinstance(pressure, (int, float))
            and not isinstance(pressure, bool) and pressure):
        return -abs(pressure)
    return pressure


def diagnostics_max_age_s(protocol_running: bool) -> float:
    return DIAGNOSTICS_MAX_AGE_S if protocol_running else IDLE_DIAGNOSTICS_MAX_AGE_S


class MeasurementState:
    def __init__(self) -> None:
        self.diagnostics: Optional[dict] = None
        self.received_at: Optional[float] = None
        self.fault: Optional[str] = None
        self.baseline_valid = False
        self.protocol_running = False

    def receive(self, diagnostics: dict) -> None:
        self.diagnostics = diagnostics
        self.received_at = time.monotonic()

    def caption(self, connected: bool) -> str:
        if self.fault:
            return "Controller fault — last reading stale"
        if not connected:
            return "Waiting for controller"
        if self.diagnostics is None:
            return "Waiting for pressure"
        if not self.diagnostics["valid"]:
            return "Pressure unavailable"
        if (self.diagnostics["age_ms"] > 500 or self.received_at is None
                or time.monotonic() - self.received_at
                > diagnostics_max_age_s(self.protocol_running)):
            return "Pressure stale"
        if not self.baseline_valid:
            return "Pressure zero required"
        return "Pressure live"
