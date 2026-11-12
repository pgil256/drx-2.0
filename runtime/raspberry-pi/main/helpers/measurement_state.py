"""Pressure validity independently of cached numeric readings or widget visibility."""

import time
from typing import Optional

# A running protocol streams status at 1 Hz; idle firmware reports every 5 s.
DIAGNOSTICS_MAX_AGE_S = 2.5
IDLE_DIAGNOSTICS_MAX_AGE_S = 7.5


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
