# Load Cell Scale Troubleshooting Guide

## Problem: Scale Jumping to 1923.3 then Staying at 0

This is a common issue indicating connection or initialization problems.

## Quick Fix Procedure

### 1. Upload and Run Diagnostic Script
```bash
# Upload scale.ino to Arduino
# Open Serial Monitor at 115200 baud
# The script will auto-diagnose on startup
```

### 2. Run Connection Test First
Type `X` in Serial Monitor to check connections. Look for:
- ✓ HX711 Ready
- ✓ Receiving data
- ✓ Stable readings

### 3. If Connection Test Fails

#### Check Physical Connections:

**HX711 to Arduino:**
| HX711 Pin | Arduino Pin | Wire Color |
|-----------|-------------|------------|
| VCC | 5V | Red |
| GND | GND | Black |
| DT/DOUT | Pin 7 | Yellow/White |
| SCK/CLK | Pin 6 | Green/Blue |

**Load Cell to HX711:**
| Load Cell Wire | HX711 Terminal | Standard Color |
|----------------|----------------|----------------|
| Excitation+ | E+ | Red |
| Excitation- | E- | Black |
| Signal+ | A+ | Green |
| Signal- | A- | White |

### 4. Common Causes and Solutions

#### Issue: Jumps to High Value (1923.3) Then 0

**Cause 1: Loose DOUT Connection**
- Symptom: Intermittent high readings
- Fix: Secure connection on Pin 7
- Test: Run `S` (stability test)

**Cause 2: Power Supply Issue**
- Symptom: Readings drop to 0 under load
- Fix: Ensure stable 5V supply
- Test: Check with multimeter

**Cause 3: Damaged HX711**
- Symptom: No recovery after reconnection
- Fix: Replace HX711 module
- Test: Try different HX711

#### Issue: Always Reads 0

**Cause 1: Load Cell Not Connected**
- Fix: Check A+/A- connections
- Test: Measure resistance between signal wires (should be ~350-1000Ω)

**Cause 2: Wrong Pin Assignment**
- Fix: Verify DOUT=7, SCK=6
- Test: Try swapping pins in code

**Cause 3: HX711 Not Initialized**
- Fix: Power cycle Arduino
- Test: Run `X` command

## Step-by-Step Diagnostic Process

### Step 1: Basic Test
```
R    # Read single value
```
Look for raw ADC value. Should be non-zero.

### Step 2: Check Stability
```
S    # Run stability test
```
Should show consistent readings with low standard deviation.

### Step 3: Monitor Continuously
```
C    # Toggle continuous mode
```
Watch for pattern:
- Consistent zeros = connection issue
- Jumping values = loose wire
- Gradual drift = temperature/EMI

### Step 4: Test Raw Values
```
W    # Toggle raw mode
C    # Start continuous
```
Raw values should be:
- Normal range: 100,000 to 8,000,000
- Problem if: 0, -1, or 8388607

## Recovery Procedures

### Procedure A: Basic Reset
1. `T` - Tare the scale
2. `R` - Read value
3. If still bad, continue to Procedure B

### Procedure B: Full Reinitialize
1. Disconnect Arduino power
2. Check all connections
3. Reconnect power
4. Upload scale.ino
5. Run `X` to verify

### Procedure C: Calibration Recovery
1. Remove all weight
2. `T` - Tare
3. `A` - Auto-calibrate
4. Follow prompts with known weight

## Testing Commands Reference

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `X` | Check connections | First step always |
| `R` | Read single value | Basic functionality test |
| `S` | Stability test | Check for loose wires |
| `C` | Continuous mode | Monitor behavior |
| `W` | Raw ADC values | Deep diagnostics |
| `T` | Tare/zero | After fixing connections |
| `A` | Auto-calibrate | After hardware fixes |
| `I` | Show info | Check current state |

## Expected Good Values

**Raw ADC Reading:**
- No load (tared): Near 0
- With load: 100,000 to 8,000,000
- Bad: 0, -1, 8388607, -8388608

**Calibrated Weight:**
- Expected range: 0-80 lbs
- Stable to ±0.1 lbs
- Bad: Jumping >1 lb, always 0

**Calibration Factor:**
- Typical: -4000 to -5000
- From motor.ino: -4360.14

## Hardware Checks

### Multimeter Tests

**Load Cell Resistance:**
- Between RED-BLACK: ~400Ω (excitation)
- Between WHITE-GREEN: ~350Ω (signal)
- Between any color and shield: >1MΩ

**HX711 Voltages:**
- VCC to GND: 5V ±0.25V
- E+ to E-: ~4.3V (excitation)
- DOUT: Pulses 0-5V when reading

### Visual Inspection
- [ ] No frayed wires
- [ ] Solid solder joints
- [ ] No corrosion on terminals
- [ ] Load cell not physically damaged
- [ ] HX711 chip not overheated

## Emergency Workaround

If scale won't stabilize, temporarily bypass in code:

```cpp
// In motor.ino, force pressure to safe value:
pressure = 0;  // Disables pressure reading
// OR
pressure = 10; // Sets constant safe pressure
```

**WARNING:** Only use workaround for testing motors, not actual operation!

## When to Replace Components

**Replace HX711 if:**
- X command shows "Not responding"
- Raw values always 8388607 or -8388608
- Chip gets hot during operation

**Replace Load Cell if:**
- Resistance measurements out of spec
- Physical damage visible
- Readings change with wire movement

**Replace Wiring if:**
- Intermittent connections
- Readings change when wires moved
- Visible damage or corrosion

## Contact Support

If issue persists after all troubleshooting:
1. Record output of commands: X, I, S, R
2. Note which fixes were attempted
3. Check if issue started after specific event
4. Document any error patterns