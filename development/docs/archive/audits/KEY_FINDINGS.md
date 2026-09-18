# KneeSpa System - Key Findings

## Executive Summary

KneeSpa is a medical device control system for automated knee rehabilitation therapy. It consists of a Raspberry Pi 4 running a PyQt5 application that controls an Arduino-based motor system with three actuators for multi-axis knee movement and pressure-based therapy protocols.

## System Architecture

### Hardware Components

1. **Raspberry Pi 4**
   - Runs the main application
   - Hosts PyQt5 GUI
   - Manages patient data and protocols
   - Communicates with Arduino via serial

2. **Arduino Controller**
   - Controls 3 actuators (Axial, Horizontal, Lateral)
   - Integrates HX711 load cell for pressure sensing
   - Implements safety features and emergency stop
   - Uses I2C for motor control (SMC device #13)

3. **Actuators**
   - **Axial**: 0-4 inches vertical movement
   - **Horizontal**: -25° to +5° flexion/extension
   - **Lateral**: -20° to +20° side-to-side movement

### Software Architecture

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

## Critical System Components

### 1. Communication Protocol

- **Serial Configuration**: 9600 baud, /dev/serial0
- **Command Format**:
  - Axial: `A[actuator_id][inches]` (e.g., "A122.5")
  - Horizontal: `B[degrees]` (e.g., "B-15")
  - Lateral: `K[degrees]` (e.g., "K10")
  - Pressure: `P[pounds]` (e.g., "P50")
  - Status: `S` (returns position and pressure)

### 2. Safety Systems

- **Hardware Emergency Stop**: GPIO Pin 16
- **Pressure Limits**: Maximum 80 lbs
- **Position Limits**: Enforced in both software and firmware
- **Connection Monitoring**: Auto-recovery on disconnect
- **Watchdog Timer**: Arduino resets on prolonged inactivity

### 3. Protocol System

Four pre-programmed therapy protocols (AC1-AC4):
- Time-based sessions (configurable duration)
- Pressure-based progression
- Pulse/oscillation modes
- Real-time monitoring and adjustment

### 4. Threading Model

- **Main Thread**: GUI and user interaction
- **Arduino Reader Thread**: Continuous serial monitoring
- **Protocol Thread**: QRunnable for treatment execution
- **Reset Worker Thread**: Emergency stop handling

## Key Files and Their Purposes

### Core Application
- `main/kneespa.py` - Main application entry, UI management
- `main/kneespa_app_di.py` - Dependency injection version (appears to be newer architecture)

### Configuration
- `main/config/constants.py` - System constants, limits, paths
- `main/config/config.py` - Configuration management
- `main/config/kneespa.cfg` - Calibration values for actuators

### Hardware Interface
- `main/helpers/arduino.py` - Serial communication handler
- `main/motor/motor.ino` - Arduino firmware

### Business Logic
- `main/helpers/protocols.py` - Treatment protocol implementation
- `main/helpers/csv.py` - Patient data management
- `main/helpers/reset_worker.py` - Emergency stop handler

### User Interface
- `main/ui/guis/kneespa.ui` - Main UI definition (172KB)
- `main/ui/dialogs/pressure_dialog.py` - Real-time pressure display
- `main/ui/dialogs/timer_dialog.py` - Session timer
- `main/ui/dialogs/video_player.py` - Instructional video player

## Critical Calibration Values

From `kneespa.cfg`:
```ini
flexion_position = 1978
a_factor = 3640       # Axial actuator calibration
b_factor = 3640       # Horizontal actuator calibration
c_factor = 3640       # Lateral actuator calibration
calibration = -28369.0 # Load cell calibration
```

## Known System States

### Git Status Analysis
- Multiple files deleted (docs/, tests/, etc.)
- New modular architecture files added (modules/core/, modules/data/)
- Configuration files modified
- Several untracked analysis files (security, bugs, etc.)

### Potential Issues Identified

1. **Thread Safety**: Multiple threads accessing serial communication
2. **GPIO Cleanup**: Needs proper cleanup on exit
3. **Connection Recovery**: Auto-reconnect mechanism in place
4. **Buffer Management**: Arduino buffer overflow protection implemented

## Communication Flow

1. **Command Flow**:
   ```
   UI Event → Command Generation → Serial Write → Arduino Processing
   ```

2. **Status Flow**:
   ```
   Arduino Status → Serial Read → Signal Emission → UI Update
   ```

3. **Protocol Execution**:
   ```
   Protocol Start → Position Commands → Pressure Monitoring → Duration Check → Protocol Complete
   ```

## Development Considerations

### Dependencies
- PyQt5 - GUI framework
- RPi.GPIO - Raspberry Pi GPIO control
- pyserial - Serial communication
- HX711 library (Arduino) - Load cell interface

### Platform Specifics
- Designed for Raspberry Pi 4 with Raspbian Buster
- Requires Python 3.7 compatibility
- Serial getty service must be disabled on /dev/serial0
- Requires proper GPIO permissions

### Testing Categories
- Unit tests - Core logic
- Integration tests - Component interaction
- UI tests - GUI functionality
- Arduino tests - Hardware communication
- Protocol tests - Treatment sequences
- Actuator tests - Movement control

## Security Considerations

- Patient data stored in CSV files (potential HIPAA concerns)
- No apparent encryption for sensitive data
- GPIO pins directly accessible
- Serial communication unencrypted

## Performance Characteristics

- Serial communication at 9600 baud
- Status updates every 5 seconds (normal mode)
- High-frequency mode available (1-second updates)
- Arduino buffer size: 64 bytes
- Command throttling: 200ms minimum interval

## Maintenance Notes

- Calibration values in config file need periodic adjustment
- Arduino firmware version: "2025-03-20"
- Load cell calibration factor: -4360.14
- Multiple unused graphic files in UI directory
- Legacy code present (commented sections)

## Future Improvements Suggested

1. Implement proper data encryption for patient information
2. Add comprehensive error recovery mechanisms
3. Improve thread synchronization
4. Implement data backup system
5. Add remote monitoring capabilities
6. Enhance logging with rotation
7. Add unit test coverage
8. Implement configuration validation