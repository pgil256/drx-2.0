"""Motor speed validation, firmware acceptance, persistence and UI gating."""

import threading
import time
from unittest.mock import Mock

import pytest

from config.config import Configuration
from fixtures.protocols import make_protocol
from helpers.arduino import Arduino, CommandHandle
from helpers.motor_speed import motor_speed_command, motor_speed_values, treatment_motor_speed
from ui.screens.treatment import TreatmentScreen

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [0, 49, 101, -1, 75.5, float("nan"), float("inf"), "bad"])
def test_invalid_speed_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        motor_speed_values({"axial_speed": value})


def test_independent_motor_speeds():
    assert motor_speed_command({"axial_speed": 75, "pulse_speed": 60}) == "V75,50,60"


def test_legacy_speed_echo_cannot_complete_a_move():
    arduino = Arduino()
    arduino.protocol_v2 = False
    move = CommandHandle("K1800")
    speed = CommandHandle("V75,50,60")
    arduino._recent_writes.extend([(time.monotonic(), move), (time.monotonic(), speed)])
    done = []
    arduino.done_emit.connect(lambda: done.append(True))
    arduino.handle_com("DONE")
    assert not speed.completed.is_set()
    arduino.handle_com("SPEED|75|50|100")
    assert not speed.completed.is_set()
    arduino.handle_com("SPEED|75|50|60")
    assert speed.completed.is_set() and speed.result == "OK"
    assert not move.completed.is_set()
    assert done == [True]
    assert not arduino.ok_event.is_set()


def test_v2_requires_matching_sequence():
    arduino = Arduino()
    arduino.protocol_v2 = True
    speed = CommandHandle("V75,50,60", sequence=42)
    arduino._pending_v2[42] = speed
    arduino.handle_com("SPEED|75|50|60")
    arduino.handle_com("OK|41")
    assert not speed.completed.is_set()
    arduino.handle_com("OK|42")
    assert speed.completed.is_set() and speed.result == "OK"


@pytest.mark.parametrize("result, accepted", [("OK", True), ("BUSY", False), ("ERR", False)])
def test_worker_requires_speed_acceptance(result, accepted):
    worker = make_protocol(motor_speeds={"axial_speed": 75})
    handle = CommandHandle("V75,50,50")
    handle.result = result
    handle.completed.set()
    worker.arduino.send_tracked.side_effect = None
    worker.arduino.send_tracked.return_value = handle
    assert worker._configure_motor_speeds() is accepted
    worker.arduino.send_tracked.assert_called_once_with("V75,50,50")


def test_missing_firmware_ack_prevents_treatment(monkeypatch):
    monkeypatch.setattr("helpers.protocols.MOTOR_SPEED_ACK_TIMEOUT_S", 0)
    worker = make_protocol(motor_speeds={})
    worker.arduino.send_tracked.return_value = CommandHandle("V50,50,50")
    worker.set_to_c_distance = Mock(return_value=True)
    monkeypatch.setattr("helpers.controller_operations.ControllerOperations.baseline", Mock())
    worker.protocol_1 = Mock()
    finished, errors = [], []
    worker.signals.finished.connect(finished.append)
    worker.signals.operation_failed.connect(errors.append)
    worker.run()
    assert finished == [False]
    assert "motor speeds" in errors[0]
    worker.protocol_1.assert_not_called()
    assert all(not c.args[0].startswith("P") for c in worker.arduino.send.call_args_list)


def test_stop_interrupts_speed_wait():
    worker = make_protocol(motor_speeds={})
    worker.arduino.send_tracked.return_value = CommandHandle("V50,50,50")
    timer = threading.Timer(0.02, worker.cancel)
    timer.start()
    try:
        start = time.monotonic()
        assert not worker._configure_motor_speeds()
        assert time.monotonic() - start < 0.5
    finally:
        timer.join()


def test_speed_defaults_round_trip_and_invalid_load(tmp_path):
    config = Configuration(str(tmp_path / "device.cfg"))
    config.get_config()
    config.save_protocol_defaults(40, 10, 10, 2, motor_speeds={
        "axial_speed": 75, "lateral_speed": 90, "pulse_speed": 60,
    })
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert motor_speed_values(loaded.protocol_defaults()) == {
        "axial_speed": 75, "lateral_speed": 90, "pulse_speed": 60,
    }
    loaded.config.set("ProtocolDefaults", "axial_speed", "nan")
    loaded._atomic_write()
    again = Configuration(config.configFile)
    again.get_config()
    assert again.default_axial_speed == 50
    assert again.default_lateral_speed == 90


def test_speed_save_failure_keeps_previous_values(tmp_path, monkeypatch):
    config = Configuration(str(tmp_path / "device.cfg"))
    before = config.protocol_defaults()
    monkeypatch.setattr(config, "_atomic_write", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        config.save_protocol_defaults(40, 10, 10, 2, motor_speeds={"pulse_speed": 60})
    assert config.protocol_defaults() == before


def test_speed_sliders_and_run_gating(qtbot):
    screen = TreatmentScreen()
    qtbot.addWidget(screen)
    screen._edit_treatment_button.click()
    assert screen._editor.isVisible()
    assert screen.settings_values()["motor_speed"] == 50
    changes = []
    screen.setting_changed.connect(lambda k, v: changes.append((k, v)))
    screen._settings["motor_speed"]._slider.setValue(2)
    assert changes == [("motor_speed", 60)]
    assert screen.settings_values()["pulse_rate"] == 2
    for running, paused, busy in ((True, False, False), (True, True, False),
                                  (False, False, True)):
        screen.set_busy(busy)
        screen.set_run_state(running, paused)
        assert not screen._settings["motor_speed"].isEnabled()
        assert screen._estop_btn.isEnabled()
    screen.set_busy(False)
    assert screen._settings["motor_speed"].isEnabled()


@pytest.mark.parametrize("value", [50, 75, 100])
def test_shared_motor_speed_reaches_all_outputs(value):
    settings = {"motor_speed": value, "pulse_speed": 100}
    assert motor_speed_command(settings) == f"V{value},{value},{value}"
    worker = make_protocol(motor_speeds=settings)
    handle = CommandHandle(motor_speed_command(settings))
    handle.result = "OK"
    handle.completed.set()
    worker.arduino.send_tracked.side_effect = None
    worker.arduino.send_tracked.return_value = handle
    assert worker._configure_motor_speeds()
    worker.arduino.send_tracked.assert_called_once_with(f"V{value},{value},{value}")


@pytest.mark.parametrize("value", [49, 101, 75.5, float("nan"), "bad"])
def test_invalid_shared_speed_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        motor_speed_command({"motor_speed": value})


def test_shared_speed_defaults_round_trip(tmp_path, qtbot):
    config = Configuration(str(tmp_path / "device.cfg"))
    config.get_config()
    config.save_protocol_defaults(40, 10, 10, 2, motor_speeds={"motor_speed": 75})
    loaded = Configuration(config.configFile)
    loaded.get_config()
    screen = TreatmentScreen()
    qtbot.addWidget(screen)
    screen.set_settings(loaded.protocol_defaults())
    assert screen.settings_values()["motor_speed"] == 75
    assert motor_speed_command(screen.settings_values()) == "V75,75,75"


def test_legacy_settings_use_lowest_speed(qtbot):
    legacy = {"axial_speed": 75, "lateral_speed": 90, "pulse_speed": 60}
    assert treatment_motor_speed(legacy) == 60
    screen = TreatmentScreen()
    qtbot.addWidget(screen)
    screen.set_settings(legacy)
    assert screen._summary_values["motor_speed"].text() == "60%"
    assert motor_speed_command(screen.settings_values()) == "V60,60,60"
