# tests/integration/test_reset_worker.py
import pytest
import time
import serial
import threading
from unittest.mock import MagicMock

from helpers.reset_worker import ResetWorker
from config.config import Configuration
from fixtures.fake_arduino import FakeArduino
from helpers.arduino import Arduino


@pytest.fixture
def reset_env():
    """Set up environment for reset worker testing."""
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
    # ResetWorker accesses marks with float-formatted keys "0.0"
    # Default marks use integer keys "0", so add float aliases
    config.AMarks["0.0"] = config.AMarks.get("0", 0)
    config.BMarks["0.0"] = config.BMarks.get("0", 1900)

    # Mock main_window with I2Cstatus
    main_window = MagicMock()
    main_window.I2Cstatus = 0

    yield arduino, fake, config, main_window

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


def auto_ack_i2c(fake, main_window, delay=0.1):
    """Background thread that sets I2Cstatus=1 whenever FakeArduino receives new commands.

    Monitors the command list and acks each new command after a short delay,
    simulating the real Arduino's DONE response being processed by the main window.
    """
    def worker():
        last_count = 0
        while getattr(main_window, '_ack_running', True):
            current_count = len(fake.commands_received)
            if current_count > last_count:
                last_count = current_count
                time.sleep(delay)
                main_window.I2Cstatus = 1
            time.sleep(0.02)

    main_window._ack_running = True
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


@pytest.mark.integration
class TestResetWorkerSequence:
    """Tests for the reset sequence command order."""

    def test_sends_y_command(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.1)

        worker = ResetWorker(arduino, config, main_window)

        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()

        # Y should be the first command
        assert fake.wait_for_command("Y", timeout=10.0)

        # Wait for worker to finish
        thread.join(timeout=60)
        main_window._ack_running = False

    def test_sends_calibration_command(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.1)

        worker = ResetWorker(arduino, config, main_window)

        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        thread.join(timeout=60)
        main_window._ack_running = False

        # L0 calibration should have been sent
        assert fake.wait_for_command("L0", timeout=1.0)

    def test_finished_signal_emitted(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.1)

        worker = ResetWorker(arduino, config, main_window)

        with qtbot.waitSignal(worker.signals.finished, timeout=60000) as blocker:
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

        thread.join(timeout=5)
        main_window._ack_running = False
        # blocker.args[0] is the success boolean
        assert blocker.args[0] is True
