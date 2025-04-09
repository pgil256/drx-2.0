# KneeSpa Test Fixtures

This directory contains test fixtures for the KneeSpa application. These fixtures provide mock implementations and utilities for testing without requiring physical hardware.

## Arduino Simulator

The `ArduinoSimulator` in `arduino_simulator.py` provides a complete simulation of the Arduino device. It can be used to test Arduino communication without requiring physical hardware.

### Key Features

- **Command Processing**: Simulates Arduino responses to commands
- **Device State**: Maintains simulated device state (positions, pressure)
- **Error Simulation**: Can be configured to simulate communication errors
- **Disconnect Simulation**: Can simulate device disconnection and reconnection

### Example Usage

```python
from tests.fixtures.arduino_simulator import ArduinoSimulator

# Create and connect a simulator
simulator = ArduinoSimulator()
simulator.connect(port="MOCK", baudrate=115200)

# Configure error conditions (optional)
simulator.set_error_conditions(
    error_rate=0.1,         # 10% chance of errors
    disconnect_after=None,  # No automatic disconnect
    dropped_bytes_rate=0.05 # 5% chance of dropped bytes
)

# Set device state (optional)
simulator.set_device_state(
    position_a=100,
    position_b=200,
    position_c=300,
    pressure=25.0
)

# Disconnect when done
simulator.disconnect()
```

## Arduino Mock

The `ArduinoTestFixture` in `arduino_mock.py` provides a fixture for testing the Arduino class with the simulator. It patches the serial and subprocess modules to use the simulator.

### Key Features

- **Serial Patching**: Redirects serial port access to the simulator
- **Subprocess Patching**: Mocks system commands for port management
- **Error Simulation**: Provides methods to simulate different error conditions
- **Reset Simulation**: Can simulate Arduino reset events

### Example Usage

```python
from tests.fixtures.arduino_mock import ArduinoTestFixture

# Create a test fixture
fixture = ArduinoTestFixture()

# Set up Arduino with simulator
arduino, simulator = fixture.setup()

# Use Arduino as normal - it will communicate with the simulator
arduino.run()
arduino.send("T")  # Test command

# Simulate a disconnection
fixture.simulate_disconnect()

# Simulate an Arduino reset
fixture.simulate_arduino_reset()

# Tear down when done
fixture.teardown()
```

## UI Mocks

The `UITestFixture` in `ui_mock.py` provides utilities for testing UI components.

### Key Features

- **Dialog Mocking**: Provides mock implementations of UI dialogs
- **Event Processing**: Handles UI event processing for tests
- **Widget Tracking**: Tracks test widgets for cleanup

### Example Usage

```python
from tests.fixtures.ui_mock import UITestFixture

# Create a test fixture
fixture = UITestFixture()
fixture.setup()

# Create and use UI components as needed
dialog = TimerDialog(5)
fixture.register_widget('timer_dialog', dialog)

# Process UI events
fixture.process_events()

# Tear down when done
fixture.teardown()
```

## Test Logger

The `TestLogCapture` in `test_logger.py` provides utilities for capturing and analyzing logs during tests.

### Key Features

- **Log Capture**: Captures logs during test execution
- **Log Analysis**: Analyzes logs for errors, warnings, etc.
- **Assertion Helpers**: Provides assertion methods for log content

### Example Usage

```python
from tests.fixtures.test_logger import capture_logs, assert_log_message

# Capture logs during a test
with capture_logs() as logs:
    # Run test code
    run_test_function()
    
    # Check logs
    assert logs.contains_message("Expected message")
    assert not logs.contains_message("Error")
    
    # Get log statistics
    analysis = logs.analyze_logs()
    print(f"Found {analysis['error_lines']} errors and {analysis['warning_lines']} warnings")

# Assert a specific message appears in logs
with assert_log_message("Expected message"):
    run_test_function()
```

## Best Practices

1. **Use with pytest fixtures**: These fixtures are designed to work with pytest fixtures
2. **Clean up resources**: Always tear down fixtures when done
3. **Handle errors**: Use try-finally blocks to ensure cleanup
4. **Mock dependencies**: Use patches to mock external dependencies
5. **Avoid UI dependencies**: Use UI mocks for headless testing