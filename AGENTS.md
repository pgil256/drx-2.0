# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Build Commands

- Run application: `python main/kneespa.py`
- Run with debug mode: `python main/kneespa.py --debug --print-logs`
- Additional options: `--config PATH` (custom config), `--sync-logs DIR` (sync logs)

## Testing

- Run all tests: `python -m pytest`
- Run specific test categories (markers defined in pytest.ini):
  - Unit tests: `python -m pytest -m unit`
  - Integration tests: `python -m pytest -m integration` (require POSIX pty; they skip on Windows — run under WSL/Linux)
  - Hardware tests: `python -m pytest -m hardware` (require real Pi + Arduino)
- Run single test file: `python -m pytest tests/unit/test_arduino_parse.py`
- Run single test: `python -m pytest tests/unit/test_protocol_logic.py::TestSetToCDistance::test_exact_mark_lookup`
- Generate coverage report: `python -m pytest --cov=main tests/`
- Firmware native tests: `bash main/motor/run_native_tests.sh` (g++ + vendored Unity; `pio test -e native` in `main/motor/` also works where PlatformIO is available)

## Architecture

### Overview
KneeSpa is a PyQt5-based medical device control application for a knee treatment system running on Raspberry Pi. It controls three actuators (axial, horizontal, lateral) via serial communication with an Arduino.

### Core Components

**`main/kneespa.py`** - Main application entry point and UI controller (`KneeSpa` class)
- Manages PyQt5 UI loaded from `.ui` files in `main/ui/guis/`
- Handles GPIO for emergency stop and controls
- Coordinates protocol execution via thread pool

**`main/helpers/arduino.py`** - Serial communication layer (`Arduino` class)
- Manages `/dev/serial0` connection to Arduino
- Uses PyQt signals (`status_emit`, `pressure_emit`, `connection_lost`) for async communication
- Thread-safe command sending with `_lock`
- Automatic reconnection and connection verification with `T` test commands

**`main/helpers/protocols.py`** - Treatment protocol execution (`Protocols` class)
- `QRunnable` implementation for background thread execution
- Four protocols: axial-only (1), left lateral (2), right lateral (3), oscillating (4)
- Pressure ramping via `run_pressure_sequence()` with tolerance-based verification
- Real-time pulse mode toggling via `use_pulse` flag

**`main/config/constants.py`** - All configuration constants
- Actuator definitions with limits, command prefixes, units
- Safety limits: `PRESSURE_MAX=80`, `AXIAL_MAX=4600`, lateral range 500-2400
- Arduino settings, GPIO pins, UI paths

**`main/config/config.py`** - Runtime configuration (`Configuration` class)
- Reads/writes `kneespa.cfg` for calibration data
- Stores actuator position marks (`CMarks`, `AMarks`, `BMarks`) for degree-to-position mapping

### Arduino Communication Protocol
Commands are single-letter prefixed strings sent via serial:
- `P<value>` - Set pressure (lbs)
- `K<position>` - Move lateral actuator (C) to position
- `A<actuator><inches>` - Move actuator to distance
- `J` / `JS` - Start/stop pulsing
- `X` - Emergency stop
- `T` - Test/keepalive (expects "OK" response)
- `HF1` / `HF0` - Enable/disable high-frequency status updates

Status responses: `STATUS_START|S|posA|posB|posC|pressure|STATUS_END`

Protocol v2 (opt-in via `KNEESPA_PROTOCOL_V2=1`, firmware FAILSAFE-2+):
commands are framed `#<seq>:<CMD>*<XX>` (XX = two-hex XOR of `<seq>:<CMD>`),
acks echo the sequence (`DONE|<seq>`, `BUSY|<seq>`, `OK|<seq>`,
`ERR|<seq>|<reason>`), and status frames carry a trailing `*<XX>` checksum.

### UI Components
- `main/ui/dialogs/` - Modal dialogs (timer, pressure, video player)
- `main/ui/widgets/` - Reusable widgets (loading spinner)
- Qt UI files in `main/ui/guis/` loaded via `uic.loadUi()`

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
- Always import constants from `main.config.constants`

### Type Annotations

- Use type hints for all function parameters and return values
- Import from `typing` module (Optional, Dict, List, etc.)

### Error Handling

- Log errors with context information using `helpers.logging.setup_logger()`
- Classify exceptions by safety criticality
