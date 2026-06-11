/*
  Arduino Motor Controller for KneeSpa - FIXED VERSION
  Controls axial, horizontal, and lateral actuators
  Based on DroneBot Workshop 2019 i2c_slave_ard.ino

  Bug fixes applied:
  - Fixed jerking counter logic
  - Added break statement in case 'F'
  - Improved command buffer handling
  - Fixed Wire communication delays
  - Added boundary checks
  - Improved status management
  - Fixed STOP pin logic (INPUT_PULLUP reads HIGH when not pressed)
*/

#define VERSION "2026-06-11-FAILSAFE-1"
#ifndef UNIT_TEST
// Hardware libraries; native unit tests supply mocks and arduino_shim.h
// (see test/) before including this file
#include "HX711.h"
#include <elapsedMillis.h>
#include <Wire.h>
#include <avr/wdt.h>
#endif

// Watchdog: reboots the MCU if loop() hangs (e.g. wedged I2C or load
// cell). NOTE: verify on hardware that the installed Mega bootloader
// recovers from WDT resets (old stk500v2 bootloaders boot-loop); set to
// 0 only if the bootloader cannot be updated.
#define ENABLE_WDT 1

// Pin definitions
#define LOADCELL_DOUT_PIN  7
#define LOADCELL_SCK_PIN   6
#define STOP_PIN           3
#define SPEED_PIN_A        9
#define DIR_FIT_FORWARD    4
#define DIR_FIT_REVERSE    5
#define DIR_A_FORWARD      30
#define DIR_A_REVERSE      31
#define A_ANALOG           A0

// Actuator constants
#define AFULLINCH          430
#define BFULLINCH          620
#define CFULLINCH          1880
#define PRESSURE_SPEED     500
#define BC_SPEED           800
#define C_SPEED            800
#define MAX_JERKS          10
#define FIT_SLOW_DELAY     (0.5 * 1000)
#define FIT_FAST_DELAY     (6 * 1000)
#define LOOP_STATUS_DELAY  5000
#define MIN_PRESSURE_LBS   0
#define MAX_PRESSURE_LBS   80
#define AXIAL_MIN_POS      0
#define AXIAL_MAX_POS      4600
#define HORIZONTAL_MIN_POS 50
#define HORIZONTAL_MAX_POS 4500
#define LATERAL_MIN_POS    500
#define LATERAL_MAX_POS    2400

// Command buffer size (increased for safety)
#define MAX_COMMAND_LENGTH 100

// Fail-safe parameters
#define HEARTBEAT_TIMEOUT     3000   // ms without host traffic while active -> stop
#define SCALE_READ_TIMEOUT    500    // ms without HX711 ready while load matters -> fault
#define PRESSURE_RELEASE_LBS  5.0    // autonomous release target after a fault
#define RELEASE_TIMEOUT       15000  // ms bound on the autonomous release move
#define PRESSURE_MOVE_TIMEOUT 30000  // ms bound on any single pressure move
#define PRESSURE_STALL_MS     5000   // ms without pressure progress -> fault
#define PRESSURE_STALL_DELTA  0.5    // lbs of progress expected within that window
#define HX711_SATURATED       8388607L  // 24-bit ADC saturation magnitude
#define POSITION_DEADBAND     25     // counts: symmetric close-enough band
#define ACTIVE_STATUS_INTERVAL 1000  // ms: status cadence during motion (non-HF)

// Status protection
volatile bool isProcessingStatus = false;
unsigned long lastCommandTime = 0;
const unsigned long MIN_COMMAND_INTERVAL = 200; // ms
unsigned long statusStartTime = 0;
bool statusAcknowledged = true; // Start with true so first status is sent
unsigned long lastStatusTime = 0;
const unsigned long STATUS_TIMEOUT = 2000; // Force-reset acknowledgment after 2 seconds


// Load cell setup
HX711 scale;
float calibration_factor = -4360.14;
float pressure = 0;          // filtered magnitude used by control/safety logic
float signedPressure = 0;    // filtered signed value (negative = wiring/drift fault)

// Non-blocking load-cell sampling state
float pressureSamples[3] = {0, 0, 0};
uint8_t pressureSampleIndex = 0;
uint8_t pressureSampleCount = 0;
unsigned long lastScaleReady = 0;    // last time the HX711 had data for us

// Fail-safe state
unsigned long lastHostTraffic = 0;   // last byte received from the Pi
bool releasingPressure = false;      // autonomous post-fault release active
unsigned long releaseStart = 0;
unsigned long pressureMoveStart = 0; // start of current pressure move
unsigned long pressureProgressTime = 0;
float pressureProgressValue = 0;
bool positionReadValid = false;      // last readPosition() I2C result ok

// Global variables
uint8_t smcDeviceNumber = 13;
int AZERO = 0;
int BZERO = 0;
int CZERO = 0;
int AInches = 0;
int BInches = 0;
float CInches = 0;
bool STOP = false;
bool bRunning = false;
bool measurePressure = false;
int forward = 1;
float desiredPressure = 0;
int pressureDirection = 0;
uint16_t position = 0;
uint16_t desiredPosition = 3;
bool highFrequencyStatus = false;
elapsedMillis timeSinceLastStatus = 0; // Timer for high-frequency updates
const unsigned long HIGH_FREQ_INTERVAL = 1000; // ms for frequent updates (adjust as needed)

// Command handling
String commandBuffer = "";
bool isCommandComplete = false;

// Timer tracking
unsigned long loopPosition = 0;

// Protocol variables
elapsedMillis timeInFIT = 0;
int FITDelay = 0;
bool moveFITForward = false;

// Jerking variables - FIXED
bool jerking = false;
int jerkDirection = 1;
int jerksCompleted = 0;
unsigned long lastJerkTime = 0;
const unsigned long jerkInterval = 200;  // Reduced from 400ms to 200ms for subtler jerking motion
bool jerkDirectionChanged = false;

// Makes Arduino restart
void(* resetFunc) (void) = 0;

// Required to allow motors to move
void exitSafeStart() {
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0x83);  // Exit safe start
  Wire.endTransmission();
}

// Set motor speed and direction
void setMotorSpeed(int16_t speed) {
  // Clamp speed to valid range
  if (speed > 3200) speed = 3200;
  if (speed < -3200) speed = -3200;

  // Log speed setting
  Serial.print("Set motor speed on: ");
  Serial.print(smcDeviceNumber);
  Serial.print(" at ");
  Serial.println(speed);

  // Determine direction
  uint8_t cmd = 0x85;  // Motor forward
  if (speed < 0) {
    cmd = 0x86;  // Motor reverse
    speed = -speed;
  }

  // Send command to motor controller
  exitSafeStart();
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(cmd);
  Wire.write(speed & 0x1F);
  Wire.write(speed >> 5 & 0x7F);
  Wire.endTransmission();
}

// Read actuator position once over I2C; returns true on success
static bool readPositionOnce(uint16_t &out) {
  // Request position from controller
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0xA1);  // Command: Get variable
  Wire.write(12);    // Variable ID: position signed
  Wire.endTransmission();

  // Read response with timeout
  unsigned long startTime = millis();
  while (Wire.available() < 2 && millis() - startTime < 50) {
    delay(1); // Short delay to prevent blocking
  }

  int returned = Wire.requestFrom(smcDeviceNumber, (uint8_t)2);
  if (returned != 2) {
    Serial.print("Wire error on device ");
    Serial.print(smcDeviceNumber);
    Serial.print(", returned: ");
    Serial.println(returned);
    return false;
  }

  // Process position data
  uint16_t value = Wire.read();
  value = (value + (Wire.read() << 8)); // Fixed bit shift

  // Sanity check on position value
  if (value > 65000) // Invalid value
    return false;

  out = value;
  return true;
}

// Read actuator position - retries once; on persistent failure returns
// the last good value for this device and clears positionReadValid so
// callers do not make safety decisions on garbage (0 used to be both
// the error value and a legal position)
uint16_t lastGoodPosition[3] = {0, 0, 0};  // indexed by device - 12

uint16_t readPosition() {
  uint16_t value = 0;
  positionReadValid = readPositionOnce(value) || readPositionOnce(value);

  uint8_t idx = 0;
  if (smcDeviceNumber >= 12 && smcDeviceNumber <= 14)
    idx = smcDeviceNumber - 12;

  if (positionReadValid) {
    lastGoodPosition[idx] = value;
    return value;
  }
  return lastGoodPosition[idx];
}

// Parse string with separator
String getValue(String data, char separator, int index) {
  int found = 0;
  int strIndex[] = {0, -1};
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

// Send status information to Serial and Serial1
bool sendStatus() {
  // Skip if status already in progress or not acknowledged (within timeout)
  if (isProcessingStatus || (!statusAcknowledged && millis() - lastStatusTime < STATUS_TIMEOUT))
    return false;

  isProcessingStatus = true;
  statusStartTime = millis();

  uint8_t lastSmcDeviceNumber = smcDeviceNumber;
  uint16_t positionA = 0;
  uint16_t positionB = 0;
  uint16_t positionC = 0;

  // Read all actuator positions
  smcDeviceNumber = 12;
  positionA = readPosition();
  smcDeviceNumber = 13;
  positionB = readPosition();
  smcDeviceNumber = 14;
  positionC = readPosition();

  // Pressure comes from the continuously-maintained filtered value;
  // never block on the HX711 inside status (it stalls the safety loop)

  // Log to Serial for debugging
  Serial.print(F("status: "));
  Serial.print(F(" 12: "));
  Serial.print(positionA);
  Serial.print(F(" 13: "));
  Serial.print(positionB);
  Serial.print(F(" 14: "));
  Serial.print(positionC);
  Serial.print(F(" pressure: "));
  Serial.println(pressure);

  // Send to Serial1 (Pi communication)
  Serial1.print("STATUS_START|S|");
  Serial1.print(positionA);
  Serial1.print("|");
  Serial1.print(positionB);
  Serial1.print("|");
  Serial1.print(positionC);
  Serial1.print("|");
  Serial1.print(pressure);
  Serial1.println("|STATUS_END");

  // Restore device number
  smcDeviceNumber = lastSmcDeviceNumber;
  statusAcknowledged = false;
  lastStatusTime = millis();
  isProcessingStatus = false;
  return true;
}

// Emergency stop all actuators
void emergencyStop() {
  Serial.println("Emergency Stop");

  smcDeviceNumber = 12;
  setMotorSpeed(0);
  Serial.println("A stopped");

  smcDeviceNumber = 13;
  setMotorSpeed(0);
  Serial.println("B stopped");

  smcDeviceNumber = 14;
  setMotorSpeed(0);
  Serial.println("C stopped");

  measurePressure = false;
  bRunning = false;
  jerking = false;
  jerksCompleted = 0; // Reset jerk counter
}

// Emergency stop, then autonomously back the axial actuator off until
// the load is released. Screw actuators hold force after a plain stop,
// so every fault path must actively release the patient. Bounded by
// load (< PRESSURE_RELEASE_LBS), travel (AZERO), and time.
void emergencyStopAndRelease(const char *reason) {
  if (releasingPressure)
    return;  // a release is already the active fault response

  Serial.print("Emergency stop + release: ");
  Serial.println(reason);
  Serial1.print("ERROR: ");
  Serial1.println(reason);

  emergencyStop();

  releasingPressure = true;
  releaseStart = millis();
  smcDeviceNumber = 12;
  setMotorSpeed(-PRESSURE_SPEED);  // negative = back off / reduce pressure
}

// True if s is a plain decimal number (optional leading -, one optional .)
bool isNumeric(const String &s) {
  if (s.length() == 0)
    return false;
  bool seenDot = false;
  bool seenDigit = false;
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (c == '-' && i == 0)
      continue;
    if (c == '.' && !seenDot) {
      seenDot = true;
      continue;
    }
    if (c < '0' || c > '9')
      return false;
    seenDigit = true;
  }
  return seenDigit;
}

// Non-blocking load-cell sampling: one HX711 read when data is ready
// (~10 Hz), saturation-rejected, median-of-3 filtered. Maintains the
// global `pressure` (magnitude) and `signedPressure` without ever
// stalling loop() the way blocking get_units() calls did.
void updatePressure() {
  if (!scale.is_ready())
    return;

  long raw = scale.read();
  lastScaleReady = millis();

  // A saturated ADC reading is a wiring/overload fault, not data.
  // (8388607/calibration ~= the documented '1923.3 lbs' spike symptom.)
  if (raw >= HX711_SATURATED || raw <= -HX711_SATURATED)
    return;

  float factor = scale.get_scale();
  if (factor == 0)
    return;  // set_scale(0) would otherwise poison readings with inf

  float units = ((float)raw - scale.get_offset()) / factor;

  pressureSamples[pressureSampleIndex] = units;
  pressureSampleIndex = (pressureSampleIndex + 1) % 3;
  if (pressureSampleCount < 3)
    pressureSampleCount++;

  if (pressureSampleCount < 3) {
    signedPressure = units;
  } else {
    // Median of three: single-sample spikes cannot move the output
    float a = pressureSamples[0], b = pressureSamples[1], c = pressureSamples[2];
    float lo = min(a, min(b, c));
    float hi = max(a, max(b, c));
    signedPressure = a + b + c - lo - hi;
  }

  pressure = signedPressure < 0 ? -signedPressure : signedPressure;
  if (pressure < 0.5)
    pressure = 0;
}

float clampPressureTarget(float target) {
  if (target < MIN_PRESSURE_LBS) return MIN_PRESSURE_LBS;
  if (target > MAX_PRESSURE_LBS) return MAX_PRESSURE_LBS;
  return target;
}

uint16_t clampPositionTarget(uint8_t deviceNumber, uint16_t target) {
  uint16_t minPos = 0;
  uint16_t maxPos = 65000;

  if (deviceNumber == 12) {
    minPos = AXIAL_MIN_POS;
    maxPos = AXIAL_MAX_POS;
  } else if (deviceNumber == 13) {
    minPos = HORIZONTAL_MIN_POS;
    maxPos = HORIZONTAL_MAX_POS;
  } else if (deviceNumber == 14) {
    minPos = LATERAL_MIN_POS;
    maxPos = LATERAL_MAX_POS;
  }

  if (target < minPos) return minPos;
  if (target > maxPos) return maxPos;
  return target;
}

// Process a fully received command
void processCommand(String cmd) {
  if (cmd.length() == 0) return;

  // Validate command length
  if (cmd.length() > MAX_COMMAND_LENGTH) {
    Serial.println("Command too long, ignoring");
    Serial1.println("ERROR: Command too long");
    return;
  }

  char commandType = cmd[0];
  String parameter = "";

  // Wait if we're sending status
  unsigned long waitStart = millis();
  while (isProcessingStatus && millis() - waitStart < 500) {
    delay(10);
  }

  // Pre-declare all variables that will be used in case statements
  uint16_t localPosition = 0;
  float inches = 0.0;
  int stage = 0;
  int speedFactor = 0;
  uint16_t localDesiredPosition = 0;
  int weight = 0;
  float calibration = 0;
  int limit = 0;
  int movement = 0;
  uint16_t positionA = 0;
  uint16_t positionB = 0;
  uint16_t positionC = 0;
  float localPressure = 0;

  // Handle different command types
  switch (commandType) {
    // Test command
    case 'T':
        Serial.println("Test command received");
        Serial1.println("OK");
        break;

    // Status acknowledgment
    case 'Q':
        statusAcknowledged = true;
        break;

    case 'H': // High Frequency Status Toggle Command
      if (cmd.length() > 2 && cmd.substring(1,3) == "F1") {
        highFrequencyStatus = true;
        Serial.println("High frequency status ON");
        timeSinceLastStatus = 0; // Reset timer immediately
        statusAcknowledged = true; // Reset flag to allow immediate status
        sendStatus(); // Send status once when activated
        Serial1.println("DONE"); // Acknowledge command
      } else if (cmd.length() > 2 && cmd.substring(1,3) == "F0") {
        highFrequencyStatus = false;
        Serial.println("High frequency status OFF");
        Serial1.println("DONE"); // Acknowledge command
      }
      break;

    // Status request
    case 'S':
      sendStatus();
      break;

    // Pressure control
    case 'P':
      if (bRunning || releasingPressure) {
        Serial1.println("BUSY");  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1);
      if (!isNumeric(parameter)) {
        Serial1.println("ERROR: Invalid P value");
        return;
      }
      desiredPressure = clampPressureTarget(parameter.toFloat());
      Serial.print("desiredPressure ");
      Serial.println(desiredPressure);

      sendStatus();
      smcDeviceNumber = 12;

      // Filtered pressure is maintained by updatePressure(); never
      // block on the load cell here
      Serial.print("pressure desired: ");
      Serial.print(desiredPressure);
      Serial.print(" pressure now: ");
      Serial.println(pressure);

      pressureDirection = 1;
      if (pressure >= desiredPressure)
        pressureDirection = -1;  // move back

      Serial.print(" pressureDirection: ");
      Serial.println(pressureDirection);

      pressureMoveStart = millis();
      pressureProgressTime = millis();
      pressureProgressValue = pressure;
      setMotorSpeed(PRESSURE_SPEED * pressureDirection);
      measurePressure = true;
      break;

    // Reset/restart
    case 'Y':
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      // Stop all motion before the MCU resets: the SMCs would otherwise
      // keep the last commanded speed until setup() zeroes them
      releasingPressure = false;
      emergencyStop();
      Serial1.println("Reset|");
      resetFunc();
      break;

    // Emergency stop
    case 'X':
      releasingPressure = false;  // host is alive and taking control
      emergencyStop();
      Serial.print(F("Stopped at Position: "));
      Serial.println(readPosition());
      Serial1.println("DONE");
      break;

    // Get position
    case 'G':
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      localPosition = readPosition();
      Serial.print(F("Get Position: "));
      Serial.print(localPosition);
      Serial1.print("P|");
      Serial1.println(localPosition);
      Serial1.println("DONE");
      break;

    // Position control
    case 'I':
      if (bRunning || releasingPressure) {
        Serial1.println("BUSY");  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1, 3);
      if (parameter.toInt() < 12 || parameter.toInt() > 14) {
        Serial1.println("ERROR: Invalid device");
        return;
      }
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);

      parameter = cmd.substring(3);
      if (!isNumeric(parameter) || parameter.toInt() < 0) {
        // Reject corrupt input: toInt() garbage would become position 0
        Serial1.println("ERROR: Invalid I value");
        return;
      }
      localDesiredPosition = parameter.toInt();
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);

      if (smcDeviceNumber == 12)
        if (localDesiredPosition <= AZERO)
          localDesiredPosition = AZERO;

      localPosition = readPosition();
      if (!positionReadValid) {
        Serial1.println("ERROR: Position read failed");
        return;
      }

      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);

      // Symmetric close-enough band: small moves in either direction
      // complete immediately instead of one-sided 25-count behavior
      if (localDesiredPosition + POSITION_DEADBAND >= localPosition &&
          localPosition + POSITION_DEADBAND >= localDesiredPosition) {
        position = localPosition;
        desiredPosition = localDesiredPosition;
        sendStatus();
        Serial1.println("DONE");
        break;
      }
      forward = (localDesiredPosition > localPosition) ? 1 : -1;

      // Copy local variables to globals for use in loop()
      position = localPosition;
      desiredPosition = localDesiredPosition;

      setMotorSpeed(forward * C_SPEED);

      Serial.print(AZERO);
      Serial.print(" ");
      Serial.print(forward);
      Serial.print(" ");
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);

      bRunning = true;
      break;

    // C Position (lateral flexion) control
    case 'K':
      if (bRunning || releasingPressure) {
        Serial1.println("BUSY");  // never silently drop a motion command
        return;
      }

      smcDeviceNumber = 14;
      Serial.println(cmd);
      parameter = cmd.substring(1);
      Serial.println(parameter);

      if (!isNumeric(parameter) || parameter.toInt() < 0) {
        // Reject corrupt input: toInt() garbage would drive the lateral
        // actuator to its clamp floor (500)
        Serial1.println("ERROR: Invalid K value");
        return;
      }
      localDesiredPosition = parameter.toInt();
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);
      Serial.println(localDesiredPosition);

      localPosition = readPosition();
      if (!positionReadValid) {
        Serial1.println("ERROR: Position read failed");
        return;
      }
      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);

      // Symmetric close-enough band (see 'I')
      if (localDesiredPosition + POSITION_DEADBAND >= localPosition &&
          localPosition + POSITION_DEADBAND >= localDesiredPosition) {
        desiredPosition = localDesiredPosition;
        position = localPosition;
        sendStatus();
        Serial1.println("DONE");
        break;
      }
      forward = (localDesiredPosition > localPosition) ? 1 : -1;

      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;

      setMotorSpeed(forward * C_SPEED);

      Serial.print(forward);
      Serial.print(" ");
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);

      bRunning = true;
      break;

    // Position in inches
    case 'A':
      if (bRunning || releasingPressure) {
        Serial1.println("BUSY");  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1, 3);
      if (parameter.toInt() < 12 || parameter.toInt() > 14) {
        Serial1.println("ERROR: Invalid device");
        return;
      }
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);

      parameter = cmd.substring(3);
      if (!isNumeric(parameter)) {
        Serial1.println("ERROR: Invalid A value");
        return;
      }
      inches = parameter.toFloat();
      if (inches < 0.0 || inches > 12.0) {
        // Reject instead of letting the float->uint16_t conversion wrap
        // a corrupted negative value to full extension
        Serial1.println("ERROR: A value out of range");
        return;
      }

      // NOTE: target math intentionally preserves the historical
      // convention (no ZERO offset for nonzero inches). The offset
      // question changes physical targets and is gated on the Batch-1
      // hardware measurement session -- see the flash checklist.
      if (smcDeviceNumber == 12) {
        localDesiredPosition = (uint16_t)(AFULLINCH * inches);
        AInches = inches;
        if (inches == 0)
          localDesiredPosition = AZERO;
      } else if (smcDeviceNumber == 13) {
        localDesiredPosition = (uint16_t)(BFULLINCH * inches);
        BInches = inches;
        if (inches == 0)
          localDesiredPosition = BZERO;
      } else if (smcDeviceNumber == 14) {
        localDesiredPosition = (uint16_t)(CFULLINCH * inches);
        CInches = inches;
        if (inches == 0)
          localDesiredPosition = CZERO;
      }
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);

      localPosition = readPosition();
      if (!positionReadValid) {
        Serial1.println("ERROR: Position read failed");
        return;
      }
      Serial.print(inches);
      Serial.print(" ");
      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);

      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;

      // Symmetric close-enough band (see 'I')
      if (desiredPosition + POSITION_DEADBAND >= position &&
          position + POSITION_DEADBAND >= desiredPosition) {
        sendStatus();
        Serial1.println("DONE");
        break;
      }
      forward = (desiredPosition > position) ? 1 : -1;

      setMotorSpeed(forward * BC_SPEED); // Start motor immediately
      bRunning = true;
      break;

    // Calibration and measurement
    case 'L':
      parameter = cmd.substring(1, 2);
      stage = parameter.toInt();

      switch (stage) {
        case 0: // Set calibration factor
          if (cmd.length() > 2)
            calibration_factor = cmd.substring(2).toFloat();
          Serial.print("calibration_factor: ");
          Serial.println(calibration_factor);
          scale.set_scale(calibration_factor);
          scale.tare();
          Serial1.println("DONE");
          break;

        case 1: // Tare scale
          Serial.print("calibration_factor: ");
          Serial.println(calibration_factor);
          scale.set_scale(calibration_factor);
          scale.tare();
          Serial.print("UNITS: ");
          Serial.println(scale.get_units(10));
          Serial1.println("DONE");
          break;

        case 4: // Get weight
          pressure = abs(scale.get_units(10));
          Serial.println(pressure);
          Serial1.print("weight|");
          Serial1.println(pressure);
          break;

        case 5: // Set zero marks
          if (cmd.length() > 2 && cmd.charAt(2) == '|') {
            // Delimited form: L5|<azero>|<bzero> -- unambiguous for any
            // digit count
            AZERO = getValue(cmd, '|', 1).toInt();
            BZERO = getValue(cmd, '|', 2).toInt();
          } else {
            // Legacy fixed-width form ("L5{:3} {:3}"): corrupts 4-digit
            // values (1900 parses as 190); kept for old hosts only
            AZERO = cmd.substring(2, 5).toInt();
            BZERO = cmd.substring(5, 9).toInt();
          }
          Serial.print("AZERO: ");
          Serial.print(AZERO);
          Serial.print("BZERO: ");
          Serial.println(BZERO);
          // Echo parsed values so the host can verify what was applied
          Serial1.print("ZEROS|");
          Serial1.print(AZERO);
          Serial1.print("|");
          Serial1.println(BZERO);
          Serial1.println("DONE");
          break;

        case 6: // Report all positions and pressure
          {
            uint16_t positionA = 0;
            uint16_t positionB = 0;
            uint16_t positionC = 0;

            smcDeviceNumber = 12;
            positionA = readPosition();
            smcDeviceNumber = 13;
            positionB = readPosition();
            smcDeviceNumber = 14;
            positionC = readPosition();

            pressure = abs(scale.get_units(10));

            Serial1.print("A|");
            Serial1.print(positionA);
            Serial1.print("|");
            Serial1.print(positionB);
            Serial1.print("|");
            Serial1.print(positionC);
            Serial1.print("|");
            Serial1.println(pressure);
          }
          break;

        default:
          Serial.println(stage);
          break;
      }
      break;

    // Jerking motion control - FIXED
    case 'J':
      parameter = "";
      if (cmd.length() > 1)
          parameter = cmd.substring(1);

      if (parameter == "") {
          Serial.println("jerking");
          jerking = true;
          // Status stays ON during pulsing: the pressure ceiling check
          // and the Pi both need telemetry exactly when force pulses
          sendStatus();
          jerksCompleted = 0;
          jerkDirection = 1;
          lastJerkTime = millis(); // Initialize jerk timer
          smcDeviceNumber = 12;
          Serial1.println("DONE");
      }

      if (parameter == "S") {
          Serial.println("stop jerking");
          jerkDirection = 0;
          jerking = false;
          jerksCompleted = 0; // Reset counter
          setMotorSpeed(0);
          Serial1.println("DONE");
      }
      break;

    // External actuator control - FIXED: Added break statement
    case 'F':
      {
        String direction = cmd.substring(1, 2);
        Serial.println(direction);

        if (direction == "+") {
          moveFITForward = true;
          FITDelay = FIT_SLOW_DELAY;
          Serial.println("Fit extending.");
          digitalWrite(DIR_FIT_FORWARD, LOW);
          digitalWrite(DIR_FIT_REVERSE, HIGH);
        } else if (direction == "-") {
          moveFITForward = true;
          FITDelay = FIT_SLOW_DELAY;
          Serial.println("Fit reversing.");
          digitalWrite(DIR_FIT_FORWARD, HIGH);
          digitalWrite(DIR_FIT_REVERSE, LOW);
        } else if (direction == "F") {
          moveFITForward = true;
          FITDelay = FIT_FAST_DELAY;
          Serial.println("Fit fast extending.");
          digitalWrite(DIR_FIT_FORWARD, LOW);
          digitalWrite(DIR_FIT_REVERSE, HIGH);
        } else if (direction == "R") {
          moveFITForward = true;
          FITDelay = FIT_FAST_DELAY;
          Serial.println("Fit fast reversing.");
          digitalWrite(DIR_FIT_FORWARD, HIGH);
          digitalWrite(DIR_FIT_REVERSE, LOW);
        } else if (direction == "0") {
          moveFITForward = false;
          Serial.println("Fit stopped.");
          digitalWrite(DIR_FIT_FORWARD, LOW);
          digitalWrite(DIR_FIT_REVERSE, LOW);
        }

        timeInFIT = 0;
        Serial1.println(F("DONE"));
      }
      break; // FIXED: Added missing break statement

    default:
      Serial.print("Unknown command: ");
      Serial.println(commandType);
      break;
  }
}

// Setup function
void setup() {
#if ENABLE_WDT
  wdt_disable();  // a pending watchdog must not fire again mid-setup
#endif

  // Join I2C bus as slave
  Wire.begin(0x8);

  // Initialize serial communication
  Serial.begin(9600);
  Serial.setTimeout(5000);
  Serial1.begin(115200);

  // SAFETY: stop all motors before anything else. After an unexpected
  // MCU reset the SMCs may still be running the last commanded speed;
  // historically they kept moving for the >1s the load-cell init took.
  AInches = 0;
  smcDeviceNumber = 12;
  setMotorSpeed(0);
  BInches = 2;
  smcDeviceNumber = 13;
  setMotorSpeed(0);
  smcDeviceNumber = 14;
  setMotorSpeed(0);
  Serial.println("All actuators stopped");

  Serial.println("\n\n\nStarting");
  Serial.print("VERSION: ");
  Serial.println(VERSION);

  // Initialize load cell
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(calibration_factor);
  delay(1000);

  // Configure pins
  pinMode(STOP_PIN, INPUT_PULLUP); // Added pull-up for stability
  pinMode(DIR_FIT_FORWARD, OUTPUT);
  pinMode(DIR_FIT_REVERSE, OUTPUT);
  pinMode(SPEED_PIN_A, OUTPUT);
  pinMode(DIR_A_FORWARD, OUTPUT);
  pinMode(DIR_A_REVERSE, OUTPUT);

  Serial.print("readPosition ");
  Serial.println(readPosition());

  // Startup complete
  Serial.println("Ready to Go");
  Serial1.println("");
  Serial1.println("Ready to Go");

  loopPosition = millis();
  lastHostTraffic = millis();
  lastScaleReady = millis();

#if ENABLE_WDT
  // Reboot into the safe state above if loop() ever hangs (wedged I2C,
  // dead load cell, etc.)
  wdt_enable(WDTO_2S);
#endif
}

// Loop state (file scope rather than function statics so the native
// tests can reset them between cases)
int loopLastPosition = -1;
int loopStallCount = 0;
unsigned long lastActiveStatus = 0;

// Main loop function - FIXED jerking logic
void loop() {
#if ENABLE_WDT
  wdt_reset();
#endif

  // Read stop pin
  STOP = digitalRead(STOP_PIN);

  // Maintain the filtered pressure value without blocking
  updatePressure();

  bool activeMotion = bRunning || measurePressure || jerking;

  // SAFETY: the physical stop button is honored in EVERY state --
  // including pressure application and pulsing, which previously
  // ignored it entirely
  if (!STOP && activeMotion) {
    emergencyStopAndRelease("Stop button pressed");
    activeMotion = false;
  }

  // SAFETY: pressure ceiling enforced in EVERY state, not only inside
  // an active pressure move (pulsing and position moves can also wind
  // traction past the limit)
  if (pressure > MAX_PRESSURE_LBS && !releasingPressure) {
    emergencyStopAndRelease("Pressure limit exceeded");
    activeMotion = false;
  }

  // SAFETY: heartbeat -- if the host goes silent while we are moving or
  // holding load, stop and release rather than continuing forever
  if (activeMotion && millis() - lastHostTraffic > HEARTBEAT_TIMEOUT) {
    emergencyStopAndRelease("Host heartbeat lost");
    activeMotion = false;
  }

  // SAFETY: a load cell that stops producing data while load matters is
  // a sensor fault; without this, pressure is whatever stale value the
  // last good read left behind
  if ((measurePressure || jerking) &&
      millis() - lastScaleReady > SCALE_READ_TIMEOUT) {
    emergencyStopAndRelease("Load cell not responding");
    activeMotion = false;
  }

  // Autonomous post-fault release: back the axial actuator off until
  // the load clears, bounded by travel and time
  if (releasingPressure) {
    smcDeviceNumber = 12;
    uint16_t releasePos = readPosition();
    bool scaleAlive = (millis() - lastScaleReady) < SCALE_READ_TIMEOUT;
    bool released = scaleAlive && pressure < PRESSURE_RELEASE_LBS;
    bool atTravelLimit =
        positionReadValid && releasePos <= (uint16_t)(AZERO + POSITION_DEADBAND);
    bool timedOut = millis() - releaseStart > RELEASE_TIMEOUT;
    if (released || atTravelLimit || timedOut) {
      setMotorSpeed(0);
      releasingPressure = false;
      if (released)
        Serial1.println("RELEASED");
      else
        Serial1.println("ERROR: Release incomplete");
      sendStatus();
    }
  }

  // Reset if processing status took too long
  if (isProcessingStatus && (millis() - statusStartTime > 500)) {
    isProcessingStatus = false;
    Serial.println("Status processing timeout");
  }

  // Check for status acknowledgment timeout
  if (!statusAcknowledged && millis() - lastStatusTime > STATUS_TIMEOUT) {
    Serial.println("Status acknowledgment timeout - resetting flag");
    statusAcknowledged = true; // Reset flag to allow new status messages
  }

  // Periodic status update - ALWAYS check high frequency status
  if (highFrequencyStatus && (timeSinceLastStatus > HIGH_FREQ_INTERVAL)) {
    // High frequency status should run regardless of motor/pressure state
    timeSinceLastStatus = 0; // Reset timer
    if (sendStatus()) {
      lastStatusTime = millis(); // Record when we sent status
    }
  }
  // Status during motion even without HF mode: the host needs telemetry
  // (and its Q acks feed the heartbeat) exactly while things move
  else if (!highFrequencyStatus && activeMotion &&
           millis() - lastActiveStatus > ACTIVE_STATUS_INTERVAL) {
    lastActiveStatus = millis();
    if (sendStatus()) {
      lastStatusTime = millis();
    }
  }
  // Regular status update only when idle
  else if (!highFrequencyStatus && !bRunning && !measurePressure && (millis() - loopPosition > LOOP_STATUS_DELAY)) {
    loopPosition = millis();
    if (sendStatus()) {
      lastStatusTime = millis(); // Record when we sent status
    }
  }

  // FIXED: Jerking motion handler with proper counter and timing
  if (jerking) {
    if (millis() - lastJerkTime >= jerkInterval) {
      lastJerkTime = millis();

      if (jerksCompleted >= MAX_JERKS) {
        // Send status update and reset counter
        sendStatus();
        jerksCompleted = 0;
      } else {
        // Perform jerk motion
        smcDeviceNumber = 12;
        setMotorSpeed(1600 * jerkDirection);  // Reduced from 3200 to prevent pressure relief
        jerkDirection = -jerkDirection;
        jerksCompleted++; // FIXED: Increment counter

        // Debug output for monitoring jerking behavior
        Serial.print("DEBUG: Jerk #");
        Serial.print(jerksCompleted);
        Serial.print(" Speed: ");
        Serial.print(1600 * jerkDirection);
        Serial.print(" Direction: ");
        Serial.println(jerkDirection == 1 ? "Forward" : "Backward");
      }
    }
  }

  // External actuator timer
  if (moveFITForward) {
    if (timeInFIT > FITDelay) {
      digitalWrite(DIR_FIT_FORWARD, LOW);
      digitalWrite(DIR_FIT_REVERSE, LOW);
      Serial.println("Fit stopped.");
      Serial.println("fit done");
      moveFITForward = false;
    }
  }

  // Running motor handler (position control)
  // (STOP pin already handled unconditionally at the top of loop())
  if (bRunning) {
    // No need to set motor speed here - already set in processCommand
    uint16_t currentPos = readPosition();

    if (positionReadValid) {
      // Debug output
      Serial.print(forward); Serial.print(" ");
      Serial.print(CInches); Serial.print(" ");
      Serial.print(currentPos); Serial.print(" ");
      Serial.print(loopLastPosition); Serial.print(" ");
      Serial.println(desiredPosition);

      // Check if position reached with hysteresis
      bool targetReached = false;
      if (forward > 0) {
        if (currentPos >= desiredPosition) {
          targetReached = true;
        }
      } else if (currentPos <= desiredPosition) {
        targetReached = true;
      }

      if (targetReached) {
        Serial.println("Stopped Moving - Target Reached");
        setMotorSpeed(0);
        bRunning = false;
        forward = 0;
      }

      // Handle stalling detection
      if (loopLastPosition == (int)currentPos) {
        loopStallCount++;
        if (loopStallCount > 5) { // Stop if stalled for too long
          Serial.println("Motor stalled - stopping");
          Serial1.println("ERROR: Motor stalled");
          setMotorSpeed(0);
          bRunning = false;
          loopStallCount = 0;
        }
      } else {
        // Movement resumed: a counter that never reset here used to
        // accumulate across the whole session and stop healthy moves
        loopStallCount = 0;
        loopLastPosition = currentPos;
      }
    }
    // On an invalid position read, skip arrival/stall decisions this
    // iteration rather than acting on garbage (0 was both the error
    // value and a legal position)

    // Cleanup after run complete
    if (!bRunning) {
      position = readPosition();
      Serial.println(position);
      sendStatus();
      Serial1.println("DONE");
    }
  }

  // Pressure monitoring and control
  // (>MAX check and load-cell-fault check already ran unconditionally
  // at the top of loop(); pressure itself is maintained by
  // updatePressure() without blocking)
  if (measurePressure) {
    smcDeviceNumber = 12;
    uint16_t currentPos = readPosition();

    // Travel envelope: a pressure move may not push past the axial
    // travel limits chasing an unreachable target
    if (positionReadValid && pressureDirection > 0 &&
        currentPos >= AXIAL_MAX_POS) {
      emergencyStopAndRelease("Axial travel limit during pressure move");
      return;
    }
    if (positionReadValid && pressureDirection < 0 &&
        currentPos <= (uint16_t)(AZERO + POSITION_DEADBAND)) {
      // Fully backed off; lower pressure is not achievable
      Serial1.println("ERROR: Axial at zero, pressure target not reached");
      setMotorSpeed(0);
      measurePressure = false;
      pressureDirection = 0;
    }

    // Time bound on the whole move
    if (measurePressure &&
        millis() - pressureMoveStart > PRESSURE_MOVE_TIMEOUT) {
      emergencyStopAndRelease("Pressure move timeout");
      return;
    }

    // Progress check: motor commanded but pressure not changing means a
    // frozen sensor or mechanical stall -- both are faults
    if (measurePressure) {
      float progress = pressure - pressureProgressValue;
      if ((pressureDirection > 0 && progress >= PRESSURE_STALL_DELTA) ||
          (pressureDirection < 0 && progress <= -PRESSURE_STALL_DELTA)) {
        pressureProgressValue = pressure;
        pressureProgressTime = millis();
      } else if (millis() - pressureProgressTime > PRESSURE_STALL_MS) {
        emergencyStopAndRelease("No pressure progress");
        return;
      }
    }

    if (measurePressure) {
      Serial.print("desiredPressure: ");
      Serial.print(desiredPressure);
      Serial.print(" pressureDirection: ");
      Serial.print(pressureDirection);
      Serial.print(" pressure: ");
      Serial.println(pressure);

      // Check if target pressure reached with hysteresis
      bool pressureReached = false;
      if (pressureDirection > 0) {
        if (pressure >= desiredPressure) {
          pressureReached = true;
        }
      } else if (pressure <= desiredPressure) {
        pressureReached = true;
      }

      if (pressureReached) {
        setMotorSpeed(0);
        measurePressure = false;
        pressureDirection = 0;
      }
    }

    // Cleanup after pressure adjustment complete
    if (!measurePressure) {
      sendStatus();
      Serial1.println("DONE");
    }
  }

  // Command reading and processing - IMPROVED buffer handling
  while (Serial1.available() > 0) {
    // Never append bytes to an already-complete command: under the rate
    // limiter this used to merge two commands into one corrupt string
    // (e.g. "Q"+"X" -> "QX", silently discarding an emergency stop)
    if (isCommandComplete)
      break;

    char incomingByte = Serial1.read();
    lastHostTraffic = millis();  // any host byte feeds the heartbeat

    if (incomingByte == '\n' || incomingByte == '\r') {  // Command complete
      if (commandBuffer.length() > 0) { // Only process non-empty commands
        isCommandComplete = true;
        break;
      }
    } else {
      // Limit buffer size to prevent overflows
      if (commandBuffer.length() < MAX_COMMAND_LENGTH - 1) {
        commandBuffer += incomingByte;  // Append character to buffer
      } else {
        // Buffer overflow - reset and report error
        Serial.println("Command buffer overflow");
        Serial1.println("ERROR: Command too long");
        commandBuffer = "";
      }
    }
  }

  // Process complete commands with rate limiting. 'X' (emergency stop)
  // is exempt from both the rate limiter and the status-in-progress
  // gate: a stop must never wait in line behind an ack
  if (isCommandComplete) {
    bool isEmergency = commandBuffer.charAt(0) == 'X';
    if (isEmergency ||
        (millis() - lastCommandTime > MIN_COMMAND_INTERVAL && !isProcessingStatus)) {
      lastCommandTime = millis();
      processCommand(commandBuffer);
      commandBuffer = "";
      isCommandComplete = false;
    }
  }
}
