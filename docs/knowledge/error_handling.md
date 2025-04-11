# KneeSpa Error Handling Strategy

This document outlines the comprehensive error handling strategy implemented in the KneeSpa system.

## Error Classification

Errors are classified by severity and impact:

1. **Safety-Critical**: Errors that could cause physical harm
   - Pressure exceeding safe limits
   - Actuator position out of safe range
   - Communication failures during treatment

2. **Functional-Critical**: Errors that prevent basic operation
   - Arduino connection failure
   - Configuration loading failure
   - Hardware initialization issues

3. **User-Experience**: Errors that impact usability but not function
   - UI rendering issues
   - Minor communication delays
   - Non-essential sensor feedback issues

4. **Informational**: Warnings and informational messages
   - Status updates
   - Performance metrics
   - Diagnostic information

## Exception Hierarchy

The system implements a custom exception hierarchy in `utils/exceptions.py`:

```
KneeSpaException (Base)
├── ActuatorException
├── ArduinoException
│   ├── ArduinoConnectionError
│   ├── ArduinoCommandError
│   └── ArduinoTimeoutError
├── SafetyException
├── AuthenticationException
└── ConfigurationException
```

## Exception Handling Patterns

### Safety-Critical Handling

```python
try:
    # Safety-critical operation
    self.set_to_pressure(pressure)
except SafetyException as e:
    # Log with highest priority
    logging.critical(f"SAFETY CRITICAL: {str(e)}")
    # Immediate emergency stop
    self.arduino.send("X")
    # Notify user with visual and audible alert
    QMessageBox.critical(
        self, "SAFETY ALERT", 
        f"Emergency stop triggered: {str(e)}"
    )
    # Signal to main application
    self.signals.emergency_stop.emit()
```

### Functional-Critical Handling

```python
try:
    # Critical functional operation
    self.arduino.connect()
except ArduinoConnectionError as e:
    # Log with high priority
    logging.error(f"CONNECTION ERROR: {str(e)}")
    # Attempt automatic recovery
    for attempt in range(3):
        try:
            self.arduino.reconnect()
            break
        except Exception:
            continue
    # If recovery fails, notify user
    if not self.arduino.connected:
        QMessageBox.critical(
            self, "Connection Error",
            "Could not establish connection to hardware."
        )
```

### User-Experience Error Handling

```python
try:
    # UI operation
    self.update_ui_elements()
except Exception as e:
    # Log with medium priority
    logging.warning(f"UI WARNING: {str(e)}")
    # Continue operation with fallback
    self.use_fallback_ui()
    # Optional user notification
    self.ui.status_label.setText(f"Display issue: {str(e)}")
```

### Informational Error Handling

```python
try:
    # Non-critical operation
    self.update_status_display()
except Exception as e:
    # Log with low priority
    logging.info(f"STATUS UPDATE ISSUE: {str(e)}")
    # Silent recovery
    pass
```

## Exception Propagation

Exceptions follow these propagation rules:

1. **Low-Level Components**: Raise specific exceptions
2. **Mid-Level Components**: Catch, handle, and re-raise if needed
3. **High-Level Components**: Provide user-friendly error messages

```python
# Low-level component
def send_command(self, command):
    try:
        self.serial_com.write(command)
    except serial.SerialException as e:
        raise ArduinoCommandError(f"Failed to send command: {str(e)}")

# Mid-level component
def execute_command(self, command):
    try:
        self.send_command(command)
    except ArduinoCommandError as e:
        # Handle or propagate
        if is_safety_critical(command):
            raise SafetyException(f"Critical command failed: {str(e)}")
        else:
            logging.error(f"Command error: {str(e)}")
            return False
    return True

# High-level component
def on_button_click(self):
    try:
        self.execute_command("P50")
    except SafetyException as e:
        QMessageBox.critical(self, "Safety Error", str(e))
    except Exception as e:
        QMessageBox.warning(self, "Error", f"An error occurred: {str(e)}")
```

## Arduino Communication Error Recovery

The Arduino communication module implements sophisticated error recovery:

1. **Connection Loss Detection**:
   ```python
   def verify_connection(self):
       """Verify Arduino communication is working."""
       tries = 0
       max_tries = 4

       while tries < max_tries:
           try:
               # Send test command and verify response
               self.serial_com.write(b"T\n")
               response = self.serial_com.readline().decode()
               if "OK" in response or "Ready" in response:
                   return True
               tries += 1
               time.sleep(1)
           except Exception:
               tries += 1
               time.sleep(1)
       return False
   ```

2. **Reconnection Strategy**:
   ```python
   def reconnect(self):
       """Attempt to reestablish Arduino connection if lost."""
       print("Attempting to reconnect to Arduino...")
       
       # Use only ttyS0 for Raspberry Pi hardware serial
       port = "/dev/ttyS0"
       
       if os.path.exists(port):
           # Try reconnection up to 3 times
           for attempt in range(3):
               if self.try_connect_to_port(port):
                   # Send emergency stop after reconnection
                   self.send("X")
                   return True
               time.sleep(2)
       return False
   ```

3. **Command Retries**:
   ```python
   def send(self, command):
       """Send a command with retry logic."""
       # Check connection first
       if not self.connected:
           if not self.reconnect():
               return False

       max_retries = 3
       for attempt in range(max_retries):
           try:
               self.serial_com.write(f"{command}\n".encode())
               self.serial_com.flush()
               return True
           except Exception as e:
               if attempt == max_retries - 1:
                   self.connected = False
                   return False
               time.sleep(0.5)
       return False
   ```

## Protocol Error Handling

The protocol system implements additional safety checks:

1. **Duration Monitoring**:
   ```python
   def check_duration(self):
       """Check if protocol duration has expired."""
       if not self.start_time:
           return False

       self.elapsed_time = time.time() - self.start_time
       return self.elapsed_time < self.duration
   ```

2. **Position Safety Limits**:
   ```python
   def set_to_angle(self, degrees):
       """Set lateral flexion to specified angle with safety limits."""
       try:
           # Validate angle is within safe limits
           if degrees < -20 or degrees > 20:
               from utils.exceptions import SafetyLimitException
               raise SafetyLimitException(
                   f"Angle {degrees} outside safe range (-20 to 20)",
                   severity="HIGH",
                   limit_type="angle",
                   current_value=degrees,
                   limit_value=20
               )
           
           # Proceed with setting angle
           # ...
       except Exception as e:
           # Log and signal error
           return False
   ```

3. **Pressure Safety Limits**:
   ```python
   def set_to_pressure(self, pressure):
       """Set axial pressure with safety limits."""
       try:
           # Validate pressure is within safe limits
           if pressure < 0 or pressure > MAX_SAFE_PRESSURE:
               from utils.exceptions import SafetyLimitException
               raise SafetyLimitException(
                   f"Pressure {pressure} outside safe range (0-{MAX_SAFE_PRESSURE})",
                   severity="HIGH",
                   limit_type="pressure",
                   current_value=pressure,
                   limit_value=MAX_SAFE_PRESSURE
               )
           
           # Proceed with setting pressure
           # ...
       except Exception as e:
           # Log and signal error
           return False
   ```

## UI Error Handling

The UI implements user-friendly error messages:

1. **Error Dialog Factory**:
   ```python
   def show_error_dialog(self, error, title=None, details=None):
       """Show appropriate error dialog based on error type."""
       if isinstance(error, SafetyException):
           icon = QMessageBox.Critical
           default_title = "Safety Alert"
       elif isinstance(error, ArduinoException):
           icon = QMessageBox.Warning
           default_title = "Communication Error"
       else:
           icon = QMessageBox.Information
           default_title = "Notice"

       title = title or default_title
       
       msg_box = QMessageBox(icon, title, str(error), parent=self)
       if details:
           msg_box.setDetailedText(details)
       msg_box.exec_()
   ```

2. **Error Handling in Event Handlers**:
   ```python
   @handle_exception
   def start_or_stop_protocol(self):
       """Start or stop protocol with error handling."""
       if self.start_button.text() == "Start":
           self.start_button.setText("Stop")
           self.start_protocol()
       else:
           self.start_button.setText("Start")
           self.stop_protocol()
   ```

## Logging Strategy

The system implements a comprehensive logging strategy:

```python
def setup_logger(component=None):
    """Setup logger with appropriate handlers."""
    logger = logging.getLogger(component or __name__)
    logger.setLevel(logging.DEBUG)
    
    # File handler for all logs
    file_handler = logging.FileHandler("logs/kneespa.log")
    file_handler.setLevel(logging.DEBUG)
    
    # File handler for errors only
    error_handler = logging.FileHandler("logs/error.log")
    error_handler.setLevel(logging.ERROR)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    error_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger
```

## Future Error Handling Enhancements

Potential enhancements to the error handling system:

1. **Telemetry**: Remote error reporting and monitoring
2. **Predictive Error Detection**: ML-based early warning system
3. **Enhanced Recovery Strategies**: More sophisticated auto-recovery
4. **Error Analytics**: Analysis of error patterns for system improvements
