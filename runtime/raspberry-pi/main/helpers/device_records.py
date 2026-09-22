"""Bounded device metadata, service history, and privacy-safe diagnostic exports."""

import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List
import zipfile


def read_json(path: Path, maximum: int = 512 * 1024) -> Any:
    """Read a regular bounded JSON file; never follow a selected symlink."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("The selected device record cannot be read.")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    """Atomically persist device-only state outside the software tree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".device-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class DeviceRecords:
    """Keep only operator preferences and derived diagnostic information."""

    def __init__(self, state_dir: Path) -> None:
        self.root = state_dir

    def preferences(self) -> Dict[str, int]:
        result = {"idle_dim_minutes": 0, "logout_minutes": 0}
        try:
            data = read_json(self.root / "device-settings.json")
            for key, choices in (("idle_dim_minutes", (0, 1, 2, 5, 10, 15, 30)),
                                 ("logout_minutes", (0, 1, 5, 10, 15, 30, 60))):
                timeout = data.get(key, 0)
                if type(timeout) is int and timeout in choices:
                    result[key] = timeout
        except (OSError, ValueError, AttributeError):
            pass
        return result

    def set_idle_timeout(self, minutes: int) -> None:
        if type(minutes) is not int or minutes not in (0, 1, 2, 5, 10, 15, 30):
            raise ValueError("Choose an available dimming timeout.")
        data = self.preferences()
        data["idle_dim_minutes"] = minutes
        write_json(self.root / "device-settings.json", data)

    def set_logout_timeout(self, minutes: int) -> None:
        if type(minutes) is not int or minutes not in (0, 1, 5, 10, 15, 30, 60):
            raise ValueError("Choose an available logout timeout.")
        data = self.preferences()
        data["logout_minutes"] = minutes
        write_json(self.root / "device-settings.json", data)

    def history(self) -> List[Dict[str, Any]]:
        """Summarize recorded observations without turning incomplete tests into passes."""
        rows = []
        paths = sorted((self.root / "service-reports").glob("hardware-*.json"), reverse=True)
        for path in paths[:200]:
            try:
                report = read_json(path)
                results = report.get("results", {})
                bench = report.get("bench_observations", {})
                statuses = [results.get(key, {}).get("status") for key in (
                    "preparation", "communication", "axial", "horizontal", "lateral", "leg",
                    "loadcell", "stops",
                )] + [bench.get(key, {}).get("status") for key in (
                    "pressure_control", "pressure_accuracy", "dynamic_stops", "watchdog",
                    "power_recovery", "limit_switches", "mechanical",
                )]
                result = ("Observed failure" if "fail" in statuses
                          else "All checks recorded as passed"
                          if all(s == "pass" for s in statuses)
                          else "Incomplete / skipped checks")
                mode = report.get("mode", "service")
                kind = "Calibration" if mode == "calibration" else "Hardware tests"
                if mode == "update":
                    kind = ("Software update" if report.get("platform") == "raspberry-pi"
                            else "Firmware update")
                    result = ("Installed" if report.get("installed") is True
                              else "Installation failed")
                if report.get("configuration_saved") is True:
                    result = ("Calibration restored; verify" if report.get("restored")
                              else "Calibration saved · " + result)
                rows.append({
                    "file": path.name, "date": str(report.get("updated_at", "Unknown")),
                    "operator": str(report.get("technician", "Unknown")),
                    "kind": kind,
                    "result": result,
                    "saved": report.get("configuration_saved") is True,
                })
            except (OSError, ValueError, TypeError, AttributeError):
                rows.append({
                    "file": path.name, "date": "Unknown", "operator": "Unknown",
                    "kind": "Unreadable report", "result": "Could not read", "saved": False,
                })
        return rows

    def report(self, name: str) -> Dict[str, Any]:
        if name != Path(name).name or not re.fullmatch(r"hardware-[\w-]+\.json", name):
            raise ValueError("Select an existing service report.")
        report = read_json(self.root / "service-reports" / name)
        if not isinstance(report, dict):
            raise ValueError("Invalid service report.")
        return report

    def diagnostic_bundle(self, context: Dict[str, Any]) -> Path:
        """Export allowlisted status plus categorized errors, never raw log messages."""
        allowed = ("device_id", "software_version", "firmware_version", "controller",
                   "device_state", "cloud", "pending_uploads", "last_sync")
        metadata = {key: context.get(key, "Unknown") for key in allowed}
        metadata["created_at"] = datetime.now(timezone.utc).isoformat()
        errors = []
        categories = (
            ("serial", "Serial communication"), ("arduino", "Controller communication"),
            ("heartbeat", "Heartbeat timeout"), ("sensor", "Sensor feedback"),
            ("pressure", "Pressure feedback"), ("upload", "Cloud upload"),
            ("smtp", "Support delivery"), ("calibration", "Calibration"),
            ("storage", "Device storage"),
        )
        paths = sorted((self.root / "logs").glob("python_*.log*"), reverse=True)
        for path in paths[:5]:
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as source:
                source.seek(max(0, path.stat().st_size - 128 * 1024))
                lines = source.read(128 * 1024).decode("utf-8", errors="replace").splitlines()
            for line in lines:
                match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ - "
                                 r"(ERROR|WARNING|CRITICAL) - ", line)
                if not match:
                    continue
                category = next((label for term, label in categories if term in line.lower()),
                                "Application error")
                errors.append({"at": match[1], "severity": match[2], "category": category})
        errors.sort(key=lambda entry: entry["at"])
        directory = self.root / "exports"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / ("diagnostics-" + datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ") + ".zip")
        with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("device.json", json.dumps(metadata, indent=2, allow_nan=False))
            archive.writestr("recent-errors.json", json.dumps(errors[-200:], indent=2))
            archive.writestr("README.txt", "Device status and categorized recent errors only.\n"
                             "No raw logs, patient data, passwords, tokens or PINs are included.\n")
        return path
