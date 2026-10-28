"""Final cleanup requires correlated home evidence and a complete, current tare."""
import re
from types import SimpleNamespace

import pytest

from fixtures.nb2 import NB2Controller
from fixtures.protocols import make_protocol
from helpers.controller_operations import BaselineError, ControllerOperations, OperationCancelled
from helpers.firmware_protocol import parse_diagnostic_frame

pytestmark = pytest.mark.unit
CONFIG = SimpleNamespace(calibration=-28369, AMarks={"0.0": 100})


def operations(link, check=lambda: None):
    link.factor, link.a_zero = CONFIG.calibration, 100
    return ControllerOperations(link, link.send_tracked, check)


@pytest.mark.parametrize("v2", [False, True])
def test_release_evidence_and_offsets_logged_before_success(protocol_clock, caplog, v2):
    link = NB2Controller(v2)
    op = operations(link)
    link.hook = lambda command, replies: [line.replace("|100|100|", "|100|83|")
                                          for line in replies]
    try:
        op.baseline(CONFIG, final_release=True)
        token = link.commands[1][2:]
        assert re.fullmatch(r"[0-9a-f]{12}", token)
        assert link.commands == ["X", "R|" + token, "L1|HOME|" + token]
        assert op.release_evidence["actual"] == 83
        assert op.release_evidence["offset"] == -1050203
        assert op.release_evidence["pressure_lb"] == 36.61
        assert op.new_offset == 123
        assert "Final retraction confirmed stopped" in caplog.text
        assert "Final pressure zero accepted" in caplog.text
        assert not link._pending_v2
    finally:
        op.close()


@pytest.mark.parametrize("failure", ["missing", "done_only", "wrong_token", "wrong_home",
                                     "below", "above", "factor", "late_fault", "disconnect"])
def test_invalid_release_never_starts_tare(protocol_clock, failure):
    link = NB2Controller()
    op = operations(link)
    def hook(command, replies):
        if not command.startswith("R|"):
            return replies
        if failure == "missing":
            return []
        if failure == "done_only":
            return ["MOTION_DONE|I|100|100", "DONE"]
        if failure == "disconnect":
            link.connection_lost.emit()
        if failure == "late_fault":
            return replies + ["FAULT|HOME_RELEASE_TIMEOUT|0|36.61"]
        frame = replies[0].split("|")
        field = {"wrong_token": (1, "ffffffffffff"), "wrong_home": (2, "101"),
                 "below": (3, "74"), "above": (3, "126"), "factor": (6, "1")}
        if failure in field:
            index, value = field[failure]
            frame[index] = value
        return ["|".join(frame), "DONE"]
    link.hook = hook
    try:
        with pytest.raises(BaselineError):
            op.baseline(CONFIG, final_release=True)
        assert not any(c.startswith("L1") for c in link.commands)
        assert not link.baseline_valid
    finally:
        op.close()


@pytest.mark.parametrize("failure", ["missing", "no_started", "wrong_factor", "no_done",
                                     "fault_after_done", "cancel_after_done", "disconnect"])
def test_tare_must_complete_without_late_fault_or_cancel(protocol_clock, failure):
    link = NB2Controller(True)
    cancelled = []
    def check():
        if cancelled:
            raise OperationCancelled("cancelled")
    op = operations(link, check)
    def hook(command, replies):
        if not command.startswith("L1|HOME|"):
            return replies
        if failure == "missing":
            return []
        if failure == "no_started":
            return replies[1:]
        if failure == "wrong_factor":
            return [line.replace("|-28369", "|-1") for line in replies]
        if failure == "no_done":
            return replies[:-1]
        if failure == "fault_after_done":
            return replies + ["FAULT|POSITION_FEEDBACK_INVALID|0|36.61"]
        if failure == "cancel_after_done":
            cancelled.append(True)
        if failure == "disconnect":
            link.connection_lost.emit()
        return replies
    link.hook = hook
    try:
        with pytest.raises((BaselineError, OperationCancelled)):
            op.baseline(CONFIG, final_release=True)
        assert sum(c.startswith("L1|HOME|") for c in link.commands) == 1
        assert not link.baseline_valid
    finally:
        op.close()


@pytest.mark.parametrize("reason,attempts", [("UNSTABLE", 2), ("SENSOR_TIMEOUT", 1),
                                           ("HOME_POSITION_CHANGED", 1)])
def test_only_explicit_unstable_gets_one_retry(protocol_clock, reason, attempts):
    link = NB2Controller()
    op = operations(link)
    def hook(command, replies):
        return ["CALIBRATION|TARE|REJECTED|" + reason] if command.startswith("L1|") else replies
    link.hook = hook
    try:
        with pytest.raises(BaselineError):
            op.baseline(CONFIG, final_release=True)
        assert sum(c.startswith("L1|HOME|") for c in link.commands) == attempts
        assert sum(c.startswith("R|") for c in link.commands) == 1
    finally:
        op.close()


def test_old_firmware_blocks_treatment_before_motion(protocol_clock):
    link = NB2Controller()
    link.firmware_capabilities = frozenset()
    link.hook = lambda cmd, replies: [line.replace("|HOME_RELEASE_V1", "") for line in replies]
    worker = make_protocol(ser=link)
    worker.run()
    assert not any(c[0] in "PIKARJL" for c in link.commands)
    assert "update required" in worker._failure_reason
    assert "HOME_RELEASE_V1" in worker._failure_reason


@pytest.mark.parametrize("reset", ["Reset|", "Ready to Go"])
def test_reset_removes_home_release_capability(reset):
    link = NB2Controller()
    link.handle_com(reset)
    assert not link.firmware_capabilities


@pytest.mark.parametrize("frame", [
    "HOME_RELEASE|ABCDEF012345|100|83|36.61|-1050203|-28369",
    "HOME_RELEASE|012345abcdef|100|4096|36.61|-1050203|-28369",
    "HOME_RELEASE|012345abcdef|100|83|nan|-1050203|-28369",
    "HOME_RELEASE|012345abcdef|100|83|-1|-1050203|-28369",
    "HOME_RELEASE|012345abcdef|100|83|36.61|-8388609|-28369",
    "HOME_RELEASE|012345abcdef|100|83|36.61|-1050203|0",
    "HOME_RELEASE|012345abcdef|100|83|36.61|-1050203|-28369|DONE",
])
def test_invalid_release_frames_are_rejected(frame):
    with pytest.raises(ValueError):
        parse_diagnostic_frame(frame)


@pytest.mark.parametrize("protocol", ["1", "2", "3", "4"])
def test_failed_final_pulse_stop_keeps_timed_completion(protocol_clock, protocol):
    link = NB2Controller()
    worker = make_protocol(ser=link, protocol=protocol, use_pulse=True, pulse_rate=4)
    link.factor = worker.config.calibration
    link.a_zero = int(worker.config.AMarks.get("0.0", worker.config.AMarks.get("0")))
    original = link.send_tracked
    def send(command):
        if command == "JS" and worker.treatment_completed:
            return None
        return original(command)
    link.send_tracked = send
    worker.run()
    assert worker.treatment_completed
    assert worker.outcome == "completed_cleanup_failed"
    assert worker.cleanup_warning.startswith("Treatment completed, but cleanup needs attention:")
    assert not any(c.startswith("R|") for c in link.commands)
    assert not link.baseline_valid
