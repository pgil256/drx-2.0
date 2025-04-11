# KneeSpa System - Version 2.1

## Overview

KneeSpa is a therapeutic device control application for knee rehabilitation treatments. The system integrates hardware controls for multiple actuators with a user-friendly GUI interface that allows medical practitioners to administer standardized therapeutic protocols.

This documentation provides a comprehensive overview of the system architecture, components, and development guidelines for the DRX-2.1 version.

## Installation
1. Install dependencies:
```
pip install -r requirements.txt
```

2. Connect the KneeSpa hardware device to your computer/Raspberry Pi.

3. Configure the device settings in `config/kneespa.cfg`

## Running the Application
```
python main/kneespa.py
```

## Testing
Run the automated test suite:
```
python -m pytest
```

Run specific test categories:
```
python -m pytest -m unit          # Unit tests only
python -m pytest -m integration   # Integration tests only
python -m pytest -m ui            # UI tests only
```

Generate coverage report:
```
python -m pytest --cov=main tests/
```

Current test coverage:
- Unit tests and integration tests: 51 tests
- Core modules covered: 
  - exceptions (89%)
  - config (83%)
  - worker_signals (100%)
  - Protocol and hardware stubs (21%)

## System Architecture

The KneeSpa system consists of the following major components:

1. **Desktop Application**: A PyQt5-based GUI application running on a Raspberry Pi
2. **Arduino Controller**: Firmware running on an Arduino that directly controls the actuators
3. **Hardware Components**: Multiple actuators, pressure sensors, and safety mechanisms

### Communication Flow

```
User → PyQt5 GUI → Serial Communication → Arduino Controller → Motors/Actuators
                                                             → Pressure Sensors
```

## Physical Components

### Actuators

The system utilizes three primary actuators:

1. **Axial Actuator (A)**: Controls axial flexion with pressure measurement
2. **Horizontal Actuator (B)**: Controls horizontal flexion (measured in degrees)
3. **Lateral Actuator (C)**: Controls lateral flexion angle (measured in degrees)
4. **Extra Actuator (FIT)**: Additional GPIO-controlled actuator for leg length adjustment

### Sensors

* **Pressure Sensor**: HX711-based load cell for measuring pressure during treatment
* **Position Feedback**: Built into each actuator for precise position control

### Safety Features

* Hardware emergency stop button
* Software limits on pressure and movement range
* Actuator stall detection
* Watchdog timer on Arduino

## Software Components

### Main Application

The main application (`kneespa.py`) implements:

* Multi-page UI system with login/authentication
* Protocol selection and execution
* Actuator control interfaces
* Visual feedback for actuator positions
* Patient data management

### Protocol System

The protocol system (`protocols.py`) implements:

* Three standardized therapeutic protocols:
  1. Axial pressure only with static 15-degree flexion
  2. Axial pressure with left lateral flexion
  3. Axial pressure with right lateral flexion
* Customizable pressure levels (10-80 lbs)
* Customizable lateral angle settings (0-20°)
* Optional pulsing/jerking motion
* Protocol duration timing (1-60 minutes)

### Arduino Controller

The Arduino controller (`motor.ino`) implements:

* I2C communication with motor controllers
* Serial communication with Raspberry Pi
* Pressure sensor measurement and calibration
* Position control with feedback
* Emergency stop handling
* Jerking/pulsing motion generation

### Helper Modules

* `arduino.py`: Serial communication interface with error recovery
* `csv.py`: Patient and user data management
* `command_queue.py`: Asynchronous command handling
* `worker_signals.py`: PyQt signal/slot definitions for threaded operations
* `protocol_settings.py`: Protocol parameter management

### Utility Modules

* `logging.py`: Custom logging configuration
* `exceptions.py`: Custom exception hierarchy

## Directory Structure

```
drx-2.1/
├── CLAUDE.md                     # Development guidelines
├── main/                         # Main application code
│   ├── config/                   # Configuration files
│   │   ├── config.py             # Configuration loader
│   │   ├── constants.py          # System constants
│   │   ├── kneespa.cfg           # Configuration file
│   │   └── settings.py           # Settings management
│   ├── data/                     # Data storage
│   │   ├── device_info.txt       # Device information
│   │   ├── patients/             # Patient data
│   │   │   └── patient_pins.csv  # Patient PIN database
│   │   └── users/                # User data
│   │       └── user_pins.csv     # User PIN database
│   ├── helpers/                  # Helper modules
│   │   ├── arduino.py            # Arduino communication
│   │   ├── command_queue.py      # Async command handling
│   │   ├── csv.py                # CSV data handling
│   │   ├── email.py              # Email notifications
│   │   ├── gpio.py               # GPIO interface
│   │   ├── protocols.py          # Protocol implementation
│   │   ├── protocol_settings.py  # Protocol configurations
│   │   └── worker_signals.py     # Threading signals
│   ├── kneespa.py                # Main application
│   ├── logs/                     # Log files
│   ├── motor/                    # Arduino firmware
│   │   └── motor.ino             # Arduino controller code
│   ├── ui/                       # UI components
│   │   ├── dialogs/              # Dialog windows
│   │   ├── guis/                 # UI definition files
│   │   └── media/                # Images and videos
│   └── utils/                    # Utility modules
│       ├── exceptions.py         # Exception handling
│       └── logging.py            # Logging configuration
├── mcp-memory-server/            # Memory caching server
├── rpi_settings/                 # Raspberry Pi configurations
└── tests/                        # Test suites
    ├── fixtures/                 # Test fixtures
    ├── integration/              # Integration tests
    └── unit/                     # Unit tests
```

## Protocol Workflows

### Protocol 1: Axial Pressure

1. Set standard 15-degree flexion angle
2. Start with minimal pressure (10 lbs)
3. Gradually increase to target pressure
4. Apply continuous pulsing if enabled
5. Hold until protocol duration expires
6. Reset actuators to zero position

### Protocol 2: Left Lateral Flexion

1. Set standard 15-degree flexion angle
2. Gradually increase to target pressure
3. Once pressure is stable, apply left lateral angle
4. Apply continuous pulsing if enabled
5. Hold until protocol duration expires
6. Reset actuators to zero position

### Protocol 3: Right Lateral Flexion

1. Set standard 15-degree flexion angle
2. Gradually increase to target pressure
3. Once pressure is stable, apply right lateral angle
4. Apply continuous pulsing if enabled
5. Hold until protocol duration expires
6. Reset actuators to zero position

## User Types and Authentication

* **Admin Users**: Full access to all functions including patient data editing
* **Standard Users**: Access to run protocols but limited editing abilities
* **Guests**: Basic view-only access

Users and patients are authenticated via PIN codes stored in CSV files.

## Hardware Communication

### Serial Protocol

The Raspberry Pi communicates with the Arduino using a serial protocol over UART:

* **Connection**: Hardware serial on the Raspberry Pi (/dev/ttyS0)
* **Baud Rate**: 115200
* **Commands**: Single character followed by parameters
* **Status Format**: `STATUS_START|S|posA|posB|posC|pressure|STATUS_END`

### Command Reference

| Command | Description                  | Parameters              |
|---------|------------------------------|-------------------------|
| T       | Test connection              | None                    |
| Q       | Acknowledge status           | None                    |
| S       | Request status               | None                    |
| P       | Set pressure                 | Target pressure (lbs)   |
| Y       | Reset/restart                | Device ID               |
| X       | Emergency stop               | None                    |
| G       | Get position                 | Device ID               |
| I       | Set absolute position        | Device ID, Position     |
| K       | Set lateral angle            | Position                |
| A       | Set position in inches       | Device ID, Inches       |
| L       | Calibration & measurement    | Stage, Parameters       |
| J       | Jerking motion control       | None or 'S' to stop     |
| F       | External actuator control    | Direction (+,-,F,R,0)   |

## Python-Arduino Integration

### Threading Model

The system uses QThreads to manage Arduino communication asynchronously:

1. Arduino communication runs in a dedicated thread
2. Protocol execution runs in the thread pool
3. UI updates are handled in the main thread
4. Status updates are sent from the thread to the main UI via signals

### Error Handling

The application implements a comprehensive error handling strategy:

1. Custom exception hierarchy in `utils/exceptions.py`
2. Connection recovery mechanisms in `arduino.py`
3. Safety-critical vs. non-critical error classification
4. Automatic emergency stop on critical errors
5. User-friendly error messages with suggested actions

## Safety Mechanisms

### Hardware Safety

* Emergency stop button directly connected to GPIO
* Mechanical limits on actuator travel
* Current monitoring to detect stalls

### Software Safety

* Maximum pressure limits (default 80 lbs)
* Maximum angle limits (default ±20°)
* Timeout protection for actuator movements
* Watchdog timer on Arduino
* Status acknowledgment protocol
* Continuous pressure monitoring

## Current MCP Integration

The current project is linked to an MCP (Memory Caching Protocol) server for state management. The mcp-memory-server directory contains:

* Node.js based memory caching server
* WebSocket communication interface
* Persistent session management

Integration details:
* Server runs alongside the main application
* Provides state persistence across application restarts
* Claude memory support via JSON config files

## Development Guidelines

### Code Style

* Follow PEP 8 standards
* 4 spaces for indentation
* Maximum line length of 100 characters
* Google-style docstrings

### Error Classification

* **Safety-Critical**: Errors that could cause physical harm
* **Functional-Critical**: Errors that prevent basic operation
* **User-Experience**: Errors that impact usability but not function
* **Informational**: Warnings and informational messages

### Testing Strategy

* Unit tests for individual components
* Integration tests for component interactions
* UI tests using mock hardware
* Use fixtures for hardware simulation

## Known Issues & Limitations

1. **Arduino Buffer Overflow**: Large command sequences can overflow the Arduino's buffer
2. **Serial Connection Instability**: Occasional serial port disconnections
3. **Pressure Calibration Drift**: Needs recalibration periodically
4. **UI Scaling Issues**: Font size problems on some displays
5. **C Actuator Stalling**: Lateral actuator can stall when under load

## Future Enhancements

1. **Enhanced Patient Data**: More comprehensive patient records
2. **Protocol Customization**: User-definable protocols
3. **Remote Monitoring**: Network-based monitoring and control
4. **Advanced Analytics**: Treatment outcome tracking
5. **Multiple Device Support**: Managing multiple KneeSpa devices

## System Requirements

* Raspberry Pi 4 or newer
* Arduino Uno or Mega
* Python 3.7+ with PyQt5
* Serial communication enabled on Raspberry Pi
* I2C enabled for motor controllers
* 5V power supply for logic
* 24V power supply for motors

---

# Knowledge Map: System Architecture and Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                      User Interface                     │
│                                                         │
│  ┌───────────┐    ┌────────────┐    ┌───────────────┐  │
│  │ Login/Auth│    │Protocol UI │    │  Setup UI     │  │
│  └─────┬─────┘    └──────┬─────┘    └───────┬───────┘  │
│        │                 │                  │          │
└────────┼─────────────────┼──────────────────┼──────────┘
         │                 │                  │
         ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────┐
│                  Application Logic                      │
│                                                         │
│  ┌───────────┐    ┌────────────┐    ┌───────────────┐  │
│  │ Data      │    │ Protocol   │    │ Config        │  │
│  │ Management│    │ Execution  │    │ Management    │  │
│  └─────┬─────┘    └──────┬─────┘    └───────┬───────┘  │
│        │                 │                  │          │
└────────┼─────────────────┼──────────────────┼──────────┘
         │                 │                  │
         ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────┐
│                Hardware Communication                   │
│                                                         │
│  ┌───────────┐    ┌────────────┐    ┌───────────────┐  │
│  │ Arduino   │    │ GPIO       │    │ Sensor        │  │
│  │ Interface │    │ Controls   │    │ Feedback      │  │
│  └─────┬─────┘    └──────┬─────┘    └───────┬───────┘  │
│        │                 │                  │          │
└────────┼─────────────────┼──────────────────┼──────────┘
         │                 │                  │
         ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────┐
│                   Hardware Layer                        │
│                                                         │
│  ┌───────────┐    ┌────────────┐    ┌───────────────┐  │
│  │ Actuators │    │ Sensors    │    │ Safety        │  │
│  │           │    │            │    │ Mechanisms    │  │
│  └───────────┘    └────────────┘    └───────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

# Protocol Execution Sequence Diagram

```
User                    KneeSpa App                Arduino               Actuators
 │                           │                        │                     │
 │ Select Protocol           │                        │                     │
 │─────────────────────────▶│                        │                     │
 │                           │                        │                     │
 │                           │ Reset Actuators        │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Reset Command       │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │                           │                        │ Status Update       │
 │                           │                        │◀────────────────────│
 │                           │ Status Received        │                     │
 │                           │◀───────────────────────│                     │
 │                           │                        │                     │
 │ Start Protocol            │                        │                     │
 │─────────────────────────▶│                        │                     │
 │                           │                        │                     │
 │                           │ Set Flexion Angle      │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Position Command    │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │                           │ Set Initial Pressure   │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Pressure Command    │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │                           │                        │ Status Update       │
 │                           │                        │◀────────────────────│
 │                           │ Status Received        │                     │
 │                           │◀───────────────────────│                     │
 │                           │                        │                     │
 │                           │ Gradual Pressure Incr. │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Pressure Command    │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │                           │ Optional: Set Lat Angle│                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Position Command    │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │                           │ Optional: Enable Pulse │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Jerk Command        │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │ Wait for Protocol Duration│                        │                     │
 │◀─────────────────────────│                        │                     │
 │                           │                        │                     │
 │                           │ Protocol Complete      │                     │
 │                           │───────────────────────▶│                     │
 │                           │                        │ Reset Command       │
 │                           │                        │────────────────────▶│
 │                           │                        │                     │
 │ Protocol Finished Message │                        │                     │
 │◀─────────────────────────│                        │                     │
 │                           │                        │                     │
```

# Key Classes and Relationships

```
┌─────────────────┐     ┌─────────────────┐    ┌──────────────────┐
│    KneeSpa      │◄────┤    Arduino      │    │   Protocols      │
│  (Main Class)   │     │ (Communication) │    │  (Treatment)     │
└────────┬────────┘     └────────┬────────┘    └─────────┬────────┘
         │                       │                       │
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐    ┌──────────────────┐
│  Configuration  │     │ Worker Signals  │    │Protocol Settings │
│   (Settings)    │     │  (Threading)    │    │   (Parameters)   │
└─────────────────┘     └─────────────────┘    └──────────────────┘
         ▲                       ▲                       ▲
         │                       │                       │
         │                       │                       │
┌─────────────────┐     ┌─────────────────┐    ┌──────────────────┐
│   CSVHelper     │     │ Custom Dialogs  │    │    Exceptions    │
│  (Data Access)  │     │   (UI Elements) │    │  (Error Handling)│
└─────────────────┘     └─────────────────┘    └──────────────────┘
```

# Module Dependencies

```
kneespa.py
├── config/
│   ├── config.py
│   ├── constants.py
│   └── settings.py
├── helpers/
│   ├── arduino.py
│   ├── command_queue.py
│   ├── csv.py
│   ├── protocols.py
│   ├── protocol_settings.py
│   └── worker_signals.py
├── ui/
│   ├── dialogs/
│   │   ├── pressure_dialog.py
│   │   ├── timer_dialog.py
│   │   └── video_player.py
│   └── guis/ (.ui files)
└── utils/
    ├── exceptions.py
    └── logging.py
```

---

This documentation serves as a comprehensive guide to the KneeSpa system architecture, components, and development guidelines. It aims to provide developers with the necessary knowledge to understand, maintain, and extend the system.
