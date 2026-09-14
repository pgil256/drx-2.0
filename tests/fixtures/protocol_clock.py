"""A deterministic clock for protocol waits in unit tests."""

from typing import Callable, List, Optional


class ProtocolClock:
    """Advance protocol time on sleep without changing the process clock."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.sleeps: List[float] = []
        self.on_sleep: Optional[Callable[[], None]] = None

    def time(self) -> float:
        """Return a nonzero simulated wall-clock timestamp."""
        return 1000.0 + self.elapsed

    def sleep(self, seconds: float) -> None:
        """Advance time and deliver optional device feedback or cancellation."""
        self.sleeps.append(seconds)
        assert len(self.sleeps) < 10000, "Protocol did not finish within the simulated wait budget"
        self.elapsed += seconds
        if self.on_sleep is not None:
            self.on_sleep()
