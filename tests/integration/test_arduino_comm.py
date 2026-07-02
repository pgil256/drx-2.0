# tests/integration/test_arduino_comm.py
import pytest
import time
import serial
from unittest.mock import patch

from helpers.arduino import Arduino
from fixtures.fake_arduino import FakeArduino, PTY_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PTY_AVAILABLE,
    reason="FakeArduino requires POSIX pty/termios support",
)


@pytest.fixture
def connected_pair():
    """Create FakeArduino + Arduino with an open serial connection."""
    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True

    import threading
    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    yield arduino, fake

    # Exception-safe teardown: stop + join the reader before touching the
    # port so it cannot react to the closing fd with reconnect attempts.
    try:
        arduino._running = False
        arduino.connected = False
        reader.join(timeout=2)
        if arduino.serial_com and getattr(arduino.serial_com, "is_open", False):
            try:
                arduino.serial_com.close()
            except Exception:
                pass
    finally:
        fake.stop()


@pytest.mark.integration
class TestArduinoConnection:
    """Tests for Arduino connection management."""

    def test_verify_connection_sends_T(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.verify_connection(tries=1, timeout_s=3.0)
        assert result is True
        assert fake.wait_for_command("T", timeout=2.0)


@pytest.mark.integration
class TestArduinoSend:
    """Tests for sending commands to Arduino."""

    def test_send_pressure_command(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("P50")
        assert result is True
        assert fake.wait_for_command("P50", timeout=2.0)

    def test_send_position_command(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("K1500")
        assert result is True
        assert fake.wait_for_command("K1500", timeout=2.0)

    def test_send_emergency_stop(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("X")
        assert result is True
        assert fake.wait_for_command("X", timeout=2.0)

    def test_send_when_disconnected(self):
        arduino = Arduino()
        arduino.connected = False
        arduino.serial_com = None
        # Should attempt reconnect and fail gracefully
        with patch.object(arduino, 'reconnect', return_value=False):
            result = arduino.send("T")
        assert result is False


@pytest.mark.integration
class TestArduinoStatusSignals:
    """Tests for status signal emission."""

    def test_status_emit_on_status_response(self, connected_pair, qtbot):
        arduino, fake = connected_pair
        # Send a command that triggers status
        arduino.send("HF1")

        # Wait for status_emit signal
        with qtbot.waitSignal(arduino.status_emit, timeout=3000) as blocker:
            pass  # HF1 triggers immediate status send from FakeArduino

        pos_a, pos_b, pos_c, pressure = blocker.args
        assert isinstance(pos_a, int)
        assert isinstance(pressure, float)


@pytest.mark.integration
class TestArduinoCorruptData:
    """Tests for handling corrupt serial data."""

    def test_corrupt_status_no_crash(self, connected_pair):
        arduino, fake = connected_pair
        fake.corrupt_status()
        arduino.send("S")
        time.sleep(0.5)
        # Should not crash - verify arduino is still functional
        result = arduino.verify_connection(tries=1, timeout_s=3.0)
        assert result is True
