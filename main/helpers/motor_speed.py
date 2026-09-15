"""Shared validation for treatment motor output settings."""

import math
from typing import Dict, Mapping, Optional

try:
    from main.config.constants import MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN
except ModuleNotFoundError:  # python main/kneespa.py
    from config.constants import MOTOR_SPEED_DEFAULTS, MOTOR_SPEED_MAX, MOTOR_SPEED_MIN


def motor_speed_values(values: Optional[Mapping[str, float]] = None) -> Dict[str, int]:
    """Validate complete output percentages, filling missing keys with defaults."""
    result = dict(MOTOR_SPEED_DEFAULTS)
    for key, default in result.items():
        value = float((values or {}).get(key, default))
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"Invalid {key}: expected an integer percentage")
        if not MOTOR_SPEED_MIN <= value <= MOTOR_SPEED_MAX:
            raise ValueError(f"Invalid {key}: outside motor output limits")
        result[key] = int(value)
    return result


def motor_speed_command(values: Mapping[str, float]) -> str:
    """Encode one atomic axial/lateral/pulsation configuration command."""
    validated = motor_speed_values(values)
    return "V" + ",".join(str(validated[key]) for key in MOTOR_SPEED_DEFAULTS)
