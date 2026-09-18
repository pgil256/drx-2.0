# tests/unit/test_arduino_send.py
"""Unit tests for Arduino SEND + CONNECTION-VERIFY logic.

Complements tests/unit/test_arduino_parse.py (handle_com parsing + v2 framing)
and tests/integration/test_arduino_comm.py (pty round-trips). These tests use a
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
from unittest.mock import MagicMock, patch

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
        with patch.object(arduino, "reconnect") as mock_reconnect:
            arduino.send("Z")
        mock_reconnect.assert_not_called()

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
        with patch.object(arduino, "reconnect") as mock_reconnect:
            assert arduino.send("Z") is False
        mock_reconnect.assert_not_called()

    def test_send_returns_false_when_port_closed(self, arduino):
        arduino.serial_com.is_open = False
        with patch.object(arduino, "reconnect") as mock_reconnect:
            assert arduino.send("Z") is False
        mock_reconnect.assert_not_called()

    def test_send_returns_false_when_io_loop_stopped(self, arduino):
        arduino._running = False
        with patch.object(arduino, "reconnect") as mock_reconnect:
            assert arduino.send("X") is False
        mock_reconnect.assert_not_called()

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
        payloads = [call.args[0] for call in arduino.serial_com.write.call_args_list]
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
            call.args[0].decode().strip()
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
