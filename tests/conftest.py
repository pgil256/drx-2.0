# tests/conftest.py
import sys
import os
import pytest
from unittest.mock import MagicMock

# Add main/ to sys.path so imports like `from config.constants import ...` work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'main'))

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

# Patch os.path.exists so constants.py's validate_paths() doesn't fail
# (paths reference /home/pi/drx-2.3/main/ which doesn't exist in test env)
_original_exists = os.path.exists


def _patched_exists(path):
    if '/home/pi/drx-2.3/' in str(path):
        return True
    return _original_exists(path)


os.path.exists = _patched_exists

# Patch os.makedirs so logging.py can create log dirs under /home/pi/...
_original_makedirs = os.makedirs


def _patched_makedirs(name, mode=0o777, exist_ok=False):
    if '/home/pi/drx-2.3/' in str(name):
        return  # Silently skip
    return _original_makedirs(name, mode=mode, exist_ok=exist_ok)


os.makedirs = _patched_makedirs

# Patch logging.handlers.RotatingFileHandler to avoid creating log files
import logging.handlers
_OriginalRotatingFileHandler = logging.handlers.RotatingFileHandler


class _MockRotatingFileHandler(logging.Handler):
    """A no-op handler that replaces RotatingFileHandler in tests."""
    def __init__(self, *args, **kwargs):
        logging.Handler.__init__(self)

    def emit(self, record):
        pass


logging.handlers.RotatingFileHandler = _MockRotatingFileHandler

# Set Qt to offscreen mode for headless testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'


# --- Integration fixtures ---

from fixtures.fake_arduino import FakeArduino


@pytest.fixture
def fake_arduino_pair():
    """
    Create a FakeArduino and a real Arduino instance connected via pty.

    Yields:
        tuple: (arduino_instance, fake_arduino_instance)
    """
    from helpers.arduino import Arduino

    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port

    yield arduino, fake

    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


@pytest.fixture
def config_with_defaults():
    """Create a Configuration instance with default mark values."""
    from config.config import Configuration
    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.a_factor = 1900
    config.b_factor = 1900
    config.c_factor = 1900
    config.calibration = 1.0
    config.flexion_position = 0
    return config


@pytest.fixture
def protocol_factory(fake_arduino_pair, config_with_defaults):
    """
    Factory for creating Protocols instances connected to FakeArduino.

    Returns a callable that creates Protocols with overridable defaults.
    """
    from helpers.protocols import Protocols

    arduino, fake = fake_arduino_pair

    def create_protocol(**kwargs):
        defaults = dict(
            a_factor=1900,
            protocol="1",
            max_pressure=50,
            max_left=10.0,
            max_right=10.0,
            duration=1,
            use_pulse=False,
            ser=arduino,
            config=config_with_defaults,
        )
        defaults.update(kwargs)
        return Protocols(**defaults), fake

    return create_protocol
