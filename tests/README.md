# KneeSpa Testing Framework

This directory contains the comprehensive testing framework for the KneeSpa physical therapy device. The framework addresses the key challenges of testing Arduino communication, actuator control, and protocol execution without requiring physical hardware.

## Test Structure

- **fixtures/** - Reusable test fixtures and mocks
- **unit/** - Unit tests for individual components
- **integration/** - Integration tests for multiple components
- **interactive_simulator.py** - Interactive tool for manual testing

## Test Categories

Tests are organized by functionality with pytest markers:

- **unit**: Basic component tests
- **integration**: Integration between components
- **arduino**: Tests focused on Arduino communication
- **protocol**: Tests of treatment protocols
- **actuator**: Tests of actuator control
- **ui**: Tests of user interface components

## Key Features

### 1. Arduino Simulator

The `ArduinoSimulator` provides a complete simulation of the Arduino device:

- Processes commands and generates appropriate responses
- Maintains state for actuator positions and pressure
- Simulates serial port communication
- Configurable error conditions and timing

### 2. Mock Arduino Hardware

The `ArduinoTestFixture` provides controlled testing of Arduino code:

- Patches serial communication to use the simulator
- Simulates system operations like port management
- Provides methods to test error conditions and recovery
- Enables testing without physical hardware

### 3. Comprehensive Logging

The `TestLogCapture` provides specialized logging for tests:

- Captures logs during test execution
- Analyzes logs for errors and warnings
- Provides assertion methods for log validation
- Context managers for log testing

### 4. Protocol Testing

Protocol tests cover all treatment protocols:

- Tests initialization and configuration
- Tests actuator control and timing
- Tests error handling and safety limits
- Tests protocol signals and events

### 5. UI Testing

UI tests cover interface components:

- Tests with mock dialogs for headless testing
- Tests signal connections and event handling
- Tests integration with Arduino and protocols

### 6. Interactive Testing

The `interactive_simulator.py` provides manual testing:

- Command-line interface for Arduino simulation
- Real-time command monitoring
- Manual state manipulation
- Error simulation controls

## Running Tests

Run the entire test suite:

```bash
python -m pytest
```

Run specific test categories:

```bash
python -m pytest -m unit              # Run unit tests
python -m pytest -m arduino           # Run Arduino tests
python -m pytest -m "protocol and not ui"  # Run protocol tests excluding UI
```

Generate coverage report:

```bash
python -m pytest --cov=main tests/
```

Run the interactive simulator:

```bash
python tests/interactive_simulator.py
```

## Implementation Approach

The testing framework was implemented following this approach:

1. **Created test fixtures** that simulate Arduino responses
   - Implemented `ArduinoSimulator` for command handling
   - Created `MockSerial` to simulate serial port
   - Added configurable error simulation

2. **Developed mock Arduino hardware** for controlled testing
   - Created `ArduinoTestFixture` to patch serial and system calls
   - Added methods to simulate connection issues and reset events
   - Configured pytest fixtures for easy use

3. **Implemented comprehensive logging** during tests
   - Created `TestLogCapture` for log monitoring
   - Added context managers for log assertions
   - Implemented log analysis utilities

4. **Created protocol-specific test scripts**
   - Tested all protocol types (1, 2, 3)
   - Tested pressure and angle control
   - Tested pulse functionality

5. **Added unit tests for individual components**
   - Tests for Arduino communication
   - Tests for protocol execution
   - Tests for CSV handling
   - Tests for configuration
   - Tests for UI components

6. **Developed integration tests** for end-to-end validation
   - Tests combining Arduino and protocols
   - Tests combining UI, Arduino, and protocols
   - Tests simulating real-world scenarios

## Test Coverage

The framework provides thorough testing for the critical components:

- **Arduino Communication**: Connection, reconnection, command handling
- **Protocol Execution**: All protocols with different parameters
- **Actuator Control**: Pressure, position, pulse control
- **Error Handling**: Communication errors, disconnection, recovery
- **UI Integration**: Dialog interaction, signal handling

## Future Enhancements

Potential future improvements to the testing framework:

1. Automated test generation for protocol parameters
2. Performance testing for long-running protocols
3. Load testing for command sequences
4. More comprehensive UI testing
5. Visualization of test results for actuator positions