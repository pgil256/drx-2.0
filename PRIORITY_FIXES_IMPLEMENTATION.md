# KneeSpa Priority Fixes - Implementation Guide

## IMMEDIATE CRITICAL FIXES (Day 1)

### Fix 1: Pressure Safety Bypass
**File**: `main/kneespa.py`
**Line**: 1600-1613

#### Current Code (DANGEROUS):
```python
def axial_flexion_pressure_go_button_clicked(self):
    self.loading_spinner.show()
    self.disable_actuator_controls()
    pounds = self.ui.axial_flexion_pressure_slider.value()  # NO VALIDATION!
    self.arduino.send(f"P{pounds}")
```

#### Fixed Code:
```python
def axial_flexion_pressure_go_button_clicked(self):
    from config.constants import PRESSURE_MAX, MIN_PRESSURE

    self.loading_spinner.show()
    self.disable_actuator_controls()

    pounds = self.ui.axial_flexion_pressure_slider.value()

    # CRITICAL SAFETY CHECK
    if pounds > PRESSURE_MAX:
        pounds = PRESSURE_MAX
        self.logger.warning(f"Pressure request {pounds} exceeds max {PRESSURE_MAX}, clamping")
        self._show_timed_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
    elif pounds < MIN_PRESSURE:
        pounds = MIN_PRESSURE

    self.arduino.send(f"P{pounds}")
    self.ui.axial_flexion_pressure_slider.setValue(pounds)  # Update UI to show clamped value
```

### Fix 2: Axial Position 100% Overshoot
**File**: `main/kneespa.py`
**Line**: 1265-1298

#### Current Code (WRONG LIMIT):
```python
if inches > 8:  # WRONG! Should be AXIAL_MAX = 4
    inches = 8
    self._show_timed_error("Actuator A input adjusted from {} to 8 inches (max)".format(inches))
```

#### Fixed Code:
```python
from config.constants import AXIAL_MAX

if inches > AXIAL_MAX:
    original_inches = inches
    inches = AXIAL_MAX
    self._show_timed_error(f"Actuator A input adjusted from {original_inches} to {AXIAL_MAX} inches (max)")
```

### Fix 3: Division by Zero - Calibration Factors
**File**: `main/kneespa.py`
**Line**: 1645-1665

#### Current Code (CRASHES):
```python
def read_position(self):
    pos_a_inches = float(pos_a) / self.a_factor * 8  # CRASH if a_factor is 0
    pos_b_degrees = float(pos_b) / self.b_factor * 30
    pos_c_degrees = float(pos_c) / self.c_factor * 40
```

#### Fixed Code:
```python
def read_position(self):
    # Safety check calibration factors
    if self.a_factor == 0 or self.b_factor == 0 or self.c_factor == 0:
        self.logger.error("Invalid calibration factors detected")
        self._show_timed_error("Calibration error - please recalibrate system")
        return (0, 0, 0, 0)  # Safe defaults

    try:
        pos_a_inches = float(pos_a) / self.a_factor * 8 if self.a_factor != 0 else 0
        pos_b_degrees = float(pos_b) / self.b_factor * 30 if self.b_factor != 0 else 0
        pos_c_degrees = float(pos_c) / self.c_factor * 40 if self.c_factor != 0 else 0
    except (ZeroDivisionError, ValueError) as e:
        self.logger.error(f"Position calculation error: {e}")
        return (0, 0, 0, pressure)
```

### Fix 4: Undefined Signal Crash
**File**: `main/helpers/arduino.py`
**Line**: 14-24 (add signal), 425 (remove bad emit)

#### Add Missing Signal (Line 24):
```python
class Arduino(QObject):
    connection_ready = pyqtSignal()
    connection_failed = pyqtSignal(str)
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    done_emit = pyqtSignal()
    pressure_emit = pyqtSignal(str)
    ready_to_go_emit = pyqtSignal()
    position_emit = pyqtSignal(int, int, str, int)
    status_emit = pyqtSignal(int, int, int, float)
    buffer_warning = pyqtSignal(str)
    connection_lost = pyqtSignal()
    display_weight_emit = pyqtSignal(float)  # ADD THIS LINE
```

#### OR Remove Bad Emit (Line 425):
```python
# DELETE OR COMMENT THIS LINE:
# self.display_weight_emit.emit(weight)
```

### Fix 5: Thread Safety - I2Cstatus Race
**File**: `main/kneespa.py`
**Line**: 193 (initialization)

#### Current Code:
```python
self.I2Cstatus = 0  # Plain integer, not thread-safe
```

#### Fixed Code:
```python
import threading

# In __init__:
self.I2Cstatus_event = threading.Event()  # Thread-safe event
self.I2Cstatus = 0  # Keep for compatibility, but use event for synchronization
```

**File**: `main/helpers/reset_worker.py`
**Line**: 33-45

#### Current Code:
```python
while self.main_window.I2Cstatus == 0:  # Unsafe polling
    time.sleep(0.1)
```

#### Fixed Code:
```python
# Wait with timeout for thread-safe event
if not self.main_window.I2Cstatus_event.wait(timeout=30):
    self.logger.error("Timeout waiting for I2C response")
    return False
self.main_window.I2Cstatus_event.clear()  # Reset for next use
```

## HIGH PRIORITY FIXES (Day 2)

### Fix 6: File Handle Leaks
**File**: `main/config/config.py`
**Lines**: 29, 95

#### Current Code (LEAKS):
```python
self.config.write(open(self.configFile, "w"))  # File never closed!
```

#### Fixed Code:
```python
with open(self.configFile, "w") as config_file:
    self.config.write(config_file)
```

### Fix 7: UI Thread Blocking
**File**: `main/kneespa.py`
**Multiple locations with `time.sleep()`

#### Example Current Code (Line 790):
```python
def emergency_stop_clicked(self, event):
    self.stop_actuators()
    time.sleep(1)  # BLOCKS UI!
    if self.worker:
        self.worker.stop()
    time.sleep(1)  # BLOCKS UI!
```

#### Fixed Code:
```python
def emergency_stop_clicked(self, event):
    self.stop_actuators()

    # Use QTimer instead of sleep
    QTimer.singleShot(1000, self._emergency_stop_phase2)

def _emergency_stop_phase2(self):
    if self.worker:
        self.worker.stop()
    QTimer.singleShot(1000, self.reset_arduino)
```

### Fix 8: adjust_pressure Missing Validation
**File**: `main/kneespa.py`
**Line**: 1430-1446

#### Add Validation:
```python
def adjust_pressure(self, target_pressure):
    from config.constants import PRESSURE_MAX, MIN_PRESSURE

    # SAFETY VALIDATION
    if target_pressure > PRESSURE_MAX:
        self.logger.warning(f"Pressure {target_pressure} exceeds max, clamping to {PRESSURE_MAX}")
        target_pressure = PRESSURE_MAX
    elif target_pressure < 0:
        target_pressure = 0

    command = f"P{target_pressure}"
    self.arduino.send(command)
```

## MEDIUM PRIORITY FIXES (Day 3)

### Fix 9: Configuration Error Handling
**File**: `main/config/config.py`
**Lines**: 39-41

#### Current Code:
```python
self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}  # KeyError!
```

#### Fixed Code:
```python
# Safe section access with defaults
self.CMarks = {}
self.AMarks = {}
self.BMarks = {}

if "CMarks" in allSections:
    try:
        self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
    except (ValueError, TypeError) as e:
        self.logger.error(f"Error parsing CMarks: {e}")
        self._set_default_marks("C")
else:
    self._set_default_marks("C")

# Repeat for AMarks and BMarks
```

### Fix 10: Lateral Position Overflow
**File**: `main/kneespa.py`
**Line**: 1300-1320

#### Add Stepping Validation:
```python
def lateral_flexion_go_button_clicked(self):
    from config.constants import LATERAL_MIN, LATERAL_MAX

    # ... existing code ...

    # Before sending command, validate final position
    target_angle = left_angle if moving_left else right_angle

    if target_angle > LATERAL_MAX:
        target_angle = LATERAL_MAX
        self._show_timed_error(f"Lateral angle limited to {LATERAL_MAX}°")
    elif target_angle < LATERAL_MIN:
        target_angle = LATERAL_MIN
        self._show_timed_error(f"Lateral angle limited to {LATERAL_MIN}°")
```

## VALIDATION CHECKLIST

After implementing each fix:

1. **Compile Check**: Ensure no syntax errors
2. **Import Check**: Verify all constants are imported
3. **Boundary Test**: Test with min/max values
4. **Error Test**: Test with invalid inputs
5. **Thread Test**: Run concurrent operations
6. **Log Review**: Check for new warnings/errors

## TESTING COMMANDS

```bash
# Run unit tests for specific fixes
python -m pytest tests/unit/test_boundaries.py -v
python -m pytest tests/unit/test_thread_safety.py -v
python -m pytest tests/unit/test_config.py -v

# Run integration tests
python -m pytest tests/integration/ -v

# Run with debug mode to see all logs
python main/kneespa.py --debug --print-logs
```

## ROLLBACK PLAN

If any fix causes issues:

1. Keep original code in comments
2. Use version control (git) for each fix
3. Test incrementally - one fix at a time
4. Have emergency stop procedure ready

## COMPLETION TRACKING

- [ ] Fix 1: Pressure Safety (CRITICAL)
- [ ] Fix 2: Axial Position Limit (CRITICAL)
- [ ] Fix 3: Division by Zero (CRITICAL)
- [ ] Fix 4: Signal Crash (CRITICAL)
- [ ] Fix 5: Thread Race (CRITICAL)
- [ ] Fix 6: File Handles (HIGH)
- [ ] Fix 7: UI Blocking (HIGH)
- [ ] Fix 8: Pressure Validation (HIGH)
- [ ] Fix 9: Config Errors (MEDIUM)
- [ ] Fix 10: Lateral Overflow (MEDIUM)

## Notes

- Always test fixes on non-production hardware first
- Keep detailed logs of all changes
- Get code review for critical safety fixes
- Document any new error conditions introduced