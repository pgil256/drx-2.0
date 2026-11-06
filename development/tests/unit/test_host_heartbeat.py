"""Host heartbeat (HOST_HEARTBEAT_V1): the I/O thread sends W every 0.5 s.

Firmware that advertises the capability latches FAULT|HOST_TIMEOUT after 3 s
with no host line during motion, once it has seen one W. These tests cover the
host side: the identity field, the cadence, and who is (and is not) sent W.
"""
import threading
import time
from unittest.mock import MagicMock

import pytest

from helpers.arduino import Arduino
from helpers.firmware_protocol import parse_diagnostic_frame

pytestmark = pytest.mark.unit

LEGACY = "FIRMWARE|2026-10-28-DRX2-NB2-SERVICE|DRX-HX711-NB2"
HEARTBEAT = LEGACY + "|HOST_HEARTBEAT_V1"


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


def connected(identity=HEARTBEAT):
    arduino = Arduino()
    arduino.serial_com = MagicMock(is_open=True)
    arduino.connected = True
    arduino._running = True
    if identity:
        arduino.handle_com(identity)
    return arduino


def w_writes(arduino):
    return [c for c in arduino.serial_com.write.call_args_list if c[0][0] == b"W\n"]


def test_identity_capability_is_parsed():
    assert parse_diagnostic_frame(HEARTBEAT) == ("firmware_identity", {
        "version": "2026-10-28-DRX2-NB2-SERVICE", "driver": "DRX-HX711-NB2",
        "host_heartbeat": True})
    assert "host_heartbeat" not in parse_diagnostic_frame(LEGACY)[1]
    # Unknown capabilities are ignored so later firmware stays readable.
    assert parse_diagnostic_frame(HEARTBEAT + "|FUTURE_V2")[1]["host_heartbeat"] is True


@pytest.mark.parametrize("frame", [
    HEARTBEAT + "|HOST_HEARTBEAT_V1", LEGACY + "|host_heartbeat_v1", LEGACY + "|",
    "FIRMWARE|v|DRX-HX711-NB2" + "|CAP_V1" * 9, "FIRMWARE|v",
])
def test_malformed_capabilities_reject_the_identity(frame):
    with pytest.raises(ValueError):
        parse_diagnostic_frame(frame)


def test_w_every_half_second_while_connected():
    arduino, clock = connected(), Clock()
    sent_at = []
    for step in range(17):  # The I/O loop wakes about every 10 ms; sample every 125 ms.
        before = len(w_writes(arduino))
        arduino._service_heartbeat(clock)
        if len(w_writes(arduino)) > before:
            sent_at.append(clock.now - 100.0)
        clock.now += 0.125  # Exact in binary, so no rounding at the 0.5 s edges.
    assert sent_at == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert arduino.heartbeats_sent == 5


@pytest.mark.parametrize("v2", [False, True])
def test_w_is_unframed_and_untracked_even_with_protocol_v2(v2):
    arduino = connected()
    arduino.protocol_v2 = v2
    arduino._service_heartbeat(Clock())
    arduino.serial_com.write.assert_called_once_with(b"W\n")
    assert not arduino._pending_v2 and not arduino._tx_queue


@pytest.mark.parametrize("identity", [LEGACY, None])
def test_no_w_without_the_capability(identity):
    arduino, clock = connected(identity), Clock()
    for _ in range(10):
        arduino._service_heartbeat(clock)
        clock.now += 0.5
    assert w_writes(arduino) == []


def test_no_w_while_disconnected_or_after_reset():
    arduino, clock = connected(), Clock()
    arduino.connected = False
    arduino._service_heartbeat(clock)
    assert w_writes(arduino) == []
    arduino.connected = True
    arduino.send_tracked("Y")  # The board restarts disarmed and must identify again.
    clock.now += 1
    arduino._service_heartbeat(clock)
    assert w_writes(arduino) == []
    arduino.handle_com(HEARTBEAT)
    arduino._service_heartbeat(clock)
    assert len(w_writes(arduino)) == 1


def test_link_loss_forgets_the_capability():
    arduino = connected()
    arduino._handle_link_lost()
    assert arduino.host_heartbeat is False


def test_io_thread_keeps_sending_while_another_thread_is_blocked():
    arduino = connected()
    port = arduino.serial_com
    port.in_waiting = 0
    names = []
    port.write.side_effect = lambda payload: names.append(threading.current_thread().name)
    arduino._start_io_thread()
    try:
        time.sleep(1.3)  # This thread stands in for a stalled GUI thread.
        assert len(names) >= 2
        assert threading.current_thread().name not in names
    finally:
        arduino.disconnect()
    count = len(names)
    time.sleep(0.6)
    assert len(names) == count
