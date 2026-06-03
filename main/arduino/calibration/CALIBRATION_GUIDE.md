# Actuator Calibration Guide for KneeSpa

## Overview
The `calibration.ino` script helps you calibrate and record actuator positions for the KneeSpa system. It allows precise measurement and recording of positions for all three actuators, then exports the data in the correct format for `kneespa.cfg`.

## Hardware Setup

### Required Equipment
- Arduino Mega 2560
- USB cable for Arduino programming
- Actuators connected to motor controllers (IDs 12, 13, 14)
- Measuring tools:
  - Ruler or caliper for axial (A) actuator (0-4 inches)
  - Protractor or angle gauge for horizontal (B) and lateral (C) actuators
- Emergency stop button connected to pin 3

### Actuator Assignments
- **Actuator A (ID 12)**: Axial movement (0-4 inches)
- **Actuator B (ID 13)**: Horizontal rotation (-25 to +5 degrees)
- **Actuator C (ID 14)**: Lateral flexion (-20 to +20 degrees)

## Installation

1. **Upload the Calibration Script**
   ```bash
   # Open Arduino IDE
   # Select Tools > Board > Arduino Mega 2560
   # Select correct COM port
   # Open calibration.ino
   # Click Upload
   ```

2. **Open Serial Monitor**
   - Set baud rate to **115200**
   - Set line ending to "Newline"
   - You should see the startup message

## Calibration Commands

### Movement Commands
| Command | Description |
|---------|-------------|
| `A+` | Move axial actuator forward |
| `A-` | Move axial actuator backward |
| `B+` | Move horizontal actuator forward |
| `B-` | Move horizontal actuator backward |
| `C+` | Move lateral actuator forward |
| `C-` | Move lateral actuator backward |
| `S` | **STOP** all movement immediately |

### Position Commands
| Command | Description | Example |
|---------|-------------|---------|
| `P` | Print current positions | `P` |
| `G A <pos>` | Go to specific A position | `G A 500` |
| `G B <pos>` | Go to specific B position | `G B 1000` |
| `G C <pos>` | Go to specific C position | `G C 1400` |

### Calibration Commands
| Command | Description | Example |
|---------|-------------|---------|
| `R A` | Record A position | See procedure below |
| `R B` | Record B position | See procedure below |
| `R C` | Record C position | See procedure below |
| `Z A` | Set current as zero for A | `Z A` |
| `Z B` | Set current as zero for B | `Z B` |
| `Z C` | Set current as zero for C | `Z C` |

### Speed Control
| Command | Description | Example |
|---------|-------------|---------|
| `M A <speed>` | Set A speed (100-3200) | `M A 800` |
| `M B <speed>` | Set B speed (100-3200) | `M B 800` |
| `M C <speed>` | Set C speed (100-3200) | `M C 800` |

### Export & Help
| Command | Description |
|---------|-------------|
| `E` | Export calibration data |
| `H` | Show help menu |

## Step-by-Step Calibration Procedure

### 1. Set Zero Positions

For each actuator, move it to its mechanical zero/home position:

```
# Move A to fully retracted position
A-
# When at zero, type:
Z A

# Move B to neutral/center position
# Use B+ or B- to position
Z B

# Move C to center (0 degrees)
# Use C+ or C- to position
Z C
```

### 2. Calibrate Axial Actuator (A)

Record positions at multiple extension points:

```
# Move to 0.5 inches extension
A+
# Stop when at 0.5 inches
S
# Record the position
R A
# Enter the measurement when prompted
0.5

# Move to 1.0 inches
A+
S
R A
1.0

# Continue for 1.5, 2.0, 2.5, 3.0, 3.5, 4.0 inches
```

### 3. Calibrate Horizontal Actuator (B)

Record positions at key angles:

```
# Move to -25 degrees
B-
S
R B
-25

# Move to -15 degrees
B+
S
R B
-15

# Continue for -5, 0, +5 degrees
```

### 4. Calibrate Lateral Actuator (C)

This requires the most calibration points:

```
# Start at -20 degrees
C-
S
R C
-20

# Record every 2.5 degrees:
# -17.5, -15, -12.5, -10, -7.5, -5, -2.5, 0,
# +2.5, +5, +7.5, +10, +12.5, +15, +17.5, +20
```

### 5. Export Calibration Data

After recording all positions:

```
E
```

This will output formatted data like:

```
[Options]
a_factor = 430
b_factor = 620
c_factor = 94

[AMarks]
0.0 = 160
0.5 = 375
1.0 = 590
...

[BMarks]
0.0 = 80
-25.0 = 15500
...

[CMarks]
-20.0 = 150
-17.5 = 292
...
```

### 6. Update kneespa.cfg

1. Copy the exported sections
2. Open `main/config/kneespa.cfg`
3. Replace the corresponding sections
4. Save the file

## Tips and Best Practices

### Accuracy Tips
- **Allow settling time**: After moving, wait 1-2 seconds before recording
- **Use consistent measurement points**: Same physical reference for each measurement
- **Multiple samples**: Record each position 2-3 times and average if needed
- **Slow speeds for precision**: Use `M A 400` for fine positioning

### Safety Guidelines
- **Always have emergency stop ready**: Pin 3 or type 'S'
- **Start with slow speeds**: Default 800, reduce to 400 for precision
- **Check mechanical limits**: Don't force beyond physical stops
- **Monitor current draw**: Excessive current indicates binding

### Troubleshooting

**Motor won't move:**
- Check I2C connections (SDA/SCL)
- Verify motor controller power
- Try exit safe start: Restart Arduino

**Position readings are 0:**
- Check encoder connections
- Verify motor controller ID (12, 13, or 14)
- Add delay between movements

**Erratic positions:**
- Reduce speed (`M A 400`)
- Check for mechanical binding
- Clean encoder disc if optical

## Example Full Calibration Session

```
# Start calibration
H                    # Show help

# Set zeros
A-                   # Move to minimum
Z A                  # Set as zero
B-                   # Move to center
Z B                  # Set as zero
C-                   # Move to center
Z C                  # Set as zero

# Calibrate A (axial)
A+                   # Move forward
S                    # Stop at 1 inch
R A                  # Record
1.0                  # Enter measurement
A+                   # Continue to 2 inches
S
R A
2.0
# ... continue for all measurements

# Calibrate B and C similarly

# Export when done
E                    # Export configuration

# Copy output to kneespa.cfg
```

## Configuration File Format

The exported data updates these sections in `kneespa.cfg`:

```ini
[Options]
a_factor = 430       # Steps per inch for A
b_factor = 620       # Steps per degree for B
c_factor = 94        # Steps per degree for C

[AMarks]
0.0 = 160           # Position at 0 inches

[BMarks]
0.0 = 80            # Position at 0 degrees

[CMarks]
-20.0 = 150         # Position at -20 degrees
0.0 = 1400          # Position at 0 degrees
20.0 = 2150         # Position at +20 degrees
```

## Quick Reference Card

```
EMERGENCY STOP: S or Pin 3

Move:  A+  A-  B+  B-  C+  C-
Stop:  S
Show:  P (positions)  H (help)

Record Position:
  1. Move to position (A+/-)
  2. Type: R A
  3. Enter measurement: 2.5

Set Zero: Z A  Z B  Z C
Export:   E

Go To:    G A 500
Speed:    M A 800
```

## Notes

- The script calculates factors automatically based on recorded positions
- More calibration points = better accuracy
- Factors are averaged across all measurement pairs
- Always test movements after updating kneespa.cfg
- Keep backup of working configuration before changes