"""Delayed completion for another command must not prove lateral arrival."""

from typing import Iterator, Tuple
from unittest.mock import MagicMock

import pytest

from config.constants import LATERAL_MOVE_TIMEOUT_S
from fixtures.protocol_clock import ProtocolClock
from fixtures.protocols import make_protocol
from helpers.arduino import Arduino, xor_checksum
from helpers.protocols import Protocols

pytestmark = pytest.mark.unit


@pytest.fixture
def link() -> Iterator[Tuple[Protocols, Arduino]]:
    """Use the actual parser, signals and command handles without opening serial."""
    arduino = Arduino()
    arduino.serial_com = MagicMock(is_open=True)
    arduino._running = True
    arduino.connected = True
    worker = make_protocol(ser=arduino)
    worker.is_running = True
    yield worker, arduino
    worker._disconnect_status()
    arduino._running = False


@pytest.mark.parametrize("v2", [False, True])
def test_delayed_done_for_prior_pressure_does_not_complete_lateral_move(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock, v2: bool,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = v2
    previous = arduino.send_tracked("P20")

    def receive_previous_done() -> None:
        if len(protocol_clock.sleeps) == 1:
            arduino.handle_com(f"DONE|{previous.sequence}" if v2 else "DONE")

    protocol_clock.on_sleep = receive_previous_done
    assert worker.set_to_c_distance(0) is False
    assert not worker.angle_set
    assert protocol_clock.elapsed >= LATERAL_MOVE_TIMEOUT_S


def test_v2_waits_for_its_own_done_even_when_telemetry_is_stale(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True
    previous = arduino.send_tracked("P20")

    def receive() -> None:
        current = arduino._tx_queue[-1][1]
        if len(protocol_clock.sleeps) == 1:
            arduino.handle_com(f"DONE|{previous.sequence}")
        elif len(protocol_clock.sleeps) == 2:
            arduino.handle_com(f"DONE|{current.sequence}")

    protocol_clock.on_sleep = receive
    assert worker.set_to_c_distance(0) is True
    assert len(protocol_clock.sleeps) == 2
    assert worker.current_pos_c == 0


@pytest.mark.parametrize("reply", ["BUSY", "ERR"])
def test_v2_rejection_cannot_be_overridden_by_unrelated_done(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock, reply: str,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True
    previous = arduino.send_tracked("HF1")

    def receive() -> None:
        if len(protocol_clock.sleeps) == 1:
            current = arduino._tx_queue[-1][1]
            suffix = "|move refused" if reply == "ERR" else ""
            arduino.handle_com(f"{reply}|{current.sequence}{suffix}")
            arduino.handle_com(f"DONE|{previous.sequence}")

    protocol_clock.on_sleep = receive
    assert worker.set_to_c_distance(0) is False
    assert len(protocol_clock.sleeps) == 1
    assert arduino._tx_queue[-1][1].result == reply


@pytest.mark.parametrize("v2", [False, True])
def test_position_feedback_still_proves_arrival_without_done(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock, v2: bool,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = v2
    report = "STATUS_START|S|0|0|1688|20|STATUS_END"
    protocol_clock.on_sleep = lambda: arduino.handle_com(f"{report}*{xor_checksum(report):02X}")
    assert worker.set_to_c_distance(0) is True
    assert worker.current_pos_c == 1688


def test_cancelled_v2_worker_never_queues_lateral_move(
    link: Tuple[Protocols, Arduino],
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True
    worker.cancel()
    assert worker.set_to_c_distance(0) is False
    assert not arduino._tx_queue


def test_v2_parse_retry_keeps_the_same_handle_and_ignores_old_sequence(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True
    sequences = []

    def receive() -> None:
        handle = arduino._tx_queue[-1][1]
        if len(protocol_clock.sleeps) == 1:
            sequences.append(handle.sequence)
            arduino.handle_com(f"ERR|{handle.sequence}|Invalid K value")
            sequences.append(handle.sequence)
        elif len(protocol_clock.sleeps) == 2:
            arduino.handle_com(f"DONE|{sequences[0]}")
        elif len(protocol_clock.sleeps) == 3:
            arduino.handle_com(f"DONE|{sequences[1]}")

    protocol_clock.on_sleep = receive
    assert worker.set_to_c_distance(0) is True
    assert len(protocol_clock.sleeps) == 3
    assert sequences[0] != sequences[1]


def test_v2_enqueue_failure_does_not_wait(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True
    arduino.connected = False
    arduino._running = False
    assert worker.set_to_c_distance(0) is False
    assert not protocol_clock.sleeps


def test_v2_cancellation_while_waiting_cannot_complete_move(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = True

    def cancel_and_ack() -> None:
        worker.cancel()
        arduino.handle_com(f"DONE|{arduino._tx_queue[-1][1].sequence}")

    protocol_clock.on_sleep = cancel_and_ack
    assert worker.set_to_c_distance(0) is False
    assert len(protocol_clock.sleeps) == 1
