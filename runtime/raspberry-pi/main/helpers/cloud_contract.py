"""Validate the device API contract before patient settings reach controls.

The wire field ``pulse_rate_hz`` means pulses per second. It is kept for API
compatibility; there is no unit conversion. Unsupported values are rejected,
never rounded or clamped into a different treatment plan.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Tuple
from uuid import UUID

try:
    from main.config.constants import PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN
except ModuleNotFoundError:
    from config.constants import PROTOCOL_MINUTES_MAX, PROTOCOL_MINUTES_MIN


# API field: (control key, minimum, maximum, increment).
SETTING_RULES = {
    "duration_min": ("duration", PROTOCOL_MINUTES_MIN, PROTOCOL_MINUTES_MAX, "1"),
    "max_pressure_lb": ("max_pressure", 10, 80, "1"),
    "max_left_deg": ("max_left", 0, 20, "1"),
    "max_right_deg": ("max_right", 0, 20, "1"),
    "pulse_rate_hz": ("pulse_rate", 0, 5, "0.2"),
}


def contract_number(value: Any, minimum: int, maximum: int, step: str) -> Decimal:
    """Return a finite, representable number or reject the entire setting."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Expected a number")
    try:
        number = Decimal(str(value))
        if (
            not number.is_finite()
            or not minimum <= number <= maximum
            or (number - minimum) % Decimal(step) != 0
        ):
            raise ValueError("Value is outside the supported range or increment")
        return number
    except InvalidOperation as exc:
        raise ValueError("Invalid number") from exc


def validate_patient(response: Any) -> Tuple[Dict[str, Any], Dict[str, float], int]:
    """Validate identity and every treatment field before changing the UI."""
    if not isinstance(response, dict) or not isinstance(response.get("settings"), dict):
        raise ValueError("Missing patient settings")
    try:
        patient_id = str(UUID(response["patient_id"]))
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid patient identity") from exc
    for field in ("display_name", "external_ref"):
        if response.get(field) is not None and not isinstance(response[field], str):
            raise ValueError("Invalid patient identity")
    settings = response["settings"]
    try:
        protocol = int(contract_number(settings["protocol_number"], 1, 4, "1"))
        values = {
            key: float(contract_number(settings[field], low, high, step))
            for field, (key, low, high, step) in SETTING_RULES.items()
        }
    except (KeyError, ValueError) as exc:
        raise ValueError("Patient settings need correction in the cloud dashboard") from exc
    patient = dict(response, patient_id=patient_id, settings=dict(settings))
    return patient, values, protocol


def end_settings(values: Dict[str, Any]) -> Dict[str, float]:
    """Capture positive angle magnitudes and the exact requested pulse rate."""
    return {
        field: float(contract_number(values[key], low, high, step))
        for field, (key, low, high, step) in SETTING_RULES.items()
        if field != "duration_min"
    }


def cloud_error_message(result: Any) -> str:
    """Translate transport errors without displaying remote bodies or secrets."""
    error = result.get("error") if isinstance(result, dict) else "unavailable"
    if not isinstance(error, str):
        error = "invalid_response"
    messages = {
        "disabled": "Cloud not configured",
        "invalid_pin": "Enter four digits for the patient PIN",
        "unknown_pin": "Patient PIN not found or inactive",
        "settings_not_supported": "Patient settings need correction in the cloud dashboard",
        "unauthorized": "Cloud device credentials need attention",
        "forbidden": "Cloud device access revoked",
        "validation_error": "Cloud rejected the record; review device configuration",
        "client_record_conflict": "Cloud record conflict; contact support",
        "invalid_response": "Cloud returned an invalid response",
        "queue_error": "Treatment record could not be saved; contact support",
    }
    if error == "rate_limited":
        return f"Too many requests. Try again in {result.get('retry_after_s', 60)} seconds"
    return messages.get(error, "Cloud unavailable; please try again")
