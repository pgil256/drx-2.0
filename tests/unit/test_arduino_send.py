# tests/unit/test_arduino_send.py
"""Unit tests for Arduino SEND + CONNECTION logic.

Complements tests/unit/test_arduino_parse.py (handle_com parsing) and
tests/integration/test_arduino_comm.py (pty round-trips). These tests use a
MagicMock serial layer so they run (and PASS) on Windows without any pty.

Covers: send(), verify_connection(), monitor_buffer(), reset_dtr().
"""
import threading
import pytest
from unittest.mock import MagicMock, patch

from helpers.arduino import Arduino


@pytest.fixture
def arduino():
    """Create an Arduino instance with a mocked, "open & connected" serial."""
    a = Arduino()
    a.serial_com = MagicMock()
    a.serial_com.is_open = True
    a.connected = True
    return a


@pytest.fixture(autouse=True)
def no_sleep():
    """Neutralise blocking time.sleep calls inside arduino.py so tests are fast.

    send() sleeps 0.3s, verify_connection() sleeps 0.5s per failed try, and
    reset_dtr() sleeps up to ~5s. Patching keeps the suite snappy on Windows.
    """
    with patch("helpers.arduino.time.sleep", return_value=None):
        yield


@pytest.mark.unit
class TestSendConnected:
    """send() behaviour when the serial link is open and connected."""

    def test_send_writes_command_with_newline(self, arduino):
        assert arduino.send("Z") is True
        arduino.serial_com.write.assert_called_once_with(b"Z\n")

    def test_send_flushes_after_write(self, arduino):
        arduino.send("Z")
        arduino.serial_com.flush.assert_called_once()

    def test_send_strips_whitespace_before_framing(self, arduino):
        """Leading/trailing whitespace is stripped, then one newline is added."""
        assert arduino.send("  GO  ") is True
        arduino.serial_com.write.assert_called_once_with(b"GO\n")

    def test_send_accepts_non_string_command(self, arduino):
        """send() coerces its argument via str() before framing."""
        assert arduino.send(42) is True
        arduino.serial_com.write.assert_called_once_with(b"42\n")

    def test_send_does_not_reconnect_when_connected(self, arduino):
        with patch.object(arduino, "reconnect") as mock_reconnect:
            arduino.send("Z")
        mock_reconnect.assert_not_called()


@pytest.mark.unit
class TestSendEmptyCommand:
    """send() refuses empty/whitespace-only commands."""

    def test_send_empty_string_returns_false(self, arduino):
        assert arduino.send("") is False
        arduino.serial_com.write.assert_not_called()

    def test_send_whitespace_only_returns_false(self, arduino):
        assert arduino.send("   ") is False
        arduino.serial_com.write.assert_not_called()


@pytest.mark.unit
class TestSendNotConnected:
    """send() reconnection behaviour when the link is down."""

    def test_send_reconnects_when_not_connected(self, arduino):
        """A disconnected Arduino should attempt reconnect(max_retries=3)."""
        arduino.connected = False
        with patch.object(arduino, "reconnect", return_value=False) as mock_reconnect:
            result = arduino.send("Z")
        assert result is False
        mock_reconnect.assert_called_once_with(max_retries=3)

    def test_send_returns_false_when_reconnect_fails(self, arduino):
        arduino.connected = False
        with patch.object(arduino, "reconnect", return_value=False):
            assert arduino.send("Z") is False

    def test_send_reconnects_when_serial_none(self, arduino):
        arduino.serial_com = None
        with patch.object(arduino, "reconnect", return_value=False) as mock_reconnect:
            assert arduino.send("Z") is False
        mock_reconnect.assert_called_once_with(max_retries=3)

    def test_send_reconnects_when_port_closed(self, arduino):
        """is_open False should trigger reconnect even if connected flag is True."""
        arduino.serial_com.is_open = False
        with patch.object(arduino, "reconnect", return_value=False) as mock_reconnect:
            assert arduino.send("Z") is False
        mock_reconnect.assert_called_once_with(max_retries=3)

    def test_send_proceeds_after_successful_reconnect(self, arduino):
        """If reconnect succeeds and the port is open, the write goes through."""
        arduino.connected = False
        # reconnect() in production re-opens serial_com; emulate that side effect.
        new_serial = MagicMock()
        new_serial.is_open = True

        def fake_reconnect(max_retries=3):
            arduino.serial_com = new_serial
            arduino.connected = True
            return True

        with patch.object(arduino, "reconnect", side_effect=fake_reconnect):
            assert arduino.send("Z") is True
        new_serial.write.assert_called_once_with(b"Z\n")


@pytest.mark.unit
class TestSendWriteFailure:
    """send() error handling when the underlying write raises."""

    def test_send_returns_false_on_write_exception(self, arduino):
        arduino.serial_com.write.side_effect = OSError("port gone")
        assert arduino.send("Z") is False

    def test_send_marks_disconnected_on_write_exception(self, arduino):
        arduino.serial_com.write.side_effect = OSError("port gone")
        arduino.send("Z")
        assert arduino.connected is False

    def test_send_emits_connection_lost_on_write_exception(self, arduino, qtbot):
        arduino.serial_com.write.side_effect = OSError("port gone")
        with qtbot.waitSignal(arduino.connection_lost, timeout=1000):
            arduino.send("Z")


@pytest.mark.unit
class TestVerifyConnection:
    """verify_connection() handshake: writes 'T', waits for an OK event."""

    def test_verify_returns_true_when_ok_received(self, arduino):
        """If the reader path sets ok_event after 'T' is sent, wait -> True.

        verify_connection() clears ok_event at the start of each try, so the
        event must be set *during* the call (mirroring handle_com firing on a
        real 'OK' reply). We set it as a side effect of the serial write.
        """
        arduino.serial_com.write.side_effect = lambda *_a, **_k: arduino.ok_event.set()
        assert arduino.verify_connection(tries=1, timeout_s=1.0) is True

    def test_verify_writes_test_byte(self, arduino):
        arduino.serial_com.write.side_effect = lambda *_a, **_k: arduino.ok_event.set()
        arduino.verify_connection(tries=1, timeout_s=1.0)
        arduino.serial_com.write.assert_called_with(b"T\n")

    def test_verify_flushes_input_buffer_before_write(self, arduino):
        arduino.serial_com.write.side_effect = lambda *_a, **_k: arduino.ok_event.set()
        arduino.verify_connection(tries=1, timeout_s=1.0)
        arduino.serial_com.reset_input_buffer.assert_called()
        arduino.serial_com.flush.assert_called()

    def test_verify_ok_arriving_during_wait_returns_true(self, arduino):
        """Simulate handle_com setting ok_event shortly after 'T' is sent."""
        def set_event_soon(*_args, **_kwargs):
            threading.Timer(0.05, arduino.ok_event.set).start()

        arduino.serial_com.write.side_effect = set_event_soon
        assert arduino.verify_connection(tries=1, timeout_s=2.0) is True

    def test_verify_returns_false_on_timeout(self, arduino):
        """No OK ever arrives -> all tries time out -> False."""
        arduino.ok_event.clear()
        assert arduino.verify_connection(tries=2, timeout_s=0.01) is False

    def test_verify_retries_until_tries_exhausted(self, arduino):
        """With no OK, 'T' is written once per try."""
        arduino.ok_event.clear()
        arduino.verify_connection(tries=3, timeout_s=0.01)
        assert arduino.serial_com.write.call_count == 3

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


@pytest.mark.unit
class TestMonitorBuffer:
    """monitor_buffer() warning + emergency-flush thresholds."""

    def test_no_warning_below_threshold(self, arduino, qtbot):
        arduino.serial_com.in_waiting = 0
        arduino.serial_com.out_waiting = 0
        # No signal expected: assert the spy never receives one.
        with qtbot.assertNotEmitted(arduino.buffer_warning):
            arduino.monitor_buffer()

    def test_output_buffer_warning_above_threshold(self, arduino, qtbot):
        """out_buffer_usage > 0.8 (of 64 bytes) emits buffer_warning."""
        arduino.serial_com.in_waiting = 0
        arduino.serial_com.out_waiting = 60  # 60/64 = 0.9375 > 0.8
        with qtbot.waitSignal(arduino.buffer_warning, timeout=1000) as blocker:
            arduino.monitor_buffer()
        assert "Output buffer" in blocker.args[0]

    def test_output_buffer_at_exact_threshold_no_warning(self, arduino, qtbot):
        """Exactly at 0.8 should NOT warn (strict > comparison)."""
        arduino.serial_com.in_waiting = 0
        arduino.serial_com.out_waiting = int(0.8 * arduino.ARDUINO_BUFFER_SIZE)  # 51 -> 0.797
        with qtbot.assertNotEmitted(arduino.buffer_warning):
            arduino.monitor_buffer()

    def test_emergency_flush_when_input_critical(self, arduino):
        """in_buffer_usage > 0.9 triggers reset_input_buffer()."""
        arduino.serial_com.in_waiting = 60  # 60/64 = 0.9375 > 0.9
        arduino.serial_com.out_waiting = 0
        arduino.monitor_buffer()
        arduino.serial_com.reset_input_buffer.assert_called_once()

    def test_no_emergency_flush_when_input_ok(self, arduino):
        arduino.serial_com.in_waiting = 0
        arduino.serial_com.out_waiting = 0
        arduino.monitor_buffer()
        arduino.serial_com.reset_input_buffer.assert_not_called()

    def test_high_input_skips_output_check(self, arduino, qtbot):
        """When input usage exceeds threshold, the output branch is skipped."""
        arduino.serial_com.in_waiting = 60  # > 0.8 -> output check skipped
        arduino.serial_com.out_waiting = 64  # would warn if it were checked
        with qtbot.assertNotEmitted(arduino.buffer_warning):
            arduino.monitor_buffer()

    def test_no_serial_returns_without_error(self, arduino):
        arduino.serial_com = None
        arduino.monitor_buffer()  # must not raise

    def test_exception_emits_connection_failed(self, arduino, qtbot):
        """A serial error during monitoring surfaces as connection_failed."""
        type(arduino.serial_com).in_waiting = property(
            lambda self: (_ for _ in ()).throw(OSError("device read error"))
        )
        try:
            with qtbot.waitSignal(arduino.connection_failed, timeout=1000):
                arduino.monitor_buffer()
        finally:
            # Remove the property so it doesn't leak into other MagicMock instances.
            del type(arduino.serial_com).in_waiting


@pytest.mark.unit
class TestResetDtr:
    """reset_dtr() DTR toggling on a mocked serial."""

    def test_reset_dtr_returns_true_on_success(self, arduino):
        arduino.serial_com.dtr = True
        assert arduino.reset_dtr() is True

    def test_reset_dtr_toggles_dtr_line(self, arduino):
        """DTR is driven low then high during the reset sequence."""
        arduino.serial_com.dtr = True
        recorded = []
        # Capture every assignment to .dtr in order.
        type(arduino.serial_com).dtr = property(
            lambda self: getattr(self, "_dtr_val", True),
            lambda self, v: (recorded.append(v), setattr(self, "_dtr_val", v))[1],
        )
        try:
            assert arduino.reset_dtr() is True
        finally:
            del type(arduino.serial_com).dtr
        assert False in recorded  # pulled low
        assert True in recorded   # raised high again

    def test_reset_dtr_returns_false_when_no_serial(self, arduino):
        arduino.serial_com = None
        assert arduino.reset_dtr() is False

    def test_reset_dtr_returns_false_on_exception(self, arduino):
        """An error while toggling DTR is caught and reported as False."""
        type(arduino.serial_com).dtr = property(
            fget=lambda self: True,
            fset=lambda self, v: (_ for _ in ()).throw(OSError("dtr fail")),
        )
        try:
            assert arduino.reset_dtr() is False
        finally:
            del type(arduino.serial_com).dtr
