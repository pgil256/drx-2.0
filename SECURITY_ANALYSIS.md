# KneeSpa Application - Actuator Control Safety Analysis

## Executive Summary

This document details critical boundary condition bugs and safety issues found in the KneeSpa application's actuator control logic. Multiple issues exist that could cause actuators to exceed mechanical limits or apply dangerous pressure levels.

---

## CRITICAL BUGS IDENTIFIED

### 1. PRESSURE SAFETY VIOLATION - Pressure Slider Lacks Upper Bound Validation
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1600-1613

**Issue:** The pressure slider has no enforced upper bound during manual operation, allowing pressure values above the 80 lbs safety limit.

**Code:**
```python
def axial_flexion_pressure_changed(self):
    # Line 1601
    pounds = self.ui.axial_flexion_pressure_slider.value()
    self.ui.axial_flexion_pressure_label.setText(str(pounds) + " lb")

def axial_flexion_pressure_go_button_clicked(self):
    # Line 1604-1613
    print("axial_flexion_pressure_go_button_clicked")
    self.loading_spinner.show()
    self.disable_actuator_controls()
    pressure = self.ui.axial_flexion_pressure_slider.value()  # NO BOUNDS CHECK!
    print(pressure)
    command = "P{}".format(pressure)
    self.arduino.send(command)
    print("Pressure cmd sent {}".format(command.strip()))
    self.loading_spinner.hide()
```

**Problem:**
- The slider value is read directly without validation
- No upper bound check against `PRESSURE_MAX = 80` lbs
- No lower bound check against `MIN_PRESSURE = 10` lbs
- If the slider is configured to allow values > 80 in the UI, this will be sent directly to Arduino

**Risk Level:** CRITICAL
- Can cause excessive pressure application leading to patient injury
- Violates safety constant `PRESSURE_MAX = 80 lbs`

**Recommended Fix:**
```python
def axial_flexion_pressure_go_button_clicked(self):
    pressure = self.ui.axial_flexion_pressure_slider.value()
    # Add bounds validation
    if pressure > PRESSURE_MAX:
        self._show_timed_error(f"Pressure {pressure} exceeds safety limit of {PRESSURE_MAX} lbs")
        return
    if pressure < MIN_PRESSURE:
        self._show_timed_error(f"Pressure {pressure} below minimum of {MIN_PRESSURE} lbs")
        return
    command = "P{}".format(pressure)
    self.arduino.send(command)
```

---

### 2. AXIAL POSITION BOUNDS VIOLATION - Exceeding 8 Inches
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1265-1298

**Issue:** The axial actuator bounds check is inconsistent with the constants definition, allowing position beyond the mechanical limit.

**Code:**
```python
def move_actuator(self, actuator, step, speed_factor, direction):
    # Line 1265-1273 (Actuator A - Axial Flexion)
    elif actuator == self.actuator_a:  # Axial Flexion
        step = 1 if int(speed_factor) > 4 else 0.5
        new_position = self.axial_flexion_position + (step * direction)

        # Check position limits
        if direction > 0 and new_position > 8:  # PROBLEM: Says max is 8!
            return
        if direction < 0 and new_position < 0:
            return
```

**Problem:**
- Constants define `AXIAL_MAX = 4 inches` (see `/mnt/c/users/user/desktop/drx-demo/main/config/constants.py` line 89)
- But the code checks `> 8` inches, allowing double the safe limit
- This is a 100% overshoot of the mechanical limit
- The constant says "4 inches" but the code checks "8"

**Constant Definition (constants.py line 57):**
```python
"LIMITS": (0, 4),  # inches  <- Says 4 inches is max
```

**Risk Level:** CRITICAL
- Actuator can extend to 8 inches when mechanical limit is 4 inches
- Causes mechanical damage or patient injury from over-extension
- Clear contradiction between constants and implementation

**Recommended Fix:**
```python
elif actuator == self.actuator_a:  # Axial Flexion
    step = 1 if int(speed_factor) > 4 else 0.5
    new_position = self.axial_flexion_position + (step * direction)

    # Use constants-defined limits
    AXIAL_LIMIT = ACTUATORS["AXIAL"]["LIMITS"][1]  # Get max from constants (4)
    if direction > 0 and new_position > AXIAL_LIMIT:
        return
    if direction < 0 and new_position < 0:
        return
```

---

### 3. LATERAL POSITION OVERFLOW - Position Increment Can Exceed Bounds
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1300-1320

**Issue:** The lateral position increment can cause the position to exceed the -20 to +20 degree range.

**Code:**
```python
elif actuator == self.actuator_c:  # Lateral Flexion
    step = 5 if int(speed_factor) > 4 else 2.5  # 2.5 or 5 degree steps
    new_position = self.lateral_flexion_position + (step * direction)

    # Round to nearest 2.5 degree increment
    new_position = round(new_position / 2.5) * 2.5

    # Check position limits
    if direction > 0 and new_position > 20:  # Line 1308-1310
        return
    if direction < 0 and new_position < -20:
        return
```

**Problem:**
- With 5-degree steps, the position can overshoot by up to 5 degrees
- Example: Position at 17.5°, step 5° forward → 22.5° (exceeds 20°)
- The bounds check comes AFTER the increment calculation
- The rounding operation can push position beyond the check

**Scenario:**
1. Current position: 17.5°
2. User clicks "fast forward" (step = 5°)
3. Calculation: 17.5 + 5 = 22.5°
4. Rounding: round(22.5/2.5)*2.5 = 22.5°
5. Bounds check: 22.5 > 20? YES → return (doesn't move)
6. But position was already updated in internal state if sent to Arduino

**Risk Level:** HIGH
- Can cause lateral actuator to exceed mechanical limits
- Bounds constants define: `LATERAL_MIN/MAX = (-20, 20)` degrees

**Recommended Fix:**
```python
elif actuator == self.actuator_c:  # Lateral Flexion
    step = 5 if int(speed_factor) > 4 else 2.5
    new_position = self.lateral_flexion_position + (step * direction)

    # Round to nearest 2.5 degree increment
    new_position = round(new_position / 2.5) * 2.5

    # BOUNDS CHECKING BEFORE SENDING COMMAND
    if new_position > 20 or new_position < -20:
        return  # Reject out-of-bounds movement
```

---

### 4. HORIZONTAL POSITION BOUNDS LOGIC ERROR
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1232-1262

**Issue:** Horizontal position bounds checking uses inverted logic compared to angle values.

**Code:**
```python
def move_actuator(self, actuator, step, speed_factor, direction):
    if actuator == self.actuator_b:  # Horizontal Flexion
        step = 10 if int(speed_factor) > 4 else 5
        new_position = self.horizontal_flexion_position + (step * direction)

        # Check position limits - CONFUSING LOGIC
        if direction >= 0 and new_position > -5:  # Line 1237
            return
        if direction < 0 and new_position < -25:  # Line 1239
            return
```

**Problem:**
- Constants define `HORIZONTAL_MIN/MAX = (-25, 5)` degrees (see constants.py line 67)
- The code checks `> -5` for forward movement, which is correct
- But the condition logic is confusing: "if moving forward AND position > -5: return"
- This PREVENTS moving forward when already past -5°, which is backwards
- Should only return if exceeding the +5° maximum, not minimum

**Risk Analysis:**
- Forward should move towards +5° (less negative)
- Backward should move towards -25° (more negative)
- Current logic prevents forward motion when already past -5°, which is incorrect

**Risk Level:** HIGH
- Prevents legitimate forward movements
- Confusing double-negative logic

**Recommended Fix:**
```python
if actuator == self.actuator_b:  # Horizontal Flexion
    step = 10 if int(speed_factor) > 4 else 5
    new_position = self.horizontal_flexion_position + (step * direction)

    # Check position limits - use named constants
    H_MIN, H_MAX = ACTUATORS["HORIZONTAL"]["LIMITS"]  # (-25, 5)

    if new_position > H_MAX or new_position < H_MIN:
        return  # Reject out-of-bounds
```

---

### 5. LEG LENGTH BOUNDS INCONSISTENCY - Comment vs Code Mismatch
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1514, 1531, 1549, 1567

**Issue:** Comments say "0.5 inches per press" but code uses "0.25" and "3.0" increments.

**Code Examples:**
```python
def forward_button_clicked(self):  # Line 1502
    # Comment says: "Move 0.5 inches per press"
    self.leg_length += 0.25  # But actually moves 0.25 (Line 1514)

def reverse_button_clicked(self):  # Line 1519
    # Comment says: "Move 0.5 inches per press"
    self.leg_length -= 0.25  # But actually moves 0.25 (Line 1531)

def forward_fast_button_clicked(self):  # Line 1536
    # Comment says: "Move 1.0 inches per press"
    self.leg_length += 3.0  # But actually moves 3.0 (Line 1549)

def reverse_fast_button_clicked(self):  # Line 1554
    # Comment says: "Move 1.0 inches per press"
    self.leg_length -= 3.0  # But actually moves 3.0 (Line 1567)
```

**Problem:**
- Forward normal: comment says 0.5, code does 0.25
- Forward fast: comment says 1.0, code does 3.0
- Reverse fast: comment says 1.0, code does 3.0
- This indicates incomplete refactoring or untested changes

**Risk Level:** MEDIUM
- Documentation doesn't match implementation
- Could cause unexpected large movements
- User expects 1.0 inch per fast click but gets 3.0 inches

**Recommended Fix:**
Update comments to match code, or fix code to match intended behavior:
```python
def forward_fast_button_clicked(self):
    """Handle forward button press - fast speed."""
    # Clarify: This moves 3.0 inches per press (not 1.0 as commented)
    self.leg_length += 3.0
    self.leg_length = min(self.leg_length, self.LEG_LENGTH_MAX)
```

---

### 6. INTERPOLATION DIVISION BY ZERO RISK
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/protocols.py`
**Lines:** 280-286

**Issue:** Linear interpolation could divide by zero if two CMarks have identical degree values.

**Code:**
```python
def set_to_c_distance(self, degrees: float) -> bool:
    # Line 264-315
    marks = sorted((float(k), int(v)) for k, v in self.config.CMarks.items())
    for i in range(len(marks) - 1):
        if marks[i][0] <= degrees <= marks[i + 1][0]:
            deg1, pos1 = marks[i]
            deg2, pos2 = marks[i + 1]
            ratio = (degrees - deg1) / (deg2 - deg1)  # LINE 285 - DIVISION BY ZERO!
            position = pos1 + int((pos2 - pos1) * ratio)
            break
```

**Problem:**
- If `deg1 == deg2` (duplicate degree keys in CMarks), division by zero occurs
- This would cause application crash
- No validation that marks are sorted with increasing degree values
- CMarks configuration could be corrupted or misconfigured

**Risk Level:** HIGH
- Would crash the protocol execution mid-treatment
- Affects patient safety if mid-protocol
- Could occur if calibration data is invalid

**Recommended Fix:**
```python
ratio = (degrees - deg1) / (deg2 - deg1)
if deg2 - deg1 == 0:  # Check for division by zero
    print(f"ERROR: Invalid CMarks configuration - duplicate degree values: {deg1}")
    raise ValueError(f"CMarks has duplicate degree: {deg1}")
ratio = (degrees - deg1) / (deg2 - deg1)
position = pos1 + int((pos2 - pos1) * ratio)
```

---

### 7. CALIBRATION FACTOR DIVISION BY ZERO
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1651-1665

**Issue:** Position to inches conversion uses calibration factors without zero-check.

**Code:**
```python
def read_position(self, position, steps, actuator):
    # Line 1645-1665
    if hasattr(self, "actuator_b") and actuator == self.actuator_b:
        inches = (position * 6) / self.config.b_factor  # LINE 1651 - Could divide by zero!
        inches = round(inches * 2.0) / 2.0
        print(f"Inches (actuator B): {inches}")
        degrees = int(-(25 - (inches / 5) * 25))
    elif hasattr(self, "actuator_a") and actuator == self.actuator_a:
        inches = (position * 6) / self.config.a_factor  # LINE 1657 - Could divide by zero!
        inches = round(inches * 2.0) / 2.0
        print(f"Inches (actuator A): {inches}")
    elif hasattr(self, "actuator_c") and actuator == self.actuator_c:
        inches = steps / (self.config.c_factor / 6)  # LINE 1661 - c_factor could be zero!
```

**Problem:**
- If `a_factor`, `b_factor`, or `c_factor` are zero or not initialized, division by zero
- Configuration loading could fail silently, leaving factors at 0
- No validation of configuration values before use
- Would crash when reading position feedback from Arduino

**Risk Level:** CRITICAL
- Application crash during protocol execution
- Prevents receiving position feedback from Arduino
- Patient safety if this occurs mid-treatment

**Recommended Fix:**
```python
def read_position(self, position, steps, actuator):
    if hasattr(self, "actuator_b") and actuator == self.actuator_b:
        if self.config.b_factor == 0:
            print(f"ERROR: b_factor not initialized!")
            return
        inches = (position * 6) / self.config.b_factor
        # ... rest of code
```

---

### 8. MISSING SLIDER RANGE CONFIGURATION
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 490-500

**Issue:** Position sliders found but range not explicitly set in Python code.

**Code:**
```python
def setup_buttons_and_labels(self):
    # Lines 492-500
    self.ui.axial_flexion_position_slider = self.ui.findChild(
        QtWidgets.QSlider, "axial_flexion_position_slider"
    )
    self.ui.lateral_flexion_position_slider = self.ui.findChild(
        QtWidgets.QSlider, "lateral_flexion_position_slider"
    )
    self.ui.horizontal_flexion_position_slider = self.ui.findChild(
        QtWidgets.QSlider, "horizontal_flexion_position_slider"
    )
    self.ui.axial_flexion_pressure_slider = self.ui.findChild(
        QtWidgets.QSlider, "axial_flexion_pressure_slider"
    )
    # NOTE: NO setRange() calls for these sliders!
```

**Problem:**
- Sliders are found but never configured with `setRange()`
- Slider ranges defined only in UI file, not validated in Python
- If UI file has wrong ranges, safety limits are not enforced in code
- Pressure slider especially dangerous - should be hardcoded to (0, 80)

**Risk Level:** HIGH
- Slider range validation depends on UI file only
- No programmatic enforcement of safety limits
- Could allow slider to exceed bounds if UI misconfigured

**Recommended Fix:**
```python
# In setup_buttons_and_labels or setup_actuator_controls
self.ui.axial_flexion_position_slider.setRange(0, 8)  # 0-4 inches, scaled by 2
self.ui.lateral_flexion_position_slider.setRange(-20, 20)  # -20 to +20 degrees
self.ui.horizontal_flexion_position_slider.setRange(-25, 5)  # -25 to +5 degrees
self.ui.axial_flexion_pressure_slider.setRange(0, 80)  # 0-80 lbs CRITICAL
```

---

### 9. MISSING PRESSURE BOUNDS IN adjust_pressure()
**Location:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`
**Lines:** 1430-1446

**Issue:** Direct pressure adjustment function lacks bounds validation.

**Code:**
```python
def adjust_pressure(self, target_pressure):
    """Adjust axial pressure to target value."""
    print(f"Adjusting pressure to {target_pressure} lbs")
    self.loading_spinner.show()
    self.disable_actuator_controls()
    try:
        self.ui.axial_flexion_pressure_label.setText(f"{target_pressure} lb")
        self.arduino.send(f"P{target_pressure}")  # NO VALIDATION!
        self.current_pressure = target_pressure
        print(f"Pressure adjusted to {target_pressure} lbs")
```

**Problem:**
- No check that `target_pressure <= PRESSURE_MAX (80)`
- No check that `target_pressure >= MIN_PRESSURE (10)`
- Any caller can pass arbitrary pressure values
- UI updates before Arduino command (could fail)

**Risk Level:** CRITICAL
- Protocol worker calls this without validation
- Could apply dangerous pressure levels

**Recommended Fix:**
```python
def adjust_pressure(self, target_pressure):
    """Adjust axial pressure to target value."""
    # Validate pressure bounds
    if target_pressure > PRESSURE_MAX:
        self._show_timed_error(f"Pressure {target_pressure} exceeds maximum {PRESSURE_MAX} lbs")
        return False
    if target_pressure < MIN_PRESSURE and target_pressure > 0:
        self._show_timed_error(f"Pressure {target_pressure} below minimum {MIN_PRESSURE} lbs")
        return False

    print(f"Adjusting pressure to {target_pressure} lbs")
    self.loading_spinner.show()
    self.disable_actuator_controls()
    try:
        self.arduino.send(f"P{target_pressure}")
        self.current_pressure = target_pressure
        self.ui.axial_flexion_pressure_label.setText(f"{target_pressure} lb")
```

---

## SUMMARY TABLE

| # | Location | Bug Type | Risk | Fix Priority |
|---|----------|----------|------|--------------|
| 1 | kneespa.py:1600-1613 | No pressure bounds check | CRITICAL | P0 |
| 2 | kneespa.py:1265-1298 | Axial max 8" vs constant 4" | CRITICAL | P0 |
| 3 | kneespa.py:1300-1320 | Lateral position overflow | HIGH | P0 |
| 4 | kneespa.py:1232-1262 | Horizontal bounds logic error | HIGH | P1 |
| 5 | kneespa.py:1502-1570 | Comment/code mismatch on leg movement | MEDIUM | P2 |
| 6 | protocols.py:280-286 | Division by zero in interpolation | HIGH | P0 |
| 7 | kneespa.py:1645-1665 | Division by zero on calibration factors | CRITICAL | P0 |
| 8 | kneespa.py:490-500 | Slider ranges not set in code | HIGH | P1 |
| 9 | kneespa.py:1430-1446 | No bounds in adjust_pressure() | CRITICAL | P0 |

---

## RECOMMENDATIONS

### Immediate Actions (P0 - Critical)
1. Add pressure bounds validation everywhere pressure is set
2. Fix axial position limit from 8" to 4"
3. Fix division by zero risks in interpolation and calibration
4. Add bounds validation in adjust_pressure()

### High Priority (P1)
1. Explicitly configure all slider ranges in Python code
2. Fix horizontal position bounds logic
3. Add validation of configuration factors on load

### Medium Priority (P2)
1. Fix comment/code mismatches in leg movement
2. Add comprehensive logging for boundary violations

### Testing Recommendations
- Test pressure slider with values above 80 lbs
- Test axial position movement to 5-8 inches
- Test lateral position overflow with repeated clicks at boundaries
- Test calibration with missing or zero factors
- Test with corrupted CMarks configuration

