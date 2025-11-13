# DRX-2.0 KneeSpa System Documentation

**Version:** 2.3
**Platform:** Raspberry Pi 4 with Raspbian Buster
**Python Version:** 3.7
**Last Updated:** November 2025

---

## Table of Contents

- [1. Project Overview](#1-project-overview)
- [2. Quick Start](#2-quick-start)
- [3. System Architecture](#3-system-architecture)
- [4. Development Guidelines](#4-development-guidelines)
- [5. Installation & Setup](#5-installation--setup)
- [6. System Components](#6-system-components)
- [7. Bug Reports & Fixes](#7-bug-reports--fixes)
- [8. Security Analysis](#8-security-analysis)
- [9. Thread Safety](#9-thread-safety)
- [10. Testing](#10-testing)
- [11. Codebase Reference](#11-codebase-reference)
- [12. Maintenance & Cleanup](#12-maintenance--cleanup)

---

## 1. Project Overview

### What is KneeSpa?

KneeSpa is a **medical device control system** for automated knee rehabilitation therapy. It consists of a Raspberry Pi 4 running a PyQt5 application that controls an Arduino-based motor system with three actuators for multi-axis knee movement and pressure-based therapy protocols.

### Key Features

- **Three-Axis Actuator Control**
  - Axial: 0-4 inches vertical movement
  - Horizontal: -25° to +5° flexion/extension
  - Lateral: -20° to +20° side-to-side movement

- **Pressure Monitoring & Safety**
  - Real-time pressure sensing (0-80 lbs)
  - HX711 load cell integration
  - Hardware emergency stop

- **Treatment Protocols**
  - Four pre-programmed protocols (AC1-AC4)
  - Configurable pressure, angles, and duration
  - Pulse/oscillation modes

- **Patient Management**
  - PIN-based authentication
  - Patient profiles and history
  - Treatment session logging

### Medical Device Compliance

This is safety-critical medical device software that must meet FDA/CE safety standards. All critical bugs must be fixed before clinical use.

---

## 2. Quick Start

### Running the Application

```bash
# Production mode
python main/kneespa.py

# Debug mode with verbose logging
python main/kneespa.py --debug --print-logs

# With custom config file
python main/kneespa.py --config /path/to/config.cfg
```

### Running Tests

```bash
# All tests
python -m pytest

# Specific test categories
python -m pytest -m unit           # Unit tests only
python -m pytest -m integration    # Integration tests
python -m pytest -m protocol       # Protocol tests
python -m pytest -m arduino        # Arduino tests
```

### Essential Configuration

Edit `/home/pi/drx-2.3/main/config/kneespa.cfg`:

```ini
[Options]
flexion_position = 1978
a_factor = 3640              # Axial calibration
b_factor = 3640              # Horizontal calibration
c_factor = 3640              # Lateral calibration
calibration = -28369.0       # Load cell calibration
unlock = 123                 # Admin unlock code

[CMarks]
-20.0 = 150                  # Lateral angle-to-position mapping
-10.0 = 720
0.0 = 0
10.0 = 1900
20.0 = 2150
```

---

## 3. System Architecture

### Hardware Components

1. **Raspberry Pi 4** - Main application host
2. **Arduino Uno** - Motor controller
3. **Three Actuators**
   - SMC #12 (Axial)
   - SMC #13 (Horizontal)
   - SMC #14 (Lateral)
4. **HX711 Load Cell** - Pressure sensor
5. **Emergency Stop** - GPIO Pin 16

### Software Stack

```
┌─────────────────────────────────────┐
│         PyQt5 GUI Application        │
│         (main/kneespa.py)           │
└────────────────┬────────────────────┘
                 │
    ┌────────────┴────────────┐
    │                         │
┌───▼────────┐       ┌────────▼────────┐
│  Protocol  │       │     Arduino     │
│  Engine    │       │  Communication  │
│(protocols) │       │   (arduino.py)  │
└────────────┘       └────────┬────────┘
                              │
                    Serial (/dev/serial0)
                              │
                 ┌────────────▼────────────┐
                 │   Arduino Controller     │
                 │     (motor.ino)         │
                 └─────────────────────────┘
```

### Communication Protocol

**Pi to Arduino** (9600 baud):
- `P<pressure>` - Set pressure target (e.g., "P50")
- `A<actuator><inches>` - Position by inches (e.g., "A122.5")
- `K<position>` - Lateral position control (e.g., "K1500")
- `S` - Request status
- `X` - Emergency stop
- `Y<code>` - Reset command
- `HF1`/`HF0` - High-frequency status toggle

**Arduino to Pi**:
- `STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END`
- `DONE` - Command completed
- `OK` - Verification response

### Threading Model

- **Main Thread** - GUI and user interaction
- **Arduino Reader Thread** - Continuous serial monitoring
- **Protocol Thread** - QRunnable for treatment execution
- **Reset Worker Thread** - Hardware initialization

---

## 4. Development Guidelines

### Code Style

- **Follow PEP 8 standards**
- **4 spaces indentation**
- **Maximum line length: 100 characters**
- **Google-style docstrings**

### Naming Conventions

- **Classes:** CamelCase (e.g., `LoggerAdapter`)
- **Functions/variables:** snake_case (e.g., `setup_logger`)
- **Constants:** UPPER_SNAKE_CASE (e.g., `APP_NAME`)

### Imports Organization

```python
# Built-in libraries
import sys
import time

# Third-party libraries
from PyQt5 import QtCore, QtWidgets
import serial

# Local modules
from main.config.core.constants import PRESSURE_MAX
```

### Type Annotations

```python
def set_to_c_distance(self, degrees: float) -> bool:
    """Set lateral actuator to specified angle."""
    pass
```

### Error Handling

- Use custom exceptions from `utils/exceptions.py`
- Log errors with context information
- Classify exceptions by safety criticality

### Development Preferences

- **Do not write test scripts for changes** - User will test manually
- Always use constants from `main.config.core.constants`
- Never commit `.env` files or sensitive data

---

## 5. Installation & Setup

### System Requirements

- **Hardware:** Raspberry Pi 4 (2GB RAM minimum, 4GB recommended)
- **OS:** Raspbian Buster (Debian 10)
- **Python:** 3.7.x
- **Storage:** 8GB minimum free space
- **Peripherals:** Arduino via Serial, GPIO access required

### Quick Installation

```bash
# 1. Clone repository
cd ~
git clone <repository-url> drx-demo-final
cd drx-demo-final

# 2. Run setup script
chmod +x setup_system.sh
./setup_system.sh

# 3. Configure environment
cp .env.example .env
nano .env  # Edit with your values

# 4. Reboot
sudo reboot
```

### Manual Installation

#### Install System Dependencies

```bash
sudo apt-get update

# Python development tools
sudo apt-get install -y python3-dev python3-pip python3-venv build-essential

# PyQt5
sudo apt-get install -y python3-pyqt5 python3-pyqt5.qtmultimedia pyqt5-dev-tools

# Hardware libraries
sudo apt-get install -y python3-rpi.gpio python3-smbus python3-serial i2c-tools

# VLC media libraries
sudo apt-get install -y vlc libvlc-dev python3-vlc
```

#### Configure Raspberry Pi

```bash
# Enable I2C
sudo raspi-config nonint do_i2c 0

# Enable Serial (disable console)
sudo raspi-config nonint do_serial 2

# Disable getty service
sudo systemctl stop serial-getty@serial0.service
sudo systemctl disable serial-getty@serial0.service

# Add user to groups
sudo usermod -a -G gpio,i2c,spi,dialout $USER
```

#### Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip==21.3.1
pip install -r requirements.txt
```

### Troubleshooting

#### Serial Port Issues

```bash
# Check serial port availability
ls -l /dev/serial*

# Verify getty is disabled
systemctl status serial-getty@serial0.service

# Test serial communication
python -c "import serial; print(serial.Serial('/dev/serial0', 9600))"
```

#### GPIO Permission Issues

```bash
# Verify group membership
groups

# Should include: gpio i2c spi dialout
# If not, run:
sudo usermod -a -G gpio,i2c,spi,dialout $USER
# Then logout and login again
```

---

## 6. System Components

### Core Application Files

| File | Lines | Purpose |
|------|-------|---------|
| `main/kneespa.py` | 2259 | Main application class and UI coordinator |
| `main/motor/motor.ino` | 889 | Arduino firmware |
| `main/helpers/protocols.py` | ~800 | Protocol execution engine |
| `main/helpers/arduino.py` | ~600 | Serial communication handler |
| `main/config/constants.py` | 211 | System constants and limits |

### Key Configuration Files

- **`main/config/kneespa.cfg`** - Runtime calibration values
- **`.env`** - Environment variables (credentials, PINs)
- **`main/data/user_pins.csv`** - User authentication data

### Safety Constants

```python
# From main/config/constants.py
PRESSURE_MAX = 80                # lbs
AXIAL_MAX = 4                    # inches
LATERAL_MIN, LATERAL_MAX = -20, 20  # degrees
HORIZONTAL_MIN, HORIZONTAL_MAX = -25, 5  # degrees
```

### Protocol System

Four pre-programmed therapy protocols (AC1-AC4):
- **Configurable Parameters:**
  - Maximum pressure (lbs)
  - Left/right lateral angles (degrees)
  - Duration (minutes)
  - Pulsing mode enabled/disabled
  - Pressure increment steps
  - Angle increment steps

---

## 7. Bug Reports & Fixes

### Critical Bugs (FIXED)

#### ✓ 1. Pressure Safety Bypass
**Issue:** No validation against PRESSURE_MAX (80 lbs)
**Location:** `kneespa.py:1604-1629`
**Fix:** Added comprehensive safety validation with clamping and warnings

#### ✓ 2. Axial Position Overshoot
**Issue:** Allowed 8 inches when AXIAL_MAX = 4 inches
**Location:** `kneespa.py:1265-1280`
**Fix:** Now uses correct `ACTUATORS["AXIAL"]["LIMITS"]` constant

#### ✓ 3. Division by Zero Protection
**Issue:** Crashes when calibration factors are zero
**Location:** `kneespa.py:1668-1702`, `protocols.py:285-291`
**Fix:** Added zero-check validation before all divisions

#### ✓ 4. Undefined Signal Crash
**Issue:** `display_weight_emit` signal not defined
**Location:** `arduino.py:25`
**Fix:** Added missing signal definition

#### ✓ 5. Thread Safety Race Conditions
**Issue:** I2Cstatus flag shared between threads without synchronization
**Location:** `kneespa.py:194`, `reset_worker.py:23-56`
**Fix:** Implemented thread-safe `threading.Event()`

#### ✓ 6. Configuration Error Handling
**Issue:** KeyError crashes on missing config sections
**Location:** `config.py:39-75`
**Fix:** Added robust error handling with defaults

#### ✓ 7. File Handle Leaks
**Issue:** Files opened but never closed
**Location:** `config.py:29,167`
**Fix:** Implemented context managers (`with open()`)

### Known Issues Summary

| Category | Critical | High | Medium | Total |
|----------|----------|------|--------|-------|
| Thread Safety | 5 | 5 | 2 | 12 |
| Boundary Conditions | 5 | 2 | 2 | 9 |
| Configuration | 2 | 1 | 0 | 3 |
| Resource Management | 0 | 3 | 1 | 4 |
| Exception Handling | 0 | 2 | 3 | 5 |
| **TOTAL** | **12** | **15** | **13** | **40** |

### Validation Results

All critical fixes have been validated:
```
Total checks: 11
Passed: 11
Failed: 0
✓ SUCCESS: All critical fixes validated!
```

---

## 8. Security Analysis

### Security Improvements (IMPLEMENTED)

#### ✓ Environment Variable Migration

**Migrated from hardcoded to .env:**
- Email credentials (SMTP)
- System unlock code
- User authentication PINs

**Setup:**
```bash
cp .env.example .env
# Edit .env with actual values
nano .env
```

#### Security Recommendations

**Immediate Actions:**
1. Change default PINs (123, 456) to secure values
2. Rotate compromised Gmail app password
3. Never commit `.env` file to version control

**For Production:**
1. Use proper database with password hashing (bcrypt, argon2)
2. Implement session management instead of PIN-based auth
3. Use secrets management service (AWS Secrets Manager, HashiCorp Vault)
4. Enable audit logging for authentication attempts
5. Implement rate limiting for login attempts

### Input Validation Issues

#### Pressure Slider Validation
- **Fixed:** Added bounds checking against PRESSURE_MAX
- **Validation:** Clamps to 0-80 lbs range

#### Arduino Command Injection
- **Risk:** Commands sent without validation
- **Mitigation:** Validate all numeric inputs before sending

#### PIN Validation
- **Issue:** No length check, rate limiting, or sanitization
- **Current:** PINs printed in logs (security issue)
- **TODO:** Add validation, rate limiting, hash storage

---

## 9. Thread Safety

### Critical Race Conditions (FIXED)

#### ✓ 1. I2Cstatus Flag Race
**Problem:** Unsynchronized flag access between threads
**Fix:** Added `threading.Event()` for thread-safe signaling

#### ✓ 2. Protocol Parameter Race
**Problem:** UI thread writes worker parameters while protocol reads
**Fix:** Added `_param_lock` for synchronized access

#### ✓ 3. Arduino Lock Scope
**Problem:** Lock released too early (TOCTOU vulnerability)
**Fix:** Expanded lock scope to cover check-use sequences

### Thread Safety Best Practices

```python
# Use threading.Event for signaling
self.I2Cstatus_event = threading.Event()

# Protect shared state with locks
with self._param_lock:
    self.use_pulse = value

# Expand lock scope for atomic operations
with self._lock:
    if self.connected:
        self.serial_com.write(cmd)
```

### Testing Recommendations

1. **Race condition testing** - Run concurrent protocol starts/stops
2. **Signal testing** - Verify all emitted signals are defined
3. **State consistency** - Log flag transitions
4. **Stress testing** - Long-duration protocols with parameter changes
5. **Deadlock detection** - Use timeout-based assertions

---

## 10. Testing

### Running Tests

```bash
# All tests
python -m pytest

# Specific categories
python -m pytest -m unit           # Unit tests
python -m pytest -m integration    # Integration tests
python -m pytest -m ui             # UI tests
python -m pytest -m arduino        # Arduino communication
python -m pytest -m protocol       # Treatment protocols
python -m pytest -m actuator       # Actuator control

# Single test file
python -m pytest tests/unit/test_arduino.py

# Single test
python -m pytest tests/unit/test_arduino.py::TestArduino::test_connect

# With coverage
python -m pytest --cov=main tests/
```

### Test Requirements

After fixes are implemented:

1. **Boundary Testing** - Verify actuators respect mechanical limits
2. **Pressure Testing** - Confirm 80 lbs maximum enforced
3. **Concurrency Testing** - Run protocols while adjusting parameters
4. **Error Recovery** - Test with corrupted config, disconnected Arduino
5. **Resource Testing** - Long-running tests for leaks
6. **Security Testing** - Input validation, PIN security

---

## 11. Codebase Reference

### Directory Structure

```
drx-2.0/
├── main/
│   ├── kneespa.py                 # Main application entry point
│   ├── config/
│   │   ├── constants.py           # System constants and limits
│   │   ├── config.py              # Configuration management
│   │   └── kneespa.cfg            # Runtime calibration values
│   ├── helpers/
│   │   ├── arduino.py             # Serial communication
│   │   ├── protocols.py           # Treatment protocol executor
│   │   ├── csv.py                 # Patient data management
│   │   ├── reset_worker.py        # Hardware initialization
│   │   └── logging.py             # Application logging
│   ├── ui/
│   │   ├── guis/                  # Qt Designer UI files
│   │   ├── dialogs/               # Dialog windows
│   │   ├── widgets/               # Custom widgets
│   │   └── media/                 # UI assets
│   ├── motor/
│   │   └── motor.ino              # Arduino firmware
│   ├── data/
│   │   ├── user_pins.csv          # User authentication
│   │   └── patients/              # Patient records
│   └── logs/                      # Application logs
├── tests/                         # Test suite
├── .env                           # Environment variables (git-ignored)
├── .env.example                   # Environment template
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

### Key Functions Reference

#### Main Application (kneespa.py)

- `set_to_distance()` - Move axial actuator to distance
- `set_to_c_distance()` - Move lateral actuator with interpolation
- `start_protocol()` - Initialize and execute treatment protocol
- `stop_protocol()` - Halt ongoing treatment
- `reset_devices()` - Full hardware reset sequence
- `enable_actuator_controls()` - Re-enable UI buttons
- `disable_actuator_controls()` - Disable UI buttons during movement

#### Arduino Communication (arduino.py)

- `send(command)` - Send command to Arduino
- `connect()` - Establish serial connection
- `disconnect()` - Close serial connection
- `verify_connection()` - Test connection status
- `reset_dtr()` - Reset Arduino via DTR line

#### Protocol Execution (protocols.py)

- `run()` - Main protocol execution loop
- `run_pressure_sequence()` - Manage pressure ramps
- `set_to_pressure()` - Set target pressure
- `set_to_c_distance()` - Set lateral angle with interpolation
- `update_status()` - Handle Arduino feedback
- `stop_protocol()` - Signal protocol termination

---

## 12. Maintenance & Cleanup

### Unused Code Analysis

**Total Unused Items:** 24
- **Unused Imports:** 22
- **Unused Methods:** 1
- **Commented Code:** 1
- **All items safe to remove:** YES

**Files with Unused Code:**
1. `main/config/config.py` - 11 items
2. `main/ui/dialogs/pressure_dialog.py` - 5 items
3. `main/helpers/protocols.py` - 4 items
4. `main/helpers/arduino.py` - 3 items
5. `main/kneespa.py` - 2 items

**Cleanup Priority:**

✓ **Priority 1** (Critical - 5 minutes)
- Remove `get_list()` method from config.py
- Remove commented `self.reconnect()` from arduino.py

✓ **Priority 2** (High - 15 minutes)
- Remove 10 imports from config.py
- Remove 5 imports from pressure_dialog.py
- Remove 4 imports from protocols.py

✓ **Priority 3** (Medium - 20-30 minutes)
- Remove remaining imports from other files

### Prevention Recommendations

**IDE Configuration:**
- PyCharm: Enable "Unused import" inspection
- VSCode: Install Pylance extension

**Command Line Tools:**
```bash
# Detect unused imports
pylint main/ --disable=all --enable=unused-import

# General style check
flake8 main/ --select=F401
```

### System Updates

```bash
# Update system packages (safe)
sudo apt-get update
sudo apt-get upgrade -y

# Update Python packages
source venv/bin/activate
pip install --upgrade -r requirements.txt

# Backup configuration
cp .env .env.backup
cp main/config/kneespa.cfg main/config/kneespa.cfg.backup
```

---

## Appendix A: Lateral Control System

The lateral control system manages side-to-side knee movement with precise angle control.

### Button Handlers

```python
# Slow movements (5° step)
forward_lateral_flexion_button      # +5° (right)
reverse_lateral_flexion_button      # -5° (left)

# Fast movements (10° step)
forward_fast_lateral_flexion_button # +10° (right)
reverse_fast_lateral_flexion_button # -10° (left)
```

### Control Flow

```
User clicks button
    ↓
move_actuator(actuator_c, step, speed, direction)
    ↓
Calculate new position with rounding to 2.5° increments
    ↓
Validate bounds (-20° to +20°)
    ↓
disable_actuator_controls()  # Lock all buttons
    ↓
Send command: "K{position}"
    ↓
Arduino moves actuator
    ↓
Arduino sends "DONE" signal
    ↓
enable_actuator_controls()   # Unlock after 200ms delay
    ↓
Ready for next movement
```

### Double-Click Protection

**Fixed Issues:**
- Added `actuator_command_in_progress` flag
- Single timer instance management
- Safety checks in `move_actuator()`
- Proper state transition after Arduino completes

---

## Appendix B: Communication Protocol Details

### Arduino Status Message Format

```
STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END

Example:
STATUS_START|S|500|800|0|45.3|STATUS_END
```

Where:
- `posA` - Axial actuator position
- `posB` - Horizontal actuator position
- `posC` - Lateral actuator position
- `pressure` - Current pressure in lbs

### Command Reference

| Command | Format | Example | Purpose |
|---------|--------|---------|---------|
| Pressure | `P<value>` | `P50` | Set pressure to 50 lbs |
| Axial Position | `A<id><inches>` | `A122.5` | Move axial to 2.5 inches |
| Lateral Position | `K<position>` | `K1500` | Move lateral to position 1500 |
| Status Request | `S` | `S` | Request current status |
| Emergency Stop | `X` | `X` | Stop all motors immediately |
| Reset | `Y<code>` | `Y12` | Reset device |
| High-Freq Mode | `HF1` / `HF0` | `HF1` | Enable/disable fast updates |

---

## Appendix C: Calibration Guide

### Load Cell Calibration

1. Zero the load cell (tare):
   ```arduino
   scale.tare();
   ```

2. Apply known weight (e.g., 10 lbs)

3. Calculate calibration factor:
   ```arduino
   calibration_factor = reading / known_weight
   ```

4. Update in `kneespa.cfg`:
   ```ini
   calibration = -4360.14
   ```

### Actuator Position Calibration

**CMarks (Lateral Angle-to-Position Mapping):**

1. Move actuator to known angle
2. Record position value from Arduino
3. Add to configuration:
   ```ini
   [CMarks]
   -20.0 = 150
   -10.0 = 720
   0.0 = 0
   10.0 = 1900
   20.0 = 2150
   ```

4. System interpolates between defined points for intermediate angles

---

## Support & Contributing

### For Issues

1. Check debug output: `python main/kneespa.py --debug --print-logs`
2. Review log files in `logs/` directory
3. Verify all dependencies installed correctly
4. Ensure hardware connections are secure

### Development Workflow

1. Create feature branch from `refactor-architecture`
2. Make changes with proper testing
3. Update documentation as needed
4. Submit pull request with detailed description

### Important Notes

- **Do not commit `.env` files** to version control
- **Test all changes on non-production hardware first**
- **Get code review for critical safety fixes**
- **Document any new error conditions introduced**

---

## License & Compliance

This is medical device software and must comply with FDA/CE regulatory requirements. All critical bugs must be fixed and thoroughly tested before clinical use.

**Current Status:** Development/Testing - NOT approved for clinical use

---

**Generated:** November 2025
**Project:** DRX-2.0 KneeSpa Rehabilitation System
**Maintainer:** [Project Team]
