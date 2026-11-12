"""The reset's L5 carries the lateral centre as the C zero (drx-demo A5)."""
from unittest.mock import Mock

import pytest

from helpers.arduino import Arduino

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("frame, expected", [
    ("ZEROS|150|1900", (150, 1900)),        # firmware before 2026-11, or no C sent
    ("ZEROS|150|1900|1450", (150, 1900)),   # firmware that applied the C zero
])
def test_zeros_echo_with_or_without_the_c_zero(frame, expected):
    arduino = Arduino()
    received = Mock()
    arduino.zeros_emit.connect(received)
    arduino.handle_com(frame)
    received.assert_called_once_with(*expected)


@pytest.mark.parametrize("frame", ["ZEROS|150|1900|1450|7", "ZEROS|150|1900|x", "ZEROS|150|1900|5000"])
def test_malformed_zeros_echo_is_ignored(frame):
    arduino = Arduino()
    received = Mock()
    arduino.zeros_emit.connect(received)
    arduino.handle_com(frame)
    received.assert_not_called()


def test_rejection_before_l5_reaches_command_rejected():
    arduino = Arduino()
    received = Mock()
    arduino.command_rejected.connect(received)
    arduino.handle_com("COMMAND_REJECTED|I|ZEROS_NOT_SET")
    received.assert_called_once_with({"command": "I", "reason": "ZEROS_NOT_SET"})
