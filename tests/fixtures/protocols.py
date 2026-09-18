"""Shared offline protocol builders; real-thread integration uses FakeArduino."""

import threading
from typing import Any
from unittest.mock import MagicMock

from config.config import Configuration
from helpers.protocols import Protocols
from helpers.arduino import Arduino, CommandHandle


def make_arduino() -> MagicMock:
    """Expose only the serial operations and signals used by these unit tests."""
    arduino = MagicMock(spec_set=[
        "send", "send_tracked", "cancel_pending_commands", "disconnect",
        "verify_connection", "is_connected", "connected", "protocol_v2", "ready_event",
        "done_emit", "error_emit", "status_emit", "pressure_emit",
        "motion_done", "calibration_result", "zeros_emit", "ready_to_go_emit",
        "command_rejected", "fault_emit", "connection_lost", "firmware_driver",
        "baseline_valid", "_signal_owner",
    ])
    arduino.protocol_v2 = False
    arduino.firmware_driver = "DRX-HX711-NB2"
    arduino.baseline_valid = True
    arduino.connected = True
    arduino.ready_event = threading.Event()
    arduino.ready_event.set()
    arduino.send.return_value = True
    arduino.verify_connection.return_value = True
    arduino.is_connected.return_value = True
    arduino.disconnect.return_value = True
    signal_owner = Arduino()
    arduino._signal_owner = signal_owner
    for name in ("done_emit", "error_emit", "status_emit", "pressure_emit", "motion_done",
                 "calibration_result", "zeros_emit", "ready_to_go_emit", "command_rejected",
                 "fault_emit", "connection_lost"):
        signal = MagicMock(spec_set=["connect", "disconnect", "emit"])
        for method in ("connect", "disconnect", "emit"):
            getattr(signal, method).side_effect = getattr(getattr(signal_owner, name), method)
        setattr(arduino, name, signal)
    arduino.send_tracked.side_effect = lambda cmd: (CommandHandle(cmd)
                                                  if arduino.send(cmd) else None)
    return arduino


def make_protocol(*, acknowledge: bool = False, **kwargs: Any) -> Protocols:
    """Build a real worker with explicit transport acceptance and optional DONE.

    Missing-DONE tests retain real acknowledgement semantics by default. Only
    pressure ramp tests opt into synchronous DONE; no clock is changed here.
    """
    defaults = dict(
        a_factor=1900, protocol="1", max_pressure=50, max_left=10.0,
        max_right=10.0, duration=1, use_pulse=False, ser=None, config=None,
    )
    defaults.update(kwargs)
    if defaults["config"] is None:
        config = Configuration()
        config._set_default_c_marks()
        config._set_default_a_marks()
        config._set_default_b_marks()
        defaults["config"] = config
    if "ser" not in kwargs:
        defaults["ser"] = make_arduino()
    worker = Protocols(**defaults)
    if acknowledge:
        def send(command: str) -> object:
            if not worker.arduino.send(command):
                return None
            if command.startswith("P"):
                target = float(command[1:].split("|")[0])
                worker.arduino.motion_done.emit("P", target, target)
            elif command.startswith("K"):
                target = float(command[1:])
                worker.arduino.motion_done.emit("K", target, target)
            worker.arduino.done_emit.emit()
            return CommandHandle(command)

        worker.arduino.send_tracked.side_effect = send
    return worker
