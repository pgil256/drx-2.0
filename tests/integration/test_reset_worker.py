# tests/integration/test_reset_worker.py
import pytest
import time
import serial
import threading
from types import SimpleNamespace

from helpers.reset_worker import ResetWorker
from config.config import Configuration
from fixtures.fake_arduino import FakeArduino, PTY_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PTY_AVAILABLE,
    reason="FakeArduino requires POSIX pty/termios support",
)
from helpers.arduino import Arduino


class FakeMainWindow:
    """Minimal stand-in for KneeSpa exposing only the DONE-synchronization
    surface ResetWorker uses, wired to the real Arduino done_emit signal.

    Unlike a MagicMock, attribute truthiness is real: `worker` is None so
    the reset's protocol-running guard does not spuriously abort, and the
    I2Cstatus_event is set by the genuine DONE chain
    (firmware DONE -> reader thread -> done_emit -> set_done).
    """

    def __init__(self, arduino):
        self.I2Cstatus = 0
        self.I2Cstatus_event = threading.Event()
        self.worker = None  # no protocol running
        arduino.done_emit.connect(self.set_done)

    def set_done(self):
        self.I2Cstatus = 1
        self.I2Cstatus_event.set()


@pytest.fixture
def reset_env():
    """Set up environment for reset worker testing."""
    fake = FakeArduino()
    fake.boot_delay = 0.1  # shorten 'Y' reboot for test speed
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
    # Realistic device factor; an implausible one makes the reset skip L0
    config.calibration = -28369.0
    config.scale_calibrated = True
    # ResetWorker accesses marks with float-formatted keys "0.0"
    # Default marks use integer keys "0", so add float aliases
    config.AMarks["0.0"] = config.AMarks.get("0", 0)
    config.BMarks["0.0"] = config.BMarks.get("0", 1900)

    main_window = FakeMainWindow(arduino)

    yield arduino, fake, config, main_window

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


@pytest.mark.integration
class TestResetWorkerSequence:
    """Tests for the reset sequence against the real DONE signal chain."""

    def test_full_reset_sequence(self, reset_env, qtbot):
        """The complete 6-step sequence runs to success, each step gated by
        a genuine firmware DONE (no artificial acks)."""
        arduino, fake, config, main_window = reset_env

        worker = ResetWorker(arduino, config, main_window)

        with qtbot.waitSignal(worker.signals.finished, timeout=25000) as blocker:
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

        thread.join(timeout=5)
        assert blocker.args[0] is True

        # Command order (ignoring automatic 'Q' status acks): the reset
        # sequence is Y, zero marks, lateral home, horizontal home,
        # axial home, calibration.
        cmds = [c for c in fake.commands_received if not c.startswith("Q")]
        prefixes = ["Y", "L5", "I14", "I13", "I12", "L0"]
        assert len(cmds) == len(prefixes), f"unexpected commands: {cmds}"
        for cmd, prefix in zip(cmds, prefixes):
            assert cmd.startswith(prefix), f"expected {prefix}, got {cmd} in {cmds}"

    def test_reset_aborts_while_protocol_running(self, reset_env, qtbot):
        """The protocol-running guard must refuse to reset and emit failure."""
        arduino, fake, config, main_window = reset_env
        main_window.worker = SimpleNamespace(is_running=True)

        worker = ResetWorker(arduino, config, main_window)

        with qtbot.waitSignal(worker.signals.finished, timeout=5000) as blocker:
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

        thread.join(timeout=5)
        assert blocker.args[0] is False
        assert not any(c.startswith("Y") for c in fake.commands_received)
