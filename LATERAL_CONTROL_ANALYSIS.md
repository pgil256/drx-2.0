# Lateral Control Handlers - Complete Analysis

## Overview
This document provides a comprehensive overview of the lateral control system implementation in the KneeSPA application, including button handlers, control enable/disable mechanisms, and scheduling logic.

---

## 1. LATERAL BUTTON HANDLERS

### Location
File: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`
Lines: 1154-1165

### Implementation

#### Forward Lateral Flexion Button (Slow Speed)
```python
# Line 1154-1156
self.ui.forward_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 5, "04", 1)  # slow speed
)
```
- **Button**: `forward_lateral_flexion_button`
- **Handler**: `move_actuator()` method
- **Parameters**: 
  - Actuator: `self.actuator_c` (Lateral actuator)
  - Step: `5` degrees
  - Speed Factor: `"04"` (slow speed)
  - Direction: `1` (forward/right)

#### Reverse Lateral Flexion Button (Slow Speed)
```python
# Line 1157-1159
self.ui.reverse_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 5, "04", -1)  # slow speed
)
```
- **Button**: `reverse_lateral_flexion_button`
- **Handler**: `move_actuator()` method
- **Parameters**: 
  - Actuator: `self.actuator_c`
  - Step: `5` degrees
  - Speed Factor: `"04"` (slow speed)
  - Direction: `-1` (reverse/left)

#### Forward Fast Lateral Flexion Button
```python
# Line 1160-1162
self.ui.forward_fast_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 10, "20", 1)  # fast speed
)
```
- **Button**: `forward_fast_lateral_flexion_button`
- **Handler**: `move_actuator()` method
- **Parameters**: 
  - Actuator: `self.actuator_c`
  - Step: `10` degrees
  - Speed Factor: `"20"` (fast speed)
  - Direction: `1` (forward/right)

#### Reverse Fast Lateral Flexion Button
```python
# Line 1163-1165
self.ui.reverse_fast_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 10, "20", -1)  # fast speed
)
```
- **Button**: `reverse_fast_lateral_flexion_button`
- **Handler**: `move_actuator()` method
- **Parameters**: 
  - Actuator: `self.actuator_c`
  - Step: `10` degrees
  - Speed Factor: `"20"` (fast speed)
  - Direction: `-1` (reverse/left)

---

## 2. CONTROL ENABLE/DISABLE METHODS

### Location
File: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`
Lines: 536-545

### disable_actuator_controls()
```python
def disable_actuator_controls(self):
    for w in self.actuator_controls:
        w.setEnabled(False)
```
**Purpose**: Disables all actuator control buttons while a movement is in progress

**Called from**:
- Line 109: `set_to_b_distance()` - Horizontal control
- Line 1244: `move_actuator()` - For horizontal movement
- Line 1284: `move_actuator()` - For axial movement
- Line 1331: `move_actuator()` - For **lateral movement**
- Line 1368: `reset_flexion_button_clicked()` - Reset operations
- Line 1417, 1453, 1544, 1560, 1578, 1595, 1613, 1627, 1647: Various other control methods
- Line 1943: Protocol warning handling
- Line 2105, 2200: Other protocol-related operations

### enable_actuator_controls()
```python
def enable_actuator_controls(self):
    if self.protocol_running == False:
        print("Scheduling controls to enable with delay...") # Add for debugging
        for w in self.actuator_controls:
            # Use a default argument to capture the current value of 'w'
            QTimer.singleShot(200, lambda widget=w: widget.setEnabled(True))
```

**Purpose**: Re-enables all actuator control buttons after movement completes

**Key Features**:
- Only enables controls if protocol is NOT running (`protocol_running == False`)
- Uses `QTimer.singleShot()` for delayed enabling (200ms delay)
- Lambda with default argument captures widget reference correctly

**Called from**:
- Line 99: `set_to_b_distance()` - After horizontal movement
- Line 152: `set_to_c_distance()` - **After lateral movement**
- Line 1693: `set_done()` - Signal from Arduino indicating movement complete
- Line 1946: Protocol warning dialog handling

---

## 3. ACTUATOR CONTROLS LIST

### Location
File: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`
Lines: 504-526

```python
self.actuator_controls = [
    # leg-length
    self.ui.forward_extra_button, self.ui.reverse_extra_button,
    self.ui.forward_fast_extra_button, self.ui.reverse_fast_extra_button,
    self.ui.reset_extra_button,
    
    # axial
    self.ui.forward_axial_flexion_button, self.ui.reverse_axial_flexion_button,
    self.ui.forward_fast_axial_flexion_button, self.ui.reverse_fast_axial_flexion_button,
    self.ui.reset_axial_flexion_button,
    self.ui.axial_flexion_position_go_button,
    self.ui.axial_flexion_pressure_go_button,
    
    # lateral
    self.ui.forward_lateral_flexion_button, self.ui.reverse_lateral_flexion_button,
    self.ui.forward_fast_lateral_flexion_button, self.ui.reverse_fast_lateral_flexion_button,
    self.ui.reset_lateral_flexion_button, self.ui.lateral_flexion_position_go_button,
    
    # horizontal
    self.ui.forward_horizontal_flexion_button, self.ui.reverse_horizontal_flexion_button,
    self.ui.forward_fast_horizontal_flexion_button, self.ui.reverse_fast_horizontal_flexion_button,
    self.ui.reset_horizontal_flexion_button, self.ui.horizontal_flexion_position_go_button,
    
    self.ui.reset_arduino_main_button, self.ui.reset_arduino_setup_button,
]
```

**Lateral buttons included**:
- `forward_lateral_flexion_button`
- `reverse_lateral_flexion_button`
- `forward_fast_lateral_flexion_button`
- `reverse_fast_lateral_flexion_button`
- `reset_lateral_flexion_button`
- `lateral_flexion_position_go_button`

---

## 4. MOVE_ACTUATOR METHOD FOR LATERAL MOVEMENT

### Location
File: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`
Lines: 1228-1364

### Method Signature
```python
def move_actuator(self, actuator, step, speed_factor, direction):
    """Move an actuator in the specified direction"""
```

### Lateral Movement Section (Lines 1308-1364)
```python
elif actuator == self.actuator_c:  # Lateral Flexion
    # Calculate step size based on speed
    step = 5 if int(speed_factor) > 4 else 2.5  # Use 2.5 degree increments
    new_position = self.lateral_flexion_position + (step * direction)
    
    # Round to nearest 2.5 degree increment
    new_position = round(new_position / 2.5) * 2.5
    
    # Check position limits using constants for safety
    from config.constants import ACTUATORS
    
    lateral_max = ACTUATORS["LATERAL"]["LIMITS"][1]  # Should be 20
    lateral_min = ACTUATORS["LATERAL"]["LIMITS"][0]  # Should be -20
    
    # Boundary checking
    if direction > 0 and new_position > lateral_max:
        self.logger.warning(f"Lateral position {new_position} exceeds max {lateral_max}")
        self._show_timed_error(f"Lateral position limited to {lateral_max}° for safety")
        return
    if direction < 0 and new_position < lateral_min:
        self.logger.warning(f"Lateral position {new_position} below min {lateral_min}")
        self._show_timed_error(f"Lateral position limited to {lateral_min}° for safety")
        return
    
    # Disable controls while moving
    self.loading_spinner.show()
    self.disable_actuator_controls()
    
    # Validate position exists in calibration
    position_key = f"{new_position:.1f}"
    if position_key not in self.config.CMarks:
        print(f"Invalid position {position_key}, skipping movement")
        return
    
    # Update internal state
    self.lateral_flexion_position = new_position
    position = self.config.CMarks[position_key]
    
    print(f" positioned to {self.lateral_flexion_position} degrees pos {position}")
    
    # Update UI display
    left_right = (
        "R"
        if self.lateral_flexion_position > 0
        else "L" if self.lateral_flexion_position < 0 else ""
    )
    self.ui.lateral_flexion_position_slider.setValue(self.lateral_flexion_position)
    self.ui.lateral_flexion_position_label.setText(
        f"{abs(self.lateral_flexion_position)}{left_right}{DEGREES}"
    )
    
    # Send command to Arduino
    command = f"K{position}"
    self.arduino.send(command)
    
    # Hide spinner after movement
    self.loading_spinner.hide()
```

### Key Features for Lateral Movement:
1. **Step Sizes**:
   - Slow (speed_factor ≤ 4): 2.5° increments
   - Fast (speed_factor > 4): 5° increments

2. **Position Limits**: -20° to +20° (enforced from constants)

3. **Control Disable/Enable Flow**:
   - Disables controls at start (line 1331)
   - Shows loading spinner
   - Sends command to Arduino via serial: `"K{position}"`
   - Arduino sends back "done" signal
   - `set_done()` method receives signal and calls `enable_actuator_controls()`

4. **UI Updates**:
   - Updates slider position
   - Updates label with directional indicators (R for right, L for left)
   - Logs position information

---

## 5. SCHEDULING MECHANISM - QTimer

### Location
File: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`
Lines: 540-545

### The "Scheduling controls to enable with delay" Message

```python
def enable_actuator_controls(self):
    if self.protocol_running == False:
        print("Scheduling controls to enable with delay...") # Add for debugging
        for w in self.actuator_controls:
            # Use a default argument to capture the current value of 'w'
            QTimer.singleShot(200, lambda widget=w: widget.setEnabled(True))
```

### Timer Details:
- **Type**: `QTimer.singleShot()` - one-time timer
- **Delay**: 200 milliseconds (0.2 seconds)
- **Purpose**: Prevents rapid clicking and allows Arduino time to process
- **Implementation**: Lambda with default argument captures widget to avoid closure issues

### Timer Usage in File:
- Line 16: `QTimer` imported from `PyQt5.QtCore`
- Lines 184-189: Timer instances created:
  ```python
  self.protocol_timer = QTimer()
  self.elapsed_timer = QTimer()
  self.complete_timer = QTimer()
  self.stop_timer = QTimer()
  self.go_timer = QTimer()
  self.reset_timer = QTimer()
  ```
- Line 545: Control re-enabling with 200ms delay
- Line 758: `protocol_timer` configured
- Line 1618: `QTimer.singleShot()` for button sequence (3000ms)
- Lines 2088-2089: Timer for dialog auto-close

---

## 6. BUTTON-TO-CONTROL FLOW SUMMARY FOR LATERAL RIGHT BUTTON

```
User clicks "forward_lateral_flexion_button"
    ↓
Signal handler triggered (line 1154-1156)
    ↓
lambda calls: self.move_actuator(self.actuator_c, 5, "04", 1)
    ↓
move_actuator() method (line 1228+):
    - Calculates new position: lateral_flexion_position + (5 * 1)
    - Validates bounds (-20° to +20°)
    - Calls disable_actuator_controls() (line 1331)
    - All buttons in self.actuator_controls set to disabled
    - Shows loading spinner
    ↓
Arduino movement command sent: "K{position}"
    ↓
[Waiting for Arduino to complete movement]
    ↓
Arduino sends "done" signal back
    ↓
set_done() signal slot triggered (line 1687-1693):
    - Sets I2Cstatus = 1
    - Calls enable_actuator_controls()
    ↓
enable_actuator_controls() (line 540-545):
    - Checks if protocol_running == False
    - Prints "Scheduling controls to enable with delay..."
    - Schedules QTimer.singleShot(200ms) for each button
    ↓
After 200ms delay:
    - Each button lambda executes: widget.setEnabled(True)
    - All lateral buttons re-enabled
    - User can click again
```

---

## 7. KEY CODE LOCATIONS SUMMARY

| Component | File | Lines |
|-----------|------|-------|
| Lateral button handlers | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 1154-1165 |
| disable_actuator_controls() | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 536-538 |
| enable_actuator_controls() | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 540-545 |
| QTimer.singleShot() scheduling | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 545 |
| Scheduling debug message | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 542 |
| move_actuator() method | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 1228-1364 |
| Lateral movement section | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 1308-1364 |
| actuator_controls list | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 504-526 |
| set_done() signal handler | `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py` | 1687-1693 |

---

## 8. DEBUGGING NOTES

The "Scheduling controls to enable with delay..." message is printed when:
1. A movement operation completes (Arduino sends "done" signal)
2. `set_done()` is called
3. `enable_actuator_controls()` is executed
4. AND `protocol_running == False` (not in protocol execution mode)

This indicates the system is ready for the next movement command.

---
