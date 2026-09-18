"""Malformed diagnostics cannot become measurements, completions or authority."""
from unittest.mock import Mock
import pytest
from fixtures.nb2 import NB2Controller
from helpers.arduino import Arduino
from helpers.firmware_protocol import parse_diagnostic_frame

pytestmark = pytest.mark.unit

@pytest.mark.parametrize("frame", [
    "MOTION_DONE|P|40|39.9", "MOTION_DONE|K|1500|1600", "MOTION_DONE|I|100|125",
    "FAULT|PRESSURE_LIMIT|40|101", "FIRMWARE|2026-09-17|DRX-HX711-NB2",
    "CALIBRATION|SET|-28369.000000", "CALIBRATION|TARE|STARTED",
    "CALIBRATION|TARE|OK|-425535|-28369", "CALIBRATION|TARE|REJECTED|UNSTABLE",
    "CALIBRATION|TARE|CANCELLED|STOP", "COMMAND_REJECTED|P|TARE_REQUIRED",
    "DIAG|HX711|-300|-200|-100|1.000000|20|40|150|1",
    "DIAG|HX711|0|0|1|0|-1|40|150|0", "NOTICE|PRESSURE_NO_PROGRESS|2150|1.5|2.5",
])
def test_valid_typed_replies(frame):
    signal, result = parse_diagnostic_frame(frame)
    assert signal and result

@pytest.mark.parametrize("frame", [
    "MOTION_DONE|P|nan|40", "MOTION_DONE|P|40|inf", "MOTION_DONE|K|1500|4096",
    "MOTION_DONE|I|100.5|100", "MOTION_DONE|K|1500|-1", "MOTION_DONE|P|40|1_0",
    "MOTION_DONE|P|40|40|DONE", "CALIBRATION|SET|0", "CALIBRATION|SET|nan",
    "CALIBRATION|TARE|OK|8388608|1", "CALIBRATION|TARE|OK|0|0",
    "DIAG|HX711|0|0|1|nan|0|0|0|1", "DIAG|HX711|0|0|1|0|0|0|0|2",
    "DIAG|HX711|0|0|1|0|-2|0|0|0", "FAULT|PRESSURE_LIMIT|40|nan",
    "NOTICE|PRESSURE_NO_PROGRESS|2150|1|-1", "COMMAND_REJECTED|P|BAD REASON",
])
def test_invalid_typed_replies_never_emit(frame):
    with pytest.raises(ValueError):
        parse_diagnostic_frame(frame)
    arduino = Arduino()
    received = Mock()
    for name in ("motion_done", "calibration_result", "sensor_diagnostics", "fault_emit",
                 "pressure_warning", "command_rejected", "done_emit"):
        getattr(arduino, name).connect(received)
    arduino.handle_com(frame)
    received.assert_not_called()


def test_identity_is_invalidated_by_reboot_and_calibration_is_blocked():
    link = NB2Controller()
    link.handle_com("Ready to Go")
    assert not link.baseline_valid and link.firmware_driver is None
    assert link.send_tracked("L01.0") is None
    assert link.send_tracked("L1|BASELINE") is None
    link.handle_com("FIRMWARE|test|DRX-HX711-NB2")
    assert link.send_tracked("L01.0") is not None


@pytest.mark.parametrize("v2", [False, True])
def test_late_rejection_after_stop_cannot_resurrect_old_motion(v2):
    link = NB2Controller(v2)
    link.hook = lambda command, replies: []
    handle = link.send_tracked("K1800")
    link.send_tracked("X")
    link.handle_com(f"ERR|{handle.sequence}|Invalid K value" if v2 else "ERROR: Invalid K value")
    assert not link._tx_queue
    assert handle.result == "CANCELLED"
