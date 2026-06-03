# tests/integration/test_protocols.py
import pytest
import time
import serial
import threading
from unittest.mock import patch

from helpers.arduino import Arduino
from helpers.protocols import Protocols
from config.config import Configuration
from fixtures.fake_arduino import FakeArduino, PTY_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PTY_AVAILABLE,
    reason="FakeArduino requires POSIX pty/termios support",
)


@pytest.fixture
def protocol_env():
    """Set up full protocol test environment with FakeArduino."""
    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True

    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.calibration = 1.0

    yield arduino, fake, config

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


def make_protocol(arduino, config, **kwargs):
    """Helper to build a Protocols instance with defaults."""
    defaults = dict(
        a_factor=1900,
        protocol="1",
        max_pressure=30,  # Low for fast tests
        max_left=5.0,
        max_right=5.0,
        duration=1,  # 1 minute (will be cut short by checking is_running)
        use_pulse=False,
        ser=arduino,
        config=config,
    )
    defaults.update(kwargs)
    return Protocols(**defaults)


def bypass_pressure_ramp(protocol, target_pressure):
    """Bypass the slow pressure ramp for tests that don't need it.

    Patches run_pressure_sequence and set_to_pressure to return immediately,
    and pre-sets current_pressure to the target value.
    """
    protocol.current_pressure = target_pressure
    protocol.run_pressure_sequence = lambda *args, **kwargs: True
    _original_set_to_pressure = protocol.set_to_pressure

    def fast_set_to_pressure(target):
        protocol.current_pressure = target
        if protocol.is_running or target == 0:
            protocol.arduino.send(f"P{target}")
        return True

    protocol.set_to_pressure = fast_set_to_pressure


@pytest.mark.integration
class TestProtocol1Axial:
    """Tests for Protocol 1 (axial pressure only)."""

    def test_sends_pressure_commands(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=30, duration=1)

        # Run protocol in a thread (it blocks)
        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for pressure commands to appear
        assert fake.wait_for_command("HF1", timeout=5.0)
        assert fake.wait_for_command("P", timeout=10.0)

        # Stop protocol
        p.is_running = False
        thread.join(timeout=15)

    def test_finished_signal_emitted(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        # Use short duration (0.1 min = 6s) so hold phase completes within timeout
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, duration=0.1)
        # Bypass pressure ramp so protocol completes quickly
        bypass_pressure_ramp(p, 20)

        with qtbot.waitSignal(p.signals.finished, timeout=30000):
            thread = threading.Thread(target=p.run, daemon=True)
            thread.start()

        thread.join(timeout=5)


@pytest.mark.integration
class TestProtocol2LeftLateral:
    """Tests for Protocol 2 (left lateral)."""

    def test_moves_c_actuator_left(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="2", max_left=10.0, max_pressure=20)
        # Bypass pressure ramp - we're testing lateral movement
        bypass_pressure_ramp(p, 20)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should send K command for left position
        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocol3RightLateral:
    """Tests for Protocol 3 (right lateral)."""

    def test_moves_c_actuator_right(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="3", max_right=10.0, max_pressure=20)
        # Bypass pressure ramp - we're testing lateral movement
        bypass_pressure_ramp(p, 20)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocol4Oscillating:
    """Tests for Protocol 4 (oscillating lateral)."""

    def test_sends_multiple_k_commands(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(
            arduino, config, protocol="4",
            max_left=5.0, max_right=5.0, max_pressure=20
        )
        # Bypass pressure ramp - we're testing oscillation
        bypass_pressure_ramp(p, 20)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should get at least one K command
        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocolStop:
    """Tests for stopping a running protocol."""

    def test_stop_sends_emergency_stop(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=50)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for protocol to start
        time.sleep(1)

        # Stop it
        p.stop()

        # Should have sent X command
        assert fake.wait_for_command("X", timeout=5.0)
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocolPulseToggle:
    """Tests for pulse mode toggling."""

    def test_pulse_sends_j_command(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, use_pulse=True)
        # Bypass pressure ramp - we're testing pulse behavior
        bypass_pressure_ramp(p, 20)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should eventually send J for pulsing
        found = fake.wait_for_command("J", timeout=20.0)

        p.is_running = False
        thread.join(timeout=15)
        assert found

    def test_pulse_toggle_off_sends_js(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, use_pulse=True)
        # Bypass pressure ramp - we're testing pulse toggle
        bypass_pressure_ramp(p, 20)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for pulse to start
        fake.wait_for_command("J", timeout=20.0)

        # Toggle pulse off
        p.use_pulse = False
        time.sleep(1)

        # Should send JS to stop pulsing
        assert fake.wait_for_command("JS", timeout=10.0)

        p.is_running = False
        thread.join(timeout=15)
