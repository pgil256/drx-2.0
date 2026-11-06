"""Read-only presentation of controller state; no motion or lifecycle transitions."""

from dataclasses import dataclass
from typing import Callable, Set

# Targets whose last update failed. A target that keeps failing (the
# treatment progress updates every second) logs one traceback, not one
# per call, until it succeeds again.
_failing: Set[str] = set()


def present(logger, target: str, update: Callable[[], object]) -> bool:
    """Run a UI update; log a failure and carry on.

    Display problems must never delay or break safety work, so nothing is
    re-raised. ``update`` is a zero-argument callable, so a missing widget
    attribute is caught here too. Returns whether the update ran.
    """
    try:
        update()
    except Exception:
        if target not in _failing:
            _failing.add(target)
            logger.exception("Could not update %s", target)
        return False
    _failing.discard(target)
    return True


@dataclass(frozen=True)
class DevicePresentation:
    label: str
    detail: str
    can_start: bool = False


def device_presentation(
    connected: bool, protocol_state: str, resetting: bool, initialized: bool,
    calibrated: bool, physical_stop: bool,
) -> DevicePresentation:
    """Describe existing conditions without equating connectivity with readiness."""
    if physical_stop:
        return DevicePresentation("Physical stop active", "Follow the device recovery procedure.")
    if not connected:
        return DevicePresentation(
            "Controller offline", "No controller connection · software commands may not reach the device."
        )
    if resetting:
        return DevicePresentation("Resetting", "Device homing in progress · wait for completion.")
    if protocol_state == "fault":
        return DevicePresentation("Recovery required", "Review the fault before resetting the device.")
    if protocol_state == "starting":
        return DevicePresentation("Preparing", "Centering and preparing the treatment.")
    if protocol_state == "stopping":
        return DevicePresentation("Stopping / recovering", "Stop requested · release and recovery pending.")
    if protocol_state == "running":
        return DevicePresentation("Treatment active", "Duration and motor speeds are locked.")
    if not calibrated:
        return DevicePresentation("Calibration required", "Technician service is required before treatment.")
    if not initialized:
        return DevicePresentation("Preparing", "Waiting for device initialization.")
    return DevicePresentation("Ready", "Review settings and patient positioning before starting.", True)
