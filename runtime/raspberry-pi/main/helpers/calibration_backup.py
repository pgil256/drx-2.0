"""Device-bound calibration backups that preserve unrelated configuration."""

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from main.config.constants import SERVICE_AXES
from helpers.device_records import read_json, write_json
from helpers.hardware_service import validate_axis_marks, _validate_scale


class CalibrationBackups:
    """Back up only calibration, with validation and an automatic pre-restore backup."""

    def __init__(self, state_dir: Path) -> None:
        self.directory = state_dir / "calibration-backups"

    def create(self, config: object, operator: str) -> Path:
        payload = {
            "schema": 1, "device_id": config.ensure_device_id(),
            "created_at": datetime.now(timezone.utc).isoformat(), "operator": operator,
            "marks": {axis: copy.deepcopy(getattr(config, spec["table"]))
                      for axis, spec in SERVICE_AXES.items()},
            "factors": {
                axis: getattr(config, spec["factor"]) for axis, spec in SERVICE_AXES.items()
            },
            "scale": config.calibration,
            "axial_service_calibrated": bool(config.axial_service_calibrated),
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.directory / f"calibration-{stamp}.json"
        write_json(path, payload)
        return path

    def list(self) -> List[str]:
        return [p.name for p in sorted(self.directory.glob("calibration-*.json"), reverse=True)
                if p.is_file() and not p.is_symlink()][:200]

    def load(self, name: str, config: object) -> Dict[str, Any]:
        if name not in self.list():
            raise ValueError("Select an existing calibration backup.")
        data = read_json(self.directory / name)
        if not isinstance(data, dict):
            raise ValueError("Invalid calibration backup.")
        if type(data.get("schema")) is not int or data["schema"] != 1:
            raise ValueError("Unsupported calibration backup format.")
        if data.get("device_id") != config.ensure_device_id():
            raise ValueError("This calibration backup belongs to a different device.")
        if type(data.get("axial_service_calibrated")) is not bool:
            raise ValueError("The backup's calibration state is invalid.")
        if not isinstance(data.get("marks"), dict) or not isinstance(data.get("factors"), dict):
            raise ValueError("Invalid calibration backup values.")
        for axis in SERVICE_AXES:
            marks = data.get("marks", {}).get(axis)
            if not isinstance(marks, dict) or not all(type(v) is int for v in marks.values()):
                raise ValueError("Invalid calibration position marks.")
            validate_axis_marks(axis, marks)
            factor = data.get("factors", {}).get(axis)
            if type(factor) is not int or not 1 <= factor <= 1000000:
                raise ValueError("Invalid calibration factor.")
        if type(data.get("scale")) not in (int, float):
            raise ValueError("Invalid load-cell calibration factor.")
        _validate_scale(data["scale"])
        if not isinstance(data.get("created_at"), str) or not isinstance(data.get("operator"), str):
            raise ValueError("Invalid calibration backup metadata.")
        return data

    def restore(self, name: str, config: object, operator: str,
                reviewed: Optional[Dict[str, Any]] = None) -> Path:
        data = self.load(name, config)
        if reviewed is not None and data != reviewed:
            raise ValueError("The backup changed. Review it again before restoring.")
        backup = self.create(config, operator)
        candidate = copy.deepcopy(config.config)
        for axis, spec in SERVICE_AXES.items():
            candidate[spec["table"]] = {str(k): str(v) for k, v in data["marks"][axis].items()}
            candidate.set("Options", spec["factor"], str(data["factors"][axis]))
        candidate.set("Options", "calibration", str(data["scale"]))
        candidate.set("Options", "axial_service_calibrated", str(data["axial_service_calibrated"]))
        config._atomic_write(candidate)
        config.config = candidate
        for axis, spec in SERVICE_AXES.items():
            setattr(config, spec["table"], dict(data["marks"][axis]))
            setattr(config, spec["factor"], data["factors"][axis])
        config.calibration = data["scale"]
        config.axial_service_calibrated = data["axial_service_calibrated"]
        config._validate_calibration()
        return backup
