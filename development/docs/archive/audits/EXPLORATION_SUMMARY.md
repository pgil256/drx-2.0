# DRX Demo Codebase - Complete Exploration Summary

## Quick Reference: What This Project Does

**KneeSpa Medical Device Control System** - A therapeutic knee rehabilitation device controller that:
- Controls 3 motorized actuators (axial compression, horizontal rotation, lateral flexion)
- Monitors pressure application (0-80 lbs safe range)
- Executes pre-programmed treatment protocols (AC1-AC4)
- Authenticates users via PIN codes
- Displays real-time treatment progress and safety metrics
- Records patient treatment sessions for medical audit trails

---

## Project Structure at a Glance

```
DRX Demo Project (Raspberry Pi based)
│
├─ UI Layer (PyQt5)
│  ├─ Main Window: Protocol selection, actuator control, status display
│  ├─ Login Screen: PIN-based user authentication
│  ├─ Patient Entry: Select patient for treatment
│  ├─ Floating Dialogs: Pressure display, countdown timer
│  └─ Media Assets: Instruction graphics, videos, UI icons
│
├─ Application Logic
│  ├─ KneeSpa (main class): Orchestrates UI, protocols, hardware
│  ├─ Protocols: Multi-stage treatment sequence executor
│  ├─ Configuration: Load/save app settings, calibration data
│  ├─ CSVHelper: Patient/user authentication data
│  └─ Logging: Comprehensive event tracking for medical compliance
│
├─ Hardware Communication
│  ├─ Arduino Interface: Serial communication via /dev/serial0
│  ├─ Command Processor: Send movement/pressure commands
│  ├─ Status Reader: Parse real-time hardware feedback
│  └─ Reset Worker: Multi-step hardware initialization
│
└─ Arduino Firmware
   ├─ Motor Controllers: I2C interface to 3 motor drivers
   ├─ Pressure Sensor: HX711 load cell for force measurement
   ├─ Position Feedback: Read actuator positions
   └─ Emergency Stop: GPIO-based safety shutdown
```

---

## Key Components Explained

### Component 1: User Interface (PyQt5)
**Files:** main/kneespa.py, main/ui/guis/kneespa.ui, dialogs/

The GUI provides:
- Protocol selection (which treatment type: AC1-AC4)
- Parameter configuration (target pressure, angles, duration)
- Real-time monitoring (current pressure, countdown timer, actuator positions)
- Video instruction playback
- Emergency stop button

### Component 2: Treatment Protocol Engine
**File:** main/helpers/protocols.py

Executes multi-stage therapy sequences:
1. Position actuators to starting configuration
2. Apply pressure in incremental steps (e.g., 10, 20, 30 lbs)
3. Move lateral actuators in patterns (left swing, right swing)
4. Hold target pressure for specified duration
5. Optional pulsing mode (rapid on/off cycles)
6. Monitor elapsed time and enforce protocol duration limits

### Component 3: Hardware Communication Layer
**File:** main/helpers/arduino.py

Manages serial communication with Arduino:
- Sends movement and pressure commands
- Reads real-time status updates (positions, pressure)
- Implements connection retry logic
- Rate-limits commands to prevent buffer overflow
- Emits PyQt signals for UI updates

### Component 4: Arduino Microcontroller
**File:** main/motor/motor.ino (889 lines)

Runs on Arduino Uno and controls:
- 3 motor controllers (I2C bus): IDs 12, 13, 14
- HX711 load cell: Pressure measurement
- Emergency stop input (GPIO pin 3)
- External actuator control (pins 4, 5, 9)
- Status reporting (position and pressure feedback)

### Component 5: Configuration Management
**Files:** main/config/constants.py, config.py, kneespa.cfg

Stores and manages:
- Hardware limits (pressure max, angle ranges)
- Calibration factors (position conversion multipliers)
- Actuator angle-to-position mappings
- Patient tolerance settings
- Application settings (logging level, timeouts)

---

## How It Works: Typical Treatment Session

```
1. USER LOGIN
   └─ User enters PIN
   └─ Validated against user_pins.csv
   └─ User profile loaded

2. PATIENT SELECTION
   └─ Select patient from database
   └─ Load patient tolerance settings
   └─ Display patient history (optional)

3. PROTOCOL SELECTION
   └─ Choose treatment type (AC1, AC2, AC3, AC4)
   └─ Review recommended settings
   └─ Optionally adjust pressure/angles/duration

4. HARDWARE RESET (if needed)
   └─ Arduino performs full reset sequence
   └─ Actuators return to neutral positions
   └─ Load cell tare/zeroed
   └─ Motor controllers initialized

5. PROTOCOL EXECUTION (in worker thread)
   └─ User clicks START
   └─ Pressure dialog opens
   └─ Timer dialog opens
   └─ Protocol sends commands in sequence
   
   └─ Stage 1: Position setup
      └─ Move actuators to starting angles
   
   └─ Stage 2: Pressure application
      └─ Gradually increase pressure: 10, 20, 30, 40 lbs...
      └─ Display updates in real-time
      └─ UI remains responsive
   
   └─ Stage 3: Angle cycles
      └─ Apply lateral flexion patterns
      └─ Move left (e.g., -10°), then right (e.g., +10°)
      └─ May repeat with pulsing enabled
   
   └─ Duration monitoring
      └─ Continue until elapsed time reaches target
      └─ Timer countdown displayed

6. PROTOCOL COMPLETION
   └─ Pressure released to zero
   └─ Actuators return to neutral
   └─ Treatment logged
   └─ Summary displayed to user

7. REPEAT OR EXIT
   └─ User can select new protocol
   └─ Or logout and exit application
```

---

## Thread Safety Issues (Known Problems)

### Issue 1: Unsynchronized Flag Access
**Location:** I2Cstatus variable
- Main thread reads/writes: `self.I2Cstatus = 0 or 1`
- Worker thread reads: `while self.main_window.I2Cstatus == 0`
- **Risk:** Race condition could cause protocol to hang or skip steps

### Issue 2: Protocol Parameter Modification During Execution
**Location:** Protocols class attributes
- UI thread may modify `use_pulse` while worker is reading it
- **Risk:** Actuator behavior becomes inconsistent mid-protocol

### Issue 3: Serial Port State TOCTOU (Time-Of-Check-Time-Of-Use)
**Location:** Arduino.send() method
- Check if connected, then release lock
- Port could close before write attempt
- **Risk:** Crash when sending command during disconnection

### Issue 4: Missing PyQt Signal Definitions
**Location:** Arduino class
- Signal `display_weight_emit` never defined
- **Risk:** Runtime crash when weight data received

---

## File Dependencies Map

```
kneespa.py (main application)
├─ imports config.constants (all hardware limits)
├─ imports config.config.Configuration (load calibration)
├─ imports helpers.arduino.Arduino (serial communication)
├─ imports helpers.protocols.Protocols (protocol executor)
├─ imports helpers.reset_worker.ResetWorker (hardware init)
├─ imports helpers.csv.CSVHelper (patient data)
├─ imports helpers.logging (event logging)
├─ imports ui.dialogs (pressure, timer, video display)
└─ imports ui.widgets.loading_spinner (animation)

protocols.py (protocol executor)
├─ imports helpers.arduino (send commands)
├─ imports config.constants (safety limits)
└─ imports helpers.logging (event tracking)

arduino.py (hardware interface)
├─ imports helpers.logging (error reporting)
└─ PyQt5.QtCore (for signals and threads)

motor.ino (Arduino firmware)
├─ HX711.h (load cell library)
├─ Wire.h (I2C communication)
└─ elapsedMillis.h (timing)
```

---

## Communication Protocols

### Pi to Arduino (Serial, 115200 baud)
```
Command Format: <type><parameters>\n

Examples:
A12 2.5      → Set axial actuator to 2.5 inches
K1500        → Set lateral position to 1500 units
P60          → Set pressure target to 60 lbs
L51602080    → Set zero marks (calibration)
J            → Start jerk motion
JS           → Stop jerk motion
X            → Emergency stop
Y12          → Reset device 12
S            → Request status
HF1          → Enable high-frequency status updates
```

### Arduino to Pi (Serial1, 115200 baud)
```
Status Message:
STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END

Example:
STATUS_START|S|500|800|0|45.3|STATUS_END

Other Responses:
DONE         → Command completed successfully
OK           → Test/verification response
weight|65.2  → Weight measurement response
```

---

## Safety and Compliance Features

### Hardware-Level Safety
- Emergency stop pin (GPIO 16) immediately halts all motors
- Motor controllers have built-in current limiting
- Pressure sensor continuously monitored

### Software-Level Safety
- Maximum pressure enforced: 80 lbs
- Actuator ranges constrained: -20 to +20° lateral, 0 to 4" axial
- Timeouts on all command operations
- Command rate limiting (minimum 200ms between commands)
- Connection verification with periodic test commands

### Medical Compliance
- PIN-based user authentication
- Patient identification for all treatments
- Treatment session logging (timestamp, duration, parameters)
- Audit trail in log files
- Error conditions logged for investigation
- Video instructions for safe operation

---

## Configuration Reference

### main/config/kneespa.cfg

**[Options]**
- `flexion_position`: Reference point for flexion actuator
- `a_factor`, `b_factor`, `c_factor`: Calibration multipliers
- `calibration`: HX711 load cell calibration value (typically negative)
- `unlock`: Admin unlock code for administrative functions

**[AMarks]** - Axial actuator position calibration
```
0.0 = 160    # Maps 0.0 inches to position 160
```

**[BMarks]** - Horizontal actuator calibration
```
0.0 = 80     # Maps 0.0 degrees to position 80
```

**[CMarks]** - Lateral actuator angle-to-position mapping (with interpolation support)
```
-20.0 = 150    # -20 degrees → position 150
-10.0 = 720    # -10 degrees → position 720
0.0 = 0        # Neutral (0 degrees) → position 0
10.0 = 1900    # +10 degrees → position 1900
20.0 = 2150    # +20 degrees → position 2150
```

---

## How to Run the Application

### Prerequisites
```bash
sudo apt-get install python3-pyqt5 python3-serial
pip install pyserial RPi.GPIO python-vlc
# Also need HX711 library installation
```

### Run Application
```bash
# Production mode (full screen, no debug output)
python main/kneespa.py

# Debug mode (windowed, verbose logging)
python main/kneespa.py --debug --print-logs

# With custom config file
python main/kneespa.py --config /path/to/config.cfg
```

### Run Tests
```bash
# All tests
python -m pytest

# Specific category
python -m pytest -m protocol    # Protocol tests only
python -m pytest -m arduino     # Arduino communication tests
python -m pytest -m ui          # UI tests
```

---

## Technology Stack Summary

| Component | Technology | Purpose |
|-----------|-----------|---------|
| GUI Framework | PyQt5 | Cross-platform desktop UI |
| Hardware Platform | Raspberry Pi | Run application, GPIO control |
| Microcontroller | Arduino Uno | Motor/sensor control |
| Serial Comm | pyserial | Pi-Arduino communication |
| Load Cell | HX711 | Pressure measurement |
| Motor Controllers | Pololu SMC | I2C motor control |
| Logging | Python logging module | Event tracking |
| Configuration | ConfigParser | INI-based settings |
| Testing | pytest | Unit and integration tests |

---

## Important Absolute File Paths

```
/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py          (Main app - 2259 lines)
/mnt/c/users/user/desktop/drx-demo-final/main/motor/motor.ino     (Arduino firmware)
/mnt/c/users/user/desktop/drx-demo-final/main/helpers/arduino.py  (Serial interface)
/mnt/c/users/user/desktop/drx-demo-final/main/helpers/protocols.py (Protocol executor)
/mnt/c/users/user/desktop/drx-demo-final/main/config/constants.py  (Configuration constants)
/mnt/c/users/user/desktop/drx-demo-final/main/config/kneespa.cfg   (Runtime config file)
/mnt/c/users/user/desktop/drx-demo-final/main/ui/guis/kneespa.ui   (Main UI design)
```

---

## Next Steps for Development

1. **Fix Thread Safety Issues**
   - Add threading.Lock() for I2Cstatus access
   - Synchronize protocol parameter access
   - Fix TOCTOU vulnerabilities in serial communication

2. **Add Missing Signal Definitions**
   - Define `display_weight_emit` in Arduino class
   - Test weight measurement functionality

3. **Enhance Testing**
   - Add unit tests for protocol execution
   - Integration tests for Arduino communication
   - UI tests for dialog updates

4. **Documentation**
   - API documentation for main classes
   - Hardware calibration guide
   - Treatment protocol specifications

5. **Quality Assurance**
   - Code review for medical device compliance
   - Static analysis for security issues
   - Load testing with extended protocol runs

