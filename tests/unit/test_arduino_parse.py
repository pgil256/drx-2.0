# tests/unit/test_arduino_parse.py
import pytest
from unittest.mock import MagicMock, patch

from helpers.arduino import Arduino, xor_checksum


@pytest.fixture
def arduino():
    """Create an Arduino instance with mocked serial connection."""
    a = Arduino()
    a.serial_com = MagicMock()
    a.serial_com.is_open = True
    a.connected = True
    return a


@pytest.mark.unit
class TestStatusParsing:
    """Tests for handle_com parsing STATUS_START messages."""

    def test_valid_status_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3|STATUS_END")
        assert blocker.args == [1500, 2000, 1200, 45.3]

    def test_truncated_status_rejected(self, arduino, qtbot):
        """A frame without STATUS_END carries potentially corrupted values
        and must never reach the safety-limit checks."""
        with qtbot.assertNotEmitted(arduino.status_emit, wait=100):
            arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3")

    def test_status_with_zero_pressure(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|0|0|0|0.0|STATUS_END")
        assert blocker.args == [0, 0, 0, 0.0]

    def test_status_too_few_fields(self, arduino):
        """Status with fewer than 5 tokens after S should not emit."""
        # This should not crash - it just won't emit since len(tokens) < 5
        arduino.handle_com("STATUS_START|S|1500|2000|STATUS_END")


@pytest.mark.unit
class TestDoneResponse:
    """Tests for DONE response parsing."""

    def test_done_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.done_emit, timeout=1000):
            arduino.handle_com("DONE")


@pytest.mark.unit
class TestOKResponse:
    """Tests for OK response parsing."""

    def test_ok_sets_event(self, arduino):
        arduino.ok_event.clear()
        arduino.handle_com("OK")
        assert arduino.ok_event.is_set()

    def test_ok_requires_exact_token(self, arduino):
        """Substring matching used to let any message containing 'OK'
        (e.g. a future error text) falsely satisfy verify_connection."""
        arduino.ok_event.clear()
        arduino.handle_com("NOT OKAY")
        assert not arduino.ok_event.is_set()


@pytest.mark.unit
class TestPositionResponse:
    """Tests for position response parsing."""

    def test_position_p_format(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.position_emit, timeout=1000) as blocker:
            arduino.handle_com("P|1500")
        assert blocker.args[0] == 1500

    def test_l6_report_feeds_status(self, arduino, qtbot):
        """The L6 'A|a|b|c|p' report carries the same payload as a status
        frame and now feeds the same signal."""
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("A|100|200|300|12.5")
        assert blocker.args == [100, 200, 300, 12.5]


@pytest.mark.unit
class TestFirmwareSafetyMessages:
    """ERROR:/BUSY/RELEASED/ZEROS lines are safety telemetry that used to
    be dropped as 'unrecognized data'."""

    def test_error_line_emits_error_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com("ERROR: Pressure limit exceeded")
        assert blocker.args == ["Pressure limit exceeded"]

    def test_busy_emits_error_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com("BUSY")
        assert blocker.args == ["BUSY"]

    def test_released_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.released_emit, timeout=1000):
            arduino.handle_com("RELEASED")

    def test_zeros_echo_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.zeros_emit, timeout=1000) as blocker:
            arduino.handle_com("ZEROS|160|1900")
        assert blocker.args == [160, 1900]


@pytest.mark.unit
class TestSendQueueing:
    """send() enqueues for the I/O thread instead of touching the port."""

    def test_send_refused_without_link(self):
        a = Arduino()
        assert a.send("T") is False

    def test_x_jumps_the_queue(self, arduino):
        arduino._running = True
        arduino.send("K1500")
        arduino.send("P20")
        arduino.send("X")
        assert list(arduino._priority_queue) == ["X"]
        assert list(arduino._tx_queue) == ["K1500", "P20"]

    def test_empty_command_refused(self, arduino):
        arduino._running = True
        assert arduino.send("  ") is False


def _frame(seq, cmd):
    body = f"{seq}:{cmd}"
    return f"#{body}*{xor_checksum(body):02X}"


@pytest.mark.unit
class TestProtocolV2Send:
    """With protocol_v2 enabled, commands are framed with seq + checksum."""

    def test_commands_are_framed(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        arduino.send("P50")
        assert list(arduino._tx_queue) == [_frame(1, "P50")]

    def test_framed_x_still_jumps_the_queue(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        arduino.send("K1500")
        arduino.send("X")
        assert list(arduino._priority_queue) == [_frame(2, "X")]
        assert list(arduino._tx_queue) == [_frame(1, "K1500")]

    def test_sequence_increments(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        arduino.send("T")
        arduino.send("T")
        assert list(arduino._tx_queue) == [_frame(1, "T"), _frame(2, "T")]


@pytest.mark.unit
class TestProtocolV2Receive:
    """Seq-bearing acks and checksummed status frames."""

    def test_done_with_seq(self, arduino, qtbot):
        arduino._running = True
        arduino.protocol_v2 = True
        handle = arduino.send_tracked("K1300")
        with qtbot.waitSignal(arduino.done_emit, timeout=1000):
            arduino.handle_com(f"DONE|{handle.sequence}")
        assert arduino.last_done_seq == handle.sequence
        assert handle.completed.is_set()
        assert handle.result == "DONE"

    def test_busy_with_seq_emits_error(self, arduino, qtbot):
        arduino._running = True
        arduino.protocol_v2 = True
        handle = arduino.send_tracked("K1300")
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com(f"BUSY|{handle.sequence}")
        assert blocker.args == ["BUSY"]
        assert handle.result == "BUSY"

    def test_err_with_seq_and_reason(self, arduino, qtbot):
        arduino._running = True
        arduino.protocol_v2 = True
        handle = arduino.send_tracked("P50")
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com(
                f"ERR|{handle.sequence}|Invalid P value"
            )
        assert blocker.args == ["Invalid P value"]
        assert handle.result == "ERR"

    def test_ok_with_seq_sets_event(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        handle = arduino.send_tracked("T", priority=True)
        arduino.ok_event.clear()
        arduino.handle_com(f"OK|{handle.sequence}")
        assert arduino.ok_event.is_set()
        assert handle.result == "OK"

    def test_stale_done_does_not_release_pending_command(self, arduino, qtbot):
        arduino._running = True
        arduino.protocol_v2 = True
        handle = arduino.send_tracked("K1300")
        with qtbot.assertNotEmitted(arduino.done_emit, wait=100):
            arduino.handle_com(f"DONE|{handle.sequence + 999}")
        assert not handle.completed.is_set()
        assert handle.sequence in arduino._pending_v2

    def test_status_with_valid_checksum_accepted(self, arduino, qtbot):
        frame = "STATUS_START|S|1500|2000|1200|45.3|STATUS_END"
        line = f"{frame}*{xor_checksum(frame):02X}"
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com(line)
        assert blocker.args == [1500, 2000, 1200, 45.3]

    def test_status_with_bad_checksum_rejected(self, arduino, qtbot):
        """A corrupted in-flight value must never reach the safety checks."""
        frame = "STATUS_START|S|1500|2000|1200|45.3|STATUS_END"
        checksum = xor_checksum(frame)
        corrupted = frame.replace("|45.3|", "|85.3|")  # flipped digit
        line = f"{corrupted}*{checksum:02X}"
        with qtbot.assertNotEmitted(arduino.status_emit, wait=100):
            arduino.handle_com(line)
        assert arduino.checksum_failures == 1

    def test_v2_rejects_unchecksummed_status(self, arduino, qtbot):
        arduino.protocol_v2 = True
        with qtbot.assertNotEmitted(arduino.status_emit, wait=100):
            arduino.handle_com(
                "STATUS_START|S|1500|2000|1200|45.3|STATUS_END"
            )


@pytest.mark.unit
class TestPressureResponse:
    """Tests for pressure response parsing."""

    def test_pressure_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.pressure_emit, timeout=1000) as blocker:
            arduino.handle_com("PR|45.5")
        assert blocker.args == ["45.5"]


@pytest.mark.unit
class TestWeightResponse:
    """Tests for weight response parsing."""

    def test_weight_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.display_weight_emit, timeout=1000) as blocker:
            arduino.handle_com("weight|32.1")
        assert blocker.args == ["32.1"]


@pytest.mark.unit
class TestReadyToGo:
    """Tests for ready-to-go response parsing."""

    def test_ready_to_go(self, arduino, qtbot):
        arduino.ready_event.clear()
        with qtbot.waitSignal(arduino.ready_to_go_emit, timeout=1000):
            arduino.handle_com("Ready to Go")
        assert arduino.ready_event.is_set()


@pytest.mark.unit
class TestGarbageInput:
    """Tests for malformed/garbage input."""

    def test_empty_string(self, arduino):
        arduino.handle_com("")
        # Should not crash

    def test_random_garbage(self, arduino):
        arduino.handle_com("xyzabc123!@#")
        # Should not crash

    def test_partial_status_delimiter(self, arduino):
        arduino.handle_com("STATUS_START|")
        # Should not crash
