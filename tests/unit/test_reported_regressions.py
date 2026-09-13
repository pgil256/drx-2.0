"""Regression coverage for the physical-stop, Setup, and patient lookup audit."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pytestqt.qtbot import QtBot

import kneespa
from controllers.connection_manager import ConnectionManager
from controllers.protocol_controller import ProtocolController
from controllers.safety_monitor import SafetyMonitor
from helpers.arduino import Arduino
from kneespa import KneeSpa, _CloudBridge
from tests.unit.test_actuator_controls import ControlsHarness
from tests.unit.test_controller_wiring import make_stub
from tests.unit.test_protocol_logic import make_protocol

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("message", ["Stop button pressed", "Stop button engaged"])
def test_physical_stop_cancels_worker_without_interrupting_firmware_release(
    qtbot: QtBot, message: str
) -> None:
    window = MagicMock()
    window.protocol_running = True
    window.protocol_state = "running"
    window._physical_stop_active = False
    worker = make_protocol(protocol="4")
    worker.is_running = True
    worker._pulse_active = True
    window.worker = worker

    SafetyMonitor(window).on_firmware_error(message)

    assert worker.is_running is False
    assert window._physical_stop_active is True
    window.set_protocol_state.assert_called_with("fault")
    window.arduino.cancel_pending_commands.assert_called_once()
    worker.current_pos_c = int(worker.config.CMarks["0.0"])
    assert worker.set_to_c_distance(0) is False
    assert worker._start_pulse() is False
    worker.stop()  # completion cleanup must preserve the autonomous release, too
    worker.arduino.send.assert_not_called()
    window.stop_actuators.assert_not_called()
    window.reset_arduino.assert_not_called()


def test_physical_stop_before_dispatch_cannot_restart_worker() -> None:
    worker = make_protocol(protocol="4")
    finished = []
    worker.signals.finished.connect(finished.append)
    worker.cancel(firmware_stopped=True)

    worker.run()

    assert worker.is_running is False
    assert finished == [False]
    worker.arduino.send.assert_not_called()


@pytest.mark.parametrize("protocol_v2", [False, True])
def test_cancel_pending_after_physical_stop_does_not_send_x(protocol_v2: bool) -> None:
    arduino = Arduino()
    arduino.protocol_v2 = protocol_v2
    arduino._running = True
    arduino.serial_com = MagicMock(is_open=True)
    handle = arduino.send_tracked("K1800")

    arduino.cancel_pending_commands()
    arduino._service_tx_queue()

    arduino.serial_com.write.assert_not_called()
    assert handle.completed.is_set()
    assert handle.result == "CANCELLED"


@pytest.mark.parametrize("key", ["axial", "horizontal", "lateral"])
def test_setup_go_requires_valid_position_calibration(key: str) -> None:
    window = make_stub()
    window.config.marks_valid = False
    window.shell.setup.row_value.return_value = 0

    assert KneeSpa._on_setup_go(window, key) is False

    window._warn_uncalibrated.assert_called_once()
    window.arduino.send.assert_not_called()
    window.set_to_distance.assert_not_called()
    window.set_to_c_distance.assert_not_called()
    window.disable_actuator_controls.assert_not_called()


def test_setup_pressure_requires_scale_calibration() -> None:
    window = make_stub()
    window.config.scale_calibrated = False
    window.shell.setup.row_value.return_value = 50

    assert KneeSpa._apply_setup_pressure(window) is False

    window._warn_uncalibrated.assert_called_once()
    window.arduino.send.assert_not_called()


def test_pressure_go_refuses_uncalibrated_scale_before_locking_controls() -> None:
    window = make_stub()
    window.config.scale_calibrated = False

    assert KneeSpa._on_setup_go(window, "pressure") is False

    window._apply_setup_pressure.assert_not_called()
    window.disable_actuator_controls.assert_not_called()


def test_pressure_release_remains_available_without_calibration() -> None:
    window = make_stub()
    window.config.scale_calibrated = False

    KneeSpa._setup_reset(window, "pressure")

    window.arduino.send.assert_called_once_with("P0")


def test_lateral_wait_exits_after_stop_during_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = make_protocol()
    worker.is_running = True
    worker.current_pos_c = -1000
    waits = []

    def pause_on_send(command: str) -> bool:
        worker.is_paused = True
        return True

    def wait_then_stop() -> None:
        waits.append(1)
        # Bound the old infinite loop without leaking a busy background thread.
        assert len(waits) <= 3
        if worker.is_paused:
            worker.is_running = False

    worker.arduino.send.side_effect = pause_on_send
    monkeypatch.setattr(worker, "_wait_while_paused", wait_then_stop)

    assert worker.set_to_c_distance(0) is False
    assert len(waits) == 2


def test_reset_done_does_not_unlock_setup_controls(qtbot: QtBot) -> None:
    window = ControlsHarness(qtbot)
    window.reset_in_progress = True
    window.initial_setup_complete = False
    window.I2Cstatus_event = threading.Event()
    window.disable_actuator_controls()

    ConnectionManager(window).set_done()
    qtbot.wait(250)

    assert window.I2Cstatus_event.is_set()
    assert window.all_disabled()
    assert window.actuator_command_in_progress is True


def test_deferred_enable_rechecks_reset_state(qtbot: QtBot) -> None:
    window = ControlsHarness(qtbot)
    window.disable_actuator_controls()
    window.enable_actuator_controls()
    window.reset_in_progress = True
    qtbot.wait(250)

    assert window.all_disabled()


def test_failed_initialization_keeps_controls_locked(qtbot: QtBot) -> None:
    window = ControlsHarness(qtbot)
    window.initial_setup_complete = False
    window.disable_actuator_controls()
    window.enable_actuator_controls()
    qtbot.wait(250)

    assert window.all_disabled()


def lookup_window() -> MagicMock:
    window = make_stub()
    window.protocol_running = False
    window._patient_lookup_id = 0
    window._cloud_bridge = _CloudBridge()
    window._cloud_bridge.lookup_done.connect(
        lambda request_id, result: KneeSpa._on_cloud_lookup_done(window, request_id, result)
    )
    return window


def test_older_patient_response_cannot_replace_newer_selection(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    window = lookup_window()
    tasks = []
    monkeypatch.setattr(
        kneespa.threading, "Thread",
        lambda *, target, daemon: SimpleNamespace(start=lambda: tasks.append(target)),
    )
    patients = {
        "A": {"patient_id": "A", "settings": {"max_pressure_lb": 30}},
        "B": {"patient_id": "B", "settings": {"max_pressure_lb": 50}},
    }
    window.cloud_client.lookup_pin.side_effect = patients.get
    KneeSpa._on_patient_pin(window, "A")
    KneeSpa._on_patient_pin(window, "B")

    tasks[1]()
    tasks[0]()

    assert window.cloud_patient["patient_id"] == "B"
    window.shell.treatment.set_settings.assert_called_once_with({"max_pressure": 50.0})


@pytest.mark.parametrize("result", [None, {"error": "unknown_pin"}])
def test_late_lookup_failure_preserves_active_treatment_patient(
    result: object, qtbot: QtBot
) -> None:
    window = lookup_window()
    window.cloud_patient = {"patient_id": "B"}
    window._treatment_patient = dict(window.cloud_patient)
    window.protocol_running = True

    KneeSpa._on_cloud_lookup_done(window, 0, result)
    ProtocolController(window)._upload_treatment(True, False, False)

    assert window.cloud_patient == {"patient_id": "B"}
    record = window.cloud_client.post_treatment_async.call_args.args[0]
    assert record["patient_id"] == "B"


def test_upload_uses_patient_captured_at_start(qtbot: QtBot) -> None:
    window = lookup_window()
    window.cloud_patient = {"patient_id": "A"}
    window._treatment_patient = {"patient_id": "B"}

    ProtocolController(window)._upload_treatment(True, False, False)

    record = window.cloud_client.post_treatment_async.call_args.args[0]
    assert record["patient_id"] == "B"


def test_cancelled_lookup_error_cannot_clear_newer_patient(qtbot: QtBot) -> None:
    window = lookup_window()
    window._patient_lookup_id = 2
    window.cloud_patient = {"patient_id": "B"}

    KneeSpa._on_cloud_lookup_done(window, 1, {"error": "unknown_pin"})

    assert window.cloud_patient == {"patient_id": "B"}
    window.shell.treatment.set_patient_error.assert_not_called()


def test_logout_invalidates_pending_lookup(qtbot: QtBot) -> None:
    window = lookup_window()
    window._block_nav_during_treatment.return_value = False
    KneeSpa._on_logout(window)

    KneeSpa._on_cloud_lookup_done(window, 0, {"patient_id": "old-session"})

    assert window.cloud_patient is None
    window.shell.treatment.set_patient.assert_not_called()


def test_start_captures_patient_and_invalidates_pending_lookup(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    from tests.unit.test_protocol_controller import make_window
    from helpers import protocols

    window = make_window()
    window.cloud_patient = {"patient_id": "B"}
    worker = MagicMock()
    monkeypatch.setattr(protocols, "Protocols", lambda *args, **kwargs: worker)
    old_request_id = window._patient_lookup_id

    assert ProtocolController(window).start_protocol() is True
    window.cloud_patient["patient_id"] = "changed"
    window.protocol_running = False  # Late reply after the treatment ended.
    KneeSpa._on_cloud_lookup_done(window, old_request_id, {"patient_id": "A"})

    assert window._treatment_patient == {"patient_id": "B"}
    window.shell.treatment.set_patient.assert_not_called()


def test_worker_failure_cannot_automatically_reset_physical_stop() -> None:
    window = MagicMock()
    window._physical_stop_active = True
    controller = ProtocolController(window)

    controller._reset_after_failure()
    controller._reset_after_release(0)

    window.reset_arduino.assert_not_called()


def test_reset_completion_after_physical_stop_does_not_restore_readiness(qtbot: QtBot) -> None:
    window = MagicMock()
    window.initial_setup_complete = False
    window._physical_stop_active = True
    window.reset_in_progress = True

    ConnectionManager(window)._on_reset_finished(True)

    assert window.initial_setup_complete is False
    window.set_protocol_state.assert_called_with("fault")
    window.reset_extra_button_clicked.assert_not_called()


def test_controls_unlock_after_successful_reset_and_final_done(qtbot: QtBot) -> None:
    window = ControlsHarness(qtbot)
    window.reset_in_progress = True
    window.initial_setup_complete = False
    window.I2Cstatus_event = threading.Event()
    window.disable_actuator_controls()
    manager = ConnectionManager(window)
    manager.set_done()
    window.initial_setup_complete = True
    window.reset_in_progress = False
    manager.set_done()  # A later DONE after the reset has finished.
    qtbot.wait(250)

    assert window.all_enabled()


def test_physical_stop_latches_fault_even_if_gpio_release_raises(qtbot: QtBot) -> None:
    window = MagicMock()
    window._physical_stop_active = False
    window._release_leg_gpio.side_effect = RuntimeError("GPIO unavailable")

    SafetyMonitor(window).on_physical_stop()

    window.set_protocol_state.assert_called_once_with("fault")
    window.disable_actuator_controls.assert_called_once()


def test_physical_stop_prevents_reset_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.unit.test_reset_worker_logic import make_worker

    worker = make_worker()
    worker.main_window._physical_stop_active = False

    def interrupted_wait(**kwargs: object) -> bool:
        worker.main_window._physical_stop_active = True
        return False

    monkeypatch.setattr(worker, "_wait_for_done", interrupted_wait)

    assert worker._try_command_with_retry("I131140") is False
    worker.arduino.send.assert_called_once_with("I131140")


def test_physical_stop_prevents_queued_reset_from_starting() -> None:
    from tests.unit.test_reset_worker_logic import make_worker

    worker = make_worker()
    worker.main_window._physical_stop_active = True
    finished = []
    worker.signals.finished.connect(finished.append)

    worker.run()

    worker.arduino.send.assert_not_called()
    assert finished == [False]


def test_physical_stop_leaves_operator_reset_available(qtbot: QtBot) -> None:
    from ui.screens.setup import SetupScreen

    setup = SetupScreen()
    qtbot.addWidget(setup)
    window = MagicMock()
    window.reset_in_progress = False
    window.shell.setup = setup
    window._physical_stop_active = False

    def disable_controls() -> None:
        for button in setup.control_buttons():
            button.setEnabled(False)

    window.disable_actuator_controls.side_effect = disable_controls

    SafetyMonitor(window).on_physical_stop()

    assert setup._reset_btn.isEnabled()
    assert all(not button.isEnabled() for row in setup._rows.values()
               for button in row.motion_buttons)


def test_failed_reset_leaves_operator_recovery_available(qtbot: QtBot) -> None:
    from tests.unit.test_connection_manager import StubWindow

    window = StubWindow()
    ConnectionManager(window)._on_reset_finished(False)

    window.shell.setup.set_reset_enabled.assert_called_once_with(True)


def test_late_connect_does_not_automatically_clear_physical_stop(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    window = MagicMock()
    window._physical_stop_active = True
    manager = ConnectionManager(window)
    reset = MagicMock()
    monkeypatch.setattr(manager, "reset_arduino", reset)

    manager._automatic_reset()

    reset.assert_not_called()


def test_lateral_wait_accepts_firmware_done_when_status_is_stale() -> None:
    """2026-09-10: a garbled status frame froze the host's view of the
    lateral position mid-move; the firmware's DONE ack must still complete
    the wait instead of the host timing the move out."""
    worker = make_protocol()
    worker.is_running = True
    worker.current_pos_c = -1000  # never within tolerance of any mark

    def ack_done(command: str) -> bool:
        assert command.startswith("K")
        worker._on_firmware_done()
        return True

    worker.arduino.send.side_effect = ack_done

    assert worker.set_to_c_distance(0) is True
    assert worker.angle_set is True


def test_lateral_wait_ignores_stale_done_from_earlier_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_protocol()
    worker.is_running = True
    worker.current_pos_c = -1000
    worker._on_firmware_done()  # DONE left over from a previous move
    monkeypatch.setattr("helpers.protocols.LATERAL_MOVE_TIMEOUT_S", 0.3)

    assert worker.set_to_c_distance(0) is False
    assert worker.angle_set is False


def test_lateral_move_timeout_covers_full_swing() -> None:
    """The bench unit moves ~1.5 deg/s; protocol 4 swings 40 deg (~26 s)."""
    from config.constants import LATERAL_MOVE_TIMEOUT_S

    assert LATERAL_MOVE_TIMEOUT_S >= 30
