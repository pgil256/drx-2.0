# KneeSpa Protocol Implementations

This document details the implementation of the three therapeutic protocols used in the KneeSpa system.

## Common Protocol Components

All protocols share these common elements:

- **Duration**: User-configurable (1-60 minutes)
- **Safety Checks**: Position and pressure monitoring
- **Reset Sequence**: Initialization and completion reset
- **Status Feedback**: Regular actuator status monitoring

## Protocol 1: Axial Pressure

Protocol 1 applies axial pressure with a static 15-degree flexion angle.

### Implementation Steps

1. **Initialization**
   ```python
   def protocol_1(self):
       """Axial protocol - pressure only with static 15-degree flexion."""
       if not self.check_duration():
           return

       # Reset to starting state
       self.signals.reset_needed.emit()
       time.sleep(2)
   ```

2. **Set Standard Flexion Angle**
   ```python
   # Set standard 15-degree flexion angle
   if not self.set_to_angle(15.0):
       self.signals.finished.emit(False)
       return
       
   # Wait to ensure angle is stable
   time.sleep(2)
   ```

3. **Initial Pressure Application**
   ```python
   # Start with minimal pressure
   current_pressure = MIN_PRESSURE
   if not self.set_to_pressure(current_pressure):
       self.signals.finished.emit(False)
       return

   self.exit_flag.wait(timeout=HOLD_TIME_SHORT)
   ```

4. **Pressure Ramping**
   ```python
   # Gradually increase to max pressure
   while (current_pressure < self.max_pressure
          and self.is_running
          and self.check_duration()):
       current_pressure = min(
           current_pressure + PRESSURE_INCREMENT, 
           self.max_pressure
       )
       if not self.set_to_pressure(current_pressure):
           self.signals.finished.emit(False)
           return
           
       # Periodically verify we're still at 15 degrees
       if current_pressure % 15 == 0:
           self.set_to_angle(15.0)

       self.exit_flag.wait(timeout=HOLD_TIME_SHORT)
   ```

5. **Pulsing or Holding**
   ```python
   # Option 1: Apply pulsing
   if self.is_running and self.use_pulse:
       if not self.apply_continuous_pulse():
           self.signals.reset_needed.emit()
           self.signals.finished.emit(False)
           return
   # Option 2: Hold at max pressure
   elif self.is_running:
       while self.is_running and self.check_duration():
           self.exit_flag.wait(timeout=HOLD_TIME_LONG)
           # Periodic status check and angle verification
           if self.is_running and self.check_duration():
               self.arduino.send("S")
               time.sleep(0.5)
               if (time.time() - self.start_time) % 60 < 1:
                   self.set_to_angle(15.0)
   ```

6. **Protocol Completion**
   ```python
   # Reset actuators after protocol completes
   self.set_to_pressure(0)
   time.sleep(2)
   self.set_to_angle(0)
   self.signals.reset_needed.emit()
   self.signals.finished.emit(True)
   ```

## Protocol 2: Left Lateral Flexion

Protocol 2 applies axial pressure with left lateral movement at static 15-degree flexion.

### Implementation Differences from Protocol 1

1. **Initial Setup (Same as Protocol 1)**
   - Reset actuators, set 15-degree flexion, start with minimal pressure

2. **Apply Left Lateral Angle After Pressure**
   ```python
   # Once at pressure, move to left lateral angle
   if self.is_running:
       # IMPORTANT: Apply lateral movement now that pressure is stable
       print(f"Moving to left lateral angle {self.max_left}°.")
       if not self.set_to_angle(self.max_left):
           self.signals.finished.emit(False)
           return
           
       # Extra wait to ensure lateral position is stable
       time.sleep(3)
   ```

3. **Pulsing or Holding with Lateral Angle**
   - Same logic as Protocol 1, but while maintaining left lateral angle

4. **Protocol Completion**
   ```python
   # First reset lateral angle back to center
   self.set_to_angle(0)
   time.sleep(2)
   
   # Then zero pressure
   self.set_to_pressure(0)
   time.sleep(2)
   ```

## Protocol 3: Right Lateral Flexion

Protocol 3 applies axial pressure with right lateral movement at static 15-degree flexion.

### Implementation Differences from Protocol 2

1. **Initial Setup (Same as Protocol 1 & 2)**
   - Reset actuators, set 15-degree flexion, start with minimal pressure

2. **Apply Right Lateral Angle After Pressure**
   ```python
   # Once at pressure, move to right lateral angle
   if self.is_running:
       # IMPORTANT: Apply lateral movement now that pressure is stable
       print(f"Moving to right lateral angle {self.max_right}°.")
       if not self.set_to_angle(self.max_right):
           self.signals.finished.emit(False)
           return
   ```

3. **Pulsing or Holding with Lateral Angle**
   - Same logic as Protocol 2, but using right lateral angle

4. **Protocol Completion (Same as Protocol 2)**
   - Reset lateral angle to center, then zero pressure

## Continuous Pulse Implementation

```python
def apply_continuous_pulse(self) -> bool:
    """Apply continuous pulse sequence until duration expires."""
    if not self.is_running or not self.use_pulse:
        return True

    try:
        # Send initial jerking command to Arduino
        self.arduino.send("J")
        self.signals.progress.emit(">>Pulsing")

        # Monitor until protocol completes or is stopped
        while self.is_running and self.check_duration():
            # Brief check interval
            time.sleep(0.5)

        # Stop jerking when done
        self.arduino.send("JS")  # Stop jerking
        time.sleep(1)
        return True

    except Exception as e:
        self.arduino.send("JS")  # Try to stop jerking even on error
        return False
```

## Safety Monitoring

Each protocol includes continuous safety monitoring:

```python
def update_status(self, pos_a, pos_b, pos_c, pressure):
    """Update current status values from Arduino feedback."""
    self.current_pressure = pressure
    # Forward pressure to UI if needed
    self.signals.pressure_emit.emit(float(pressure))

def check_duration(self):
    """Check if protocol duration has expired."""
    if not self.start_time:
        return False

    self.elapsed_time = time.time() - self.start_time
    return self.elapsed_time < self.duration
```

## Error Handling and Recovery

The protocol implementation includes robust error handling:

1. **Function Return Values**: All critical functions return boolean success/failure
2. **Exception Handling**: Try/except blocks around all hardware communication
3. **Signal-Based Error Reporting**: WorkerSignals for error communication
4. **Emergency Reset**: Reset sequence on critical errors

## Protocol Parameters

Each protocol utilizes these configurable parameters:

- **max_pressure**: Maximum pressure in pounds (10-80)
- **max_left**: Maximum left lateral angle in degrees (0-20)
- **max_right**: Maximum right lateral angle in degrees (0-20)
- **duration**: Protocol duration in minutes (1-60)
- **use_pulse**: Boolean flag to enable pulsing motion
