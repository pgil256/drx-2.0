"""Validated typed diagnostics for the explicit-tare firmware contract."""
import math
import re


HX711_PROTOCOL_DRIVER = "DRX-HX711-NB2"


def _number(value, nonzero=False):
    if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("Invalid numeric spelling")
    result = float(value)
    if not math.isfinite(result) or (nonzero and result == 0):
        raise ValueError("Invalid finite numeric value")
    return result


def _integer(value, low, high):
    if not re.fullmatch(r"-?[0-9]+", value):
        raise ValueError("Invalid integer")
    result = int(value)
    if not low <= result <= high:
        raise ValueError("Integer outside protocol range")
    return result


def _label(value):
    if not re.fullmatch(r"[A-Za-z0-9_.+:-]{1,96}", value):
        raise ValueError("Invalid protocol label")
    return value


def parse_diagnostic_frame(frame):
    """Return (signal name, dict), None for unrelated frames, or raise ValueError.

    These replies report evidence, not a generic motion completion. In particular,
    a NOTICE never becomes a safety fault or a command to stop the machine.
    """
    parts = frame.split("|")
    if parts[0] == "MOTION_DONE":
        if len(parts) != 4 or parts[1] not in ("P", "I", "K", "A"):
            raise ValueError("Malformed motion completion")
        if parts[1] == "P":
            target, actual = _number(parts[2]), _number(parts[3])
        else:
            target, actual = (_integer(value, 0, 4095) for value in parts[2:])
        maximum = 100 if parts[1] == "P" else 4095
        if not 0 <= target <= maximum or not 0 <= actual <= maximum:
            raise ValueError("Motion completion outside feedback range")
        return "motion_done", {"kind": parts[1], "target": target, "actual": actual}
    if parts[0] == "FAULT":
        if len(parts) != 4:
            raise ValueError("Malformed controller fault")
        return "fault_emit", {"reason": _label(parts[1]),
                              "target": _number(parts[2]), "pressure": _number(parts[3])}
    if parts[0] == "CALIBRATION":
        if len(parts) == 3 and parts[1] == "SET":
            return "calibration_result", {"operation": "set", "status": "ok",
                                           "factor": _number(parts[2], nonzero=True)}
        if len(parts) >= 3 and parts[1] == "TARE":
            status = parts[2]
            result = {"operation": "tare", "status": status.lower()}
            if status == "STARTED" and len(parts) == 3:
                return "calibration_result", result
            if status == "OK" and len(parts) == 5:
                result.update(offset=_integer(parts[3], -8388608, 8388607),
                              factor=_number(parts[4], nonzero=True))
                return "calibration_result", result
            if status in ("REJECTED", "CANCELLED") and len(parts) == 4:
                result["reason"] = _label(parts[3])
                return "calibration_result", result
        raise ValueError("Malformed calibration response")
    if parts[0] == "DIAG":
        if len(parts) >= 2 and parts[1] == "HARDWARE":
            if len(parts) != 7 or any(value not in ("0", "1") for value in parts[2:]):
                raise ValueError("Malformed hardware diagnostics")
            fields = ("a_ok", "b_ok", "c_ok", "stop_pressed", "fit_active")
            return "hardware_diagnostics", dict(zip(fields, (value == "1" for value in parts[2:])))
        if len(parts) != 10 or parts[1] != "HX711":
            raise ValueError("Malformed HX711 diagnostics")
        values = {"raw": _integer(parts[2], -8388608, 8388607),
                  "offset": _integer(parts[3], -8388608, 8388607),
                  "factor": _number(parts[4], nonzero=True),
                  "signed_lb": _number(parts[5]),
                  "age_ms": _integer(parts[6], -1, 4294967295),
                  "max_gap_ms": _integer(parts[7], 0, 4294967295),
                  "read_us": _integer(parts[8], 0, 4294967295),
                  "ready": bool(_integer(parts[9], 0, 1))}
        values["valid"] = values["age_ms"] >= 0
        return "sensor_diagnostics", values
    if parts[0] == "FIRMWARE":
        if len(parts) != 3:
            raise ValueError("Malformed firmware identity")
        return "firmware_identity", {"version": _label(parts[1]), "driver": _label(parts[2])}
    if parts[0] == "NOTICE":
        if len(parts) != 5 or parts[1] != "PRESSURE_NO_PROGRESS":
            raise ValueError("Malformed pressure notice")
        pressure = _number(parts[4])
        if pressure < 0:
            raise ValueError("Negative reported pressure")
        return "pressure_warning", {"reason": parts[1],
                                    "travel_counts": _integer(parts[2], 0, 65535),
                                    "rise_lb": _number(parts[3]), "pressure_lb": pressure}
    if parts[0] == "COMMAND_REJECTED":
        if len(parts) != 3:
            raise ValueError("Malformed command rejection")
        return "command_rejected", {"command": _label(parts[1]), "reason": _label(parts[2])}
    return None
