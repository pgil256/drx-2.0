# development/tests/unit/test_arduino_send.py
"""Unit tests for Arduino SEND + CONNECTION-VERIFY logic.

Complements development/tests/unit/test_arduino_parse.py (handle_com parsing + v2 framing)
and development/tests/integration/test_arduino_comm.py (pty round-trips). These tests use a
MagicMock serial layer so they run (and PASS) on Windows without any pty.

Adapted from the GUI line's send tests to the FAILSAFE transport contract:
send() QUEUES for the I/O thread and never writes, blocks, or reconnects
inline (a multi-second reconnect inside send() used to freeze the UI exactly
when the device was misbehaving). The old monitor_buffer()/reset_dtr() tests
were retired with those methods.
"""
import threading
import time
import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from helpers.arduino import Arduino


@pytest.fixture
def arduino():
    """An Arduino instance with a mocked, "open & connected" serial and a
    live-looking I/O loop flag (no real thread is started)."""
    a = Arduino()
    a.serial_com = MagicMock()
    a.serial_com.is_open = True
    a.connected = True
    a._running = True
    return a


@pytest.mark.unit
class TestSendQueuesCommand:
    """send() behaviour when the serial link is open and the loop is live."""

    def test_send_returns_true_and_queues(self, arduino):
        assert arduino.send("Z") is True
        assert [cmd for cmd, _ in arduino._tx_queue] == ["Z"]

    def test_send_strips_whitespace_before_queueing(self, arduino):
        assert arduino.send("  GO  ") is True
        assert [cmd for cmd, _ in arduino._tx_queue] == ["GO"]

    def test_send_accepts_non_string_command(self, arduino):
        """send() coerces its argument via str() before queueing."""
        assert arduino.send(42) is True
        assert [cmd for cmd, _ in arduino._tx_queue] == ["42"]

    def test_send_never_writes_inline(self, arduino):
        """Writing belongs to the I/O thread; send() must not touch the port."""
        arduino.send("Z")
        arduino.serial_com.write.assert_not_called()

    def test_send_does_not_reconnect_when_connected(self, arduino):
        with patch.object(arduino, "connect_to_arduino") as mock_connect:
            arduino.send("Z")
        mock_connect.assert_not_called()

    def test_emergency_stop_uses_priority_queue(self, arduino):
        """'X' must jump ahead of queued commands, not wait in line."""
        arduino.send("P40")
        arduino.send("X")
        assert [cmd for cmd, _ in arduino._priority_queue] == ["X"]
        assert not arduino._tx_queue


@pytest.mark.unit
class TestSendEmptyCommand:
    """send() refuses empty/whitespace-only commands."""

    def test_send_empty_string_returns_false(self, arduino):
        assert arduino.send("") is False
        assert not arduino._tx_queue and not arduino._priority_queue

    def test_send_whitespace_only_returns_false(self, arduino):
        assert arduino.send("   ") is False
        assert not arduino._tx_queue and not arduino._priority_queue


@pytest.mark.unit
class TestSendNoUsableLink:
    """send() fails FAST on a dead link and never attempts a reconnect —
    the caller (e.g. stop_actuators) owns the operator alarm."""

    def test_send_returns_false_when_serial_none(self, arduino):
        arduino.serial_com = None
        with patch.object(arduino, "connect_to_arduino") as mock_connect:
            assert arduino.send("Z") is False
        mock_connect.assert_not_called()

    def test_send_returns_false_when_port_closed(self, arduino):
        arduino.serial_com.is_open = False
        with patch.object(arduino, "connect_to_arduino") as mock_connect:
            assert arduino.send("Z") is False
        mock_connect.assert_not_called()

    def test_send_returns_false_when_io_loop_stopped(self, arduino):
        arduino._running = False
        with patch.object(arduino, "connect_to_arduino") as mock_connect:
            assert arduino.send("X") is False
        mock_connect.assert_not_called()

    def test_nothing_queued_on_dead_link(self, arduino):
        arduino.serial_com = None
        arduino.send("Z")
        assert not arduino._tx_queue and not arduino._priority_queue


@pytest.mark.unit
class TestVerifyConnection:
    """verify_connection(): queues 'T' probes and waits for the OK event."""

    def test_verify_returns_true_when_ok_received(self, arduino):
        """The reader path sets ok_event when a real 'OK' reply arrives;
        simulate it landing shortly after the probe is queued."""
        threading.Timer(0.05, arduino.ok_event.set).start()
        assert arduino.verify_connection(tries=1, timeout_s=2.0) is True

    def test_verify_queues_test_probe_with_priority(self, arduino):
        arduino.ok_event.set()
        arduino.verify_connection(tries=1, timeout_s=0.5)
        assert "T" in [cmd for cmd, _ in arduino._priority_queue]

    def test_verify_returns_false_on_timeout(self, arduino):
        """No OK ever arrives -> all tries time out -> False."""
        arduino.ok_event.clear()
        assert arduino.verify_connection(tries=2, timeout_s=0.01) is False

    def test_verify_retries_until_tries_exhausted(self, arduino):
        """With no OK, one 'T' probe is queued per try."""
        arduino.ok_event.clear()
        arduino.verify_connection(tries=3, timeout_s=0.01)
        assert [cmd for cmd, _ in arduino._priority_queue] == ["T", "T", "T"]

    def test_verify_returns_false_when_serial_none(self, arduino):
        arduino.serial_com = None
        assert arduino.verify_connection(tries=1, timeout_s=0.01) is False

    def test_verify_returns_false_when_port_closed(self, arduino):
        arduino.serial_com.is_open = False
        assert arduino.verify_connection(tries=1, timeout_s=0.01) is False

    def test_verify_clears_ready_event_when_not_open(self, arduino):
        arduino.serial_com.is_open = False
        arduino.connection_ready_event.set()
        arduino.verify_connection(tries=1, timeout_s=0.01)
        assert not arduino.connection_ready_event.is_set()


class TestDrainBeforeDisconnect:
    def test_safety_queue_is_written_before_drain_completes(self, arduino):
        arduino.send("P40")
        arduino.send("X")

        arduino._service_tx_queue()

        assert arduino.wait_for_drain(0.1) is True
        payloads = [call[0][0] for call in arduino.serial_com.write.call_args_list]
        assert payloads == [b"X\n"]

    def test_disconnect_reports_drain_timeout_then_clears_queue(self, arduino):
        arduino.send("X")

        assert arduino.disconnect(drain_timeout=0.01) is False
        assert not arduino._priority_queue


@pytest.mark.unit
class TestTrackedQueueSafety:
    @pytest.mark.parametrize("protocol_v2", [False, True])
    def test_stop_discards_old_motion_but_allows_pressure_release(self, arduino, protocol_v2):
        arduino.protocol_v2 = protocol_v2
        old_move = arduino.send_tracked("P40")
        old_priority = arduino.send_tracked("K1500", priority=True)
        stop = arduino.send_tracked("X")
        release = arduino.send_tracked("P0")

        arduino._service_tx_queue()

        payloads = [
            call[0][0].decode().strip()
            for call in arduino.serial_com.write.call_args_list
        ]
        if protocol_v2:
            payloads = [payload.split(":", 1)[1].split("*")[0] for payload in payloads]
        assert payloads == ["X", "P0"]
        for handle in (old_move, old_priority):
            assert handle.completed.is_set()
            assert handle.result == "CANCELLED"
            assert not handle.written.is_set()
            assert handle.sequence not in arduino._pending_v2
        assert stop.written.is_set()
        assert release.written.is_set()

    def test_identical_commands_track_their_own_writes(self, arduino):
        first = arduino.send_tracked("P0")
        second = arduino.send_tracked("P0")

        arduino._service_tx_queue()
        assert first.written.is_set()
        assert not second.written.is_set()

        arduino._last_tx = 0
        arduino._service_tx_queue()
        assert second.written.is_set()

    def test_priority_duplicate_does_not_mark_normal_command_written(self, arduino):
        normal = arduino.send_tracked("T")
        priority = arduino.send_tracked("T", priority=True)
        # Keep the normal queue paced while sending the priority probe.
        arduino._last_tx = time.time()

        arduino._service_tx_queue()

        assert priority.written.is_set()
        assert not normal.written.is_set()

    @pytest.mark.parametrize("protocol_v2", [False, True])
    def test_disconnect_does_not_claim_unsent_command_was_written(self, arduino, protocol_v2):
        arduino.protocol_v2 = protocol_v2
        handle = arduino.send_tracked("X")

        arduino.disconnect()

        assert not handle.written.is_set()
        assert handle.completed.is_set()
        assert handle.result == "DISCONNECTED"

    @pytest.mark.parametrize("protocol_v2", [False, True])
    def test_failed_write_resolves_handle_without_claiming_delivery(self, arduino, protocol_v2):
        from serial import SerialException

        arduino.protocol_v2 = protocol_v2
        handle = arduino.send_tracked("X")
        arduino.serial_com.write.side_effect = SerialException("link failed")

        with pytest.raises(SerialException):
            arduino._service_tx_queue()

        assert not handle.written.is_set()
        assert handle.completed.is_set()
        assert handle.result == "DISCONNECTED"
        assert handle.sequence not in arduino._pending_v2
        assert arduino._write_in_progress == 0

    def test_unsolicited_write_does_not_complete_queued_handle(self, arduino):
        handle = arduino.send_tracked("T")

        # The silence watchdog writes its own probe without using the queue.
        arduino._write_now("T")

        assert not handle.written.is_set()
        arduino._service_tx_queue()
        assert handle.written.is_set()


class ScriptedPort:
    """A port that serves scripted chunks without blocking.

    Each poll of ``in_waiting`` takes the next script item when nothing is
    pending: bytes arrive, a number idles that many seconds, a callable runs.
    The loop stops once the script is used up. ``events`` records polls and
    writes in order.
    """

    def __init__(self, arduino, script):
        self.arduino = arduino
        self.script = list(script)
        self.pending = b""
        self.events = []
        self.is_open = True

    @property
    def in_waiting(self):
        self.events.append("poll")
        if not self.pending:
            if not self.script:
                self.arduino._running = False
                return 0
            item = self.script.pop(0)
            if callable(item):
                item()
                return 0
            if isinstance(item, (int, float)):
                time.sleep(item)
                return 0
            self.pending = item
        return len(self.pending)

    def read(self, size):
        data, self.pending = self.pending[:size], self.pending[size:]
        return data

    def readline(self):
        raise AssertionError("readline() blocks up to the read timeout")

    def write(self, payload):
        self.events.append(payload)
        return len(payload)

    def flush(self):
        pass

    def close(self):
        self.is_open = False


@pytest.mark.unit
class TestIoLoopReads:
    """V9: reads never block, so a partial line cannot hold up a stop."""

    @pytest.fixture
    def handled(self, arduino, monkeypatch):
        lines = []
        monkeypatch.setattr(arduino, "handle_com", lines.append)
        return lines

    def run(self, arduino, script):
        port = ScriptedPort(arduino, script)
        arduino.serial_com = port
        arduino.read_from_com()
        return port

    @pytest.mark.timeout(10)
    def test_a_stop_queued_behind_half_a_line_is_written_on_the_next_pass(
        self, arduino, handled
    ):
        port = self.run(arduino, [b"S|1|2", lambda: arduino.send("X"), 0.0])
        polls = [index for index, event in enumerate(port.events) if event == "poll"]
        queued = polls[1]  # the second poll ran the script item that queued the X
        assert port.events[queued + 1] == b"X\n"  # written before the next poll
        assert handled == []  # the half line is still waiting for its end

    @pytest.mark.timeout(10)
    def test_a_line_split_across_reads_is_handled_once_whole(self, arduino, handled):
        self.run(arduino, [b"S|1|2", b"|3|4\nOK\r\n", b"OK"])
        assert handled == ["S|1|2|3|4", "OK"]

    @pytest.mark.timeout(10)
    def test_a_line_that_never_ends_is_handed_on_by_itself(
        self, arduino, handled, monkeypatch
    ):
        """As readline() did at its timeout: the next line starts clean."""
        monkeypatch.setattr(arduino, "PARTIAL_LINE_TIMEOUT_S", 0.05)
        self.run(arduino, [b"Rea", 0.1, 0.0, b"Ready to Go\n"])
        assert handled == ["Rea", "Ready to Go"]

    @pytest.mark.timeout(10)
    def test_an_overlong_line_with_no_ending_is_discarded(
        self, arduino, handled, monkeypatch
    ):
        monkeypatch.setattr(arduino, "MAX_PARTIAL_LINE", 16)
        self.run(arduino, [b"x" * 40, b"OK\n"])
        assert handled == ["OK"]


@pytest.mark.unit
class TestIoLoopLinkLoss:
    """read_from_com() must report a dead port instead of spinning on it.

    Each test runs the loop on the calling thread; the loop ends when it
    declares the link lost. The timeout turns the old endless loop into a
    failure instead of a hang.
    """

    @pytest.fixture
    def lost(self, arduino):
        events = []
        arduino.connection_lost.connect(lambda: events.append("lost"))
        return events

    @pytest.mark.timeout(10)
    def test_raw_oserror_from_vanished_device_declares_link_lost(self, arduino, lost):
        # pyserial's in_waiting is a bare fcntl.ioctl: an unplugged
        # USB-serial adapter raises OSError(EIO), not SerialException.
        type(arduino.serial_com).in_waiting = PropertyMock(
            side_effect=OSError(5, "Input/output error")
        )

        arduino.read_from_com()

        assert lost == ["lost"]
        assert arduino.connected is False
        assert arduino._running is False

    @pytest.mark.timeout(10)
    def test_persistent_unexpected_error_still_trips_silence_watchdog(
        self, arduino, lost, monkeypatch
    ):
        monkeypatch.setattr(arduino, "RX_SILENCE_LIMIT_S", 0.05)
        monkeypatch.setattr(arduino, "PROBE_TIMEOUT_S", 0.05)
        monkeypatch.setattr(
            arduino, "_service_tx_queue", MagicMock(side_effect=RuntimeError("bug"))
        )

        arduino.read_from_com()

        arduino.serial_com.write.assert_any_call(b"T\n")
        assert lost == ["lost"]

    @pytest.mark.timeout(10)
    def test_failed_probe_write_declares_link_lost(self, arduino, lost, monkeypatch):
        monkeypatch.setattr(arduino, "RX_SILENCE_LIMIT_S", 0.0)
        arduino.serial_com.in_waiting = 0
        arduino.serial_com.write.side_effect = OSError(5, "Input/output error")

        arduino.read_from_com()

        assert lost == ["lost"]

    @pytest.mark.timeout(10)
    def test_line_handling_error_is_not_a_link_loss(self, arduino, lost, monkeypatch):
        arduino.serial_com.in_waiting = 10
        arduino.serial_com.read.return_value = b"S|1|2|3|4\n"

        def boom(data):
            arduino._running = False
            raise ValueError("parser bug")

        monkeypatch.setattr(arduino, "handle_com", boom)

        arduino.read_from_com()

        assert lost == []
        assert arduino.connected is True
