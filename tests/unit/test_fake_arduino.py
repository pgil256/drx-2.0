# tests/unit/test_fake_arduino.py
import pytest
import os
import time
import serial

from fixtures.fake_arduino import FakeArduino, PTY_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PTY_AVAILABLE,
    reason="FakeArduino requires POSIX pty/termios support",
)


def send_cmd(fake, cmd_bytes):
    """Send a command to the FakeArduino via the slave (serial port) side."""
    # Open slave fd as a file for writing to avoid pty echo issues
    os.write(fake._slave_fd, cmd_bytes)


@pytest.mark.unit
class TestFakeArduinoBasic:
    """Smoke tests for FakeArduino simulator."""

    def test_creates_pty(self):
        fake = FakeArduino()
        fake.start()
        try:
            assert fake.port is not None
            assert os.path.exists(fake.port)
        finally:
            fake.stop()

    def test_responds_to_test_command(self):
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"T\n")
            assert fake.wait_for_command("T", timeout=2.0)
        finally:
            fake.stop()

    def test_tracks_commands(self):
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"P50\n")
            assert fake.wait_for_command("P", timeout=2.0)
            assert fake.get_last_command("P") == "P50"
        finally:
            fake.stop()

    def test_pressure_ramp(self):
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"P50\n")
            # Wait for command to be received and processed
            assert fake.wait_for_command("P", timeout=2.0)
            # Give time for pressure to ramp
            time.sleep(0.5)
            # Pressure should be moving toward 50
            assert fake.pressure > 0
        finally:
            fake.stop()

    def test_emergency_stop(self):
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"P50\n")
            assert fake.wait_for_command("P", timeout=2.0)
            send_cmd(fake, b"X\n")
            assert fake.wait_for_command("X", timeout=2.0)
            time.sleep(0.1)
            assert fake.measure_pressure is False
            assert fake.b_running is False
            assert fake.jerking is False
        finally:
            fake.stop()

    def test_position_movement(self):
        fake = FakeArduino()
        fake.position_c = 1200
        fake.start()
        try:
            send_cmd(fake, b"K1800\n")
            time.sleep(0.5)
            # Position should be moving toward 1800
            assert fake.position_c > 1200
        finally:
            fake.stop()
