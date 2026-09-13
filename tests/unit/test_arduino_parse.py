# tests/unit/test_arduino_parse.py
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from controllers.safety_monitor import SafetyMonitor
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
class TestTelemetryIntegrity:
    """Corrupt UART reports must not become measured positions or limit alerts."""

    @pytest.mark.parametrize("protocol_v2", [False, True])
    def test_reported_lateral_digit_flip_and_real_excursion(self, arduino, protocol_v2):
        arduino.protocol_v2 = protocol_v2
        window = SimpleNamespace(
            initial_setup_complete=True,
            config=None,
            treatment_panel=MagicMock(),
            logger=MagicMock(),
            _show_safety_alert=MagicMock(),
        )
        monitor = SafetyMonitor(window)
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.status_emit.connect(monitor.on_status)
        frame = "STATUS_START|S|636|1358|1940|27.41|STATUS_END"
        wire = f"{frame}*{xor_checksum(frame):02X}"

        arduino.handle_com(wire)
        # September 10 log: firmware logged 1940; Pi saw 3940 seven ms later.
        arduino.handle_com(wire.replace("|1940|", "|3940|"))
        arduino.handle_com(wire)

        assert received == [(636, 1358, 1940, 27.41)] * 2
        assert arduino.checksum_failures == 1
        window._show_safety_alert.assert_not_called()
        assert arduino.serial_com.write.call_count == 2

        # An actual out-of-range measurement with a valid checksum must warn.
        excursion = frame.replace("|1940|", "|3940|")
        arduino.handle_com(f"{excursion}*{xor_checksum(excursion):02X}")
        assert received[-1][2] == 3940
        window._show_safety_alert.assert_called_once()
        assert "Lateral position limit exceeded (3940" in (
            window._show_safety_alert.call_args.args[0]
        )

    @pytest.mark.parametrize("report", [
        "STATUS_START|S|636|1358|3940|27.41|STATUS_END",
        "S|636|1358|3940|27.41",
        "A|636|1358|3940|27.41",
    ])
    @pytest.mark.parametrize("protocol_v2", [False, True])
    def test_protected_link_rejects_missing_checksum(self, arduino, report, protocol_v2):
        arduino.protocol_v2 = protocol_v2
        if not protocol_v2:
            frame = "STATUS_START|S|636|1358|1940|27.41|STATUS_END"
            arduino.handle_com(f"{frame}*{xor_checksum(frame):02X}")
            # A boot/reset banner must not silently remove checksum protection.
            arduino.handle_com("Ready to Go")
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.serial_com.reset_mock()

        arduino.handle_com(report)

        assert received == []
        arduino.serial_com.write.assert_not_called()

    @pytest.mark.parametrize("suffix", ["*", "*0", "*GG", "*+0", "*000", "junk"])
    def test_malformed_checksum_rejected(self, arduino, suffix):
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.handle_com("STATUS_START|S|636|1358|1940|27.41|STATUS_END" + suffix)
        assert received == []
        arduino.serial_com.write.assert_not_called()

    def test_valid_checksum_followed_by_garbage_rejected(self, arduino):
        frame = "STATUS_START|S|636|1358|1940|27.41|STATUS_END"
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.handle_com(f"{frame}*{xor_checksum(frame):02X}garbage")
        assert received == []

    @pytest.mark.parametrize("frame", [
        "STATUS_START|S|636|1358|1940|27.41|extra|STATUS_END",
        "STATUS_START|S|636|1358|1940|27.41|STATUS_END|STATUS_END",
        "STATUS_START|A|636|1358|1940|27.41|STATUS_END",
        "STATUS_START|S|636|1358|1_940|27.41|STATUS_END",
        "STATUS_START|S|636|1358|1940|NaN|STATUS_END",
        "STATUS_START|S|636|1358|1940|inf|STATUS_END",
        "STATUS_START|S|636|1358|1940|1e309|STATUS_END",
        "S|636|1358|1940|27.41|extra",
        "A|636|1358|1940|27.41|extra",
    ])
    def test_malformed_payload_rejected_even_with_checksum(self, arduino, frame):
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.handle_com(f"{frame}*{xor_checksum(frame):02X}")
        assert received == []
        arduino.serial_com.write.assert_not_called()

    def test_log_quoting_status_is_only_a_diagnostic(self, arduino):
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.handle_com("LOG|STATUS_START|S|636|1358|3940|27.41|STATUS_END")
        assert received == []
        arduino.serial_com.write.assert_not_called()

    def test_legacy_status_supported_before_checksum_detection(self, arduino):
        received = []
        arduino.status_emit.connect(lambda *values: received.append(values))
        arduino.handle_com("S|636|1358|1940|27.41")
        assert received == [(636, 1358, 1940, 27.41)]


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
    """Firmware notices must not be dropped as unrecognized data."""

    def test_error_line_emits_error_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com("ERROR: Pressure limit exceeded")
        assert blocker.args == ["Pressure limit exceeded"]

    def test_warning_line_emits_separate_advisory_signal(self, arduino, qtbot):
        errors = []
        arduino.error_emit.connect(errors.append)
        with qtbot.waitSignal(arduino.warning_emit, timeout=1000) as blocker:
            arduino.handle_com("WARNING: Motor stalled")
        assert blocker.args == ["Motor stalled"]
        assert errors == []

    def test_busy_emits_error_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.error_emit, timeout=1000) as blocker:
            arduino.handle_com("BUSY")
        assert blocker.args == ["BUSY"]

    def test_log_line_is_logged_verbatim_without_signals(self, arduino):
        fired = []
        for sig in (arduino.error_emit, arduino.warning_emit,
                    arduino.status_emit, arduino.done_emit):
            sig.connect(lambda *a: fired.append(a))
        with patch.object(arduino, "logger") as log:
            arduino.handle_com("LOG|Wire error on device 14, returned: 0")
        log.info.assert_called_once_with(
            "Firmware: %s", "Wire error on device 14, returned: 0"
        )
        assert fired == []

    def test_unrecognized_line_is_logged_at_info(self, arduino):
        with patch.object(arduino, "logger") as log:
            arduino.handle_com("something new from the device")
        log.info.assert_called_once_with(
            "Unrecognized data format: %s", "something new from the device"
        )

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
        assert [cmd for cmd, _ in arduino._priority_queue] == ["X"]
        assert not arduino._tx_queue

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
        assert [cmd for cmd, _ in arduino._tx_queue] == [_frame(1, "P50")]

    def test_framed_x_still_jumps_the_queue(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        arduino.send("K1500")
        arduino.send("X")
        assert [cmd for cmd, _ in arduino._priority_queue] == [_frame(2, "X")]
        assert not arduino._tx_queue

    def test_sequence_increments(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        arduino.send("T")
        arduino.send("T")
        assert [cmd for cmd, _ in arduino._tx_queue] == [_frame(1, "T"), _frame(2, "T")]


@pytest.mark.unit
class TestParseRejectionRetry:
    """A firmware parse rejection means the command never ran; the transport
    resends it once before surfacing an error (2026-09-10: one corrupted
    byte in I131340 faulted the whole reset sequence)."""

    def _errors(self, arduino):
        seen = []
        arduino.error_emit.connect(seen.append)
        return seen

    def test_v1_rejection_resends_matching_command_once(self, arduino):
        arduino._running = True
        errors = self._errors(arduino)
        handle = arduino.send_tracked("I131340")
        arduino._service_tx_queue()
        assert arduino.serial_com.write.call_count == 1

        arduino.handle_com("ERROR: Invalid I value")
        assert errors == []
        assert handle.retries == 1
        assert list(arduino._tx_queue) == [("I131340", handle)]
        assert arduino.link_retries == 1

        arduino._last_tx = 0
        arduino._service_tx_queue()
        assert arduino.serial_com.write.call_count == 2
        arduino.handle_com("ERROR: Invalid I value")
        assert errors == ["Invalid I value"]  # second time: real fault
        assert arduino._tx_queue == deque()

    def test_v1_rejection_for_unrelated_letter_is_not_retried(self, arduino):
        arduino._running = True
        errors = self._errors(arduino)
        arduino.send_tracked("I131340")
        arduino._service_tx_queue()
        arduino.handle_com("ERROR: Invalid K value")
        assert errors == ["Invalid K value"]
        assert arduino._tx_queue == deque()

    def test_non_parse_error_is_not_retried(self, arduino):
        arduino._running = True
        errors = self._errors(arduino)
        arduino.send_tracked("I131340")
        arduino._service_tx_queue()
        arduino.handle_com("ERROR: Position read failed")
        assert errors == ["Position read failed"]
        assert arduino._tx_queue == deque()

    def test_v1_rejection_skips_acks_and_probes(self, arduino):
        arduino._running = True
        errors = self._errors(arduino)
        handle = arduino.send_tracked("P50")
        arduino._service_tx_queue()
        arduino._last_tx = 0
        arduino.send_tracked("T", priority=True)
        arduino._service_tx_queue()
        arduino.handle_com("ERROR: Invalid P value")
        assert errors == []
        assert list(arduino._tx_queue) == [("P50", handle)]

    def test_v2_rejection_resends_under_new_sequence(self, arduino):
        arduino._running = True
        arduino.protocol_v2 = True
        errors = self._errors(arduino)
        handle = arduino.send_tracked("I131340")
        first_seq = handle.sequence
        arduino._service_tx_queue()

        arduino.handle_com(f"ERR|{first_seq}|Checksum mismatch")
        assert errors == []
        assert handle.retries == 1
        assert handle.sequence != first_seq
        assert first_seq not in arduino._pending_v2
        assert arduino._pending_v2[handle.sequence] is handle
        wire, queued_handle = arduino._tx_queue[0]
        assert queued_handle is handle
        assert wire.startswith(f"#{handle.sequence}:I131340*")

        arduino.handle_com(f"ERR|{handle.sequence}|Checksum mismatch")
        assert errors == ["Checksum mismatch"]
        assert handle.result == "ERR"
        assert handle.completed.is_set()


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
        # A parse rejection is resent once (see TestParseRejectionRetry);
        # the second rejection is the real command error
        arduino.handle_com(f"ERR|{handle.sequence}|Invalid P value")
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
