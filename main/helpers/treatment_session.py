"""One immutable cloud record for each dispatched treatment session."""

import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

try:
    from main.config.constants import APP_VERSION
except ModuleNotFoundError:
    from config.constants import APP_VERSION


@dataclass
class TreatmentSession:
    """Keep wall time, active elapsed time and terminal outcome independent of UI cleanup."""

    patient_id: Optional[str]
    protocol_number: int
    planned_duration_s: int
    client_record_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_clock: float = field(default_factory=lambda: time.monotonic())
    paused_at: Optional[float] = None
    paused_seconds: float = 0.0
    outcome: Optional[str] = None
    ended_at: Optional[datetime] = None
    actual_duration_s: Optional[int] = None
    finalized: bool = False
    completion_handled: bool = False
    reset_requested: bool = False
    record: Optional[Dict[str, Any]] = None

    def pause(self) -> None:
        """Freeze active time without changing the wall-clock start."""
        if self.paused_at is None and self.outcome is None:
            self.paused_at = time.monotonic()

    def resume(self) -> None:
        """Exclude the completed pause interval from elapsed time."""
        if self.paused_at is not None and self.outcome is None:
            self.paused_seconds += time.monotonic() - self.paused_at
            self.paused_at = None

    def elapsed(self) -> int:
        """Return active seconds, also when stopping during a pause."""
        if self.actual_duration_s is not None:
            return self.actual_duration_s
        clock = self.paused_at if self.paused_at is not None else time.monotonic()
        return max(0, int(clock - self.started_clock - self.paused_seconds))

    def latch(self, outcome: str) -> None:
        """Keep the first terminal reason and time through all later cleanup signals."""
        if self.outcome is None:
            self.actual_duration_s = self.elapsed()
            self.ended_at = max(self.started_at, datetime.now(timezone.utc))
            self.outcome = outcome

    def finish(self, settings: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """Produce a record once; unlinked manual sessions never become cloud records."""
        if self.finalized or self.outcome is None:
            return None
        self.finalized = True
        if self.patient_id is None:
            return None
        self.record = {
            "schema_version": 1,
            "client_record_id": self.client_record_id,
            "patient_id": self.patient_id,
            "protocol_number": self.protocol_number,
            "outcome": self.outcome,
            "planned_duration_s": self.planned_duration_s,
            "actual_duration_s": self.actual_duration_s,
            "settings_at_end": deepcopy(settings),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "app_version": APP_VERSION,
            "fw_version": None,
        }
        return deepcopy(self.record)
