"""Every kind of stop does what StopController's POLICIES table says (A2).

One test runs each kind against the controller-test window and checks the
commands it sends, whether it drives the EMERGENCYSTOP line first, the
DeviceState flags it sets (and that it sets no others), the screen it
leaves, the session outcome it latches and when it schedules the release.
The table cannot drift from the code without one of these failing. The
entry points that used to own each stop are checked to route through it.
"""
import threading
from types import MethodType
from unittest.mock import MagicMock

import pytest

import controllers.stop_controller as sc_mod
import kneespa
from config.constants import EMERGENCYSTOP
from controllers.device_state import WINDOW_ATTRIBUTES
from controllers.safety_monitor import SafetyMonitor
from controllers.stop_controller import (
    COMMAND_FAULT, ESTOP, FAULT, FIRMWARE_RELEASE_WAIT_S, OPERATOR, PHYSICAL, POLICIES,
    SHUTDOWN, firmware_release_pending, stops_for,
)
from fixtures.controllers import make_window

pytestmark = pytest.mark.unit

# The arguments each kind is run with in the table test.
OPTIONS = {
    OPERATOR: {},
    ESTOP: {},
    PHYSICAL: {},
    FAULT: {"reason": "Load cell fault", "fault": True},
    COMMAND_FAULT: {"message": "Invalid P value"},
    SHUTDOWN: {},
}


class RecordingArduino:
    """Records the serial calls a stop makes, in one list with the GPIO line."""

    def __init__(self, events):
        self._events = events
        self.baseline_valid = True
        self._connect_cancel = threading.Event()

    def send(self, command):
        self._events.append(("send", command))
        return True

    def cancel_pending_commands(self):
        self._events.append(("cancel_pending_commands",))


@pytest.fixture
def stopping(monkeypatch):
    """A running treatment, with the stop line and timers recorded, not run."""
    events = []
    gpio = MagicMock()
    gpio.output.side_effect = lambda pin, level: events.append(("gpio", pin, level))
    timer = MagicMock()
    monkeypatch.setattr(sc_mod, "GPIO", gpio)
    monkeypatch.setattr(sc_mod, "QTimer", timer)
    window = make_window("running")
    window.arduino = RecordingArduino(events)
    # The real stop_actuators, so the X it sends is recorded with the rest.
    window.stop_actuators = MethodType(kneespa.KneeSpa.stop_actuators, window)
    return window, events, gpio, timer


def device_flags(window):
    """The DeviceState fields, by field name, as the window holds them."""
    return {
        field: getattr(window, attribute, None)
        for attribute, field in WINDOW_ATTRIBUTES.items()
        if field != "protocol_state"
    }


def test_every_kind_has_a_policy():
    assert set(POLICIES) == {OPERATOR, ESTOP, PHYSICAL, FAULT, COMMAND_FAULT, SHUTDOWN}
    assert set(OPTIONS) == set(POLICIES)


@pytest.mark.parametrize("kind", sorted(POLICIES))
def test_each_kind_does_what_its_policy_says(stopping, kind):
    window, events, gpio, timer = stopping
    policy = POLICIES[kind]
    session = window.protocol._session
    before = device_flags(window)

    stops_for(window).stop(kind, **OPTIONS[kind])

    assert tuple(event[1] for event in events if event[0] == "send") == policy.commands
    line = [event for event in events if event[0] == "gpio"]
    if policy.hardware_line:
        # Low before anything else; high again only in the later phase.
        assert events[0] == ("gpio", EMERGENCYSTOP, gpio.LOW)
        assert line == [events[0]]
    else:
        assert line == []
    assert device_flags(window) == {**before, **policy.flags}
    screen = "running" if policy.screen == "unchanged" else policy.screen
    assert window.protocol_state == screen
    assert session.outcome == policy.outcome
    delays = [call[0][0] for call in timer.singleShot.call_args_list]  # 3.7: no .args
    assert delays == ([] if policy.release_after_ms is None else [policy.release_after_ms])


def test_a_fault_stop_without_a_fault_latches_stopped(stopping):
    window, events, _, _ = stopping
    session = window.protocol._session

    stops_for(window).stop(FAULT, reason="Pressure-progress Stop", fault=False)

    assert session.outcome == "stopped"
    window.treatment_panel.set_fault.assert_not_called()
    assert window.protocol_state == "fault"
    assert tuple(event[1] for event in events) == POLICIES[FAULT].commands


def test_the_shutdown_after_a_physical_stop_drops_queued_commands(stopping):
    window, events, _, _ = stopping
    window._physical_stop_active = True

    stops_for(window).stop(SHUTDOWN)

    # X would abort the firmware's own release, so nothing is sent.
    assert events == [("cancel_pending_commands",)]
    window.worker.cancel.assert_called_once_with(firmware_stopped=True)


def test_the_physical_stop_drops_queued_commands(stopping):
    window, events, _, _ = stopping

    stops_for(window).stop(PHYSICAL)

    assert events == [("cancel_pending_commands",)]
    window.worker.cancel.assert_called_once_with(firmware_stopped=True)


def test_the_physical_stop_is_latched_before_other_owners_are_cancelled(stopping):
    """A leg move cancelled by the stop sends X unless the latch is already set."""
    window, _, _, _ = stopping
    latched = []
    window.connection.cancel_reset = lambda: latched.append(window._physical_stop_active)

    stops_for(window).stop(PHYSICAL)

    assert latched == [True]


@pytest.mark.parametrize("kind", [OPERATOR, ESTOP, FAULT, COMMAND_FAULT])
def test_no_later_stop_sends_x_after_the_physical_stop(stopping, kind):
    """An on-screen Stop tapped after the button must not end the release."""
    window, events, _, _ = stopping
    stops_for(window).stop(PHYSICAL)
    events.clear()

    stops_for(window).stop(kind, **OPTIONS[kind])

    assert ("send", "X") not in events
    assert window._physical_stop_active is True


@pytest.mark.parametrize("latch", [FAULT, COMMAND_FAULT, PHYSICAL])
@pytest.mark.parametrize("kind", [OPERATOR, ESTOP])
def test_a_stop_after_a_latched_fault_leaves_the_fault(stopping, latch, kind):
    """The release phases never run for a latched fault, so "stopping" would
    never end, and that state refuses logout, exit and restart."""
    window, events, gpio, timer = stopping
    stops_for(window).stop(latch, **OPTIONS[latch])
    assert window.protocol_state == "fault"
    events.clear()
    timer.reset_mock()
    window.worker.cancel.reset_mock()

    stops_for(window).stop(kind, **OPTIONS[kind])

    assert window.protocol_state == "fault"
    assert window.protocol_running is False
    assert window.protocol.block_active_treatment_exit() is False
    timer.singleShot.assert_not_called()
    # It is still a stop: the producer is cancelled and the outputs are stopped.
    window.worker.cancel.assert_called_once_with()
    if kind == ESTOP:
        assert events[0] == ("gpio", EMERGENCYSTOP, gpio.LOW)
    if latch != PHYSICAL:
        assert ("send", "X") in events


def test_reset_is_held_while_the_firmware_releases(stopping):
    """Reset sends Y, which ends the release, and homes the axial actuator last."""
    window, _, _, timer = stopping

    stops_for(window).stop(PHYSICAL, release_started=True)

    assert firmware_release_pending(window)
    window.shell.setup.set_reset_enabled.assert_called_with(False)
    delays = [call[0][0] for call in timer.singleShot.call_args_list]
    assert delays == [int(FIRMWARE_RELEASE_WAIT_S * 1000)]


@pytest.mark.parametrize("ending", ["released", "incomplete", "no result"])
def test_reset_is_offered_once_the_firmware_release_ends(stopping, ending):
    window, _, _, timer = stopping
    safety = SafetyMonitor(window)
    safety.on_firmware_error("Stop button pressed")
    assert firmware_release_pending(window)
    window.shell.setup.set_reset_enabled.reset_mock()

    if ending == "released":
        safety.on_pressure_released()
    elif ending == "incomplete":
        safety.on_firmware_error("Release incomplete")
    else:
        timer.singleShot.call_args[0][1]()  # the bound passes with no result

    assert not firmware_release_pending(window)
    window.shell.setup.set_reset_enabled.assert_called_with(True)


def test_a_refused_command_while_the_button_is_held_does_not_hold_reset(stopping):
    """ "Stop button engaged" starts no release, so there is nothing to wait for."""
    window, _, _, timer = stopping

    SafetyMonitor(window).on_firmware_error("Stop button engaged")

    assert window._physical_stop_active is True
    assert not firmware_release_pending(window)
    window.shell.setup.set_reset_enabled.assert_called_with(True)
    timer.singleShot.assert_not_called()


def test_the_timer_of_an_earlier_press_cannot_end_a_later_release(stopping, monkeypatch):
    window, _, _, timer = stopping
    clock = [100.0]
    monkeypatch.setattr(sc_mod.time, "monotonic", lambda: clock[0])
    stops_for(window).stop(PHYSICAL, release_started=True)
    first_timer = timer.singleShot.call_args[0][1]
    clock[0] += 15.0
    stops_for(window).stop(PHYSICAL, release_started=True)
    clock[0] += 5.0

    first_timer()

    assert firmware_release_pending(window)


def test_a_lost_timer_cannot_hold_reset_for_good(stopping, monkeypatch):
    window, _, _, _ = stopping
    clock = [100.0]
    monkeypatch.setattr(sc_mod.time, "monotonic", lambda: clock[0])
    stops_for(window).stop(PHYSICAL, release_started=True)

    clock[0] += FIRMWARE_RELEASE_WAIT_S

    assert not firmware_release_pending(window)


def _cleanup(window):
    window.arduino = None  # Stop polling at the transport; only the stop matters.
    kneespa.KneeSpa.cleanup(window)


@pytest.mark.parametrize("enter, kind, options", [
    pytest.param(lambda w: w.protocol.stop_protocol(), OPERATOR, {},
                 id="stop_protocol"),
    pytest.param(lambda w: w.protocol.emergency_stop_clicked(None), ESTOP,
                 {"outcome": "fault"}, id="emergency_stop_clicked"),
    pytest.param(lambda w: w.protocol.stop_without_recovery("Load cell fault", fault=True),
                 FAULT, {"reason": "Load cell fault", "fault": True},
                 id="stop_without_recovery"),
    pytest.param(lambda w: SafetyMonitor(w).on_physical_stop(), PHYSICAL,
                 {"release_started": False}, id="on_physical_stop"),
    pytest.param(lambda w: SafetyMonitor(w).on_firmware_error("Stop button pressed"),
                 PHYSICAL, {"release_started": True}, id="stop_button_notice"),
    pytest.param(lambda w: SafetyMonitor(w).on_firmware_error("Stop button engaged"),
                 PHYSICAL, {"release_started": False}, id="stop_button_refusal"),
    pytest.param(lambda w: SafetyMonitor(w).on_firmware_error("Invalid P value"),
                 COMMAND_FAULT, {"message": "Invalid P value"}, id="command_rejection"),
    pytest.param(_cleanup, SHUTDOWN, {}, id="cleanup"),
])
def test_the_old_entry_points_route_through_the_controller(monkeypatch, enter, kind, options):
    monkeypatch.setattr(kneespa, "GPIO", MagicMock())
    window = make_window("running")
    window.protocol.stops.stop = MagicMock()

    enter(window)

    window.protocol.stops.stop.assert_called_once_with(kind, **options)
    cloud_thread = getattr(window, "_cloud_close_thread", None)
    if cloud_thread is not None:
        cloud_thread.join(timeout=1)
