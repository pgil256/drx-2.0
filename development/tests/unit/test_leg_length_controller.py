"""FIT homing, command accounting, and interruption regressions without hardware."""

from unittest.mock import MagicMock

import pytest

from controllers import leg_length_controller as module
from controllers.connection_manager import ConnectionManager
from helpers.arduino import Arduino, CommandHandle
from kneespa import KneeSpa
from fixtures.controllers import make_window


pytestmark = pytest.mark.unit


@pytest.fixture(params=[False, True], ids=["legacy", "v2"])
def leg(request, qtbot, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    window = make_window()
    window.leg_length = 4.0
    window.arduino = Arduino()
    window.arduino.protocol_v2 = request.param
    window.arduino.send = MagicMock(return_value=True)
    handles = []

    def send(command):
        handle = CommandHandle(command)
        handles.append(handle)
        return handle

    window.arduino.send_tracked = MagicMock(side_effect=send)
    controller = module.LegLengthController(window)
    window.leg = controller
    yield controller, window, now, handles
    controller.cancel()


def complete(leg):
    controller, window, now, handles = leg
    handle = handles[-1]
    handle.written.set()
    controller._poll()
    now[0] += module.MOVES[handle.command][1] + 0.01
    handle.result = "DONE"
    handle.completed.set()
    window.arduino.done_emit.emit()
    controller._poll()


def home(leg):
    controller, window, _, handles = leg
    assert controller.home()
    complete(leg)
    assert controller.position is None
    assert controller.active
    assert [handle.command for handle in handles] == ["FR", "FR"]
    complete(leg)
    assert controller.position == window.leg_length == 0
    assert not controller.active
    assert not controller.boot_home_pending


def test_full_retract_required_before_zero(leg):
    home(leg)


def test_jogs_accumulate_only_on_completion(leg):
    controller, window, _, _ = leg
    home(leg)
    for command, expected in [("F+", 0.25), ("FF", 3.25), ("F-", 3.0), ("FR", 0.0)]:
        previous = controller.position
        assert controller.move(command)
        assert controller.position == previous
        assert not controller.move("F+")
        complete(leg)
        assert controller.position == expected
        window.shell.setup.set_leg_length_estimate.assert_called_with(
            expected, "From retracted zero",
        )


def test_gpio_waits_for_write_and_stops_without_reply(leg, monkeypatch):
    controller, _, now, handles = leg
    drive = MagicMock()
    monkeypatch.setattr(controller, "_drive", drive)
    controller.home()
    controller._poll()
    drive.assert_not_called()
    handles[-1].written.set()
    controller._poll()
    drive.assert_called_with(False)
    now[0] += 6.1
    controller._poll()
    drive.assert_called_with(None)
    assert controller.position is None
    now[0] += 3.1
    controller._poll()
    assert not controller.active
    assert controller.boot_home_pending


@pytest.mark.parametrize("interruption", ["cancel", "disconnect", "reject", "fault", "physical"])
def test_interrupted_home_never_sets_zero_or_runs_second_stroke(leg, interruption):
    controller, window, now, handles = leg
    callback = MagicMock()
    assert controller.home(callback)
    handles[-1].written.set()
    controller._poll()
    now[0] += 1
    if interruption == "cancel":
        controller.cancel()
    elif interruption == "disconnect":
        window.arduino.connection_lost.emit()
    elif interruption == "reject":
        window.arduino.command_rejected.emit({"command": "F", "reason": "BUSY"})
    elif interruption == "fault":
        window.arduino.fault_emit.emit({"reason": "ESTOP"})
    else:
        window._physical_stop_active = True
        controller._poll()
        window.arduino.send.assert_not_called()
    complete(leg)  # Late completion cannot resurrect the cancelled operation.
    callback.assert_called_once_with(False)
    assert controller.position is None
    assert controller.boot_home_pending
    assert len(handles) == 1
    assert not controller.move("F+")


def test_cancelled_jog_requires_rehome(leg):
    controller, _, _, _ = leg
    home(leg)
    assert controller.move("F+")
    controller.cancel()
    assert controller.position is None
    assert not controller.move("F+")


def test_unrelated_done_cannot_finish_home(leg):
    controller, window, now, handles = leg
    controller.home()
    handles[-1].written.set()
    controller._poll()
    window.arduino.done_emit.emit()
    now[0] += 6.1
    controller._poll()
    assert controller.active
    assert controller.position is None
    assert len(handles) == 1
    if window.arduino.protocol_v2:
        window.arduino.done_emit.emit()  # Another command's sequenced DONE.
        controller._poll()
        assert len(handles) == 1


def test_completed_command_cannot_restart_gpio_after_gui_delay(leg, monkeypatch):
    controller, window, _, handles = leg
    drive = MagicMock()
    monkeypatch.setattr(controller, "_drive", drive)
    controller.home()
    handle = handles[-1]
    handle.written.set()
    if window.arduino.protocol_v2:
        handle.result = "DONE"
        handle.completed.set()
    else:
        window.arduino.done_emit.emit()
    controller._poll()
    assert not controller.active
    assert controller.position is None
    assert all(call.args == (None,) for call in drive.call_args_list)


@pytest.mark.parametrize("flag", ["reset_in_progress", "protocol_running",
                                   "actuator_command_in_progress", "_calibration_active"])
def test_leg_commands_cannot_overlap_other_owners(leg, flag):
    controller, window, _, handles = leg
    setattr(window, flag, True)
    assert not controller.home()
    assert handles == []


def test_boot_readiness_waits_for_leg_and_later_reset_preserves_it(leg):
    controller, window, _, handles = leg
    manager = ConnectionManager(window)
    window.connection = manager
    worker = MagicMock()
    manager.reset_worker = worker
    window.reset_in_progress = True
    window.initial_setup_complete = False
    manager._on_reset_finished(True, worker)
    assert window.reset_in_progress and not window.initial_setup_complete
    complete(leg)
    assert not window.initial_setup_complete
    complete(leg)
    assert window.initial_setup_complete and not window.reset_in_progress
    assert controller.move("F+")
    complete(leg)
    before = len(handles)
    manager._on_reset_finished(True)
    window._reflect_setup = MagicMock()
    KneeSpa.reset_setup_readings(window)
    assert controller.position == window.leg_length == 0.25
    assert len(handles) == before
    assert all(call.args[0] != "leg_length" for call in window._reflect_setup.call_args_list)


def test_boot_failure_blocks_readiness_and_explicit_retry_can_home(leg):
    controller, window, _, _ = leg
    manager = ConnectionManager(window)
    window.reset_in_progress = True
    window.initial_setup_complete = False
    manager._on_reset_finished(True)
    controller.cancel()
    assert not window.initial_setup_complete
    assert window.protocol_state == "fault"
    window.reset_in_progress = True
    manager._on_reset_finished(True)
    complete(leg)
    complete(leg)
    assert window.initial_setup_complete


def test_general_done_does_not_unlock_leg_motion(leg):
    controller, window, _, _ = leg
    window.controls_enable_timer = None
    assert controller.home()
    window.actuator_command_in_progress = True
    KneeSpa.enable_actuator_controls(window)
    assert window.actuator_command_in_progress
    assert window.controls_enable_timer is None


def test_slider_target_uses_completed_quarter_inch_commands(leg):
    controller, window, _, handles = leg
    home(leg)
    assert controller.move_to(1.25)
    for step in range(5):
        assert controller.position == 0
        assert controller.active
        complete(leg)
    assert controller.position == window.leg_length == 1.25
    assert [handle.command for handle in handles[2:]] == ["F+"] * 5
    assert controller.move_to(0.5)
    for _ in range(3):
        complete(leg)
    assert controller.position == 0.5
    assert [handle.command for handle in handles[-3:]] == ["F-"] * 3
    before = len(handles)
    assert controller.move_to(0.5)
    assert len(handles) == before


@pytest.mark.parametrize("target", [-0.25, 6.25, float("nan"), float("inf"), 0.1])
def test_invalid_slider_target_cannot_send_motion(leg, target):
    controller, _, _, handles = leg
    home(leg)
    before = len(handles)
    assert not controller.move_to(target)
    assert len(handles) == before
    assert controller.position == 0


def test_slider_target_requires_zero_and_cannot_continue_after_stop(leg):
    controller, _, _, handles = leg
    assert not controller.move_to(1)
    assert handles == []
    home(leg)
    assert controller.move_to(1)
    complete(leg)
    assert controller.active
    controller.cancel()
    before = len(handles)
    complete(leg)  # An interrupted stroke's late reply cannot queue another.
    assert len(handles) == before
    assert controller.position is None
    assert not controller.move_to(1)


@pytest.mark.parametrize("flag", ["reset_in_progress", "protocol_running",
                                   "actuator_command_in_progress", "_calibration_active",
                                   "_physical_stop_active", "_no_automatic_recovery"])
def test_slider_target_preserves_motion_guards(leg, flag):
    controller, window, _, handles = leg
    home(leg)
    before = len(handles)
    setattr(window, flag, True)
    assert not controller.move_to(1)
    assert len(handles) == before
