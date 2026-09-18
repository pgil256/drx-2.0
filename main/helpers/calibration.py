"""Draft calibration data and transactional persistence for the service panel."""

import copy
import math
import os
import shutil
from datetime import datetime
from typing import Dict, Optional

try:
    from main.config.constants import (
        CALIBRATION_AXES, CALIBRATION_DISTANCE_REFERENCE_INCHES,
    )
except ModuleNotFoundError:  # Direct entry point: python main/kneespa.py
    from config.constants import CALIBRATION_AXES, CALIBRATION_DISTANCE_REFERENCE_INCHES


def angle_key(angle: float) -> str:
    """Use one key spelling so recapturing 0 replaces both '0' and '0.0'."""
    return f"{float(angle):.1f}"


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


class CalibrationDraft:
    """Keep operator edits separate from the live configuration until Save."""

    def __init__(self, config: object) -> None:
        self.marks = {
            axis: {angle_key(float(k)): int(v) for k, v in getattr(config, spec["table"]).items()}
            for axis, spec in CALIBRATION_AXES.items()
        }
        self.factors = {
            axis: int(getattr(config, spec["factor"]))
            for axis, spec in CALIBRATION_AXES.items()
        }
        self.original_marks = copy.deepcopy(self.marks)
        self.original_factors = dict(self.factors)
        self.recorded = {axis: set() for axis in CALIBRATION_AXES}

    @property
    def dirty(self) -> bool:
        """Whether there are values to save."""
        return self.marks != self.original_marks or self.factors != self.original_factors

    def record(self, axis: str, angle: float, position: int) -> None:
        """Associate an independently measured angle with settled feedback."""
        spec = CALIBRATION_AXES[axis]
        low, high = spec["angle_limits"]
        if not math.isfinite(angle) or not low <= angle <= high:
            raise ValueError(f"Measured angle must be between {low} and {high} degrees.")
        low, high = spec["position_limits"]
        if not low <= position <= high:
            raise ValueError(f"Position must be between {low} and {high} counts.")
        key = angle_key(angle)
        self.marks[axis][key] = position
        self.recorded[axis].add(key)

    def validate(self) -> None:
        """Validate edited tables without rewriting untouched device geometry."""
        for axis, spec in CALIBRATION_AXES.items():
            if self.marks[axis] != self.original_marks[axis]:
                pairs = sorted((float(k), v) for k, v in self.marks[axis].items())
                low, high = spec["angle_limits"]
                if len(pairs) < 2 or pairs[0][0] != low or pairs[-1][0] != high:
                    raise ValueError(f"{spec['label']}: record both {low}° and {high}° endpoints.")
                if not all(math.isfinite(a) and low <= a <= high for a, _ in pairs):
                    raise ValueError(f"{spec['label']}: angle outside the allowed range.")
                positions = [p for _, p in pairs]
                low, high = spec["position_limits"]
                if not all(low <= p <= high for p in positions):
                    raise ValueError(f"{spec['label']}: position outside firmware limits.")
                deltas = [b - a for a, b in zip(positions, positions[1:])]
                if not (all(d > 0 for d in deltas) or all(d < 0 for d in deltas)):
                    raise ValueError(f"{spec['label']}: positions must follow angle order.")
            if not 1 <= self.factors[axis] <= 1000000:
                raise ValueError(f"{spec['label']}: factor must be between 1 and 1,000,000.")

    def save(self, config: object) -> Optional[str]:
        """Back up and atomically replace changed sections; propagate write errors.

        Live data is updated only after a successful write. Unrelated settings,
        including load-cell calibration and axial marks, are preserved.
        """
        self.validate()
        if not self.dirty:
            return None
        candidate = copy.deepcopy(config.config)
        changed: Dict[str, object] = {}
        for axis, spec in CALIBRATION_AXES.items():
            if self.marks[axis] != self.original_marks[axis]:
                candidate[spec["table"]] = {k: str(v) for k, v in self.marks[axis].items()}
                changed[spec["table"]] = dict(self.marks[axis])
            if self.factors[axis] != self.original_factors[axis]:
                if not candidate.has_section("Options"):
                    candidate.add_section("Options")
                candidate.set("Options", spec["factor"], str(self.factors[axis]))
                changed[spec["factor"]] = self.factors[axis]
        backup = None
        if os.path.isfile(config.configFile):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = f"{config.configFile}.{stamp}.bak"
            shutil.copy2(config.configFile, backup)
        config._atomic_write(candidate)
        config.config = candidate
        for attr, value in changed.items():
            setattr(config, attr, value)
        # Preserve existing calibration-confidence errors; editing B/C alone
        # must never certify fallback axial geometry or load-cell calibration.
        config._validate_calibration()
        self.original_marks = copy.deepcopy(self.marks)
        self.original_factors = dict(self.factors)
        return backup
