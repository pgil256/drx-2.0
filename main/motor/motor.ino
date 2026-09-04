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

#define VERSION "2026-09-04-FAILSAFE-6"
#ifndef UNIT_TEST
// Hardware libraries; native unit tests supply mocks and arduino_shim.h
// (see test/) before including this file
#include "HX711.h"
#include <elapsedMillis.h>
#include <Wire.h>
#include <avr/wdt.h>
#endif

// Watchdog: reboots the MCU if loop() hangs (e.g. wedged I2C or load
// cell). The production Mega's bootloader recovers cleanly from WDT
// resets (verified on hardware, Phase E §3.2 / E4, 2026-07-08).
// resetBoard() relies on the same mechanism; if a unit ever needs
// ENABLE_WDT 0 (boot-looping bootloader), resetBoard() must be
// reworked for it too.
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
// Pressure moves and the autonomous post-fault release drive the axial
// actuator at the same speed position moves are known to move it at
// (BC_SPEED). At the historical 500 the axial actuator never broke away
// on-device (2026-07-08: +500 commanded for 5 s, zero counts of travel,
// while 800-speed position moves ran fine), so pressure could never
// build -- and worse, a post-fault release would not have moved either.
#define PRESSURE_SPEED     800
#define BC_SPEED           800
#define C_SPEED            800
#define MAX_JERKS          10
#define MIN_JERK_INTERVAL  100   // fastest host-settable pulse cadence (ms)
#define MAX_JERK_INTERVAL  5000  // slowest host-settable pulse cadence (ms)
#define FIT_SLOW_DELAY     (0.5 * 1000)
#define FIT_FAST_DELAY     (6 * 1000)
#define LOOP_STATUS_DELAY  5000
#define MIN_PRESSURE_LBS   0
#define MAX_PRESSURE_LBS   80     // maximum accepted treatment target
#define PRESSURE_WARNING_LBS 100  // warning-only measured-pressure threshold
#define AXIAL_MIN_POS      0
#define AXIAL_MAX_POS      4600
// The calibrated -25 deg horizontal mark (BMarks) sits at position 0; the old
// floor of 50 silently clamped every legal -25 deg command ~0.5 deg short and
// then tripped the host's limit warning on arrival.
#define HORIZONTAL_MIN_POS 0
#define HORIZONTAL_MAX_POS 4500
#define LATERAL_MIN_POS    500
#define LATERAL_MAX_POS    2400

// Command buffer size (increased for safety)
#define MAX_COMMAND_LENGTH 100

// Fail-safe parameters
#define HEARTBEAT_TIMEOUT     10000  // sustained host silence before warning
#define SCALE_READ_TIMEOUT    500    // ms without HX711 ready -> warning
#define PRESSURE_RELEASE_LBS  5.0    // autonomous release target after E-stop
#define RELEASE_TIMEOUT       15000  // ms bound on E-stop pressure release
#define PRESSURE_MOVE_TIMEOUT 30000  // ms before advisory pressure warning
#define PRESSURE_STALL_MS     5000   // legacy progress-check window
#define PRESSURE_STALL_DELTA  0.5    // legacy progress-change threshold
#define PRESSURE_PROGRESS_FAULT_ENABLED 0  // disabled: interferes with live control
#define HX711_SATURATED       8388607L  // 24-bit ADC saturation magnitude
#define POSITION_DEADBAND     25     // counts: symmetric close-enough band
#define POSITION_STALL_MS     20000  // sustained no-progress time before warning
#define POSITION_PROGRESS_COUNTS 4   // encoder progress that resets stall timer
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
bool pressureWarningIssued = false;
bool heartbeatWarningIssued = false;
bool scaleWarningIssued = false;
bool axialTravelWarningIssued = false;
bool pressureTimeoutWarningIssued = false;
bool pressureProgressWarningIssued = false;
bool positionStallWarningIssued = false;
bool positionReadValid = false;      // last readPosition() I2C result ok

// Protocol v2 framing. The host opts in per command by sending
// "#<seq>:<CMD>*<XX>" where XX is the two-hex-digit XOR of "<seq>:<CMD>".
// Acks then echo the sequence (DONE|<seq>, BUSY|<seq>, OK|<seq>,
// ERR|<seq>|<reason>) and status frames carry a trailing "*<XX>"
// checksum. A flipped digit in a command or status line was previously
// undetectable ("P10" -> "P70" passed every check on both sides).
// Unframed commands keep the exact legacy behavior.
bool hostV2 = false;        // host has sent at least one framed command
long currentCmdSeq = -1;    // seq of the command being processed (-1 = v1)
long activeCmdSeq = -1;     // seq of the motion/pressure command in flight
long activeFitCmdSeq = -1;  // seq of the timed FIT command in flight

// Global variables
uint8_t smcDeviceNumber = 13;
int AZERO = 0;
int BZERO = 0;
int CZERO = 0;
int AInches = 0;
int BInches = 0;
float CInches = 0;
bool STOP = true;            // mirrors STOP_PIN: INPUT_PULLUP idles HIGH (= not pressed)
bool stopWasPressed = false; // previous loop's button state (press-edge detection)
uint8_t runningDevice = 12;  // SMC addressed by the position move in flight
bool bRunning = false;
bool measurePressure = false;
int forward = 1;
float desiredPressure = 0;
int pressureDirection = 0;
uint16_t position = 0;
uint16_t desiredPosition = 3;
bool highFrequencyStatus = false;
int loopLastPosition = -1;
unsigned long loopStallStart = 0;
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
// Boot default = the host default of 2 pulses/sec (DEFAULT_JERK_INTERVAL_MS in
// constants.py; paired values are checked by scripts/check_limits_sync.py).
// It used to boot at 200 ms while the host UI claimed 2/sec. Host-settable via
// J<ms> (Phase 3.5 §15.2).
unsigned long jerkInterval = 500;
bool jerkDirectionChanged = false;

// Forward declarations (the native test build has no Arduino-IDE
// prototype generation)
uint8_t xorChecksum(const String &s, unsigned int from, unsigned int to);
void emitAck(const char *token, long seq);
void emitCmdError(const char *reason);
void emitSafetyWarning(const char *reason);
bool parseV2Frame(const String &raw, String &inner);
bool isEmergencyBuffer(const String &b);

// Force a true hardware reset by arming the shortest watchdog and
// spinning. The previous jump-to-0 restart re-entered the program with
// interrupts live and peripherals (TWI, UARTs, WDT) in mid-flight
// state; on the production Mega it wedged the MCU until power cycle
// (reproduced on hardware, 2026-07-08). Requires the WDT-safe
// bootloader verified in Phase E §3.2.
void resetBoard() {
  Serial.flush();   // let queued diagnostics drain
  Serial1.flush();  // "Reset|" must reach the host before the reset
  wdt_enable(WDTO_15MS);
#ifndef UNIT_TEST
  for (;;) {}  // watchdog fires in ~15 ms
#endif
}

// Required to allow motors to move
void exitSafeStart() {
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0x83);  // Exit safe start
  Wire.endTransmission();
}

// Set motor speed and direction. Returns the Wire::endTransmission() code
// of the speed write (0 = acknowledged) so safety-critical callers can
// notice a NACK/timeout instead of assuming the SMC took the command.
uint8_t setMotorSpeed(int16_t speed) {
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
  return Wire.endTransmission();
}

// Read actuator position once over I2C; returns true on success
static bool readPositionOnce(uint16_t &out) {
  // Request position from controller
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0xA1);  // Command: Get variable
  Wire.write(12);    // Variable ID: position signed
  Wire.endTransmission();

  // requestFrom() performs the (timeout-bounded, see setWireTimeout) read
  // itself. The old pre-request wait on Wire.available() could never be
  // satisfied -- nothing is in the RX buffer before requestFrom -- so every
  // position read burned its full 50 ms, stretching the safety loop (and
  // the STOP-button poll) by 100-400 ms during motion.
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

  // Send to Serial1 (Pi communication). Built as one string so a
  // checksum can cover the whole frame for v2 hosts.
  String frame = "STATUS_START|S|";
  frame += String((int)positionA);
  frame += "|";
  frame += String((int)positionB);
  frame += "|";
  frame += String((int)positionC);
  frame += "|";
  frame += String(pressure);
  frame += "|STATUS_END";
  Serial1.print(frame);
  if (hostV2) {
    char suffix[5];
    snprintf(suffix, sizeof(suffix), "*%02X",
             xorChecksum(frame, 0, frame.length()));
    Serial1.print(suffix);
  }
  Serial1.println("");

  // Restore device number
  smcDeviceNumber = lastSmcDeviceNumber;
  statusAcknowledged = false;
  lastStatusTime = millis();
  isProcessingStatus = false;
  return true;
}

// Stop the open-loop leg-length/FIT actuator. This actuator is driven by
// GPIO rather than an SMC, so setting SMC speeds to zero does not affect it.
void stopFIT() {
  moveFITForward = false;
  FITDelay = 0;
  timeInFIT = 0;
  activeFitCmdSeq = -1;
  digitalWrite(DIR_FIT_FORWARD, LOW);
  digitalWrite(DIR_FIT_REVERSE, LOW);
}

// Zero one SMC on the emergency-stop path, retrying a NACKed/timed-out I2C
// write. The stop used to be fire-and-forget: a transient bus fault
// coincident with STOP/X left that SMC at its last speed while the firmware
// reported everything stopped.
static void stopDeviceOrReport(uint8_t device) {
  smcDeviceNumber = device;
  uint8_t rc = 1;
  for (uint8_t attempt = 0; attempt < 3 && rc != 0; attempt++)
    rc = setMotorSpeed(0);
  if (rc != 0) {
    Serial1.print("ERROR: Motor stop not acknowledged ");
    Serial1.println((int)device);
  }
}

// Emergency stop all actuators
void emergencyStop() {
  Serial.println("Emergency Stop");

  // Aborted motion/pressure commands never get a DONE (v1 behavior);
  // drop the in-flight sequence so a later completion cannot echo it
  activeCmdSeq = -1;

  stopDeviceOrReport(12);
  Serial.println("A stopped");

  stopDeviceOrReport(13);
  Serial.println("B stopped");

  stopDeviceOrReport(14);
  Serial.println("C stopped");

  stopFIT();
  Serial.println("FIT stopped");

  measurePressure = false;
  bRunning = false;
  jerking = false;
  jerksCompleted = 0; // Reset jerk counter
}

// Emergency stop, then autonomously back the axial actuator off until
// the load is released. This is reserved for an actual E-stop input.
// Bounded by load (< PRESSURE_RELEASE_LBS), travel (AZERO), and time.
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

// Advisory device notice. Warnings never alter motion or protocol state;
// only the physical/explicit emergency-stop path may do that.
void emitSafetyWarning(const char *reason) {
  Serial.print("Safety warning: ");
  Serial.println(reason);
  Serial1.print("WARNING: ");
  Serial1.println(reason);
}

// XOR checksum over s[from..to)
uint8_t xorChecksum(const String &s, unsigned int from, unsigned int to) {
  uint8_t x = 0;
  for (unsigned int i = from; i < to && i < s.length(); i++)
    x ^= (uint8_t)s.charAt(i);
  return x;
}

// Emit an ack token, with "|<seq>" appended for v2-framed commands
void emitAck(const char *token, long seq) {
  Serial1.print(token);
  if (seq >= 0) {
    Serial1.print("|");
    Serial1.print(seq);  // long: (int) truncated seq > 32767 on AVR
  }
  Serial1.println("");
}

// Emit an error for the command being processed: "ERR|<seq>|<reason>"
// for v2, the legacy "ERROR: <reason>" otherwise
void emitCmdError(const char *reason) {
  if (currentCmdSeq >= 0) {
    Serial1.print("ERR|");
    Serial1.print(currentCmdSeq);  // long (see emitAck)
    Serial1.print("|");
    Serial1.println(reason);
  } else {
    Serial1.print("ERROR: ");
    Serial1.println(reason);
  }
}

// While the physical STOP is held nothing may START moving: a motion command
// accepted then would run for one loop, trip the stop, and leave a fresh
// error + release cycle behind it (a twitch and error spam per command)
bool rejectIfStopEngaged() {
  if (!STOP) {
    emitCmdError("Stop button engaged");
    return true;
  }
  return false;
}

// Parse "#<seq>:<CMD>*<XX>" into inner CMD; verifies the checksum.
// Returns false (after emitting an error) on a malformed/corrupt frame.
bool parseV2Frame(const String &raw, String &inner) {
  int colon = raw.indexOf(':');
  int star = raw.indexOf('*');
  if (colon < 2 || star < colon + 2 || star + 1 >= (int)raw.length()) {
    currentCmdSeq = -1;
    emitCmdError("Malformed frame");
    return false;
  }
  hostV2 = true;
  long seq = raw.substring(1, colon).toInt();
  uint8_t expected =
      (uint8_t)strtol(raw.substring(star + 1).c_str(), NULL, 16);
  uint8_t actual = xorChecksum(raw, 1, (unsigned int)star);
  if (actual != expected) {
    currentCmdSeq = seq;
    emitCmdError("Checksum mismatch");
    currentCmdSeq = -1;
    return false;
  }
  currentCmdSeq = seq;
  inner = raw.substring(colon + 1, star);
  return true;
}

// Emergency stop must bypass the rate limiter whether framed or not
bool isEmergencyBuffer(const String &b) {
  if (b.length() == 0)
    return false;
  if (b.charAt(0) == 'X')
    return true;
  if (b.charAt(0) == '#') {
    int colon = b.indexOf(':');
    if (colon > 0 && colon + 1 < (int)b.length() && b.charAt(colon + 1) == 'X')
      return true;
  }
  return false;
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
    emitCmdError("Command too long");
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
        emitAck("OK", currentCmdSeq);
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
        emitAck("DONE", currentCmdSeq); // Acknowledge command
      } else if (cmd.length() > 2 && cmd.substring(1,3) == "F0") {
        highFrequencyStatus = false;
        Serial.println("High frequency status OFF");
        emitAck("DONE", currentCmdSeq); // Acknowledge command
      }
      break;

    // Status request
    case 'S':
      sendStatus();
      break;

    // Pressure control
    case 'P':
      if (bRunning || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1);
      if (!isNumeric(parameter)) {
        emitCmdError("Invalid P value");
        return;
      }
      localPressure = clampPressureTarget(parameter.toFloat());
      // While the physical STOP is engaged only a RELEASE (target at or
      // below the current load) may start. The host's e-stop chain asserts
      // the stop line and then sends X + P0 -- that P0 must keep working.
      if (!STOP && localPressure > pressure) {
        emitCmdError("Stop button engaged");
        return;
      }
      desiredPressure = localPressure;
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

      // Already at/below the target with nowhere to go -- the common
      // case is the host's post-protocol "P0" release arriving when no
      // load was ever applied. Starting a backward move here would only
      // trip the axial-at-zero guard and fault the host over a no-op.
      if (pressureDirection < 0 && pressure <= desiredPressure) {
        Serial.println("Pressure already at target; nothing to move");
        sendStatus();
        emitAck("DONE", currentCmdSeq);
        break;
      }

      Serial.print(" pressureDirection: ");
      Serial.println(pressureDirection);

      pressureMoveStart = millis();
      pressureProgressTime = millis();
      pressureProgressValue = pressure;
      axialTravelWarningIssued = false;
      pressureTimeoutWarningIssued = false;
      pressureProgressWarningIssued = false;
      setMotorSpeed(PRESSURE_SPEED * pressureDirection);
      measurePressure = true;
      activeCmdSeq = currentCmdSeq;
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
      resetBoard();
      break;

    // Emergency stop
    case 'X':
      releasingPressure = false;  // host is alive and taking control
      emergencyStop();
      Serial.print(F("Stopped at Position: "));
      Serial.println(readPosition());
      emitAck("DONE", currentCmdSeq);
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
      emitAck("DONE", currentCmdSeq);
      break;

    // Position control
    case 'I':
      if (rejectIfStopEngaged()) return;
      if (bRunning || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1, 3);
      if (parameter.toInt() < 12 || parameter.toInt() > 14) {
        emitCmdError("Invalid device");
        return;
      }
      if (measurePressure && parameter.toInt() == 12) {
        // The axial SMC is already being driven by a pressure move
        emitAck("BUSY", currentCmdSeq);
        return;
      }
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);

      parameter = cmd.substring(3);
      if (!isNumeric(parameter) || parameter.toInt() < 0 || parameter.toInt() > 65000) {
        // Reject corrupt input: toInt() garbage would become position 0,
        // and a >16-bit value would wrap to an arbitrary target
        emitCmdError("Invalid I value");
        return;
      }
      localDesiredPosition = parameter.toInt();
      // Axial floor FIRST, then the travel clamp, so AZERO can never
      // re-raise a target the clamp just bounded (L5 rejects out-of-range
      // marks too; this keeps the order right regardless)
      if (smcDeviceNumber == 12 && (long)localDesiredPosition <= (long)AZERO)
        localDesiredPosition = (uint16_t)AZERO;
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);

      localPosition = readPosition();
      if (!positionReadValid) {
        emitCmdError("Position read failed");
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
        emitAck("DONE", currentCmdSeq);
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

      activeCmdSeq = currentCmdSeq;
      loopLastPosition = localPosition;
      loopStallStart = millis();
      positionStallWarningIssued = false;
      runningDevice = smcDeviceNumber;
      bRunning = true;
      break;

    // C Position (lateral flexion) control
    case 'K':
      if (rejectIfStopEngaged()) return;
      if (bRunning || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);  // never silently drop a motion command
        return;
      }

      smcDeviceNumber = 14;
      Serial.println(cmd);
      parameter = cmd.substring(1);
      Serial.println(parameter);

      if (!isNumeric(parameter) || parameter.toInt() < 0 || parameter.toInt() > 65000) {
        // Reject corrupt input: toInt() garbage would drive the lateral
        // actuator to its clamp floor (500); >16-bit values would wrap
        emitCmdError("Invalid K value");
        return;
      }
      localDesiredPosition = parameter.toInt();
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);
      Serial.println(localDesiredPosition);

      localPosition = readPosition();
      if (!positionReadValid) {
        emitCmdError("Position read failed");
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
        emitAck("DONE", currentCmdSeq);
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

      activeCmdSeq = currentCmdSeq;
      loopLastPosition = localPosition;
      loopStallStart = millis();
      positionStallWarningIssued = false;
      runningDevice = smcDeviceNumber;
      bRunning = true;
      break;

    // Position in inches
    case 'A':
      if (rejectIfStopEngaged()) return;
      if (bRunning || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);  // never silently drop a motion command
        return;
      }

      parameter = cmd.substring(1, 3);
      if (parameter.toInt() < 12 || parameter.toInt() > 14) {
        emitCmdError("Invalid device");
        return;
      }
      if (measurePressure && parameter.toInt() == 12) {
        // The axial SMC is already being driven by a pressure move
        emitAck("BUSY", currentCmdSeq);
        return;
      }
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);

      parameter = cmd.substring(3);
      if (!isNumeric(parameter)) {
        emitCmdError("Invalid A value");
        return;
      }
      inches = parameter.toFloat();
      if (inches < 0.0 || inches > 12.0) {
        // Reject instead of letting the float->uint16_t conversion wrap
        // a corrupted negative value to full extension
        emitCmdError("A value out of range");
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
        emitCmdError("Position read failed");
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
        emitAck("DONE", currentCmdSeq);
        break;
      }
      forward = (desiredPosition > position) ? 1 : -1;

      setMotorSpeed(forward * BC_SPEED); // Start motor immediately
      activeCmdSeq = currentCmdSeq;
      loopLastPosition = localPosition;
      loopStallStart = millis();
      positionStallWarningIssued = false;
      runningDevice = smcDeviceNumber;
      bRunning = true;
      break;

    // Calibration and measurement
    case 'L':
      parameter = cmd.substring(1, 2);
      stage = parameter.toInt();

      switch (stage) {
        case 0: // Set calibration factor
          if (cmd.length() > 2) {
            parameter = cmd.substring(2);
            // A zero/garbage factor used to be applied silently: set_scale(0)
            // makes updatePressure() bail out forever (pressure frozen at
            // its last value) while lastScaleReady keeps advancing, so even
            // the "Load cell not responding" notice never fires.
            if (!isNumeric(parameter) || parameter.toFloat() == 0) {
              emitCmdError("Invalid L0 factor");
              break;
            }
            calibration_factor = parameter.toFloat();
          }
          Serial.print("calibration_factor: ");
          Serial.println(calibration_factor);
          scale.set_scale(calibration_factor);
          scale.tare();
          emitAck("DONE", currentCmdSeq);
          break;

        case 1: // Tare scale
          Serial.print("calibration_factor: ");
          Serial.println(calibration_factor);
          scale.set_scale(calibration_factor);
          scale.tare();
          Serial.print("UNITS: ");
          Serial.println(scale.get_units(10));
          emitAck("DONE", currentCmdSeq);
          break;

        case 4: // Get weight
          pressure = abs(scale.get_units(10));
          Serial.println(pressure);
          Serial1.print("weight|");
          Serial1.println(pressure);
          break;

        case 5: // Set zero marks
          {
            long newAZero, newBZero;
            if (cmd.length() > 2 && cmd.charAt(2) == '|') {
              // Delimited form: L5|<azero>|<bzero> -- unambiguous for any
              // digit count
              newAZero = getValue(cmd, '|', 1).toInt();
              newBZero = getValue(cmd, '|', 2).toInt();
            } else {
              // Legacy fixed-width form ("L5{:3} {:3}"): corrupts 4-digit
              // values (1900 parses as 190); kept for old hosts only
              newAZero = cmd.substring(2, 5).toInt();
              newBZero = cmd.substring(5, 9).toInt();
            }
            // The marks feed the axial floor (I/A), the E-stop release
            // floor and the "at home" checks as signed ints compared
            // against uint16 positions. An unvalidated value (typo'd
            // config, corrupt line) used to be applied as-is: above
            // AXIAL_MAX_POS it re-raised every clamped target past the
            // travel limit; negative it wrapped to ~65k and ended the
            // release after one iteration. Keep the previous marks instead.
            if (newAZero < AXIAL_MIN_POS || newAZero > AXIAL_MAX_POS ||
                newBZero < HORIZONTAL_MIN_POS || newBZero > HORIZONTAL_MAX_POS) {
              emitCmdError("Invalid L5 zero marks");
              break;
            }
            AZERO = (int)newAZero;
            BZERO = (int)newBZero;
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
          emitAck("DONE", currentCmdSeq);
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

      if (parameter == "S") {
          Serial.println("stop jerking");
          // Stop only the pulsing axial motor, and only if pulsing was
          // active. setMotorSpeed(0) used to hit whichever SMC was last
          // addressed: a JS from the host's live pulse-rate control during
          // a K/I move zeroed THAT actuator mid-travel and left bRunning
          // set forever (no DONE, then BUSY for every command until X).
          if (jerking) {
              smcDeviceNumber = 12;
              setMotorSpeed(0);
          }
          jerkDirection = 0;
          jerking = false;
          jerksCompleted = 0; // Reset counter
          emitAck("DONE", currentCmdSeq);
      } else {
          if (rejectIfStopEngaged()) return;
          // Pulsing drives the axial SMC: refuse to overlap an in-flight
          // axial pressure/position move or the E-stop release. The host
          // worker only starts J once those moves have reported DONE, and
          // it treats BUSY as transient.
          if (measurePressure || releasingPressure ||
              (bRunning && runningDevice == 12)) {
              emitAck("BUSY", currentCmdSeq);
              return;
          }
          // Optional numeric parameter sets the pulse cadence in ms (J<ms>,
          // Phase 3.5 §15.2). A bare 'J' keeps the current jerkInterval.
          // Out-of-range / malformed values are ignored so a bad rate can
          // never drive an unsafe cadence — pulsing still starts at the
          // last good interval and DONE is still acked.
          if (parameter.length() > 0) {
              long requested = parameter.toInt();
              if (requested >= MIN_JERK_INTERVAL && requested <= MAX_JERK_INTERVAL) {
                  jerkInterval = (unsigned long)requested;
              }
          }
          Serial.println("jerking");
          jerking = true;
          // Status stays ON during pulsing: the pressure ceiling check
          // and the Pi both need telemetry exactly when force pulses
          sendStatus();
          jerksCompleted = 0;
          jerkDirection = 1;
          lastJerkTime = millis(); // Initialize jerk timer
          smcDeviceNumber = 12;
          emitAck("DONE", currentCmdSeq);
      }
      break;

    // External actuator control - FIXED: Added break statement
    case 'F':
      {
        String direction = cmd.substring(1, 2);
        Serial.println(direction);

        if (direction == "0") {
          stopFIT();
          Serial.println("Fit stopped.");
          emitAck("DONE", currentCmdSeq);
          break;
        }

        if (moveFITForward) {
          emitAck("BUSY", currentCmdSeq);
          break;
        }
        if (rejectIfStopEngaged()) break;

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
        } else {
          emitCmdError("Invalid F direction");
          break;
        }

        timeInFIT = 0;
        // Completion is emitted when the timed movement physically ends.
        // The previous immediate DONE re-enabled conflicting UI controls
        // while the FIT motor was still moving for up to six seconds.
        activeFitCmdSeq = currentCmdSeq;
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
  // Wire busy-waits with no timeout by default; a wedged bus or dead
  // SMC must time out (auto-recovering the TWI) rather than hang setup
  // or the safety loop forever
  Wire.setWireTimeout(25000, true);

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
// tests can reset it between cases)
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

  bool activeMotion = bRunning || measurePressure || jerking || moveFITForward;

  // SAFETY: the physical stop button is honored in EVERY state --
  // including pressure application, pulsing, AND the static hold. During
  // the hold (the longest phase of a treatment: motor zeroed, patient
  // under load) no motion flag is set, so the button used to be ignored
  // there entirely. A press with load present now runs the same
  // stop-and-release. That case is edge-triggered so a held button cannot
  // re-fire a fresh release every loop after one ends incomplete; motion
  // commands are refused while the button is held (rejectIfStopEngaged).
  bool stopPressed = !STOP;
  bool loadPresent = pressure > PRESSURE_RELEASE_LBS;
  if (stopPressed && (activeMotion || (loadPresent && !stopWasPressed))) {
    emergencyStopAndRelease("Stop button pressed");
    activeMotion = false;
  }
  stopWasPressed = stopPressed;

  // Measured-pressure warning. Treatment targets remain capped separately at
  // MAX_PRESSURE_LBS; this high telemetry threshold is advisory only.
  if (pressure > PRESSURE_WARNING_LBS) {
    if (!pressureWarningIssued) {
      emitSafetyWarning("Pressure warning threshold exceeded");
      pressureWarningIssued = true;
    }
  } else {
    pressureWarningIssued = false;
  }

  // Host-heartbeat and load-cell notices are advisory. Motion continues until
  // an actual E-stop is asserted.
  if (activeMotion && millis() - lastHostTraffic > HEARTBEAT_TIMEOUT) {
    if (!heartbeatWarningIssued) {
      emitSafetyWarning("Host heartbeat lost");
      heartbeatWarningIssued = true;
    }
  } else {
    heartbeatWarningIssued = false;
  }

  if ((measurePressure || jerking) &&
      millis() - lastScaleReady > SCALE_READ_TIMEOUT) {
    if (!scaleWarningIssued) {
      emitSafetyWarning("Load cell not responding");
      scaleWarningIssued = true;
    }
  } else {
    scaleWarningIssued = false;
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
        // Status/rest slot. Pulses alternate +/- and MAX_JERKS is even, so
        // the 10th pulse always leaves the motor in reverse; leaving that
        // applied through this slot made every 11-interval cycle 5 forward
        // / 6 reverse -- a steady backward creep under load. Rest instead.
        smcDeviceNumber = 12;
        setMotorSpeed(0);
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
      emitAck("DONE", activeFitCmdSeq);
      activeFitCmdSeq = -1;
    }
  }

  // Running motor handler (position control)
  // (STOP pin already handled unconditionally at the top of loop())
  if (bRunning) {
    // Address the SMC this move belongs to: the pressure and pulse handlers
    // below reset smcDeviceNumber to 12 every iteration, so a concurrent
    // K/I13 move used to have its arrival judged against the wrong axis
    // (and its stop sent to the wrong SMC)
    smcDeviceNumber = runningDevice;
    uint16_t currentPos = readPosition();

    if (positionReadValid) {
      // Debug output
      Serial.print(forward); Serial.print(" ");
      Serial.print(CInches); Serial.print(" ");
      Serial.print(currentPos); Serial.print(" ");
      Serial.print(loopLastPosition); Serial.print(" ");
      Serial.println(desiredPosition);

      // Arrival uses the SAME symmetric POSITION_DEADBAND band as the
      // command-time close-enough check (see 'I'/'K'/'A'): an actuator
      // that settles within the deadband of its target has arrived. The
      // old strict compare (>=/<=) never registered arrival when the
      // axial actuator bottomed out at its home a few counts short of
      // AZERO, so the stall detector below fired "Motor stalled" on a
      // reset that had actually reached home.
      bool targetReached =
          (desiredPosition + POSITION_DEADBAND >= currentPos &&
           currentPos + POSITION_DEADBAND >= desiredPosition);

      if (targetReached) {
        Serial.println("Stopped Moving - Target Reached");
        setMotorSpeed(0);
        bRunning = false;
        forward = 0;
        loopLastPosition = -1;
        loopStallStart = 0;
      } else {
        // Loop iterations are much faster than encoder updates, so a poll
        // count can report a false stall almost immediately. Require a full
        // no-progress interval instead. Small encoder jitter or movement in
        // the wrong direction does not reset the timer; meaningful movement
        // toward the target does.
        long progress = ((long)currentPos - (long)loopLastPosition) * forward;
        if (loopLastPosition < 0 || progress >= POSITION_PROGRESS_COUNTS) {
          loopLastPosition = currentPos;
          loopStallStart = millis();
          positionStallWarningIssued = false;
        } else if (millis() - loopStallStart >= POSITION_STALL_MS &&
                   !positionStallWarningIssued) {
          emitSafetyWarning("Motor stalled");
          positionStallWarningIssued = true;
        }
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
      emitAck("DONE", activeCmdSeq);
      activeCmdSeq = -1;
    }
  }

  // Pressure monitoring and control
  // (>MAX check and load-cell-fault check already ran unconditionally
  // at the top of loop(); pressure itself is maintained by
  // updatePressure() without blocking)
  if (measurePressure) {
    smcDeviceNumber = 12;
    uint16_t currentPos = readPosition();

    // Travel envelope notice: a forward pressure move that reaches the
    // axial travel limit warns ONCE and keeps going. Owner policy
    // (2026-09-04): warnings never stop a pressure move -- only an
    // E-stop (physical STOP / 'X') does. AXIAL_MAX_POS is far beyond the
    // host's 0-4 in working range, so this is diagnostic in practice.
    if (positionReadValid && pressureDirection > 0 &&
        currentPos >= AXIAL_MAX_POS) {
      if (!axialTravelWarningIssued) {
        emitSafetyWarning("Axial travel limit during pressure move");
        axialTravelWarningIssued = true;
      }
    } else {
      axialTravelWarningIssued = false;
    }
    if (positionReadValid && pressureDirection < 0 &&
        currentPos <= (uint16_t)(AZERO + POSITION_DEADBAND) &&
        pressure > desiredPressure) {
      // The actuator cannot back off any farther. End this pressure move
      // without raising a device safety fault; the host can continue to
      // display the measured pressure while the travel floor remains
      // enforced here. The normal cleanup below emits DONE.
      Serial.println(
          "Axial at zero before pressure target; ending pressure move");
      setMotorSpeed(0);
      measurePressure = false;
      pressureDirection = 0;
    }

    // Time bound on the whole move
    if (measurePressure &&
        millis() - pressureMoveStart > PRESSURE_MOVE_TIMEOUT) {
      if (!pressureTimeoutWarningIssued) {
        emitSafetyWarning("Pressure move timeout");
        pressureTimeoutWarningIssued = true;
      }
    }

    // The pressure-progress warning is disabled. Some valid live adjustments
    // hold a nearly constant load for longer than this heuristic allows,
    // causing false notices. If re-enabled, it remains advisory.
    if (PRESSURE_PROGRESS_FAULT_ENABLED && measurePressure) {
      float progress = pressure - pressureProgressValue;
      if ((pressureDirection > 0 && progress >= PRESSURE_STALL_DELTA) ||
          (pressureDirection < 0 && progress <= -PRESSURE_STALL_DELTA)) {
        pressureProgressValue = pressure;
        pressureProgressTime = millis();
        pressureProgressWarningIssued = false;
      } else if (millis() - pressureProgressTime > PRESSURE_STALL_MS &&
                 !pressureProgressWarningIssued) {
        emitSafetyWarning("No pressure progress");
        pressureProgressWarningIssued = true;
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
      emitAck("DONE", activeCmdSeq);
      activeCmdSeq = -1;
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
    bool isEmergency = isEmergencyBuffer(commandBuffer);
    if (isEmergency ||
        (millis() - lastCommandTime > MIN_COMMAND_INTERVAL && !isProcessingStatus)) {
      lastCommandTime = millis();
      String execBuffer = commandBuffer;
      currentCmdSeq = -1;
      bool frameOk = true;
      if (commandBuffer.charAt(0) == '#')
        frameOk = parseV2Frame(commandBuffer, execBuffer);
      if (frameOk)
        processCommand(execBuffer);
      currentCmdSeq = -1;
      commandBuffer = "";
      isCommandComplete = false;
    }
  }
}
