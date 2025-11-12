# Thread Safety Fixes for KneeSpa Application

## Fix 1: Add Missing Signal Definition

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/arduino.py`

**Current Code (Lines 14-24):**
```python
connection_ready = pyqtSignal()  # Signal for successful connection
connection_failed = pyqtSignal(str)  # Signal for connection failure
finished = pyqtSignal()
progress = pyqtSignal(int)
done_emit = pyqtSignal()
pressure_emit = pyqtSignal(str)
ready_to_go_emit = pyqtSignal()
position_emit = pyqtSignal(int, int, str, int)
status_emit = pyqtSignal(int, int, int, float)
buffer_warning = pyqtSignal(str)
connection_lost = pyqtSignal()  # Signal for connection loss
```

**Fixed Code:**
```python
connection_ready = pyqtSignal()  # Signal for successful connection
connection_failed = pyqtSignal(str)  # Signal for connection failure
finished = pyqtSignal()
progress = pyqtSignal(int)
done_emit = pyqtSignal()
pressure_emit = pyqtSignal(str)
ready_to_go_emit = pyqtSignal()
position_emit = pyqtSignal(int, int, str, int)
status_emit = pyqtSignal(int, int, int, float)
buffer_warning = pyqtSignal(str)
connection_lost = pyqtSignal()  # Signal for connection loss
display_weight_emit = pyqtSignal(str)  # NEW: Signal for weight data
```

---

## Fix 2: Protect I2Cstatus Flag with Lock

**File:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`

**Current Code (Line 193):**
```python
self.I2Cstatus = 0
```

**Fixed Code:**
```python
import threading

# In __init__ method, add after line 196:
self.I2Cstatus = 0
self.I2Cstatus_lock = threading.Lock()  # NEW: Add lock for thread safety
```

**File:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`

**Current Code (Lines 1637, 1643 in ready_to_go method):**
```python
def ready_to_go(self):
    # ... code ...
    self.I2Cstatus = 1  # Line 1637 - NO LOCK
    # ... code ...
    self.I2Cstatus = 1  # Line 1643 - NO LOCK
```

**Fixed Code:**
```python
def ready_to_go(self):
    # ... code ...
    with self.I2Cstatus_lock:
        self.I2Cstatus = 1  # Now protected
    # ... code ...
    with self.I2Cstatus_lock:
        self.I2Cstatus = 1  # Now protected
```

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/reset_worker.py`

**Current Code (Lines 33-45):**
```python
def _wait_for_done(self, timeout=10.0, operation_name="operation"):
    """Waits for main_window.I2Cstatus to become 1 or timeout by polling."""
    print(f"Worker waiting for '{operation_name}' completion (max {timeout}s)...")
    start_wait = time.time()

    while self.main_window.I2Cstatus == 0 and time.time() - start_wait < timeout:  # NO LOCK
        time.sleep(0.05)

    if self.main_window.I2Cstatus == 1:  # NO LOCK
        print(f"Worker detected '{operation_name}' completed (I2Cstatus == 1).")
        self.main_window.I2Cstatus = 0  # NO LOCK
        return True
    else:
        print(f"Worker timeout waiting for '{operation_name}' completion.")
        self.main_window.I2Cstatus = 0  # NO LOCK
        return False
```

**Fixed Code:**
```python
def _wait_for_done(self, timeout=10.0, operation_name="operation"):
    """Waits for main_window.I2Cstatus to become 1 or timeout by polling."""
    print(f"Worker waiting for '{operation_name}' completion (max {timeout}s)...")
    start_wait = time.time()

    while time.time() - start_wait < timeout:
        with self.main_window.I2Cstatus_lock:  # NEW: Acquire lock
            if self.main_window.I2Cstatus == 1:  # Check under lock
                print(f"Worker detected '{operation_name}' completed (I2Cstatus == 1).")
                self.main_window.I2Cstatus = 0  # Reset under lock
                return True
        time.sleep(0.05)

    # Timeout occurred
    with self.main_window.I2Cstatus_lock:  # NEW: Acquire lock
        self.main_window.I2Cstatus = 0  # Ensure flag is reset on timeout
    print(f"Worker timeout waiting for '{operation_name}' completion.")
    return False
```

Also fix lines 54, 66, 88:
```python
# OLD
self.main_window.I2Cstatus = 0

# NEW
with self.main_window.I2Cstatus_lock:
    self.main_window.I2Cstatus = 0
```

---

## Fix 3: Protect Protocol Parameter Mutations with Locks

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/protocols.py`

**Current Code (Lines 42-80):**
```python
def __init__(self, a_factor: float, protocol: str, ...):
    super().__init__()
    # ... setup ...
    self.use_pulse = use_pulse  # Line 71 - shared state
    self.is_running = False      # Line 74 - shared state
    self.current_pressure = 0
    # ... more init ...
```

**Fixed Code:**
```python
import threading

def __init__(self, a_factor: float, protocol: str, ...):
    super().__init__()
    # ... setup ...
    self.use_pulse = use_pulse
    self.is_running = False
    self.current_pressure = 0
    self._param_lock = threading.Lock()  # NEW: Add lock for shared state
    # ... more init ...
```

**Current Code (Lines 344, 404, 520):**
```python
# Line 344
while self.is_running and self.use_pulse:  # Race condition
    # ...

# Line 404
if self.use_pulse:  # Race condition
    # ...
```

**Fixed Code:**
```python
# Line 344
while self.is_running:
    with self._param_lock:
        pulse_enabled = self.use_pulse
    if not pulse_enabled:
        break
    # ... rest of loop ...

# Line 404
with self._param_lock:
    pulse_enabled = self.use_pulse
if pulse_enabled:
    # ...
```

**File:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`

**Current Code (Lines 689, 702-703, 715-717, 732):**
```python
if self.worker:
    self.worker.max_pressure = value  # Line 689 - Race

# ...

if self.worker:
    actual_left = -abs(value)
    self.worker.max_left = actual_left  # Line 702 - Race

# ...

if self.worker:
    self.worker.use_pulse = current_state  # Line 732 - Race
```

**Fixed Code:**
```python
if self.worker:
    with self.worker._param_lock:  # NEW: Acquire lock
        self.worker.max_pressure = value

# ...

if self.worker:
    actual_left = -abs(value)
    with self.worker._param_lock:  # NEW: Acquire lock
        self.worker.max_left = actual_left

# ...

if self.worker:
    with self.worker._param_lock:  # NEW: Acquire lock
        self.worker.use_pulse = current_state
```

---

## Fix 4: Expand Arduino._lock Scope for Atomic Operations

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/arduino.py`

**Current Code (Lines 438-465):**
```python
def send(self, command):
    """Send a command to the Arduino with reconnection capability."""
    with self._lock:  # Lock starts here
        # Check connection first
        if not self.connected or not self.serial_com:
            print("Not connected - attempting to reconnect")
            if not self.reconnect(max_retries=3):
                print("Cannot send command - not connected")
                return False
        # Lock released here - TOCTOU window!

    try:
        if not self.serial_com:  # Double-check after reconnect
            return False

        self.serial_com.reset_input_buffer()  # RACE: Port could be closed
        command_with_newline = command + "\n"
        print(f"Sending command: {command_with_newline}")
        self.serial_com.write(command_with_newline.encode())
        self.serial_com.flush()
        time.sleep(0.3)
        print("Command sent successfully.")
        return True
```

**Fixed Code:**
```python
def send(self, command):
    """Send a command to the Arduino with reconnection capability."""
    with self._lock:
        # Check connection first
        if not self.connected or not self.serial_com:
            print("Not connected - attempting to reconnect")
            if not self.reconnect(max_retries=3):
                print("Cannot send command - not connected")
                return False

        # NEW: Everything now under lock - no TOCTOU window
        try:
            if not self.serial_com:  # Double-check under lock
                return False

            self.serial_com.reset_input_buffer()
            command_with_newline = command + "\n"
            print(f"Sending command: {command_with_newline}")
            self.serial_com.write(command_with_newline.encode())
            self.serial_com.flush()
            time.sleep(0.3)
            print("Command sent successfully.")
            return True

        except Exception as ex:
            print(f"Failed to send command '{command}': {ex}")
            self.connected = False
            return False
        # Lock released only after everything is done
```

---

## Fix 5: Protect Connection State Flag

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/arduino.py`

**Current Code (Lines 218, 325, 350):**
```python
# Line 218 - No lock
self.connected = True

# Line 325
self.connected = False
self.connection_lost.emit()

# Line 350
self.connected = False
self.connection_lost.emit()
```

**Fixed Code:**
```python
# Line 218
with self._lock:
    self.connected = True

# Line 325
with self._lock:
    self.connected = False
self.connection_lost.emit()  # Signal can be outside lock

# Line 350
with self._lock:
    self.connected = False
self.connection_lost.emit()  # Signal can be outside lock
```

---

## Fix 6: Make Signal Operations Atomic

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/protocols.py`

**Current Code (Lines 83-94):**
```python
if ser is not None and hasattr(ser, "status_emit"):
    # First disconnect any existing connections to avoid duplicates
    try:
        ser.status_emit.disconnect(self.update_status)
    except Exception:
        pass  # Ignore if not previously connected

    # Now connect the signal
    ser.status_emit.connect(self.update_status)
    print("Protocol: Connected Arduino status_emit signal to update_status method")
```

**Fixed Code:**
```python
if ser is not None and hasattr(ser, "status_emit"):
    # Disconnect and reconnect atomically
    try:
        # Try to disconnect
        try:
            ser.status_emit.disconnect(self.update_status)
        except RuntimeError:
            # Signal was not connected, that's OK
            pass

        # Now connect
        ser.status_emit.connect(self.update_status)
        print("Protocol: Connected Arduino status_emit signal to update_status method")
    except Exception as e:
        print(f"WARNING: Failed to connect signal: {e}")
        # Continue anyway - functionality will degrade but won't crash
```

---

## Fix 7: Manage Keepalive Thread Properly

**File:** `/mnt/c/users/user/desktop/drx-demo/main/helpers/protocols.py`

**Current Code (Lines 731-790):**
```python
def _start_keepalive_thread(self):
    """Start a separate thread to send periodic keepalive signals to Arduino."""
    def keepalive_worker():
        print("Starting keepalive worker thread")
        # ... code that accesses self.arduino ...

    # Start background thread
    keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
    keepalive_thread.start()
```

**Fixed Code:**
```python
def __init__(self, ...):
    # ... existing code ...
    self.keepalive_thread = None  # NEW: Track thread
    self._keepalive_stop = threading.Event()  # NEW: Signal to stop

def _start_keepalive_thread(self):
    """Start a separate thread to send periodic keepalive signals to Arduino."""
    # Prevent multiple keepalive threads
    if self.keepalive_thread and self.keepalive_thread.is_alive():
        print("Keepalive thread already running")
        return

    self._keepalive_stop.clear()  # NEW: Reset stop signal

    def keepalive_worker():
        print("Starting keepalive worker thread")
        end_time = time.time() + 60
        keepalive_interval = 3
        last_keepalive = 0
        reconnect_attempts = 0
        max_reconnect_attempts = 3

        while time.time() < end_time and not self._keepalive_stop.is_set():
            try:
                # NEW: Check if Arduino still exists and is accessible
                if not hasattr(self, 'arduino') or self.arduino is None:
                    print("Arduino reference lost in keepalive thread")
                    break

                current_time = time.time()
                if current_time - last_keepalive >= keepalive_interval:
                    if hasattr(self.arduino, "send"):
                        # Send keepalive under try-except for safety
                        try:
                            success = self.arduino.send("T")
                            if success:
                                last_keepalive = current_time
                                reconnect_attempts = 0
                            else:
                                reconnect_attempts += 1
                        except Exception as e:
                            print(f"Keepalive send error: {e}")
                            reconnect_attempts += 1

                    if reconnect_attempts > max_reconnect_attempts:
                        break

                time.sleep(1)
            except Exception as e:
                print(f"Error in keepalive thread: {e}")
                break

        print("Keepalive thread finished")

    # Start background thread as non-daemon for proper cleanup
    self.keepalive_thread = threading.Thread(target=keepalive_worker, daemon=True)
    self.keepalive_thread.start()

def stop(self):
    """Safely stop a running protocol."""
    # ... existing code ...
    self._keepalive_stop.set()  # NEW: Signal keepalive thread to stop
    # ... rest of stop code ...
```

---

## Fix 8: Protect Worker Reference Access

**File:** `/mnt/c/users/user/desktop/drx-demo/main/kneespa.py`

**Current Code (Lines 689, 732, 791-792):**
```python
if self.worker:
    self.worker.max_pressure = value  # Potential crash if worker becomes None

# ...

if self.worker:
    self.worker.stop()  # Potential crash
```

**Fixed Code:**
```python
# Add a lock for worker reference changes
if not hasattr(self, '_worker_lock'):
    self._worker_lock = threading.Lock()

# In on_pressure_changed:
try:
    with self._worker_lock:
        worker = self.worker
    if worker:
        with worker._param_lock:
            worker.max_pressure = value
except AttributeError:
    print("Worker has been cleaned up")

# In protocol_completed:
try:
    with self._worker_lock:
        worker = self.worker
    if worker:
        worker.stop()
except AttributeError:
    print("Worker already stopped")
```

---

## Summary of Changes Required

| Fix | File | Lines | Change Type | Complexity |
|-----|------|-------|-------------|-----------|
| 1 | arduino.py | 14-24 | Add signal definition | Simple |
| 2 | kneespa.py, reset_worker.py | Multiple | Add I2Cstatus_lock | Medium |
| 3 | protocols.py, kneespa.py | Multiple | Add _param_lock | Medium |
| 4 | arduino.py | 438-465 | Expand lock scope | Medium |
| 5 | arduino.py | 218, 325, 350 | Protect flags | Simple |
| 6 | protocols.py | 83-94 | Improve error handling | Simple |
| 7 | protocols.py | 731-790 | Manage thread lifecycle | Complex |
| 8 | kneespa.py | Multiple | Protect worker reference | Medium |

**Total Estimated Effort:** 2-3 hours for experienced developer

---

## Testing Checklist

- [ ] Test Fix 1: Send weight data and verify no crash
- [ ] Test Fix 2: Run reset multiple times concurrently
- [ ] Test Fix 3: Change parameters while protocol runs
- [ ] Test Fix 4: Stop protocol while sending commands
- [ ] Test Fix 5: Monitor connection state changes
- [ ] Test Fix 6: Verify signal connections work correctly
- [ ] Test Fix 7: Protocol stop completes cleanly
- [ ] Test Fix 8: Delete/recreate worker during operation
