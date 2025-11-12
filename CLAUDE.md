# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

- **Platform**: Raspberry Pi 4
- **Operating System**: Raspbian Buster
- **Python Version**: 3.7
- This application is designed to run on a Raspberry Pi 4 with Buster OS and requires Python 3.7 compatibility

## Build Commands

- Install dependencies: `pip install -r requirements.txt`
- Run application: `python main/kneespa.py`
- Run with debug mode: `python main/kneespa.py --debug --print-logs`
- Additional options: `--config PATH` (custom config), `--sync-logs DIR` (sync logs)

## Testing

- Run all tests: `python -m pytest`
- Run specific test categories:
  - Unit tests: `python -m pytest -m unit`
  - Integration tests: `python -m pytest -m integration`
  - UI tests: `python -m pytest -m ui`
  - Arduino tests: `python -m pytest -m arduino`
  - Protocol tests: `python -m pytest -m protocol`
  - Actuator tests: `python -m pytest -m actuator`
- Run single test file: `python -m pytest tests/unit/test_arduino.py`
- Run single test: `python -m pytest tests/unit/test_arduino.py::TestArduino::test_connect`
- Generate coverage report: `python -m pytest --cov=main tests/`

## Code Style Guidelines

### Formatting & Structure

- Follow PEP 8 standards
- Use 4 spaces for indentation
- Maximum line length of 100 characters
- Google-style docstrings for functions and classes

### Naming Conventions

- Classes: CamelCase (e.g., `LoggerAdapter`)
- Functions/variables: snake_case (e.g., `setup_logger`)
- Constants: UPPER_SNAKE_CASE (e.g., `APP_NAME`)

### Imports & Organization

- Order: built-in libs → third-party libs → local modules
- Group imports by category with a blank line between groups
- Always import constants from `main.config.core.constants`

### Type Annotations

- Use type hints for all function parameters and return values
- Import from `typing` module (Optional, Dict, List, etc.)

### Error Handling

- Use custom exceptions from `utils/exceptions.py`
- Log errors with context information
- Classify exceptions by safety criticality

## System Architecture Overview

### Application Type
This is a **medical device control system** for knee rehabilitation therapy, consisting of:
- PyQt5 GUI application running on Raspberry Pi 4
- Arduino-based motor controller for actuator control
- Real-time pressure monitoring and safety systems

### Key Components

1. **Main Application** (`main/kneespa.py`)
   - PyQt5-based GUI with multiple pages (Home, Setup, Main, Help, Profile)
   - Patient management and authentication
   - Protocol execution and monitoring

2. **Arduino Controller** (`main/motor/motor.ino`)
   - Controls 3 actuators: Axial (0-4"), Horizontal (-25° to +5°), Lateral (-20° to +20°)
   - HX711 load cell integration for pressure sensing (max 80 lbs)
   - Emergency stop functionality

3. **Communication**
   - Serial interface via `/dev/serial0` at 9600 baud
   - Text-based command protocol (e.g., "A122.5", "B-15", "K10", "P50")
   - Threaded architecture for non-blocking operation

### Critical Files

- `main/config/constants.py` - System limits, GPIO pins, paths
- `main/config/kneespa.cfg` - Actuator calibration values
- `main/helpers/arduino.py` - Serial communication handler
- `main/helpers/protocols.py` - Treatment protocol implementation
- `main/ui/dialogs/pressure_dialog.py` - Real-time pressure display

### Safety Considerations

- **Hardware Emergency Stop**: GPIO Pin 16
- **Pressure Limit**: 80 lbs maximum
- **Position Limits**: Enforced in software and firmware
- **Connection Monitoring**: Auto-recovery mechanisms
- **Thread Safety**: Lock-based synchronization for serial access

### Development Notes

1. **Serial Port**: Ensure `/dev/serial0` is available and getty service is disabled
2. **GPIO Access**: Application requires proper GPIO permissions
3. **Threading**: Multiple threads for UI, serial reading, and protocol execution
4. **Calibration**: Values in `kneespa.cfg` are hardware-specific
5. **Dependencies**: PyQt5, RPi.GPIO, pyserial are critical

### Common Issues & Solutions

- **Serial Port Busy**: Stop `serial-getty@serial0.service`
- **GPIO Cleanup**: Ensure proper cleanup on application exit
- **Buffer Overflow**: Arduino buffer is 64 bytes, implement throttling
- **Connection Loss**: Auto-reconnect is implemented but may need manual reset

### Testing Considerations

- **Hardware Mock**: Tests should mock Arduino communication
- **GPIO Mock**: Use mock GPIO for testing outside Raspberry Pi
- **Protocol Testing**: Verify timing and sequence accuracy
- **Thread Safety**: Test concurrent access to shared resources

### Development Preferences

- **Testing**: Do not write test scripts for changes. User will test manually.
