"""Regression coverage for software stops, startup, final homing, and shutdown."""
import threading
from unittest.mock import MagicMock

import pytest
from pytestqt.qtbot import QtBot

from controllers.connection_manager import ConnectionManager
from controllers.protocol_controller import ProtocolController
from helpers.arduino import Arduino, CommandHandle
from helpers.reset_worker import ResetWorker
from kneespa import KneeSpa
from tests.unit.test_protocol_controller import make_window
from tests.unit.test_protocol_logic import make_protocol
from tests.unit.test_reset_worker_logic import make_config


pytestmark = pytest.mark.unit


def transport() -> Arduino:
    arduino = Arduino()
    arduino.protocol_v2 = False
    arduino._running = True
    arduino.serial_com = MagicMock(is_open=True)
    return arduino


@pytest.mark.parametrize("action", ["stop_protocol", "emergency_stop_clicked"])
def test_stop_cancels_new_motion_before_delayed_cleanup(
    action: str, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    arduino = transport()
    worker = make_protocol(protocol="4", ser=arduino)
    worker.is_running = True
    window = make_window("running")
    window.worker = worker
    window.arduino = arduino
    window.stop_actuators.side_effect = lambda: arduino.send("X")
    controller = ProtocolController(window)
    callbacks = []
    monkeypatch.setattr(
        "controllers.protocol_controller.QTimer.singleShot",
        lambda ms, callback: callbacks.append(callback),
    )
    old_motion = arduino.send_tracked("K1600")

    if action == "stop_protocol":
        controller.stop_protocol()
    else:
        controller.emergency_stop_clicked(None)

    assert worker.is_running is False
    assert worker._send_command("K1800") is False
    arduino._service_tx_queue()
    assert old_motion.result == "CANCELLED"
    assert [c.args[0] for c in arduino.serial_com.write.call_args_list] == [b"X\n"]

    callbacks[0]()  # The delayed release still runs after immediate cancellation.
    arduino._service_tx_queue()
    writes = [c.args[0] for c in arduino.serial_com.write.call_args_list]
    assert writes[-1] == b"P0\n"
    assert not any(command.startswith(b"K") for command in writes)


def test_failed_centering_never_dispatches_or_starts_treatment_timer(
    monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    window = make_window("starting")
    window.set_to_c_distance.return_value = False
    worker_cls = MagicMock()
    monkeypatch.setattr("controllers.protocol_controller.protocols.Protocols", worker_cls)

    assert ProtocolController(window).start_protocol() is False

    worker_cls.assert_not_called()
    window.threadpool.start.assert_not_called()
    window.protocol_timer.start.assert_not_called()
    assert window.protocol_state == "fault"
    window.ui.start_button.setEnabled.assert_called_with(False)


@pytest.mark.parametrize("protocol_v2", [False, True])
def test_reset_does_not_home_leg_length(protocol_v2: bool, qtbot: QtBot) -> None:
    """The reset sequence ends at calibration: it neither sends FR nor
    drives the leg-length GPIO, and readiness follows the L0 ack."""
    window = make_window()
    window.config = make_config()
    window.worker = None
    window._physical_stop_active = False
    window._closing = False
    window.initial_setup_complete = False
    window.I2Cstatus_event = threading.Event()
    window.arduino.protocol_v2 = protocol_v2
    manager = ConnectionManager(window)
    sent = []
    finished = []
    threads = []

    def send(command: str) -> bool:
        sent.append(command)
        window.I2Cstatus_event.set()
        return True

    def send_tracked(command: str) -> CommandHandle:
        sent.append(command)
        handle = CommandHandle(command)
        handle.result = "DONE"
        handle.completed.set()
        return handle

    def start(worker: ResetWorker) -> None:
        worker.signals.finished.connect(finished.append)
        thread = threading.Thread(target=worker.run, daemon=True)
        threads.append(thread)
        thread.start()

    window.arduino.send.side_effect = send
    window.arduino.send_tracked.side_effect = send_tracked
    window.threadpool.start.side_effect = start
    manager.reset_arduino()
    try:
        qtbot.waitUntil(lambda: bool(finished), timeout=5000)
    finally:
        for thread in threads:
            thread.join(timeout=2)

    assert finished == [True]
    assert not any(c.startswith("F") for c in sent)
    assert sent[-1].startswith("L0")
    assert window.reset_in_progress is False
    assert window.initial_setup_complete is True
    window._start_leg_reset_gpio.assert_not_called()
    window._finish_leg_reset.assert_not_called()
    window.reset_extra_button_clicked.assert_not_called()
    window.enable_actuator_controls.assert_called_once()


@pytest.mark.parametrize("physical_stop", [False, True])
@pytest.mark.parametrize("worker_present", [False, True])
def test_shutdown_discards_manual_motion_before_draining(
    physical_stop: bool, worker_present: bool, qtbot: QtBot
) -> None:
    arduino = transport()
    window = make_window()
    window._physical_stop_active = physical_stop
    window.arduino = arduino
    window.arduino_thread = None
    window.worker = make_protocol(ser=arduino) if worker_present else None
    if window.worker:
        window.worker.is_running = True
    serial = arduino.serial_com
    window.connection = ConnectionManager(window)
    queued_motion = arduino.send_tracked("P50")

    def drain_and_disconnect(drain_timeout: float) -> bool:
        assert window._closing is True
        if window.worker:
            assert window.worker._send_command("K1800") is False
        for _ in range(3):
            arduino._last_tx = 0
            arduino._service_tx_queue()
        return True

    arduino.disconnect = drain_and_disconnect
    KneeSpa.cleanup(window)

    writes = [c.args[0] for c in serial.write.call_args_list]
    assert writes == ([] if physical_stop else [b"X\n", b"P0\n", b"HF0\n"])
    assert queued_motion.result == "CANCELLED"
    assert window.arduino is None


def test_shutdown_suppresses_delayed_recovery(qtbot: QtBot) -> None:
    window = make_window()
    window._closing = True
    controller = ProtocolController(window)
    manager = ConnectionManager(window)

    controller._stop_phase2()
    controller._stop_phase3()
    controller._emergency_stop_phase2()
    controller._emergency_stop_phase3()
    manager._automatic_reset()
    manager._on_reset_finished(True)

    window.reset_arduino.assert_not_called()
    window.worker.stop.assert_not_called()


def test_shutdown_prevents_queued_reset_worker_from_sending() -> None:
    window = make_window()
    window.worker = None
    window._closing = True
    worker = ResetWorker(window.arduino, make_config(), window)

    worker.run()

    window.arduino.send.assert_not_called()
