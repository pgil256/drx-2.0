"""Device and lifecycle flags in one plain-Python owner (no Qt).

The window used to hold these as loose attributes, read through chains like
``getattr(window, "_calibration_active", False) is True``. ``DeviceState``
owns them and answers the questions those chains asked. The window keeps its
old attribute names: :class:`DeviceStateAttributes` turns each one into a
property that delegates here, so existing code, tests and the simulator keep
working while callers move to the methods.
"""

from typing import Dict, Optional


class DeviceState:
    """The flags that decide whether the device may move, reset or be left."""

    def __init__(self) -> None:
        self.closing = False
        self.calibration_active = False
        self.device_maintenance_active = False
        self.reset_in_progress = False
        self.actuator_command_in_progress = False
        self.physical_stop_active = False
        self.no_automatic_recovery = False
        self.protocol_state = "idle"
        self.initial_setup_complete = False

    def busy_reason(self) -> Optional[str]:
        """The work that must finish before leaving the screen, or None."""
        if self.device_maintenance_active is True or self.calibration_active is True:
            return "device service"
        if self.reset_in_progress is True:
            return "reset"
        if self.actuator_command_in_progress is True:
            return "movement"
        return None

    def can_exit(self) -> bool:
        """No device service, reset or movement is in progress.

        An active treatment is checked separately, by the protocol controller.
        """
        return self.busy_reason() is None

    def can_move(self) -> bool:
        """Manual motion controls may be enabled again.

        False while the app closes, during device service or a reset, before
        the first successful reset, and while a fault is latched. A physical
        stop and a stop without recovery both latch a fault, so they are
        covered. A command still in progress does not block this: completing
        that command is what re-enables the controls.
        """
        # Truthiness for the reset and setup flags, as the window always used.
        return not (
            self.closing is True
            or self.calibration_active is True
            or self.device_maintenance_active is True
            or self.reset_in_progress
            or not self.initial_setup_complete
            or self.protocol_state == "fault"
        )


# Window attribute -> DeviceState field. The names stay as they were.
WINDOW_ATTRIBUTES: Dict[str, str] = {
    "_closing": "closing",
    "_calibration_active": "calibration_active",
    "_device_maintenance_active": "device_maintenance_active",
    "reset_in_progress": "reset_in_progress",
    "actuator_command_in_progress": "actuator_command_in_progress",
    "_physical_stop_active": "physical_stop_active",
    "_no_automatic_recovery": "no_automatic_recovery",
    "protocol_state": "protocol_state",
    "initial_setup_complete": "initial_setup_complete",
}


def _delegate(field: str) -> property:
    def get(owner):
        return getattr(owner.device_state, field)

    def set_(owner, value):
        setattr(owner.device_state, field, value)

    return property(get, set_, doc=f"Delegates to DeviceState.{field}.")


class DeviceStateAttributes:
    """Mixin that exposes a ``DeviceState``'s flags under the window's names.

    The state is created on first use, so objects built without running
    ``__init__`` (test harnesses binding unbound window methods) work too.
    """

    @property
    def device_state(self) -> DeviceState:
        state = self.__dict__.get("_device_state")
        if state is None:
            state = DeviceState()
            self.__dict__["_device_state"] = state
        return state


for _attribute, _field in WINDOW_ATTRIBUTES.items():
    setattr(DeviceStateAttributes, _attribute, _delegate(_field))
del _attribute, _field
