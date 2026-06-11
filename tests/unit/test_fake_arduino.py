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


def wait_until(predicate, timeout=2.0, interval=0.02):
    """Poll until predicate() is truthy or timeout; returns the last value."""
    deadline = time.time() + timeout
    result = predicate()
    while not result and time.time() < deadline:
        time.sleep(interval)
        result = predicate()
    return result


def read_output(fake, duration=0.5):
    """Collect everything the fake wrote to the serial side for `duration`."""
    import select as _select
    import tty as _tty
    _tty.setraw(fake._slave_fd)
    data = b""
    deadline = time.time() + duration
    while time.time() < deadline:
        ready, _, _ = _select.select([fake._slave_fd], [], [], 0.05)
        if ready:
            try:
                data += os.read(fake._slave_fd, 4096)
            except OSError:
                break
    return data.decode(errors="replace")


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
            # X may wait out the command rate limiter before processing
            assert wait_until(lambda: not fake.measure_pressure)
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


@pytest.mark.unit
class TestFakeArduinoFirmwareParity:
    """Verify the fixture matches motor.ino's observable serial contract."""

    def test_done_emitted_after_position_move(self):
        fake = FakeArduino()
        fake.position_c = 1200
        fake.start()
        try:
            send_cmd(fake, b"K1300\n")
            output = read_output(fake, duration=0.6)
            assert "DONE" in output
            assert fake.position_c == 1300
            assert fake.b_running is False
        finally:
            fake.stop()

    def test_done_emitted_after_pressure_reached(self):
        fake = FakeArduino()
        fake.pressure_rate = 500.0  # reach target quickly
        fake.start()
        try:
            send_cmd(fake, b"P20\n")
            output = read_output(fake, duration=0.6)
            assert "DONE" in output
            assert fake.measure_pressure is False
            assert fake.pressure == 20.0
        finally:
            fake.stop()

    def test_y_resets_without_done(self):
        """'Y' replies Reset| then reboots into 'Ready to Go'; the firmware
        resets before it could ever print DONE."""
        fake = FakeArduino()
        fake.boot_delay = 0.05
        fake.start()
        try:
            send_cmd(fake, b"HF1\n")  # something to verify reboot clears
            assert wait_until(lambda: fake.high_frequency_status)
            send_cmd(fake, b"Y\n")
            output = read_output(fake, duration=0.8)
            reset_pos = output.find("Reset|")
            ready_pos = output.find("Ready to Go")
            assert reset_pos != -1 and ready_pos != -1 and reset_pos < ready_pos
            between = output[reset_pos:ready_pos]
            assert "DONE" not in between
            assert fake.high_frequency_status is False
        finally:
            fake.stop()

    def test_status_flows_while_jerking(self):
        """Pulsing used to suppress all telemetry (noStatus), blinding the
        pressure ceiling check; status must keep flowing during jerk now."""
        fake = FakeArduino()
        fake.hf_interval = 0.05
        fake.start()
        try:
            send_cmd(fake, b"HF1\n")
            assert wait_until(lambda: fake.high_frequency_status)
            send_cmd(fake, b"J\n")
            assert wait_until(lambda: fake.jerking)
            read_output(fake, duration=0.2)  # drain anything in flight
            send_cmd(fake, b"Q\n")  # ack so the next frame is allowed
            output = read_output(fake, duration=0.4)
            assert "STATUS_START" in output
        finally:
            fake.stop()

    def test_busy_reply_while_running(self):
        fake = FakeArduino()
        fake.movement_speed = 50.0  # slow, so the first move stays active
        fake.position_c = 1200
        fake.start()
        try:
            send_cmd(fake, b"K1800\n")
            assert wait_until(lambda: fake.b_running)
            send_cmd(fake, b"P40\n")
            output = read_output(fake, duration=0.6)
            assert "BUSY" in output
        finally:
            fake.stop()

    def test_l5_delimited_echoes_zeros(self):
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"L5|160|1900\n")
            output = read_output(fake, duration=0.4)
            assert "ZEROS|160|1900" in output
            assert "DONE" in output
        finally:
            fake.stop()

    def test_status_backpressure_until_q_ack(self):
        """After one status frame, further frames wait for a 'Q' ack
        (or the 2 s STATUS_TIMEOUT)."""
        fake = FakeArduino()
        fake.hf_interval = 0.05
        fake.start()
        try:
            send_cmd(fake, b"HF1\n")
            output = read_output(fake, duration=0.5)
            assert output.count("STATUS_START") == 1
            send_cmd(fake, b"Q\n")
            output = read_output(fake, duration=0.5)
            assert output.count("STATUS_START") == 1
        finally:
            fake.stop()

    def test_move_commands_dropped_while_running(self):
        fake = FakeArduino()
        fake.movement_speed = 50.0  # slow, so the first move stays active
        fake.position_c = 1200
        fake.start()
        try:
            send_cmd(fake, b"K1800\n")
            assert wait_until(lambda: fake.b_running)
            send_cmd(fake, b"K1300\n")
            assert fake.wait_for_command("K1300", timeout=2.0)
            time.sleep(0.3)  # let the rate limiter process it
            # Second command silently dropped: target still 1800
            assert fake._target_position_c == 1800
        finally:
            fake.stop()

    def test_pressure_limit_error(self):
        fake = FakeArduino()
        fake.pressure_rate = 5.0  # slow ramp so overshoot hits mid-ramp
        fake.start()
        try:
            send_cmd(fake, b"P50\n")
            assert wait_until(lambda: fake.measure_pressure)
            fake.simulate_pressure_overshoot(85.0)
            output = read_output(fake, duration=0.5)
            assert "ERROR: Pressure limit exceeded" in output
            assert fake.measure_pressure is False
        finally:
            fake.stop()

    def test_command_rate_limited(self):
        """Two back-to-back commands are processed >= min_command_interval
        apart, mirroring the firmware's MIN_COMMAND_INTERVAL."""
        fake = FakeArduino()
        fake.start()
        try:
            send_cmd(fake, b"T\nT\n")
            output = read_output(fake, duration=0.15)
            assert output.count("OK") == 1, f"got: {output!r}"
            output += read_output(fake, duration=0.3)
            assert output.count("OK") == 2
        finally:
            fake.stop()
