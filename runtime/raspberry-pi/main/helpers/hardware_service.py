"""Measured hardware calibration drafts, validation and atomic persistence."""

import copy
import math
import os
import shutil
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Tuple

try:
    from main.config.constants import SERVICE_AXES
except ModuleNotFoundError:  # Direct execution of main/kneespa.py
    from config.constants import SERVICE_AXES

from config.config import MIN_PLAUSIBLE_SCALE_FACTOR


def _finite(value: object, label: str) -> float:
    """Return a finite numeric value without accepting boolean measurements."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{label} must be a finite number.") from error
    if isinstance(value, bool) or not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number.")
    return result


def _measurement_key(value: float) -> str:
    """Canonicalize numeric keys without rounding measured values."""
    return str(float(value))


def _position(value: object, limits: Tuple[int, int]) -> int:
    """Validate feedback in counts before converting it to an integer."""
    number = _finite(value, "Position")
    if not number.is_integer() or not limits[0] <= number <= limits[1]:
        raise ValueError(f"Position must be an integer from {limits[0]} to {limits[1]} counts.")
    return int(number)


def validate_axis_marks(axis: str, marks: Mapping[str, int]) -> List[Tuple[float, int]]:
    """Check endpoint coverage, sensor limits and the order of measured marks."""
    spec = SERVICE_AXES[axis]
    low, high = spec["measurement_limits"]
    pairs = sorted(
        (_finite(key, "Measured value"), _position(value, spec["position_limits"]))
        for key, value in marks.items()
    )
    if len(pairs) < 2 or pairs[0][0] != low or pairs[-1][0] != high:
        raise ValueError(f"{spec['label']}: record both {low} and {high} {spec['unit']} endpoints.")
    if any(not low <= measured <= high for measured, _ in pairs):
        raise ValueError(f"{spec['label']}: measured value outside the allowed range.")
    if len({measured for measured, _ in pairs}) != len(pairs):
        raise ValueError(f"{spec['label']}: duplicate measured values.")
    deltas = [right[1] - left[1] for left, right in zip(pairs, pairs[1:])]
    increasing = all(delta > 0 for delta in deltas)
    decreasing = all(delta < 0 for delta in deltas)
    if not increasing and (axis == "axial" or not decreasing):
        order = "increase with distance" if axis == "axial" else "follow measured angle order"
        raise ValueError(f"{spec['label']}: positions must strictly {order}.")
    return pairs


def axial_position(marks: Mapping[str, int], inches: float) -> int:
    """Interpolate validated axial marks without extrapolating outside travel."""
    measured = _finite(inches, "Axial distance")
    pairs = validate_axis_marks("axial", marks)
    if not pairs[0][0] <= measured <= pairs[-1][0]:
        raise ValueError("Axial distance must be between 0 and 4 inches.")
    for index, (distance, position) in enumerate(pairs):
        if measured == distance:
            return position
        if measured < distance:
            previous_distance, previous_position = pairs[index - 1]
            fraction = (measured - previous_distance) / (distance - previous_distance)
            return round(previous_position + fraction * (position - previous_position))
    raise ValueError("Axial distance has no calibrated position.")


def load_cell_factor(unloaded_raw: float, loaded_raw: float, known_lbs: float) -> float:
    """Calculate signed HX711 counts per pound from an unloaded and reference reading."""
    unloaded = _finite(unloaded_raw, "Unloaded reading")
    loaded = _finite(loaded_raw, "Loaded reading")
    reference = _finite(known_lbs, "Reference load")
    # HX711 measurements are signed 24-bit ADC counts. Rails indicate a bad
    # measurement even though they are representable by the converter.
    if not all(-8388608 < value < 8388607 for value in (unloaded, loaded)):
        raise ValueError("Raw load-cell reading is at or outside the ADC limits.")
    if reference <= 0:
        raise ValueError("Use a positive independently measured reference load in pounds.")
    if abs(loaded - unloaded) < 1000:
        raise ValueError("The loaded and unloaded readings must differ by at least 1000 counts.")
    factor = (loaded - unloaded) / reference
    _validate_scale(factor)
    return factor


def _validate_scale(value: float) -> None:
    """Reject nonfinite and implausible counts-per-pound factors."""
    scale = _finite(value, "Load-cell factor")
    if not MIN_PLAUSIBLE_SCALE_FACTOR <= abs(scale) <= 100000000:
        raise ValueError(
            f"Load-cell factor magnitude must be between {MIN_PLAUSIBLE_SCALE_FACTOR:g} "
            "and 100,000,000 counts per pound."
        )


class HardwareServiceDraft:
    """Keep measurements out of the live configuration until reviewed and saved."""

    def __init__(self, config: object) -> None:
        self.marks = {
            axis: {
                _measurement_key(float(key)): value
                for key, value in getattr(config, spec["table"]).items()
            }
            for axis, spec in SERVICE_AXES.items()
        }
        self.factors = {
            axis: getattr(config, spec["factor"]) for axis, spec in SERVICE_AXES.items()
        }
        self.scale = config.calibration
        self.original_marks = copy.deepcopy(self.marks)
        self.original_factors = dict(self.factors)
        self.original_scale = self.scale
        self.recorded = {axis: set() for axis in SERVICE_AXES}
        self._axial_calibrated = bool(getattr(config, "axial_service_calibrated", False))

    @property
    def dirty(self) -> bool:
        """Whether reviewed values or a newly measured axial table need saving."""
        return bool(
            self.marks != self.original_marks or self.factors != self.original_factors
            or self.scale != self.original_scale or self._enabling_axial
        )

    @property
    def _enabling_axial(self) -> bool:
        return not self._axial_calibrated and bool(self.recorded["axial"])

    def record(self, axis: str, measured: float, position: int) -> None:
        """Associate an operator measurement with settled position feedback."""
        spec = SERVICE_AXES[axis]
        value = _finite(measured, "Measured value")
        low, high = spec["measurement_limits"]
        if not low <= value <= high:
            raise ValueError(f"Measured value must be between {low} and {high} {spec['unit']}.")
        feedback = _position(position, spec["position_limits"])
        key = _measurement_key(value)
        self.marks[axis][key] = feedback
        self.recorded[axis].add(key)

    def validate(self) -> None:
        """Validate changes while retaining untouched device-specific geometry."""
        for axis, spec in SERVICE_AXES.items():
            edited = self.marks[axis] != self.original_marks[axis]
            if edited or (axis == "axial" and self._enabling_axial):
                validate_axis_marks(axis, self.marks[axis])
                if axis == "axial" and not self._axial_calibrated:
                    if not {"0.0", "4.0"}.issubset(self.recorded["axial"]):
                        raise ValueError("Axial: capture measured 0 and 4 inch endpoints first.")
            factor = _finite(self.factors[axis], f"{spec['label']} distance factor")
            if not factor.is_integer() or not 1 <= factor <= 1000000:
                raise ValueError(f"{spec['label']}: factor must be an integer from 1 to 1,000,000.")
        if self.scale != self.original_scale:
            _validate_scale(self.scale)

    def changes(self) -> List[Tuple[str, str, str]]:
        """Return setting, previous value and proposed value for operator review."""
        changes = []
        for axis, spec in SERVICE_AXES.items():
            before = self.original_marks[axis]
            after = self.marks[axis]
            for key in sorted(set(before) | set(after), key=float):
                if before.get(key) != after.get(key):
                    changes.append((
                        f"{spec['label']} {key} {spec['unit']}",
                        str(before.get(key, "—")), str(after.get(key, "—")),
                    ))
            if self.factors[axis] != self.original_factors[axis]:
                changes.append((
                    f"{spec['label']} distance readout factor (counts / 6 in)",
                    str(self.original_factors[axis]), str(self.factors[axis]),
                ))
        if self.scale != self.original_scale:
            changes.append(("Load-cell factor (counts / lb)", str(self.original_scale),
                            str(self.scale)))
        if self._enabling_axial:
            changes.append(("Use measured axial positions", "Disabled", "Enabled"))
        return changes

    def save(self, config: object) -> Optional[str]:
        """Back up the prior file and atomically publish only reviewed changes.

        Any validation, backup or write failure leaves live settings untouched.
        Unrelated parser sections and calibration confidence errors are retained.
        """
        self.validate()
        if not self.dirty:
            return None
        candidate = copy.deepcopy(config.config)
        if not candidate.has_section("Options"):
            candidate.add_section("Options")
        changed: Dict[str, object] = {}
        for axis, spec in SERVICE_AXES.items():
            if self.marks[axis] != self.original_marks[axis] or (
                axis == "axial" and self._enabling_axial
            ):
                candidate[spec["table"]] = {
                    key: str(value) for key, value in self.marks[axis].items()
                }
                changed[spec["table"]] = dict(self.marks[axis])
            if self.factors[axis] != self.original_factors[axis]:
                candidate.set("Options", spec["factor"], str(int(self.factors[axis])))
                changed[spec["factor"]] = int(self.factors[axis])
        if self._enabling_axial:
            candidate.set("Options", "axial_service_calibrated", "True")
            changed["axial_service_calibrated"] = True
        if self.scale != self.original_scale:
            candidate.set("Options", "calibration", str(float(self.scale)))
            changed["calibration"] = float(self.scale)
        backup = None
        if os.path.isfile(config.configFile):
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            backup = f"{config.configFile}.{stamp}.bak"
            shutil.copy2(config.configFile, backup)
        config._atomic_write(candidate)
        config.config = candidate
        for attribute, value in changed.items():
            setattr(config, attribute, value)
        config._validate_calibration()
        self.original_marks = copy.deepcopy(self.marks)
        self.original_factors = dict(self.factors)
        self.original_scale = self.scale
        self._axial_calibrated = bool(getattr(config, "axial_service_calibrated", False))
        return backup
