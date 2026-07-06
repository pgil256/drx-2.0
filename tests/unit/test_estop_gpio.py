# tests/unit/test_estop_gpio.py
"""B3: the emergency-stop path drives the hardware EMERGENCYSTOP GPIO line.

Hazard: a serial-only e-stop silently does nothing when the link is down.
Acceptance: the GPIO line is asserted (LOW) before - and independent of -
the serial 'X'; it is released (HIGH) again before the recovery reset,
which needs a powered machine to home the actuators.
"""
import pytest
from unittest.mock import MagicMock

import controllers.protocol_controller as pc_mod
from controllers.protocol_controller import ProtocolController
from config.constants import EMERGENCYSTOP


class RecordingWindow:
    """Stub window that records the order of stop-path calls."""

    def __init__(self, events):
        self._events = events
        self.worker = MagicMock()
        self.worker.stop.side_effect = lambda: events.append("worker.stop")

    def stop_actuators(self):
        self._events.append("stop_actuators")

    def reset_arduino(self, event=None):
        self._events.append("reset_arduino")


@pytest.fixture
def estop_env(monkeypatch):
    events = []
    gpio = MagicMock()
    gpio.output.side_effect = lambda pin, level: events.append(("gpio", pin, level))
    monkeypatch.setattr(pc_mod, "GPIO", gpio)
    window = RecordingWindow(events)
    return events, gpio, ProtocolController(window), window


@pytest.mark.unit
class TestEmergencyStopGpio:
    def test_asserts_gpio_low_before_serial_x(self, qtbot, estop_env):
        """The hardware line goes LOW first: it must not depend on the
        serial link that the 'X' command needs."""
        events, gpio, controller, _ = estop_env
        controller.emergency_stop_clicked(None)
        assert events[0] == ("gpio", EMERGENCYSTOP, gpio.LOW)
        assert events[1] == "stop_actuators"

    def test_gpio_failure_does_not_block_serial_stop(self, qtbot, estop_env):
        """A GPIO error must never swallow the serial stop."""
        events, gpio, controller, _ = estop_env
        gpio.output.side_effect = RuntimeError("gpio unavailable")
        controller.emergency_stop_clicked(None)
        assert "stop_actuators" in events

    def test_phase2_stops_worker(self, estop_env):
        events, _, controller, _ = estop_env
        controller._emergency_stop_phase2()
        assert events == ["worker.stop"]

    def test_phase3_releases_gpio_then_resets(self, estop_env):
        """Recovery homing needs the machine powered: HIGH before reset."""
        events, gpio, controller, _ = estop_env
        controller._emergency_stop_phase3()
        assert events == [("gpio", EMERGENCYSTOP, gpio.HIGH), "reset_arduino"]

    def test_phase3_resets_even_if_gpio_release_fails(self, estop_env):
        events, gpio, controller, _ = estop_env
        gpio.output.side_effect = RuntimeError("gpio unavailable")
        controller._emergency_stop_phase3()
        assert "reset_arduino" in events
