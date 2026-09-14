"""Shared offline protocol builders; real-thread integration uses FakeArduino."""

import threading
from typing import Any
from unittest.mock import MagicMock

from config.config import Configuration
from helpers.protocols import Protocols


def make_arduino() -> MagicMock:
    """Expose only the serial operations and signals used by these unit tests."""
    arduino = MagicMock(spec_set=[
        "send", "send_tracked", "cancel_pending_commands", "disconnect",
        "verify_connection", "is_connected", "connected", "protocol_v2", "ready_event",
        "done_emit", "error_emit", "status_emit", "pressure_emit",
    ])
    arduino.protocol_v2 = False
    arduino.connected = True
    arduino.ready_event = threading.Event()
    arduino.ready_event.set()
    arduino.send.return_value = True
    arduino.verify_connection.return_value = True
    arduino.is_connected.return_value = True
    arduino.disconnect.return_value = True
    for name in ("done_emit", "error_emit", "status_emit", "pressure_emit"):
        setattr(arduino, name, MagicMock(spec_set=["connect", "disconnect", "emit"]))
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
        def send(command: str) -> bool:
            worker._on_firmware_done()
            return True

        worker.arduino.send.side_effect = send
    return worker
