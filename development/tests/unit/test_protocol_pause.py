"""Unit tests for Protocols pause/resume + pulse-rate command (Phase 3.5).

These build a Protocols worker against a MagicMock Arduino (no serial), so they
exercise the pause/resume state machine, the clock-freeze in check_duration, and
the firmware-gated J<ms> / bare-J pulse command — without running any protocol.
"""

from functools import partial
import time

import pytest

import helpers.protocols as protocols_mod
from fixtures.protocol_clock import ProtocolClock
from fixtures.protocols import make_protocol


make_worker = partial(make_protocol, protocol="1", use_pulse=True, pulse_rate=2.0)


pytestmark = pytest.mark.unit


def test_pause_noop_when_not_running():
    w = make_worker()
    w.is_running = False
    w.pause()
    assert w.is_paused is False


def test_pause_sets_state_and_stops_pulse():
    w = make_worker()
    w.is_running = True
    w._pulse_active = True  # firmware pulsing is on
    w.arduino.reset_mock()
    w.pause()
    assert w.is_paused is True
    assert w._pause_started is not None
    # Pause must HOLD (stop pulsing) and never send an emergency stop.
    w.arduino.send.assert_called_once_with("JS")
    assert w._pulse_active is False


def test_pause_without_active_pulse_sends_nothing():
    """During the ramp or a lateral move no pulse is running. A JS there
    stalled the in-flight move on the deployed firmware (JS zeroed whichever
    SMC was last addressed), failing the treatment after its timeout."""
    w = make_worker()
    w.is_running = True
    w._pulse_active = False
    w.arduino.reset_mock()
    w.pause()
    assert w.is_paused is True
    w.arduino.send.assert_not_called()


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


@pytest.mark.parametrize("command", ["P50", "K1500", "J"], ids=["pressure", "lateral", "pulse"])
def test_cancelled_worker_rejects_commands_even_if_running_flag_is_reset(command: str) -> None:
    """Cancellation permanently closes the send gate to late callbacks."""
    w = make_worker()
    w.cancel()
    w.is_running = True
    assert w._send_command(command) is False
    w.arduino.send.assert_not_called()


def test_cancellation_while_paused_aborts_ramp(protocol_clock: ProtocolClock) -> None:
    """A paused worker can be cancelled without resuming or sending pressure."""
    w = make_worker()
    w.is_running = True
    w.is_paused = True
    protocol_clock.on_sleep = w.cancel
    assert w.run_pressure_sequence(10, 50) is False
    assert w.is_paused is False
    w.arduino.send.assert_not_called()


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

    try:
        # The initial 10-lb waypoint was already completed by the preamble.
        # Only its next waypoint may be sent before the pause.
        assert sends == ["P20|80"]
    finally:
        w.cancel()
        t.join(timeout=2)
    assert not t.is_alive()
