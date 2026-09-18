# DRX Demo Codebase Exploration Report

**Date:** November 8, 2025
**Project:** KneeSpa Control System (DRX Medical Device)
**Repository:** /mnt/c/users/user/desktop/drx-demo-final

---

## Executive Summary

The DRX Demo project is a **PyQt5-based medical device control application** designed to manage and control therapeutic knee equipment called "KneeSpa". The system communicates with an Arduino microcontroller to manage three motorized actuators (axial, horizontal, and lateral), monitor patient pressure application, and execute calibrated treatment protocols. The codebase is designed to run on a Raspberry Pi with GPIO control and serial communication to Arduino.

**Key Characteristics:**
- Medical device control software (patient safety critical)
- Multi-threaded PyQt5 GUI application
- Real-time hardware communication with Arduino via serial
- Treatment protocol execution system
- User authentication and patient data management
- Video playback and instructional support

---

## Directory Structure and Project Organization

```
/mnt/c/users/user/desktop/drx-demo-final/
├── main/                          # Primary application code
│   ├── kneespa.py                # Main application entry point (2259 lines)
│   ├── kneespa_app_di.py          # Dependency injection configuration
│   ├── config/                    # Configuration management
│   │   ├── config.py              # Dynamic configuration loader
│   │   ├── constants.py           # App-wide constants and settings
│   │   └── kneespa.cfg            # Runtime configuration file
│   ├── helpers/                   # Core helper modules
│   │   ├── arduino.py             # Serial communication with Arduino
│   │   ├── protocols.py           # Treatment protocol executor
│   │   ├── csv.py                 # User/patient data loading
│   │   ├── reset_worker.py        # Hardware reset sequence worker
│   │   └── logging.py             # Application logging framework
│   ├── ui/                        # User interface components
│   │   ├── main.py                # UI initialization (if separate)
│   │   ├── guis/                  # Qt Designer UI files
│   │   │   ├── kneespa.ui         # Main application UI (169 KB)
│   │   │   ├── login.ui           # User login screen
│   │   │   ├── enter-patient.ui   # Patient entry form
│   │   │   ├── video-player.ui    # Video playback interface
│   │   │   └── enter-tolerance.ui # Patient tolerance setup
│   │   ├── dialogs/               # Dialog windows
│   │   │   ├── pressure_dialog.py # Real-time pressure display
│   │   │   ├── timer_dialog.py    # Protocol countdown timer
│   │   │   └── video_player.py    # Video playback handler
│   │   ├── widgets/               # Custom widgets
│   │   │   └── loading_spinner.py # Loading animation
│   │   └── media/                 # UI assets
│   │       ├── images/            # Icons, graphics, logos
│   │       ├── buttons/           # Control button icons
│   │       ├── graphics/          # Protocol instruction graphics
│   │       ├── logos/             # DRX and KneeSpa logos
│   │       ├── spinners/          # Loading animations
│   │       └── videos/            # Instructional videos
│   ├── motor/                     # Arduino firmware
│   │   └── motor.ino              # Arduino microcontroller code
│   ├── data/                      # Patient/user data files
│   │   ├── user_pins.csv          # User authentication database
│   │   └── patients/              # Patient records
│   ├── calibrate/                 # Calibration utilities
│   └── logs/                      # Application logs
│
├── tests/                         # Test suite (deleted from index)
├── rpi_settings/                  # Raspberry Pi configuration
├── docs/                          # Documentation (deleted from index)
├── CLAUDE.md                      # Claude AI guidelines
├── BUG_ANALYSIS_REPORT.md         # Bug analysis documentation
├── THREAD_SAFETY_ANALYSIS.md      # Concurrency issue analysis
└── [other config files]

```

---

## Application Purpose and Architecture

### Primary Purpose
**Medical Device Control System** for knee rehabilitation and physical therapy. The KneeSpa apparatus provides:
- Axial flexion/compression (up to 4 inches)
- Horizontal positioning (up to 25 degrees rotation)
- Lateral knee flexion (-20 to +20 degrees)
- Pressure application monitoring (up to 80 lbs safe limit)

### Core Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 PyQt5 GUI (Main Thread)                      │
│  - User login and authentication                             │
│  - Patient selection and profile                             │
│  - Protocol selection and parameter configuration            │
│  - Real-time status displays (pressure, timer, position)     │
│  - Video instruction playback                                │
└──────────────────┬──────────────────────────────────────────┘
                   │ Signals
                   ▼
┌─────────────────────────────────────────────────────────────┐
│          Protocol/Worker Threads (QRunnable)                 │
│  - Protocols: Execute multi-stage treatment sequences        │
│  - ResetWorker: Handle hardware initialization              │
│  - Status monitoring and feedback                            │
└──────────────────┬──────────────────────────────────────────┘
                   │ Serial Commands
                   ▼
┌─────────────────────────────────────────────────────────────┐
│            Arduino Communication (QObject)                   │
│  - Serial port management (/dev/serial0)                     │
│  - Command transmission to Arduino                           │
│  - Real-time status reading (position, pressure)             │
│  - Connection verification                                   │
└──────────────────┬──────────────────────────────────────────┘
                   │ Serial Data
                   ▼
┌─────────────────────────────────────────────────────────────┐
│          Arduino Uno Microcontroller                         │
│  - I2C motor controller interface                            │
│  - HX711 load cell (pressure sensor)                         │
│  - Motor speed/direction control                             │
│  - Position feedback reading                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Key Python Modules and Their Purposes

### 1. **main/kneespa.py** (2259 lines)
**Role:** Primary application class and UI coordinator

**Key Classes:**
- `KneeSpa(QMainWindow)` - Main application window inheriting from PyQt5's main window

**Major Responsibilities:**
- Application initialization and UI setup
- User authentication and login management
- Patient selection and data management
- Protocol selection and parameter configuration
- Hardware reset sequence coordination
- Real-time status monitoring and display
- Actuator control and positioning
- Protocol execution orchestration
- Emergency stop functionality

**Key Methods:**
- `__init__(debug_mode)` - Application initialization
- `set_to_distance()` - Move axial actuator to distance
- `set_to_c_distance()` - Move lateral actuator to angle (with interpolation)
- `start_protocol()` - Initialize and execute treatment protocol
- `stop_protocol()` - Halt ongoing treatment
- `reset_devices()` - Full hardware reset sequence
- `enable/disable_actuator_controls()` - Control UI responsiveness
- Various event handlers for UI interactions

**Threading Model:**
- Main thread for UI and user interaction
- Worker threads for protocols and reset operations
- Signal-based communication with workers

---

### 2. **main/helpers/arduino.py**
**Role:** Serial communication interface with Arduino microcontroller

**Key Classes:**
- `Arduino(QObject)` - Serial communication handler

**PyQt5 Signals Emitted:**
- `connection_ready()` - Connection established
- `connection_failed(str)` - Connection attempt failed
- `status_emit(int, int, int, float)` - Position A, B, C and pressure
- `pressure_emit(str)` - Pressure data updates
- `position_emit(int, int, str, int)` - Position feedback
- `done_emit()` - Command completion
- `ready_to_go_emit()` - System ready signal
- `buffer_warning(str)` - Buffer overflow warning
- `connection_lost()` - Connection dropped

**Major Responsibilities:**
- Establish and maintain serial connection to Arduino
- Send commands to Arduino motor controllers
- Parse and emit real-time status updates
- Handle connection errors and reconnection
- Implement command queuing and rate limiting
- Monitor Arduino buffer usage
- Verify connection status with test commands
- DTR-based Arduino reset capability

**Key Methods:**
- `send(command)` - Send command string to Arduino
- `connect()` - Establish serial connection
- `disconnect()` - Close serial connection
- `verify_connection()` - Test connection status
- `release_busy_port()` - Release stuck serial port
- `reset_dtr()` - Reset Arduino via DTR line

**Command Protocol:**
Commands sent to Arduino include:
- `P<pressure>` - Set pressure target
- `A<actuator><inches>` - Position by inches
- `K<position>` - Lateral position control
- `I<actuator><position>` - Position control
- `J`/`JS` - Jerk motion start/stop
- `L<stage><params>` - Calibration and measurement
- `X` - Emergency stop
- `Y<code>` - Reset command
- `S` - Request status
- `G<actuator>` - Get position
- `HF1`/`HF0` - High-frequency status toggle

---

### 3. **main/helpers/protocols.py**
**Role:** Treatment protocol execution engine

**Key Classes:**
- `Protocols(QRunnable)` - Main protocol executor
- `WorkerSignals(QObject)` - Signal definitions for protocol events

**PyQt5 Signals Emitted:**
- `finished(bool)` - Protocol complete or failed
- `stopped(bool)` - Protocol stopped by user
- `error(tuple)` - Error occurred during execution
- `result(object)` - Protocol results
- `progress(str)` - Progress updates
- `pressure_emit(float)` - Pressure status updates
- `status_emit(int, int, int, float)` - Full actuator/pressure status
- `reset_needed()` - Signal requesting hardware reset

**Major Responsibilities:**
- Execute multi-stage treatment protocols (AC1-AC4)
- Manage pressure sequences with increment logic
- Control actuator positioning (axial, horizontal, lateral)
- Monitor elapsed time and enforce duration limits
- Handle pulsing mode (rapid on/off cycles)
- Real-time status monitoring and adjustment
- Protocol parameter validation and enforcement
- Thread-safe communication with Arduino

**Protocol Types Supported:**
- Protocol AC1, AC2, AC3, AC4 (configurable)
- Each protocol has configurable:
  - Maximum pressure (lbs)
  - Left/right lateral angles (degrees)
  - Duration (minutes)
  - Pulsing mode enabled/disabled
  - Pressure increment steps
  - Angle increment steps

**Key Methods:**
- `run()` - Main protocol execution loop
- `run_pressure_sequence()` - Manage pressure ramps
- `set_to_pressure()` - Set target pressure
- `set_to_c_distance()` - Set lateral angle with interpolation
- `update_status()` - Handle Arduino feedback
- `check_duration()` - Monitor elapsed time
- `stop_protocol()` - Signal protocol termination

---

### 4. **main/config/constants.py**
**Role:** Centralized configuration and magic numbers

**Key Constants Defined:**
```python
# Application Info
APP_NAME = "KneeSpa"
APP_VERSION = "2.3"
APP_BASE_DIR = "/home/pi/drx-2.3/main/"

# UI Pages
PAGES = {"HOME": 0, "SETUP": 1, "MAIN": 2, "HELP": 3, "PROFILE": 4}

# Actuator Configuration
ACTUATORS = {
    "AXIAL": {
        "ID": "12",
        "LIMITS": (0, 4),        # inches
        "COMMAND_PREFIX": "A12",
        "MULTIPLIER": 2,
    },
    "HORIZONTAL": {
        "ID": "13",
        "LIMITS": (-25, 5),      # degrees
        "COMMAND_PREFIX": "B",
        "MULTIPLIER": 1,
    },
    "LATERAL": {
        "ID": "14",
        "LIMITS": (-20, 20),     # degrees
        "COMMAND_PREFIX": "K",
        "MULTIPLIER": 1,
    },
}

# Safety Limits
PRESSURE_MAX = 80                # lbs
AXIAL_MAX = 4600                 # units
LATERAL_MIN = 500, LATERAL_MAX = 2400
HORIZONTAL_MIN = 50, HORIZONTAL_MAX = 4500

# Arduino Communication
ARDUINO_SETTINGS = {
    "CALIBRATION_DELAY": 2000,   # ms
    "COMMAND_DELAY": 1500,       # ms
    "ARDUINO_PORT": "/dev/serial0",
    "CONNECTION_TIMEOUT_S": 30,
}

# GPIO Pins
EMERGENCYSTOP = 16
EXTRAFORWARD = 27
EXTRABACKWARD = 22
EXTRAENABLE = 17

# Protocols
PROTOCOL_MAPPING = {
    1: "AC1", 2: "AC2", 3: "AC3", 4: "AC4"
}
```

---

### 5. **main/config/config.py**
**Role:** Runtime configuration management

**Key Classes:**
- `Configuration` - Load and save application configuration

**Configuration File Format:**
INI-style file at `/home/pi/drx-2.3/main/config/kneespa.cfg`

**Sections:**
- `[Options]` - General settings (flexion position, calibration factor, unlock code)
- `[AMarks]` - Axial actuator position calibration points
- `[BMarks]` - Horizontal actuator position calibration points
- `[CMarks]` - Lateral actuator angle-to-position mappings

**Example CMarks:**
```
-20.0 = 150      # -20 degrees -> position 150
-10.0 = 720      # -10 degrees -> position 720
0.0 = 0          # Neutral position
20.0 = 2150      # +20 degrees -> position 2150
```

**Major Responsibilities:**
- Load configuration from file
- Provide type-safe access to settings
- Support default values for missing options
- Update configuration file with changes
- Calibration factor management
- Position mark storage and retrieval

---

### 6. **main/helpers/reset_worker.py**
**Role:** Asynchronous hardware reset sequence execution

**Key Classes:**
- `ResetWorker(QRunnable)` - Multi-step reset executor
- `ResetWorkerSignals(QObject)` - Signal definitions

**Signals:**
- `finished(bool)` - Reset success/failure
- `error(str)` - Error message if reset fails

**Reset Sequence Steps:**
1. Send reset command ('Y') to Arduino
2. Set zero mark reference positions (L5)
3. Reset Actuator C (lateral) to neutral (I14)
4. Reset Actuator B (horizontal) to default (A13)
5. Reset Actuator A (axial) to zero (I12)
6. Send calibration factor (L0)

**Major Responsibilities:**
- Execute multi-step reset without blocking UI
- Handle command timeouts and retries
- Perform DTR-based Arduino reset on failure
- Flag-based command completion detection
- Exception handling and cleanup

---

### 7. **main/helpers/csv.py**
**Role:** Patient and user data management

**Key Classes:**
- `CSVHelper` - CSV file loading and parsing

**Data Sources:**
- User authentication: `/home/pi/drx-2.3/main/data/user_pins.csv`
- Patient records: `/home/pi/drx-2.3/main/data/patients/`

**CSV Format:**
PIN-indexed dictionary storing user credentials and patient information

**Major Responsibilities:**
- Load user authentication data
- Parse patient records
- Provide data access interface
- Handle file not found errors gracefully

---

### 8. **main/ui/dialogs/pressure_dialog.py**
**Role:** Real-time pressure display widget

**Key Class:**
- `PressureDialog(QDialog)` - Floating dialog showing current pressure

**Features:**
- Color-coded pressure indication
  - Green: < 50 lbs
  - Orange: 50-70 lbs
  - Red: >= 70 lbs
- Updates when pressure changes > 0.5 lbs
- Always-on-top floating window
- Formatted display: "Pressure: XX.X lbs"

---

### 9. **main/ui/dialogs/timer_dialog.py**
**Role:** Protocol countdown timer display

**Key Class:**
- `TimerDialog(QDialog)` - Floating timer widget

**Features:**
- Displays remaining protocol time: "HH:MM"
- Color coding based on time remaining
  - Default blue-gray: > 60 seconds
  - Orange: 30-60 seconds
  - Red: < 30 seconds
- Updates from parent window protocol state

---

### 10. **main/ui/widgets/loading_spinner.py**
**Role:** Loading animation widget

**Key Class:**
- `LoadingSpinner(QWidget)` - Animated loading indicator

**Features:**
- Customizable size (default 300px)
- Adjustable animation speed
- Centered display
- Used during Arduino communication and reset operations

---

### 11. **main/helpers/logging.py**
**Role:** Application logging framework

**Key Classes:**
- `LoggerSetup(Singleton)` - Configure and manage logging
- `LoggerAdapter` - Context-aware logger wrapper

**Logging Configuration:**
- Main log: `/home/pi/drx-2.3/main/logs/kneespa.log` (10MB rotating)
- Error log: `/home/pi/drx-2.3/main/logs/error.log` (5MB rotating)
- Debug log: `/home/pi/drx-2.3/main/logs/debug.log` (20MB rotating)
- Console output with simplified formatting

**Features:**
- Singleton pattern for single logger instance
- Component-based logging (add context to messages)
- Qt warning filtering
- Rotating file handlers with backup counts

---

## Arduino Firmware (motor.ino)

**Target:** Arduino Uno microcontroller

**External Libraries:**
- HX711.h - Load cell ADC interface
- elapsedMillis.h - Timing utilities
- Wire.h - I2C communication

**Key Hardware Interfaces:**

1. **I2C Motor Controllers** (three units: 12, 13, 14)
   - Motor speed and direction control
   - Position feedback reading
   - Safe start/exit commands

2. **HX711 Load Cell** (pins 7, 6)
   - Pressure measurement
   - Calibration factor: -4360.14 (can be adjusted)
   - Tare (zero) operation support

3. **GPIO Controls**
   - Pin 3: Emergency stop input
   - Pins 4, 5: Direction control (fit/external actuator)
   - Pin 9: Speed PWM (fit/external actuator)
   - Pins 30, 31: Motor A direction control

**Command Processing:**
Reads serial commands from Raspberry Pi and executes corresponding motor/sensor operations:
- Position control commands (A, I, K)
- Pressure control (P)
- Calibration (L)
- Motion control (J - jerk, F - external actuator)
- Status reporting (S, G, L6)
- Device reset (Y, X)

**Status Reporting:**
Format: `STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END`
Sent at:
- Regular intervals (5 second idle)
- High-frequency intervals (1 second when enabled)
- After command completion

**Features:**
- Rate limiting on command processing (200ms minimum)
- Status acknowledgment mechanism
- Command buffer protection (50 char max)
- Position interpolation for smooth motion
- Jerking motion for therapeutic effect
- Stall detection and timeout handling

---

## Configuration Files

### kneespa.cfg
**Location:** `/home/pi/drx-2.3/main/config/kneespa.cfg`
**Format:** INI (ConfigParser)

**[Options] Section:**
```
flexion_position = 1978          # Axial flexion reference position
a_factor = 3640                  # Calibration multiplier for actuator A
b_factor = 3640                  # Calibration multiplier for actuator B
c_factor = 3640                  # Calibration multiplier for actuator C
unlock = 123                     # Admin unlock code
calibration = -28369.0           # HX711 load cell calibration factor
```

**[AMarks] Section:**
Position calibration points for axial (axial) actuator
```
0.0 = 160    # Zero position (neutral)
```

**[BMarks] Section:**
Position calibration points for horizontal (flexion) actuator
```
0.0 = 80     # Zero position (neutral)
```

**[CMarks] Section:**
Angle-to-position mapping for lateral (side-to-side) actuator
Supports interpolation between defined points:
```
-20.0 = 150   # -20 degrees
-10.0 = 720   # -10 degrees
0.0 = 0       # Neutral (0 degrees)
10.0 = 1900   # +10 degrees
20.0 = 2150   # +20 degrees
```

---

## UI Components and Screens

### Main Application Window (kneespa.ui - 169 KB)
**Central Widget:** "central_widget"
**Pages:**
- HOME (0): Welcome/startup screen
- SETUP (1): Initial configuration
- MAIN (2): Active treatment control
- HELP (3): Help and instructions
- PROFILE (4): User profile management

**Key UI Elements:**
- Protocol selector (AC1-AC4)
- Pressure adjustment controls
- Lateral angle adjustment (left/right)
- Real-time displays
- Emergency stop button
- Start/Stop protocol buttons
- Actuator control buttons

### Login Screen (login.ui)
PIN-based authentication for users

### Patient Entry Screen (enter-patient.ui)
Patient selection and enrollment interface

### Video Player (video-player.ui, video_player.py)
Display instructional videos for protocols

### Dialogs
- **PressureDialog**: Real-time pressure display
- **TimerDialog**: Protocol countdown timer
- **VideoPlayer**: Embedded video playback

---

## Data Flow and Communication Patterns

### Protocol Execution Flow
```
User selects protocol
         ↓
Configure parameters (pressure, angles, duration, pulse mode)
         ↓
Click START
         ↓
KneeSpa.start_protocol() creates Protocols worker
         ↓
QThreadPool executes Protocols.run() in background
         ↓
Protocol sends commands to Arduino via arduino.send()
         ↓
Arduino executes motor control
         ↓
Arduino sends status updates via Serial1
         ↓
Arduino.reader_thread() parses STATUS messages
         ↓
Arduino emits status_emit() PyQt signal
         ↓
Protocol receives via update_status() slot
         ↓
Protocol emits pressure_emit() for dialogs
         ↓
Main UI updates pressure_dialog and timer_dialog
         ↓
Protocol waits for target conditions met
         ↓
Repeat for next stage or complete protocol
```

### Hardware Reset Flow
```
User clicks RESET or system initializes
         ↓
KneeSpa.reset_devices() creates ResetWorker
         ↓
QThreadPool executes ResetWorker.run()
         ↓
Reset steps executed sequentially:
  1. Send 'Y' (reset)
  2. Set zero marks ('L5')
  3. Reset each actuator ('I14', 'A13', 'I12')
  4. Send calibration ('L0')
         ↓
Each step waits for completion (I2Cstatus flag)
         ↓
On timeout, attempt DTR reset and retry
         ↓
signals.finished(bool) emitted
         ↓
KneeSpa handles reset result (success/failure)
```

---

## Safety Systems and Constraints

### Hardware Limits
```
ACTUATOR          MIN        MAX        UNITS
─────────────────────────────────────────────
Axial (A12)       0          4          inches
Horizontal (B13)  -25        5          degrees
Lateral (C14)     -20        20         degrees
Pressure          0          80         lbs
```

### Software Safety Features
1. **Pressure Capping**: All pressure commands limited to 80 lbs
2. **Position Bounds Checking**: All actuator commands constrained to limits
3. **Emergency Stop**: GPIO pin 16 triggers immediate shutdown
4. **Timeout Protection**: Commands have enforced timeouts
5. **Rate Limiting**: Minimum 200ms between commands to Arduino
6. **Buffer Monitoring**: Tracks Arduino serial buffer usage
7. **Connection Verification**: Regular test commands (T) sent

### Medical Device Compliance Features
1. **Patient Identification**: PIN-based user authentication
2. **Protocol Tracking**: Treatment history maintained
3. **Pressure Monitoring**: Real-time display and logging
4. **Video Instructions**: Instructional content for safe operation
5. **Error Logging**: Comprehensive error tracking for audit trails
6. **Tolerance Setup**: Per-patient angle and pressure configuration

---

## Known Issues and Concerns

### Critical Issues (from analysis reports)
1. **Thread Safety**: Unsynchronized flag access (I2Cstatus) between worker threads
2. **Race Conditions**: Protocol parameters can be modified during execution
3. **TOCTOU Vulnerabilities**: Serial port state can change between check and use
4. **Missing Signals**: Some PyQt5 signals not defined (display_weight_emit)
5. **No Mutex Protection**: Shared resources lack proper synchronization

### Identified Risks
- Patient safety impact from unprotected concurrency
- Potential deadlocks in protocol execution
- Serial communication failures during concurrent access
- Reset operations hanging due to flag synchronization

---

## Development and Testing Infrastructure

### Testing Framework
- pytest for unit testing
- Test markers: unit, integration, ui, arduino, protocol, actuator
- Fixtures for Arduino mocking and simulation
- Conftest.py for test configuration

### Logging and Debugging
- Comprehensive logging with rotating file handlers
- Debug log captures all events
- Error log tracks failures
- Console output for real-time monitoring
- Print statements throughout code for diagnostics

### Requirements
- PyQt5 (GUI framework)
- pyserial (Arduino communication)
- RPi.GPIO (Raspberry Pi GPIO)
- python-vlc (Video playback)
- HX711 library (Load cell driver)

---

## Key Files Reference

| File | Lines | Purpose |
|------|-------|---------|
| main/kneespa.py | 2259 | Main application class |
| main/motor/motor.ino | 889 | Arduino firmware |
| main/helpers/protocols.py | ~800 | Protocol execution |
| main/helpers/arduino.py | ~600 | Serial communication |
| main/config/constants.py | 211 | Configuration constants |
| main/ui/guis/kneespa.ui | 169KB | Main UI design |
| main/config/kneespa.cfg | 36 lines | Runtime configuration |

---

## Summary

The DRX KneeSpa system is a sophisticated medical device control application combining:
- **Hardware Control**: Three motorized actuators, pressure sensor, GPIO controls
- **Real-time Communication**: Serial protocol with Arduino microcontroller
- **Patient Management**: User authentication, patient profiling, tolerance configuration
- **Treatment Protocols**: Multi-stage therapy sequences with configurable parameters
- **Safety Systems**: Hardware limits, emergency stops, timeout protection
- **User Interface**: PyQt5-based GUI with video instruction playback
- **Data Persistence**: Configuration files, calibration data, patient records

The codebase demonstrates medical device engineering best practices in terms of modularity, configuration management, and hardware abstraction. However, recent analysis has identified critical thread-safety issues that should be addressed before clinical use.

