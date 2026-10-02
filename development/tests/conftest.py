# tests/conftest.py
from contextlib import ExitStack
import logging
import os
import sys
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

# Add main/ to sys.path so imports like `from config.constants import ...` work.
# Its parent is deliberately absent: main.config.constants would be a second copy.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'development'))
sys.path.insert(0, os.path.join(REPO_ROOT, 'runtime', 'raspberry-pi', 'main'))

# Add tests/ to sys.path so `from fixtures.fake_arduino import ...` works
sys.path.insert(0, os.path.dirname(__file__))

# Mock RPi.GPIO before any module imports it
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()

# Mock PyQt5.QtMultimedia (may not be available without system libpulse)
sys.modules['PyQt5.QtMultimedia'] = MagicMock()
sys.modules['PyQt5.QtMultimediaWidgets'] = MagicMock()

# Mock vlc (video player dependency not available in test env)
sys.modules['vlc'] = MagicMock()

# Set Qt to offscreen mode for headless testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'


def pytest_configure(config: pytest.Config) -> None:
    """Isolate import-time application logs without patching filesystem APIs."""
    from config import constants

    stack = ExitStack()
    config.add_cleanup(stack.close)
    log_base = stack.enter_context(TemporaryDirectory(prefix="kneespa-test-logs-"))
    app_logger = logging.getLogger(constants.APP_NAME)
    serial_logger = logging.getLogger(f"{constants.APP_NAME}.serial")
    saved_handlers = list(app_logger.handlers)
    saved_serial_handlers = list(serial_logger.handlers)
    saved_filters = list(logging.getLogger("PyQt5").filters)
    saved_level = app_logger.level

    def restore_logging() -> None:
        for handler in list(app_logger.handlers):
            if handler not in saved_handlers:
                app_logger.removeHandler(handler)
                handler.close()
        app_logger.setLevel(saved_level)
        for handler in list(serial_logger.handlers):
            if handler not in saved_serial_handlers:
                serial_logger.removeHandler(handler)
                handler.close()
        logging.getLogger("PyQt5").filters[:] = saved_filters

    # Close file handles before TemporaryDirectory removes the log directory.
    stack.callback(restore_logging)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(constants, "LOG_DIR", log_base)
        from helpers import logging as app_logging

    # logging imports LOG_DIR by value; leave only its local copy isolated
    # for the session, including tests that reconstruct the logger singleton.
    stack.callback(setattr, app_logging, "LOG_DIR", constants.LOG_DIR)


# --- Integration fixtures ---

from fixtures.fake_arduino import FakeArduino, PTY_AVAILABLE

# NOTE: the pre-FAILSAFE Arduino had a release_busy_port() that ran
# `fuser -k <port>` on reconnect — in tests the port is a pty held by the
# pytest process itself, so a stray reconnect SIGKILLed the whole run
# (the historical exit-137 on Ubuntu CI). This branch's Arduino removed
# that path entirely; no session-wide neutralization is needed anymore.


@pytest.fixture
def fake_arduino_pair():
    """A FakeArduino and a real Arduino connected over a pty, reader running.

    Yields:
        tuple: (arduino_instance, fake_arduino_instance)
    """
    import threading

    import serial

    from helpers.arduino import Arduino

    if not PTY_AVAILABLE:
        pytest.skip("FakeArduino requires POSIX pty/termios support")

    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True
    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    yield arduino, fake

    # Exception-safe teardown, in dependency order: stop and join the reader
    # BEFORE closing the port (the legacy reader reacted to a dying port with
    # reconnect attempts -- multi-second sleeps and new threads that outlive
    # the test), then close the serial fd, then stop/join the FakeArduino
    # thread and close the pty.
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
