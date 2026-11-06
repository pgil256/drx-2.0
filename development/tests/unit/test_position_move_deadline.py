"""Firmware position-move deadline (drx-demo A3): ERR ends the move, never resent."""
from typing import Iterator, Tuple
from unittest.mock import MagicMock

import pytest

from config.constants import LATERAL_MOVE_TIMEOUT_S
from fixtures.nb2 import NB2Controller
from fixtures.protocol_clock import ProtocolClock
from fixtures.protocols import make_protocol
from fixtures.reset import make_config, make_main_window
from helpers.arduino import PARSE_REJECTIONS, Arduino
from helpers.protocols import Protocols
from helpers.reset_worker import ResetWorker

pytestmark = pytest.mark.unit

TIMEOUT = "POSITION_MOVE_TIMEOUT"


def test_timeout_is_not_a_parse_rejection():
    # A parse rejection is resent once; a move stopped at its deadline must not be.
    assert TIMEOUT not in PARSE_REJECTIONS


@pytest.mark.parametrize("v2", [False, True])
@pytest.mark.parametrize("step", ["K", "I13", "I120"])
def test_reset_step_timeout_fails_the_reset_without_replay(protocol_clock, v2, step):
    link = NB2Controller(v2)
    link.hook = lambda command, replies: ["ERR|" + TIMEOUT] if command.startswith(step) else replies
    worker = ResetWorker(link, make_config(), make_main_window())
    finished, errors = [], []
    worker.signals.finished.connect(finished.append)
    worker.signals.error.connect(errors.append)
    worker.run()
    assert finished == [False]
    assert errors and TIMEOUT in errors[0]
    assert link.commands.count("Y") == 1                  # not a timeout: no replay
    assert sum(c.startswith(step) for c in link.commands) == 1  # and no resend
    assert link.commands[-1] == "X"
    assert not link.baseline_valid


@pytest.fixture
def link() -> Iterator[Tuple[Protocols, Arduino]]:
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
def test_lateral_timeout_ends_the_protocol_move_at_once(
    link: Tuple[Protocols, Arduino], protocol_clock: ProtocolClock, v2: bool,
) -> None:
    worker, arduino = link
    arduino.protocol_v2 = v2

    def stopped_at_deadline() -> None:
        if len(protocol_clock.sleeps) == 1:
            handle = arduino._tx_queue[-1][1]
            arduino.handle_com(f"ERR|{handle.sequence}|{TIMEOUT}" if v2 else "ERROR: " + TIMEOUT)

    protocol_clock.on_sleep = stopped_at_deadline
    assert worker.set_to_c_distance(0) is False
    assert not worker.angle_set
    assert protocol_clock.elapsed < LATERAL_MOVE_TIMEOUT_S
    assert TIMEOUT in (worker._failure_reason or "")
    assert sum(1 for _wire, handle in arduino._tx_queue if handle.command.startswith("K")) <= 1
