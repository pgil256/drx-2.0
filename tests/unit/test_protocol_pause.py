"""Unit tests for Protocols pause/resume + pulse-rate command (Phase 3.5).

These build a Protocols worker against a MagicMock Arduino (no serial), so they
exercise the pause/resume state machine, the clock-freeze in check_duration, and
the firmware-gated J<ms> / bare-J pulse command — without running any protocol.
"""

import time
from unittest.mock import MagicMock

import pytest

import helpers.protocols as protocols_mod
from helpers.protocols import Protocols

pytestmark = pytest.mark.unit


def make_worker(**kwargs):
    defaults = dict(
        a_factor=1900,
        protocol="1",
        max_pressure=50,
        max_left=10.0,
        max_right=10.0,
        duration=1,        # 1 minute -> 60s
        use_pulse=True,
        ser=MagicMock(),
        config=MagicMock(),
        pulse_rate=2.0,
    )
    defaults.update(kwargs)
    return Protocols(**defaults)


def test_pause_noop_when_not_running():
    w = make_worker()
    w.is_running = False
    w.pause()
    assert w.is_paused is False


def test_pause_sets_state_and_stops_pulse():
    w = make_worker()
    w.is_running = True
    w.arduino.reset_mock()
    w.pause()
    assert w.is_paused is True
    assert w._pause_started is not None
    # Pause must HOLD (stop pulsing) and never send an emergency stop.
    w.arduino.send.assert_called_once_with("JS")


def test_resume_clears_pause_and_shifts_clock():
    w = make_worker()
    w.is_running = True
    w.start_time = time.time() - 5.0
    w.pause()
    paused_start = w.start_time
    time.sleep(0.05)
    w.resume()
    assert w.is_paused is False
    assert w._pause_started is None
    # start_time shifted forward by (roughly) the paused span.
    assert w.start_time > paused_start


def test_check_duration_frozen_while_paused():
    w = make_worker(duration=1)  # 60s
    w.is_running = True
    w.start_time = time.time() - 59.0  # ~1s left
    w.pause()
    frozen = w.elapsed_time
    w.check_duration()
    e1 = w.elapsed_time
    time.sleep(0.1)
    w.check_duration()
    e2 = w.elapsed_time
    # Elapsed time does not advance while paused.
    assert e1 == pytest.approx(e2, abs=1e-6)


def test_wait_while_paused_returns_when_unpaused():
    w = make_worker()
    w.is_running = True
    # Not paused -> returns immediately.
    w._wait_while_paused()  # should not hang
    assert True


def test_start_pulse_bare_j_without_firmware_support(monkeypatch):
    monkeypatch.setattr(protocols_mod, "PULSE_RATE_FIRMWARE_SUPPORT", False)
    w = make_worker(pulse_rate=2.0)
    w.arduino.reset_mock()
    w._start_pulse()
    w.arduino.send.assert_called_once_with("J")


def test_start_pulse_with_interval_when_firmware_supported(monkeypatch):
    monkeypatch.setattr(protocols_mod, "PULSE_RATE_FIRMWARE_SUPPORT", True)
    w = make_worker(pulse_rate=2.0)  # 2/sec -> 500 ms
    w.arduino.reset_mock()
    w._start_pulse()
    w.arduino.send.assert_called_once_with("J500")


def test_start_pulse_interval_clamped(monkeypatch):
    monkeypatch.setattr(protocols_mod, "PULSE_RATE_FIRMWARE_SUPPORT", True)
    w = make_worker(pulse_rate=0.1)  # 0.1/sec -> 10000 ms, clamped to 5000
    w.arduino.reset_mock()
    w._start_pulse()
    w.arduino.send.assert_called_once_with("J5000")


# ----- ramp-phase pause hold (regression for the high-severity review finding) -----
def test_ramp_blocks_at_entry_when_paused():
    """Pausing before the ramp issues any command must hold — no P sent."""
    import threading
    w = make_worker(max_pressure=80)
    w.is_running = True
    w.is_paused = True
    w.arduino.send.return_value = True
    w.arduino.reset_mock()

    done = []
    t = threading.Thread(target=lambda: done.append(w.run_pressure_sequence(10, 80)),
                         daemon=True)
    t.start()
    time.sleep(0.3)
    # Held at the entry gate: nothing sent, not returned.
    assert w.arduino.send.call_count == 0
    assert not done
    # Release + stop so the worker unwinds.
    w.is_paused = False
    w.is_running = False
    t.join(timeout=2)
    assert not t.is_alive()


def test_ramp_stops_escalating_when_paused_mid_ramp():
    """Pausing after the first P must stop pressure escalation (the safety fix)."""
    import threading
    w = make_worker(max_pressure=80)
    w.is_running = True
    w.current_pressure = 100  # always "stable" so waits would pass instantly

    sends = []

    def fake_send(cmd):
        sends.append(cmd)
        # Pause as soon as the first pressure command is issued.
        if cmd.startswith("P") and len([c for c in sends if c.startswith("P")]) == 1:
            w.is_paused = True
        return True

    w.arduino.send.side_effect = fake_send

    t = threading.Thread(target=lambda: w.run_pressure_sequence(10, 80), daemon=True)
    t.start()
    time.sleep(0.5)

    # No escalated pressure (> the initial 10 lbs) may be sent while paused.
    escalated = [c for c in sends if c.startswith("P") and float(c[1:]) > 10]
    assert escalated == [], f"pressure escalated while paused: {sends}"

    w.is_paused = False
    w.is_running = False
    t.join(timeout=2)
