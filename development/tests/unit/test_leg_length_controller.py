"""Timed leg-length (FIT) moves and interruption regressions without hardware.

Nothing measures the leg-length actuator, so the controller keeps no position,
shows none and applies no software travel limit (drx-demo, 12 November 2026).
"""

from unittest.mock import MagicMock

import pytest

from controllers import leg_length_controller as module
from controllers.connection_manager import ConnectionManager
from helpers.arduino import Arduino, CommandHandle
from fixtures.motion import make_motion
from fixtures.controllers import make_window


pytestmark = pytest.mark.unit


@pytest.fixture(params=[False, True], ids=["legacy", "v2"])
def leg(request, qtbot, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    window = make_window()
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


def test_jogs_need_no_zero_or_position(leg):
    """The first jog after startup runs: there is no zero to establish."""
    controller, window, _, handles = leg
    for command in ("F+", "FF", "F-", "FR"):
        assert controller.move(command)
        assert controller.active
        assert not controller.move("F+")  # one move at a time
        complete(leg)
        assert not controller.active
    assert [handle.command for handle in handles] == ["F+", "FF", "F-", "FR"]
    assert not hasattr(controller, "position")
    window._show_timed_error.assert_not_called()


def test_no_software_travel_limit(leg):
    """drx-demo used to refuse a third fast extend at a made-up 6 in."""
    controller, _, _, handles = leg
    for _ in range(4):
        assert controller.move("FF")
        complete(leg)
    for _ in range(4):
        assert controller.move("FR")
        complete(leg)
    assert [handle.command for handle in handles] == ["FF"] * 4 + ["FR"] * 4


def test_return_retracts_with_two_back_to_back_fr_moves(leg):
    controller, window, _, handles = leg
    assert controller.retract()
    window.disable_actuator_controls.assert_called()
    window.loading_spinner.show.assert_called()
    complete(leg)
    assert controller.active
    assert [handle.command for handle in handles] == ["FR", "FR"]
    window.enable_actuator_controls.assert_not_called()
    complete(leg)
    assert not controller.active
    assert [handle.command for handle in handles] == ["FR", "FR"]
    window.loading_spinner.hide.assert_called()
    window.enable_actuator_controls.assert_called()


def test_nothing_is_sent_to_the_setup_screen(leg):
    controller, window, _, _ = leg
    setup = window.shell.setup
    setup.reset_mock()
    assert controller.move("FF")
    complete(leg)
    assert controller.retract()
    complete(leg)
    complete(leg)
    assert controller.move("F+")
    controller.cancel()
    assert setup.method_calls == []


def test_gpio_waits_for_write_and_stops_without_reply(leg, monkeypatch):
    controller, window, now, handles = leg
    drive = MagicMock()
    monkeypatch.setattr(controller, "_drive", drive)
    controller.retract()
    controller._poll()
    drive.assert_not_called()
    handles[-1].written.set()
    controller._poll()
    drive.assert_called_with(False)
    now[0] += 6.1
    controller._poll()
    drive.assert_called_with(None)
    assert controller.active
    now[0] += 3.1
    controller._poll()
    assert not controller.active
    window._show_timed_error.assert_called_with("Leg movement timed out.")
    assert len(handles) == 1


@pytest.mark.parametrize("interruption", ["cancel", "disconnect", "reject", "fault", "physical"])
def test_interrupted_return_stops_and_runs_no_second_stroke(leg, interruption):
    controller, window, now, handles = leg
    assert controller.retract()
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
    if interruption != "physical":
        window.arduino.send.assert_called_once_with("X")
    complete(leg)  # Late completion cannot resurrect the cancelled operation.
    assert not controller.active
    assert len(handles) == 1
    window.enable_actuator_controls.assert_called()


@pytest.mark.parametrize("message", ["Stop button pressed", "Stop button engaged"])
def test_stop_button_error_ends_the_move_without_a_stop_command(leg, message):
    """An X after the device's stop button would end the firmware's release."""
    controller, window, _, _ = leg
    assert controller.move("F+")

    window.arduino.error_emit.emit(message)

    assert not controller.active
    window.arduino.send.assert_not_called()


def test_other_errors_still_stop_an_interrupted_move(leg):
    controller, window, _, _ = leg
    assert controller.move("F+")

    window.arduino.error_emit.emit("Motor stall timeout 13")

    assert not controller.active
    window.arduino.send.assert_called_once_with("X")


def test_cancelled_jog_does_not_block_the_next_one(leg):
    controller, _, _, handles = leg
    assert controller.move("F+")
    controller.cancel()
    assert controller.move("F+")
    assert [handle.command for handle in handles] == ["F+", "F+"]


def test_unrelated_done_cannot_finish_return(leg):
    controller, window, now, handles = leg
    controller.retract()
    handles[-1].written.set()
    controller._poll()
    window.arduino.done_emit.emit()
    now[0] += 6.1
    controller._poll()
    assert controller.active
    assert len(handles) == 1
    if window.arduino.protocol_v2:
        window.arduino.done_emit.emit()  # Another command's sequenced DONE.
        controller._poll()
        assert len(handles) == 1


def test_completed_command_cannot_restart_gpio_after_gui_delay(leg, monkeypatch):
    controller, window, _, handles = leg
    drive = MagicMock()
    monkeypatch.setattr(controller, "_drive", drive)
    controller.retract()
    handle = handles[-1]
    handle.written.set()
    if window.arduino.protocol_v2:
        handle.result = "DONE"
        handle.completed.set()
    else:
        window.arduino.done_emit.emit()
    controller._poll()
    assert not controller.active
    assert all(call[0] == (None,) for call in drive.call_args_list)


@pytest.mark.parametrize("flag", ["reset_in_progress", "protocol_running",
                                   "actuator_command_in_progress", "_calibration_active",
                                   "_physical_stop_active", "_no_automatic_recovery"])
def test_leg_commands_cannot_overlap_other_owners(leg, flag):
    controller, window, _, handles = leg
    setattr(window, flag, True)
    assert not controller.retract()
    assert not controller.move("F+")
    assert handles == []


@pytest.mark.parametrize("first_boot", [True, False])
def test_resets_never_move_the_leg(leg, first_boot):
    """Startup no longer retracts the leg: there is no reference to set."""
    controller, window, _, handles = leg
    manager = ConnectionManager(window)
    window.connection = manager
    worker = MagicMock()
    manager.reset_worker = worker
    window.reset_in_progress = True
    window.initial_setup_complete = not first_boot
    manager._on_reset_finished(True, worker)
    assert window.initial_setup_complete and not window.reset_in_progress
    assert handles == []
    assert not controller.active


def test_general_done_does_not_unlock_leg_motion(leg):
    controller, _, _, _ = leg
    assert controller.retract()
    motion = make_motion(leg=controller)  # the Setup gate sees the moving leg
    motion.state.actuator_command_in_progress = True
    motion.enable_actuator_controls()
    assert motion.state.actuator_command_in_progress
    assert motion.controls_enable_timer is None
