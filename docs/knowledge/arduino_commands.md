# Arduino Command Protocol Reference

## Overview

The KneeSpa system communicates with the Arduino controller using a simple serial protocol. This document provides a comprehensive reference for all commands, their parameters, and expected responses.

## Connection Details

- **Port**: Hardware serial on Raspberry Pi (/dev/ttyS0)
- **Baud Rate**: 115200
- **Data Format**: 8N1 (8 data bits, no parity, 1 stop bit)
- **Flow Control**: None
- **Line Ending**: Newline (`\n`)

## Command Format

Commands are sent as ASCII text with the following format:

```
<COMMAND_CHAR>[PARAMETERS]\n
```

Where:
- `COMMAND_CHAR` is a single letter identifying the command
- `PARAMETERS` are optional command-specific parameters
- `\n` is the newline character (ASCII 10)

## Response Format

Responses vary by command but generally follow these formats:

### Standard Command Acknowledgment
```
DONE
```

### Status Response
```
STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END
```

Where:
- `posA`, `posB`, `posC` are integer actuator positions
- `pressure` is a floating-point pressure value in pounds

## Command Reference

### Test Connection (T)

Tests if the Arduino is responding.

- **Format**: `T\n`
- **Parameters**: None
- **Response**: `OK` or `Test command received`
- **Example**: `T\n`

### Status Acknowledgment (Q)

Acknowledges receipt of a status message.

- **Format**: `Q\n`
- **Parameters**: None
- **Response**: None (internal flag is set)
- **Example**: `Q\n`

### Status Request (S)

Requests current status of all actuators and pressure.

- **Format**: `S\n`
- **Parameters**: None
- **Response**: 
  ```
  STATUS_START|S|<posA>|<posB>|<posC>|<pressure>|STATUS_END
  DONE
  ```
- **Example**: `S\n`

### Set Pressure (P)

Sets target pressure for axial actuator.

- **Format**: `P<pressure>\n`
- **Parameters**: 
  - `pressure`: Target pressure in pounds (0-80)
- **Response**: `DONE` (when pressure reached)
- **Example**: `P40\n` (sets pressure to 40 lbs)

### Reset/Restart (Y)

Resets the Arduino controller.

- **Format**: `Y<device_id>\n`
- **Parameters**: 
  - `device_id`: Two-digit device ID (optional)
- **Response**: 
  ```
  Reset|
  DONE
  ```
- **Example**: `Y\n`

### Emergency Stop (X)

Emergency stop for all actuators.

- **Format**: `X\n`
- **Parameters**: None
- **Response**: None (immediate stop action)
- **Example**: `X\n`

### Get Position (G)

Gets current position of a specific actuator.

- **Format**: `G<device_id>\n`
- **Parameters**: 
  - `device_id`: Two-digit device ID
- **Response**: 
  ```
  P|<position>
  DONE
  ```
- **Example**: `G12\n` (gets position of actuator 12)

### Set Absolute Position (I)

Sets absolute position of an actuator.

- **Format**: `I<device_id><position>\n`
- **Parameters**: 
  - `device_id`: Two-digit device ID
  - `position`: Integer position value
- **Response**: `DONE` (when position reached)
- **Example**: `I121000\n` (sets actuator 12 to position 1000)

### Set Lateral Angle (K)

Sets lateral flexion angle position.

- **Format**: `K<position>\n`
- **Parameters**: 
  - `position`: Integer position value
- **Response**: `DONE` (when position reached)
- **Example**: `K1500\n` (sets lateral actuator to position 1500)

### Set Position in Inches (A)

Sets position of an actuator in inches.

- **Format**: `A<device_id><inches>\n`
- **Parameters**: 
  - `device_id`: Two-digit device ID
  - `inches`: Float value in inches
- **Response**: `DONE` (when position reached)
- **Example**: `A122.5\n` (sets actuator 12 to 2.5 inches)

### Calibration & Measurement (L)

Performs calibration and measurement operations.

- **Format**: `L<stage>[parameters]\n`
- **Parameters**: 
  - `stage`: Single-digit stage number (0-6)
  - `parameters`: Additional parameters based on stage
- **Response**: Varies by stage
- **Examples**:
  - `L0-28369.0\n` (calibration factor setting)
  - `L5098 123\n` (set zero marks for A and B actuators)

### Jerking Motion Control (J)

Controls jerking/pulsing motion.

- **Format**: `J[S]\n`
- **Parameters**: 
  - `S`: Optional parameter to stop jerking
- **Response**: `DONE`
- **Examples**:
  - `J\n` (start jerking)
  - `JS\n` (stop jerking)

### External Actuator Control (F)

Controls external actuator movement.

- **Format**: `F<direction>\n`
- **Parameters**: 
  - `direction`: One of `+`, `-`, `F`, `R`, or `0`
    - `+`: Forward (slow)
    - `-`: Reverse (slow)
    - `F`: Forward (fast)
    - `R`: Reverse (fast)
    - `0`: Stop
- **Response**: `DONE`
- **Example**: `F+\n` (slow forward movement)

## Error Handling

The Arduino controller has limited error-handling capabilities. When errors occur, they may not be explicitly reported. The Python application is expected to implement timeout mechanisms and error recovery.

Common error scenarios:

- **Communication timeout**: No response within expected timeframe
- **Incomplete data**: Partial or corrupted serial data
- **Buffer overflow**: Command buffer overflow (max 24 characters)
- **Invalid command**: Unrecognized command character
- **Invalid parameters**: Parameters out of range or invalid format

## Status Monitoring

To ensure reliable operation, the application should:

1. Send periodic status requests (`S`)
2. Acknowledge each status message (`Q`)
3. Monitor for status timeouts
4. Implement reconnection logic for communication failures

## Safety Considerations

Critical safety commands:

- **Emergency Stop (X)**: Should always be processed immediately
- **Status Request (S)**: Used to monitor position and pressure
- **Reset/Restart (Y)**: Used to recover from error states

The Arduino implements internal safety checks, but the application should maintain its own safety monitoring and limits.
