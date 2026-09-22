"""Deterministic synthetic mechanism, independent of application calibration."""
import json
import math
import random
from pathlib import Path
from typing import Dict, Optional


DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "synthetic.json"


def inverse_marks(marks: Dict[str, float], counts: float) -> float:
    """Convert physical counts through the independent fixture's measured landmarks."""
    pairs = sorted((value, float(angle)) for angle, value in marks.items())
    if counts <= pairs[0][0]:
        return pairs[0][1]
    for (low, start), (high, end) in zip(pairs, pairs[1:]):
        if counts <= high:
            return start + (end - start) * (counts - low) / (high - low)
    return pairs[-1][1]


class Plant:
    """Keep requested motor outputs, physical position, and sensor readings separate."""

    def __init__(self, seed: int = 1, profile: Optional[dict] = None) -> None:
        self.profile = profile or json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
        self.rng = random.Random(seed)
        self.position = {"a": 0.0, "b": 1140.0, "c": 1688.0}
        self.sensor = dict(self.position)
        self.velocity = dict.fromkeys(self.position, 0.0)
        self.force = 0.0
        self.reported_force = 0.0
        self.raw_force = 0.0
        self.tare_force = 0.0
        self.sensor_age = 0.0
        self.fit_inches = 0.0
        self.fit_velocity = 0.0
        self.faults: dict = {}
        self.gpio: Dict[int, int] = {}

    def step(self, dt: float) -> None:
        """Advance motor motion and load feedback by a fixed positive timestep."""
        if not 0 < dt <= 0.1:
            raise ValueError("Plant timestep must be in (0, 0.1]")
        bounds = {"a": (0, self.profile["axial_max_counts"]), "b": (0, 2280),
                  "c": (500, 2400)}
        for axis, velocity in self.velocity.items():
            if not self.faults.get("jam_" + axis):
                low, high = bounds[axis]
                self.position[axis] = min(high, max(low, self.position[axis] + velocity * dt))
            if not self.faults.get("freeze_" + axis):
                self.sensor[axis] = round(self.position[axis])
        self.fit_inches = min(6.0, max(0.0, self.fit_inches + self.fit_velocity * dt))
        extension = self.position["a"] / self.profile["axial_counts_per_inch"]
        self.force = max(0.0, extension - self.profile["contact_inches"])
        self.force *= self.profile["stiffness_lb_per_inch"]
        if self.faults.get("pressure_stale"):
            self.sensor_age += dt
        else:
            self.sensor_age = 0.0
            alpha = 1 - math.exp(-dt / max(0.001, self.profile["sensor_lag_s"]))
            self.raw_force += (self.force - self.raw_force) * alpha
            noise = self.rng.uniform(-1, 1) * self.profile["pressure_noise_lb"]
            measured = self.raw_force - self.tare_force + noise
            measured += float(self.faults.get("pressure_bias", 0))
            self.reported_force = 0.0 if abs(measured) < 0.5 else abs(measured)

    def pose(self) -> dict:
        """Return physical pose in units understood by the Blender-exported rig."""
        return {
            "axial_inches": self.position["a"] / self.profile["axial_counts_per_inch"],
            "horizontal_degrees": inverse_marks(self.profile["horizontal_marks"],
                                                self.position["b"]),
            "lateral_degrees": inverse_marks(self.profile["lateral_marks"], self.position["c"]),
            "fit_inches": self.fit_inches,
            "force_lb": self.force,
        }
