"""
Pytest configuration and fixtures for KneeSpa tests.
"""
import sys
import os
import pytest
from typing import Tuple, Generator, Any

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from main.helpers.arduino import Arduino
from main.config.config import Config
from tests.fixtures.arduino_simulator import ArduinoSimulator
from tests.fixtures.arduino_mock import ArduinoTestFixture


@pytest.fixture
def config() -> Config:
    """Fixture to provide a Config instance.
    
    Returns:
        A Config instance
    """
    return Config()


@pytest.fixture
def arduino_fixture() -> Generator[ArduinoTestFixture, None, None]:
    """Fixture to provide an ArduinoTestFixture.
    
    This fixture creates an ArduinoTestFixture and tears it down after the test.
    
    Yields:
        An ArduinoTestFixture instance
    """
    fixture = ArduinoTestFixture()
    yield fixture
    fixture.teardown()


@pytest.fixture
def arduino_mock(arduino_fixture: ArduinoTestFixture) -> Tuple[Arduino, ArduinoSimulator]:
    """Fixture to provide a mocked Arduino instance.
    
    This fixture sets up an Arduino instance with a mock serial interface.
    
    Args:
        arduino_fixture: The ArduinoTestFixture from the arduino_fixture fixture
        
    Returns:
        A tuple of (Arduino instance, ArduinoSimulator instance)
    """
    return arduino_fixture.setup()


@pytest.fixture
def arduino_mock_with_errors(arduino_fixture: ArduinoTestFixture) -> Tuple[Arduino, ArduinoSimulator]:
    """Fixture to provide a mocked Arduino instance with simulated errors.
    
    This fixture sets up an Arduino instance with a mock serial interface
    configured to generate random errors.
    
    Args:
        arduino_fixture: The ArduinoTestFixture from the arduino_fixture fixture
        
    Returns:
        A tuple of (Arduino instance, ArduinoSimulator instance)
    """
    return arduino_fixture.setup(simulate_errors=True)


# Add markers for test categories
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: mark a test as a unit test")
    config.addinivalue_line("markers", "integration: mark a test as an integration test")
    config.addinivalue_line("markers", "ui: mark a test as a UI test")
    config.addinivalue_line("markers", "arduino: mark a test as an Arduino test")
    config.addinivalue_line("markers", "protocol: mark a test as a protocol test")
    config.addinivalue_line("markers", "actuator: mark a test as an actuator test")