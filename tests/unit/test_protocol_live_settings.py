"""Live Treatment-setting behavior for a running protocol."""

from unittest.mock import MagicMock, call

import pytest

import helpers.protocols as protocols_mod
from helpers.protocols import Protocols


pytestmark = pytest.mark.unit


def make_worker(**kwargs):
    defaults = {
        "a_factor": 1900,
        "protocol": "2",
        "max_pressure": 50,
        "max_left": 10.0,
        "max_right": 10.0,
        "duration": 1,
        "use_pulse": True,
        "ser": MagicMock(),
        "config": MagicMock(),
        "pulse_rate": 2.0,
    }
    defaults.update(kwargs)
    worker = Protocols(**defaults)
    worker.arduino.send.return_value = True
    return worker


def test_zero_pulse_rate_stops_immediately():
    worker = make_worker()
    worker.is_running = True
    worker._pulse_active = True  # firmware pulsing is on
    worker.arduino.reset_mock()

    assert worker.request_live_pulse_rate(0)

    assert worker.use_pulse is False
    assert worker.pulse_rate == 0
    worker.arduino.send.assert_called_once_with("JS")
    assert worker._pulse_active is False


def test_zero_pulse_rate_without_active_pulse_only_flags():
    """No JS when nothing is pulsing: the worker simply never starts it. (On
    the deployed firmware a stray JS zeroes the last-addressed SMC.)"""
    worker = make_worker()
    worker.is_running = True
    worker._pulse_active = False
    worker.arduino.reset_mock()

    assert worker.request_live_pulse_rate(0)

    assert worker.use_pulse is False
    worker.arduino.send.assert_not_called()


def test_start_pulse_marks_pulse_active():
    worker = make_worker()
    worker.arduino.reset_mock()
    assert worker._start_pulse()
    assert worker._pulse_active is True


def test_overpressure_during_hold_routes_through_worker_revision():
    """The GUI-thread status slot must not send P itself while the worker's
    hold loop owns the axial SMC (it stops pulsing first, then applies)."""
    worker = make_worker()
    worker.is_running = True
    worker._live_phase = True
    worker.arduino.reset_mock()
    before = worker._pressure_revision

    worker.update_status(0, 0, 0, worker.max_pressure + 10)

    worker.arduino.send.assert_not_called()
    assert worker._pressure_revision == before + 1


def test_overpressure_while_paused_backs_off_directly():
    worker = make_worker()
    worker.is_running = True
    worker._live_phase = True
    worker.is_paused = True
    worker.arduino.reset_mock()

    worker.update_status(0, 0, 0, worker.max_pressure + 10)

    worker.arduino.send.assert_called_once_with(f"P{float(worker.max_pressure)}")


def test_positive_live_pulse_change_reprograms_active_cadence(monkeypatch):
    monkeypatch.setattr(protocols_mod, "PULSE_RATE_FIRMWARE_SUPPORT", True)
    worker = make_worker()
    worker.is_running = True
    worker.arduino.reset_mock()

    assert worker.request_live_pulse_rate(4)
    ok, pulse_active = worker._sync_live_pulse(True)

    assert ok
    assert pulse_active
    worker.arduino.send.assert_called_once_with("J250")


@pytest.mark.parametrize(
    ("side", "value", "attribute", "expected"),
    [
        ("left", 15, "max_left", -15),
        ("right", 12, "max_right", 12),
    ],
)
def test_live_angle_request_updates_protocol_limit(side, value, attribute, expected):
    worker = make_worker()

    assert worker.request_live_angle(side, value)

    assert getattr(worker, attribute) == expected


def test_active_side_angle_is_applied_by_worker_thread():
    worker = make_worker(use_pulse=False)
    worker.is_running = True
    worker._active_lateral_side = "left"
    worker.set_to_c_distance = MagicMock(return_value=True)

    worker.request_live_angle("left", 16)
    ok, pulse_active = worker._service_live_motion_updates(False)

    assert ok
    assert pulse_active is False
    worker.set_to_c_distance.assert_called_once_with(-16)


def test_inactive_oscillation_side_waits_for_that_side():
    worker = make_worker(use_pulse=False)
    worker.is_running = True
    worker._active_lateral_side = "left"
    worker.set_to_c_distance = MagicMock(return_value=True)

    worker.request_live_angle("right", 18)
    ok, _ = worker._service_live_motion_updates(False)

    assert ok
    worker.set_to_c_distance.assert_not_called()


def test_live_pressure_stops_pulse_adjusts_then_restarts(monkeypatch):
    monkeypatch.setattr(protocols_mod, "PULSE_RATE_FIRMWARE_SUPPORT", True)
    worker = make_worker()
    worker.is_running = True
    worker._apply_live_pressure_target = MagicMock(return_value=True)
    worker.arduino.reset_mock()

    worker.request_live_pressure(70)
    ok, pulse_active = worker._service_live_motion_updates(True)

    assert ok
    assert pulse_active
    worker._apply_live_pressure_target.assert_called_once_with(70)
    assert worker.arduino.send.call_args_list == [
        call("JS"),
        call("J500"),
    ]


def test_live_pressure_increase_uses_safe_increments():
    worker = make_worker(use_pulse=False)
    worker.is_running = True
    worker.current_pressure = 45
    commanded = []

    def set_pressure(value):
        commanded.append(value)
        worker.current_pressure = value
        return True

    worker.set_to_pressure = set_pressure

    assert worker._apply_live_pressure_target(70)
    assert commanded == [55, 65, 70]


def test_live_pressure_decrease_applies_directly():
    worker = make_worker(use_pulse=False)
    worker.is_running = True
    worker.current_pressure = 65
    worker.set_to_pressure = MagicMock(return_value=True)

    assert worker._apply_live_pressure_target(40)
    worker.set_to_pressure.assert_called_once_with(40)


def test_pulse_off_does_not_end_the_hold_phase(monkeypatch):
    worker = make_worker()
    worker.is_running = True
    worker.check_duration = MagicMock(side_effect=[True, True, False])
    monkeypatch.setattr(protocols_mod.time, "sleep", lambda _seconds: None)
    original_sync = worker._sync_live_pulse
    sync_count = 0

    def sync_then_disable(pulse_active):
        nonlocal sync_count
        result = original_sync(pulse_active)
        sync_count += 1
        if sync_count == 1:
            with worker._live_settings_lock:
                worker.pulse_rate = 0
                worker.use_pulse = False
                worker._pulse_revision += 1
        return result

    worker._sync_live_pulse = sync_then_disable
    worker.arduino.reset_mock()

    assert worker._pulse_or_hold_phase()
    assert worker.check_duration.call_count == 3
    assert worker.arduino.send.call_args_list == [call("J500"), call("JS")]


def test_protocol_2_reads_latest_left_angle_after_pressure_ramp():
    worker = make_worker(use_pulse=False)
    worker.is_running = True

    def finish_preamble(_banner):
        worker.request_live_angle("left", 17)
        return True

    worker._preamble = finish_preamble
    worker.set_to_c_distance = MagicMock(return_value=True)
    worker._pulse_or_hold_phase = MagicMock(return_value=True)
    worker._release = MagicMock(return_value=True)

    worker._run_standard_protocol("test", "left")

    worker.set_to_c_distance.assert_called_once_with(-17)
