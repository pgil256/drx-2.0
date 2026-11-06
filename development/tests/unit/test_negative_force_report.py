"""Force below the tared zero is logged, never a fault or a UI change (drx-demo A6)."""
from unittest.mock import Mock

import pytest

from helpers.arduino import Arduino
from helpers.firmware_protocol import parse_diagnostic_frame

pytestmark = pytest.mark.unit

FRAME = "DIAG|PRESSURE|NEGATIVE|-3.25|-325"


def test_frame_parses_to_negative_force():
    assert parse_diagnostic_frame(FRAME) == ("negative_force", {"signed_lb": -3.25, "raw": -325})


@pytest.mark.parametrize("frame", [
    "DIAG|PRESSURE|NEGATIVE|-3.25", "DIAG|PRESSURE|NEGATIVE|-3.25|1|2",
    "DIAG|PRESSURE|NEGATIVE|low|1", "DIAG|PRESSURE|POSITIVE|3|1",
    "DIAG|PRESSURE|NEGATIVE|-3.25|99999999",
])
def test_malformed_frames_are_rejected(frame):
    with pytest.raises(ValueError):
        parse_diagnostic_frame(frame)


def test_driver_logs_a_warning_and_raises_no_fault():
    arduino = Arduino()
    arduino.logger = Mock()
    received, faults, errors = Mock(), Mock(), Mock()
    arduino.negative_force.connect(received)
    arduino.fault_emit.connect(faults)
    arduino.error_emit.connect(errors)
    arduino.handle_com(FRAME)
    received.assert_called_once_with({"signed_lb": -3.25, "raw": -325})
    faults.assert_not_called()
    errors.assert_not_called()
    message, signed_lb, raw = arduino.logger.warning.call_args[0]
    assert "below the tared zero" in message and (signed_lb, raw) == (-3.25, -325)
