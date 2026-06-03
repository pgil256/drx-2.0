# Lateral Control - Quick Reference Guide

## File Location
**Primary File**: `/mnt/c/users/user/desktop/drx-demo-final/main/kneespa.py`

---

## Quick Access Points

### 1. Lateral Button Click Handlers (Lines 1154-1165)
Where the lateral buttons are connected to their handler methods.

```python
# Forward (right) button - slow
self.ui.forward_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 5, "04", 1)
)

# Reverse (left) button - slow
self.ui.reverse_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 5, "04", -1)
)

# Forward (right) button - fast
self.ui.forward_fast_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 10, "20", 1)
)

# Reverse (left) button - fast
self.ui.reverse_fast_lateral_flexion_button.clicked.connect(
    lambda: self.move_actuator(self.actuator_c, 10, "20", -1)
)
```

**Note**: `self.actuator_c` is the LATERAL actuator

---

### 2. Control Disable/Enable Methods (Lines 536-545)

#### disable_actuator_controls()
```python
def disable_actuator_controls(self):
    for w in self.actuator_controls:
        w.setEnabled(False)
```
- Disables ALL control buttons
- Called at the start of any movement

#### enable_actuator_controls()
```python
def enable_actuator_controls(self):
    if self.protocol_running == False:
        print("Scheduling controls to enable with delay...")
        for w in self.actuator_controls:
            QTimer.singleShot(200, lambda widget=w: widget.setEnabled(True))
```
- Re-enables ALL control buttons
- Uses 200ms delay via QTimer
- Only works when `protocol_running == False`
- **THIS IS WHERE THE DEBUG MESSAGE COMES FROM**

---

### 3. Movement Execution (Lines 1308-1364)

For lateral (actuator_c) movements:
- **Step Size**: 2.5° (slow) or 5° (fast)
- **Position Limits**: -20° to +20°
- **Arduino Command**: `"K{position}"` (e.g., "K50")
- **Control Flow**: 
  1. Disable controls
  2. Send command to Arduino
  3. Wait for Arduino "done" signal
  4. Enable controls with 200ms delay

---

### 4. What Triggers the "Scheduling..." Message

The message `"Scheduling controls to enable with delay..."` appears when:

1. Arduino completes a movement
2. Sends "done" signal
3. `set_done()` method (line 1687) receives it
4. Calls `enable_actuator_controls()` (line 1693)
5. Message prints (line 542)
6. QTimer schedules re-enabling after 200ms

---

### 5. Lateral Button Metadata

| Button | Type | Step | Speed Factor | Direction |
|--------|------|------|--------------|-----------|
| forward_lateral_flexion | Slow | 5° | "04" | +1 (right) |
| reverse_lateral_flexion | Slow | 5° | "04" | -1 (left) |
| forward_fast_lateral_flexion | Fast | 10° | "20" | +1 (right) |
| reverse_fast_lateral_flexion | Fast | 10° | "20" | -1 (left) |

---

### 6. Actuator Mapping

- **actuator_a**: Axial (leg length) - 0 to 4 inches
- **actuator_b**: Horizontal (knee) - -25° to -5°
- **actuator_c**: Lateral (knee abduction/adduction) - -20° to +20°

---

### 7. Key Variables

| Variable | Type | Purpose |
|----------|------|---------|
| `self.lateral_flexion_position` | float | Current position in degrees |
| `self.protocol_running` | bool | True if protocol active |
| `self.actuator_controls` | list | All control buttons |
| `self.loading_spinner` | widget | Shows during movement |

---

### 8. Command Sequence for Lateral Right Button

```
User clicks "forward_lateral_flexion_button"
  ↓
Handler calls: move_actuator(actuator_c, 5, "04", 1)
  ↓
Calculate: new_pos = current_lateral_position + (5 * 1)
  ↓
Validate: -20 ≤ new_pos ≤ 20
  ↓
Disable all buttons via: disable_actuator_controls()
  ↓
Send to Arduino: "K{calibrated_position}"
  ↓
Show loading spinner
  ↓
[Arduino processes, moves actuator]
  ↓
Arduino sends "done" signal back
  ↓
set_done() receives signal
  ↓
Enable controls via: enable_actuator_controls()
  ↓
Print: "Scheduling controls to enable with delay..."
  ↓
Schedule timers: QTimer.singleShot(200ms, lambda widget=w: w.setEnabled(True))
  ↓
[After 200ms] Each button lambda executes
  ↓
All buttons enabled again, user can click
```

---

### 9. For Debugging

Add these prints to track lateral movement:

```python
# In move_actuator(), lateral section (around line 1310)
print(f"Lateral movement requested: direction={direction}, speed_factor={speed_factor}")
print(f"Current position: {self.lateral_flexion_position}°")
print(f"New position: {new_position}°")
print(f"Arduino command: K{position}")

# In set_done() (around line 1690)
print(f"Movement complete, re-enabling controls")
print(f"Protocol running: {self.protocol_running}")
```

---

### 10. Common Issues & Checks

**Issue**: Buttons not re-enabling after movement
- Check: Is `protocol_running` True? (Line 541 condition)
- Check: Is `set_done()` being called? (Look for Arduino signal)
- Check: Is the 200ms timer firing? (Add print on line 545)

**Issue**: Lateral position not updating
- Check: Is position in `self.config.CMarks`? (Line 1335)
- Check: Are calibration values correct?

**Issue**: Arduino command not working
- Check: Is command format correct? `"K{position}"` (Line 1361)
- Check: Is Arduino receiving the command?

---
