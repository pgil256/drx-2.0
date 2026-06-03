# Lateral Control Flow Diagrams

## 1. Button Click to Movement Complete Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ USER INTERACTION PHASE                                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User clicks button (e.g., forward_lateral_flexion_button)         │
│         │                                                           │
│         ▼                                                           │
│  Button signal emitted: clicked.connect() triggered                │
│         │                                                           │
│         ▼                                                           │
│  Lambda executed: self.move_actuator(self.actuator_c, 5, "04", 1) │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ MOVEMENT PREPARATION PHASE                                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  move_actuator() method called                                     │
│         │                                                           │
│         ├─→ Validate direction and speed_factor parameters         │
│         │                                                           │
│         ├─→ Calculate new_position:                                │
│         │   new_pos = lateral_flexion_position + (step * direction)│
│         │                                                           │
│         ├─→ Round to nearest 2.5° increment                        │
│         │                                                           │
│         ├─→ Check bounds: -20° ≤ new_pos ≤ 20°                    │
│         │   If out of bounds:                                      │
│         │   └─→ Log warning and show error, RETURN                 │
│         │                                                           │
│         ├─→ disable_actuator_controls()                            │
│         │   (All buttons set to .setEnabled(False))                │
│         │                                                           │
│         ├─→ Show loading spinner                                   │
│         │                                                           │
│         ├─→ Verify position exists in config.CMarks                │
│         │   If missing:                                            │
│         │   └─→ Log error and RETURN                               │
│         │                                                           │
│         ├─→ Update internal state:                                 │
│         │   lateral_flexion_position = new_position                │
│         │                                                           │
│         ├─→ Update UI elements:                                    │
│         │   - lateral_flexion_position_slider.setValue()           │
│         │   - lateral_flexion_position_label.setText()             │
│         │   - Add direction indicator (R/L)                        │
│         │                                                           │
│         └─→ Get calibrated position from config.CMarks             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ARDUINO COMMUNICATION PHASE                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Send command: arduino.send("K{position}")                         │
│  Example: arduino.send("K50")                                      │
│         │                                                           │
│         ├─→ Serial port transmission                               │
│         │   (9600 baud via /dev/serial0)                           │
│         │                                                           │
│         ├─→ Arduino receives "K50"                                 │
│         │                                                           │
│         ├─→ Arduino activates Lateral (C) actuator                 │
│         │                                                           │
│         └─→ Actuator physically moves to position                  │
│             [~500-2000ms movement time]                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │ (Arduino finishes movement)
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ ARDUINO RESPONSE PHASE                                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Arduino sends "done" signal back                                  │
│  (Signal transmitted via serial port)                              │
│         │                                                           │
│         ▼                                                           │
│  Arduino reader thread receives signal                             │
│         │                                                           │
│         ▼                                                           │
│  PyQt signal emitted: done_signal.emit()                           │
│         │                                                           │
│         ▼                                                           │
│  set_done() method called (line 1687)                              │
│         │                                                           │
│         ├─→ I2Cstatus = 1                                          │
│         │                                                           │
│         ├─→ I2Cstatus_event.set()                                  │
│         │                                                           │
│         └─→ enable_actuator_controls()  ◄─ KEY POINT              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ CONTROL RE-ENABLING PHASE WITH SCHEDULING                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  enable_actuator_controls() method called                          │
│         │                                                           │
│         ├─→ Check condition: if protocol_running == False          │
│         │   If True, continue; if False, EXIT                      │
│         │                                                           │
│         ├─→ PRINTS: "Scheduling controls to enable with delay..."  │
│         │           (This is the debug message!) ◄─ HERE IT IS!   │
│         │                                                           │
│         ├─→ For each widget in self.actuator_controls:             │
│         │   │                                                       │
│         │   ├─→ Create lambda: lambda widget=w: widget.setEnabled()│
│         │   │                                                       │
│         │   └─→ Schedule with timer:                               │
│         │       QTimer.singleShot(200, lambda_function)            │
│         │                                                           │
│         │   [Timer list created, all scheduled at 200ms delay]     │
│         │                                                           │
│         └─→ Return from enable_actuator_controls()                 │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │
         │ [200 milliseconds pass...]
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ BUTTON RE-ENABLING PHASE (AFTER TIMER)                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  For each lateral button (and all other actuator buttons):         │
│  Timer fires → Lambda executes:                                    │
│  widget.setEnabled(True)                                           │
│         │                                                           │
│         ├─→ forward_lateral_flexion_button.setEnabled(True)        │
│         ├─→ reverse_lateral_flexion_button.setEnabled(True)        │
│         ├─→ forward_fast_lateral_flexion_button.setEnabled(True)   │
│         ├─→ reverse_fast_lateral_flexion_button.setEnabled(True)   │
│         ├─→ reset_lateral_flexion_button.setEnabled(True)          │
│         ├─→ lateral_flexion_position_go_button.setEnabled(True)    │
│         │   [Plus all other actuator buttons]                      │
│         │                                                           │
│         └─→ All buttons now CLICKABLE again                        │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
         │
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│ READY FOR NEXT MOVEMENT                                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ✓ All control buttons enabled                                    │
│  ✓ UI updated with new position                                    │
│  ✓ Loading spinner hidden                                          │
│  ✓ Movement complete and settled                                   │
│                                                                     │
│  User can now click any button for next movement                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Control Disable/Enable State Machine

```
                        BUTTON CLICK
                             │
                             ▼
                   ┌──────────────────┐
                   │  ENABLED STATE   │
                   │  (Initial State) │
                   └──────────────────┘
                             │
                             │ disable_actuator_controls()
                             ▼
                   ┌──────────────────┐
                   │ DISABLED STATE   │
                   │  (All buttons    │
                   │   disabled)      │
                   └──────────────────┘
                             │
                             │ Arduino finishes movement,
                             │ sends "done" signal
                             │
                             ▼
                   ┌──────────────────┐
                   │ SCHEDULING STATE │
                   │  (QTimer         │
                   │   scheduled at   │
                   │   200ms delay)   │
                   └──────────────────┘
                             │
                             │ 200ms QTimer expires
                             │
                             ▼
                   ┌──────────────────┐
                   │  ENABLED STATE   │
                   │  (Ready for next │
                   │   movement)      │
                   └──────────────────┘
```

---

## 3. Data Flow: Lateral Position Update

```
┌──────────────────────────────────────────────────────────┐
│ Current State:                                            │
│ - lateral_flexion_position = 0°                          │
│ - Button: forward_lateral_flexion_button (direction = 1) │
│ - Speed: slow (5° step)                                  │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Calculation:                                              │
│ new_position = 0 + (5 * 1) = 5°                          │
│ rounded = round(5 / 2.5) * 2.5 = 5.0°                   │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Boundary Check:                                           │
│ -20 ≤ 5 ≤ 20? YES, proceed                              │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Config Lookup:                                            │
│ position_key = "5.0"                                     │
│ calibrated_pos = config.CMarks["5.0"] = 50              │
│ (Example: maps 5° to position 50 in firmware)            │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ State Update:                                             │
│ lateral_flexion_position = 5.0°                          │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ UI Update:                                                │
│ Slider: setValue(5.0)                                    │
│ Label: setText("5R°")  [5 degrees to the Right]          │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Arduino Communication:                                    │
│ Send: "K50"  [K command with position 50]                │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│ Result:                                                   │
│ - Actuator moves to 5° right                             │
│ - UI reflects new position                               │
│ - Controls re-enabled after 200ms                        │
│ - lateral_flexion_position = 5.0°                        │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Timing Diagram: Movement and Control Re-enabling

```
Time     │ Event                              │ State
─────────┼────────────────────────────────────┼──────────────────
  0ms    │ Button clicked                     │ ENABLED
         │ disable_actuator_controls() called │ → DISABLED
  5ms    │ Arduino command sent: "K50"        │ DISABLED
  10ms   │ Arduino receiving/processing       │ DISABLED
         │ Loading spinner visible            │ 
─────────┼────────────────────────────────────┼──────────────────
500ms    │ Arduino completes movement         │ DISABLED
         │ Actuator physically stops moving   │ 
─────────┼────────────────────────────────────┼──────────────────
505ms    │ Arduino sends "done" signal        │ DISABLED
  510ms  │ set_done() called                  │ DISABLED
         │ enable_actuator_controls() called  │ DISABLED
         │ Message: "Scheduling controls..."  │ → SCHEDULING
         │ QTimer.singleShot(200) scheduled   │ SCHEDULING
  515ms  │ Function returns                   │ SCHEDULING
─────────┼────────────────────────────────────┼──────────────────
  700ms  │ QTimer fires (200ms elapsed)       │ SCHEDULING
         │ Lambdas execute                    │ → ENABLED
         │ All buttons.setEnabled(True)       │ ENABLED
  705ms  │ Loading spinner hidden             │ ENABLED
─────────┼────────────────────────────────────┼──────────────────
  ...    │ User ready to click next button    │ ENABLED
```

---

## 5. Lateral Button Parameter Matrix

```
BUTTON NAME                    │ STEP │ SPEED │ DIR │ BEHAVIOR
────────────────────────────────┼──────┼───────┼─────┼─────────────────
forward_lateral_flexion         │  5°  │ "04"  │ +1  │ Slow right
reverse_lateral_flexion         │  5°  │ "04"  │ -1  │ Slow left
forward_fast_lateral_flexion    │ 10°  │ "20"  │ +1  │ Fast right
reverse_fast_lateral_flexion    │ 10°  │ "20"  │ -1  │ Fast left
────────────────────────────────┴──────┴───────┴─────┴─────────────────

Legend:
- STEP: Position change per button click (degrees)
- SPEED: Speed factor sent to Arduino
- DIR: Direction multiplier (+1 = right/forward, -1 = left/backward)
- Slow movements use 2.5° increments internally
- Fast movements use 5° increments internally
```

---

## 6. Control Hierarchy

```
                        start_or_stop_protocol()
                                 │
                    ┌────────────┴────────────┐
                    │                         │
              set protocol_running to True/False
                    │
                    ▼
         enable_actuator_controls()
                    │
        ┌───────────┴───────────┐
        │                       │
   If protocol_running:     If not protocol_running:
   └─→ EXIT (do nothing)    └─→ Schedule button re-enabling
                                │
                                ├─→ Print: "Scheduling controls..."
                                │
                                └─→ For each button in actuator_controls:
                                    ├─→ Create delayed lambda
                                    └─→ QTimer.singleShot(200ms, lambda)

                        BUTTON STATES BY CONTEXT
┌────────────────────────────────────────────────────────┐
│ During Protocol Execution (protocol_running = True):   │
│ ├─ All actuator buttons: DISABLED                      │
│ └─ Reason: Prevent manual intervention during therapy  │
├────────────────────────────────────────────────────────┤
│ During Single Movement (protocol_running = False):     │
│ ├─ Initial: ENABLED                                    │
│ ├─ During movement: DISABLED                           │
│ └─ After Arduino done: SCHEDULED for 200ms → ENABLED   │
├────────────────────────────────────────────────────────┤
│ Idle State (protocol_running = False):                 │
│ └─ All buttons: ENABLED                                │
└────────────────────────────────────────────────────────┘
```

---
