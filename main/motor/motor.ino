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

#define VERSION "2026-09-17-DRX2-NB2"
#define HX711_DRIVER "DRX-HX711-NB2"
#include <math.h>
#ifndef UNIT_TEST
// Hardware libraries; native unit tests supply mocks and arduino_shim.h
// (see test/) before including this file
#include "hx711_sampler.h"
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
#define TREATMENT_SPEED_MAX 1600
#define MOTOR_SPEED_MIN_PERCENT 50
#define MOTOR_SPEED_MAX_PERCENT 100
int axialSpeed = PRESSURE_SPEED;
int lateralSpeed = C_SPEED;
int pulseSpeed = TREATMENT_SPEED_MAX;
#define MIN_JERK_INTERVAL  100   // fastest host-settable pulse cadence (ms)
#define MAX_JERK_INTERVAL  5000  // slowest host-settable pulse cadence (ms)
#define FIT_SLOW_DELAY     (0.5 * 1000)
#define FIT_FAST_DELAY     (6 * 1000)
#define LOOP_STATUS_DELAY  5000
#define MIN_PRESSURE_LBS   0
#define MAX_PRESSURE_LBS   80     // maximum accepted treatment target
#define PRESSURE_WARNING_LBS 100  // warning-only measured-pressure threshold
#define PRESSURE_TARGET_TOLERANCE_LBS 2  // control goal around the target
#define PRESSURE_OVERSHOOT_ALLOWANCE_LBS 10  // accepted excess after settling
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
// Advisory only: the move keeps going until the host acts. Must stay
// BELOW the host's PRESSURE_BUILD_TIMEOUT_S (constants.py, 90 s) so this
// warning reaches the operator before the host gives up. Raised from
// 30 s on 2026-09-10 (slow axial load build).
#define PRESSURE_MOVE_TIMEOUT 80000  // ms before advisory pressure warning
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
Hx711Sampler scale;
float calibration_factor = -4360.14;
float pressure = 0;          // filtered magnitude used by control/safety logic
float signedPressure = 0;    // filtered signed value (negative = wiring/drift fault)

// Non-blocking load-cell sampling state
float pressureSamples[3] = {0, 0, 0};
uint8_t pressureSampleIndex = 0;
uint8_t pressureSampleCount = 0;
unsigned long lastScaleReady = 0;    // last time the HX711 had data for us

const float PRESSURE_HARD_LIMIT = 100.0;
// Increasing pressure reaches the requested target, not its lower tolerance
// edge. Keep the 2 lb band for reductions/release and already-satisfied loads
// at/above target. The separate +10 lb allowance is only an overshoot ceiling.
const float PRESSURE_TARGET_BAND = 2.0;
const float PRESSURE_OVERSHOOT_LIMIT = 10.0;
const unsigned long PRESSURE_SAMPLE_TIMEOUT = 500; // ms
const unsigned long PRESSURE_MOVE_DEADLINE = 90000UL; // ms; app allows 5 s for the final reply.
bool pressureSampleValid = false;
bool pressureCalibrated = false;
bool pressureGuardActive = false;
bool pressureFault = false;
bool pressureDonePending = false;
float pressureCeiling = 0;
float protocolPressureLimit = 0; // Selected protocol target, distinct from a ramp step.
unsigned long lastPressureSample = 0;
unsigned long pressureMoveStarted = 0;
uint16_t cachedPositions[3] = {0, 0, 0};
const unsigned long AXIAL_QUERY_INTERVAL = 500; // ms during pressure/pulse motion
const unsigned long MOTOR_I2C_TIMEOUT_US = 25000UL;
unsigned long lastAxialQuery = 0;
long lastRawPressure = 0;
unsigned long maxPressurePollGap = 0, lastPressurePoll = 0, lastPressureReadUs = 0;
bool pressurePollStarted = false;
// Allow post-home load relaxation, but never extend the overall deadline when
// a candidate window is discarded. The app/probe allow 10 s for this reply.
const unsigned long TARE_TIMEOUT_MS = 8000;
const unsigned long TARE_MIN_SPAN_MS = 900;
const uint8_t TARE_MIN_SAMPLES = 10;
const float TARE_MAX_RANGE_LB = 0.5;
bool tareActive = false;
unsigned long tareStarted = 0, tareFirstSample = 0;
uint16_t tareCount = 0;
int64_t tareSum = 0;
long tareMin = 0, tareMax = 0;
// Operator-requested notice only: existing limits/timeout continue to govern.
const uint16_t PRESSURE_PROGRESS_TRAVEL = 2150; // 5 inches at 430 counts/inch.
const float PRESSURE_PROGRESS_MIN_RISE = 2.0;
bool pressureProgressActive = false, pressureProgressNotified = false;
uint16_t pressureStartPosition = 0;
float pressureStartForce = 0;


long tareCmdSeq = -1;
uint16_t positionTolerance = 0;
char positionCommandKind = 'I';
const float PULSE_RELEASE_DROP = 2.0;
const unsigned long PULSE_RECOVERY_TIMEOUT = 5000UL;
int pulseMotorSpeed = 0;
void servicePressure();
void reportSensorDiagnostics();
void tripPressureFault(const char *reason);
void setPulseSpeed(int speed);
float pulseReleaseFloor();
void reportPressureDone(long seq);
void emitAck(const char *token, long seq);
void emergencyStop();

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
// ERR|<seq>|<reason>). Status reports always carry a trailing "*<XX>"
// checksum, including for legacy hosts. A flipped digit was previously
// undetectable ("P10" -> "P70" passed every check on both sides).
// Unframed commands keep their legacy command/ack behavior.
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
unsigned long jerksCompleted = 0;  // strokes since J; debug/telemetry only
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

// Debug tee. Every diagnostic the sketch used to print only on the USB
// Serial (9600, nothing listening on the Pi in normal operation) now also
// goes to the Pi as one "LOG|<line>" frame per completed line on Serial1,
// so firmware output ("Wire error on device 14, returned: 0", per-frame
// positions, motor speed writes) shows up in the host log next to the
// host's own lines. Lines are buffered until println() so a LOG| frame is
// never interleaved with a status or ack frame.
class DebugTee {
  String buf;
 public:
  template <typename T> size_t print(const T &v) {
    Serial.print(v);
    buf += String(v);
    return 0;
  }
  template <typename T> size_t println(const T &v) {
    print(v);
    return println();
  }
  size_t println() {
    Serial.println();
    if (buf.length()) {
      Serial1.print(F("LOG|"));
      Serial1.println(buf);
      buf = "";
    }
    return 0;
  }
};
DebugTee Dbg;

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
  if (speed != 0 && pressureFault) return 0;
  // Clamp speed to valid range
  if (speed > 3200) speed = 3200;
  if (speed < -3200) speed = -3200;

  // Log speed setting
  Dbg.print("Set motor speed on: ");
  Dbg.print(smcDeviceNumber);
  Dbg.print(" at ");
  Dbg.println(speed);

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
  if (smcDeviceNumber < 12 || smcDeviceNumber > 14) return false;
  Wire.clearWireTimeoutFlag();
  Wire.beginTransmission(smcDeviceNumber);
  bool commandWritten = Wire.write(0xA1) == 1;
  bool variableWritten = Wire.write(12) == 1;
  bool valid = Wire.endTransmission() == 0 && commandWritten && variableWritten;
  if (valid) {
    valid = Wire.requestFrom(smcDeviceNumber, (uint8_t)2) == 2;
    if (valid) {
      int low = Wire.read(), high = Wire.read();
      valid = low >= 0 && low <= 255 && high >= 0 && high <= 255;
      out = (uint16_t)low | ((uint16_t)high << 8);
      valid = valid && out <= 4095;
    }
  }
  return valid && !Wire.getWireTimeoutFlag();
}

// Read actuator position - retries once; on persistent failure returns
// the last good value for this device and clears positionReadValid so
// callers do not make safety decisions on garbage (0 used to be both
// the error value and a legal position)
uint16_t lastGoodPosition[3] = {0, 0, 0};  // indexed by device - 12

uint16_t readPosition() {
  uint16_t value = 0;
  servicePressure();
  positionReadValid = readPositionOnce(value) || readPositionOnce(value);
  servicePressure();

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

// Use the same checksummed telemetry for periodic status and L6 reports.
// The Pi validates this suffix even when command framing (v2) is disabled.
void emitPositionReport(uint16_t positionA, uint16_t positionB,
                        uint16_t positionC, float measuredPressure) {
  String frame = "STATUS_START|S|";
  frame += String((int)positionA);
  frame += "|";
  frame += String((int)positionB);
  frame += "|";
  frame += String((int)positionC);
  frame += "|";
  frame += String(measuredPressure);
  frame += "|STATUS_END";
  char suffix[5];
  snprintf(suffix, sizeof(suffix), "*%02X",
           xorChecksum(frame, 0, frame.length()));
  Serial1.print(frame);
  Serial1.println(suffix);
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

  bool positionsValid = true;
  // Read all actuator positions
  smcDeviceNumber = 12;
  positionA = readPosition();
  positionsValid = positionsValid && positionReadValid;
  smcDeviceNumber = 13;
  positionB = readPosition();
  positionsValid = positionsValid && positionReadValid;
  smcDeviceNumber = 14;
  positionC = readPosition();
  positionsValid = positionsValid && positionReadValid;

  if (!positionsValid) {
    smcDeviceNumber = lastSmcDeviceNumber;
    isProcessingStatus = false;
    reportSensorDiagnostics();
    return false;
  }
  // Pressure comes from the continuously-maintained filtered value;
  // never block on the HX711 inside status (it stalls the safety loop)

  // Log to Serial for debugging
  Dbg.print(F("status: "));
  Dbg.print(F(" 12: "));
  Dbg.print(positionA);
  Dbg.print(F(" 13: "));
  Dbg.print(positionB);
  Dbg.print(F(" 14: "));
  Dbg.print(positionC);
  Dbg.print(F(" pressure: "));
  Dbg.println(pressure);

  emitPositionReport(positionA, positionB, positionC, pressure);
  reportSensorDiagnostics();

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
  Dbg.println("Emergency Stop");

  // Aborted motion/pressure commands never get a DONE (v1 behavior);
  // drop the in-flight sequence so a later completion cannot echo it
  activeCmdSeq = -1;

  stopDeviceOrReport(12);
  Dbg.println("A stopped");

  stopDeviceOrReport(13);
  Dbg.println("B stopped");

  stopDeviceOrReport(14);
  Dbg.println("C stopped");

  stopFIT();
  Dbg.println("FIT stopped");

  measurePressure = false;
  pressureDirection = 0;
  pressureDonePending = false;
  pressureGuardActive = false;
  axialSpeed = PRESSURE_SPEED;
  lateralSpeed = C_SPEED;
  pulseSpeed = TREATMENT_SPEED_MAX;
  pressureProgressActive = false;
  pulseMotorSpeed = 0;
  if (tareActive) {
    tareActive = false;
    pressureCalibrated = false;
    Serial1.println("CALIBRATION|TARE|CANCELLED|STOP");
  }
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

  Dbg.print("Emergency stop + release: ");
  Dbg.println(reason);
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
  Dbg.print("Safety warning: ");
  Dbg.println(reason);
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
  // Echo the raw bytes on the debug tee so a corrupted command can be
  // seen for what it was (the host resends parse rejections once)
  Dbg.print("Rejected command: ");
  Dbg.println(commandBuffer);
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
void reportFirmwareIdentity() {
  Serial1.print("FIRMWARE|");
  Serial1.print(VERSION);
  Serial1.print("|");
  Serial1.println(HX711_DRIVER);
}

void reportSensorDiagnostics() {
  Serial1.print("DIAG|HX711|");
  Serial1.print(lastRawPressure);
  Serial1.print("|");
  Serial1.print(scale.get_offset());
  Serial1.print("|");
  Serial1.print(scale.get_scale(), 6);
  Serial1.print("|");
  Serial1.print(signedPressure, 6);
  Serial1.print("|");
  if (pressureSampleValid) Serial1.print(millis() - lastPressureSample);
  else Serial1.print(-1);
  Serial1.print("|");
  Serial1.print(maxPressurePollGap);
  Serial1.print("|");
  Serial1.print(lastPressureReadUs);
  Serial1.print("|");
  Serial1.println(scale.is_ready() ? 1 : 0);
}

void rejectTare(const char *reason) {
  tareActive = false;
  pressureCalibrated = false;
  Serial1.print("CALIBRATION|TARE|REJECTED|");
  Serial1.println(reason);
}

void acceptTareSample(long raw) {
  if (tareCount > 0) {
    if (raw < tareMin) tareMin = raw;
    if (raw > tareMax) tareMax = raw;
    float range = (float)((int64_t)tareMax - tareMin) / fabs(scale.get_scale());
    // Homing can leave the load relaxing after the motor has stopped. Start
    // a new candidate at this reading instead of failing the entire tare.
    // Only a complete subsequent stable window may replace the old offset.
    if (range > TARE_MAX_RANGE_LB) tareCount = 0;
  }
  if (tareCount == 0) {
    tareFirstSample = millis();
    tareMin = tareMax = raw;
    tareSum = 0;
  }
  tareSum += raw;
  ++tareCount;
  if (tareCount >= TARE_MIN_SAMPLES && millis() - tareFirstSample >= TARE_MIN_SPAN_MS) {
    scale.set_offset((long)(tareSum / tareCount));
    tareActive = false;
    pressureCalibrated = true;
    signedPressure = scale.units(raw);
    pressure = fabs(signedPressure) < 0.5 ? 0 : fabs(signedPressure);
    Serial1.print("CALIBRATION|TARE|OK|");
    Serial1.print(scale.get_offset());
    Serial1.print("|");
    Serial1.println(scale.get_scale(), 6);
    emitAck("DONE", tareCmdSeq);
    tareCmdSeq = -1;
  }
}

void stopPressureMotor() {
  uint8_t savedDevice = smcDeviceNumber;
  smcDeviceNumber = 12;
  setMotorSpeed(0);
  smcDeviceNumber = savedDevice;
}

void setPulseSpeed(int speed) {
  if (speed == pulseMotorSpeed) return;
  uint8_t savedDevice = smcDeviceNumber;
  smcDeviceNumber = 12;
  setMotorSpeed(speed);
  smcDeviceNumber = savedDevice;
  pulseMotorSpeed = speed;
}

float pulseReleaseFloor() {
  return max(0.0f, desiredPressure - PULSE_RELEASE_DROP);
}

void tripPressureFault(const char *reason) {
  if (pressureFault) return;
  pressureCalibrated = false;
  pressureFault = true; // Latch before stopping; queued commands cannot restart.
  emergencyStop();
  Serial1.print("FAULT|");
  Serial1.print(reason);
  Serial1.print("|");
  Serial1.print(desiredPressure);
  Serial1.print("|");
  Serial1.println(pressure);
}

void servicePressure() {
  if (pressureFault) return;
  unsigned long now = millis();
  // A fresh read must not erase a preceding sensor-service gap.
  if (pressureGuardActive && pressurePollStarted &&
      now - lastPressurePoll > PRESSURE_SAMPLE_TIMEOUT) {
    tripPressureFault("PRESSURE_SENSOR_TIMEOUT");
    return;
  }
  if (pressurePollStarted) {
    unsigned long gap = now - lastPressurePoll;
    if (gap > maxPressurePollGap) maxPressurePollGap = gap;
  }
  pressurePollStarted = true;
  lastPressurePoll = now;
  if (tareActive && now - tareStarted >= TARE_TIMEOUT_MS) {
    rejectTare(!tareCount || now - lastPressureSample > PRESSURE_SAMPLE_TIMEOUT ?
               "SENSOR_TIMEOUT" : "UNSTABLE");
  }
  long raw = 0;
  Hx711Sampler::Result result = scale.read_if_ready(raw, lastPressureReadUs);
  if (result != Hx711Sampler::NOT_READY) {
    lastRawPressure = raw;
    signedPressure = scale.units(raw);
    float sample = fabs(signedPressure);
    if (result == Hx711Sampler::INVALID || !isfinite(sample)) {
      pressureSampleValid = false;
      if (tareActive) { rejectTare("SENSOR_INVALID"); return; }
      if (pressureCalibrated || pressureGuardActive)
        tripPressureFault("PRESSURE_INVALID");
      return;
    }
    pressure = sample < 0.5 ? 0 : sample;
    // A sensor gap cannot count toward the duration of a stable window.
    if (tareActive && now - lastPressureSample > PRESSURE_SAMPLE_TIMEOUT)
      tareCount = 0;
    lastPressureSample = now;
    lastScaleReady = now;
    pressureSampleValid = true;
    if (tareActive) { acceptTareSample(raw); return; }
    if (((pressureCalibrated || pressureGuardActive) && pressure > PRESSURE_HARD_LIMIT) ||
        (pressureGuardActive && pressure > pressureCeiling)) {
      tripPressureFault("PRESSURE_LIMIT");
      return;
    }
    if (measurePressure &&
        ((pressureDirection > 0 && pressure >= desiredPressure) ||
         (pressureDirection < 0 && pressure <= desiredPressure + PRESSURE_TARGET_BAND))) {
      stopPressureMotor(); // Stop before sending any status or DONE message.
      measurePressure = false;
      pressureDirection = 0;
      pressureCeiling = protocolPressureLimit + PRESSURE_OVERSHOOT_LIMIT;
      pressureDonePending = true;
    }
    if (jerking && ((jerkDirection > 0 && pressure >= desiredPressure) ||
                    (jerkDirection < 0 && pressure <= pulseReleaseFloor())))
      setPulseSpeed(0); // Stop at the sampled bound, before telemetry or phase timing.
  }
  if (pressureGuardActive &&
      (!pressureSampleValid || now - lastPressureSample > PRESSURE_SAMPLE_TIMEOUT)) {
    tripPressureFault("PRESSURE_SENSOR_TIMEOUT");
  } else if (measurePressure && now - pressureMoveStarted >= PRESSURE_MOVE_DEADLINE) {
    tripPressureFault("PRESSURE_MOVE_TIMEOUT");
  }
}

void reportPressureDone(long seq) {
  Serial1.print("MOTION_DONE|P|");
  Serial1.print(desiredPressure); Serial1.print("|"); Serial1.println(pressure);
  emitAck("DONE", seq);
}

void reportPositionDone(char kind, uint16_t target, uint16_t actual, long seq) {
  Serial1.print("MOTION_DONE|"); Serial1.print(kind == 'K' ? "K" : kind == 'A' ? "A" : "I");
  Serial1.print("|"); Serial1.print(target); Serial1.print("|"); Serial1.println(actual);
  emitAck("DONE", seq);
}

void rejectCommand(const char *command, const char *reason) {
  Serial1.print("COMMAND_REJECTED|"); Serial1.print(command);
  Serial1.print("|"); Serial1.println(reason);
}

void updatePressure() { servicePressure(); }


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
int positionMoveSpeed(uint8_t device) {
  if (device == 12) return axialSpeed;
  if (device == 14) return lateralSpeed;
  return BC_SPEED;
}

// Zero-pressure release always uses the proven fixed output, independently
// of the treatment speed selection (as does the autonomous E-stop release).
int pressureMoveSpeed() {
  return desiredPressure <= 0 ? PRESSURE_SPEED : axialSpeed;
}

void processCommand(String cmd) {
  if (cmd.length() == 0) return;

  // Validate command length
  if (cmd.length() > MAX_COMMAND_LENGTH) {
    Dbg.println("Command too long, ignoring");
    emitCmdError("Command too long");
    return;
  }

  char commandType = cmd[0];
  if (pressureFault && commandType != 'Y' && commandType != 'X' &&
      commandType != 'T' && commandType != 'Q' && commandType != 'S' &&
      commandType != 'H' && cmd != "JS" && cmd != "F0") {
    char kind[2] = {commandType, 0};
    rejectCommand(kind, "FAULT_LATCHED");
    return;
  }
  if (tareActive && (commandType == 'P' || commandType == 'I' || commandType == 'K' ||
      commandType == 'A' || (commandType == 'J' && cmd != "JS") ||
      (commandType == 'F' && cmd != "F0"))) {
    char kind[2] = {commandType, 0};
    rejectCommand(kind, "TARE_BUSY");
    return;
  }
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
  uint16_t localDesiredPosition = 0;
  float localPressure = 0;

  // Handle different command types
  switch (commandType) {
    case 'V': {
      // Atomic V<axial%>,<lateral%>,<pulse%>. Configuration alone must never
      // start a motor or change the speed of an in-flight centering move.
      int values[3] = {0, 0, 0};
      int field = 0;
      bool hasDigit = false;
      bool valid = true;
      for (unsigned int i = 1; i < cmd.length(); ++i) {
        char c = cmd[i];
        if (c >= '0' && c <= '9') {
          values[field] = values[field] * 10 + (c - '0');
          hasDigit = true;
          if (values[field] > MOTOR_SPEED_MAX_PERCENT) { valid = false; break; }
        } else if (c == ',' && hasDigit && field < 2) {
          ++field;
          hasDigit = false;
        } else { valid = false; break; }
      }
      if (!hasDigit || field != 2) valid = false;
      for (int i = 0; i < 3; ++i) {
        if (values[i] < MOTOR_SPEED_MIN_PERCENT) valid = false;
      }
      if (!valid) { emitCmdError("Invalid V speeds"); return; }
      if (measurePressure || jerking || releasingPressure ||
          (bRunning && runningDevice == 12)) {
        emitAck("BUSY", currentCmdSeq);
        return;
      }
      axialSpeed = TREATMENT_SPEED_MAX * (long)values[0] / 100;
      lateralSpeed = TREATMENT_SPEED_MAX * (long)values[1] / 100;
      pulseSpeed = TREATMENT_SPEED_MAX * (long)values[2] / 100;
      if (currentCmdSeq >= 0) {
        emitAck("OK", currentCmdSeq);
      } else {
        // Dedicated legacy ack: never masquerade as a motion DONE or T OK.
        Serial1.print("SPEED|");
        Serial1.print(values[0]); Serial1.print("|");
        Serial1.print(values[1]); Serial1.print("|");
        Serial1.println(values[2]);
      }
      break;
    }
    // Test command
    case 'T':
        Dbg.println("Test command received");
        emitAck("OK", currentCmdSeq);
        reportFirmwareIdentity();
        reportSensorDiagnostics();
        break;

    // Status acknowledgment
    case 'Q':
        statusAcknowledged = true;
        break;

    case 'H': // High Frequency Status Toggle Command
      if (cmd.length() > 2 && cmd.substring(1,3) == "F1") {
        highFrequencyStatus = true;
        Dbg.println("High frequency status ON");
        timeSinceLastStatus = 0; // Reset timer immediately
        statusAcknowledged = true; // Reset flag to allow immediate status
        sendStatus(); // Send status once when activated
        emitAck("DONE", currentCmdSeq); // Acknowledge command
      } else if (cmd.length() > 2 && cmd.substring(1,3) == "F0") {
        highFrequencyStatus = false;
        Dbg.println("High frequency status OFF");
        emitAck("DONE", currentCmdSeq); // Acknowledge command
      }
      break;

    // Status request
    case 'S':
      sendStatus();
      break;

    // Pressure control
    case 'P': {
      float localPressure = 0;
      float localPressureLimit = 0;
      if (!pressureCalibrated) {
        Serial1.println("COMMAND_REJECTED|P|TARE_REQUIRED");
        return;
      }
      if (bRunning || jerking || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);
        return;
      }

      parameter = cmd.substring(1);
      {
        char *end = NULL;
        localPressure = strtod(parameter.c_str(), &end);
        bool validTarget = end != parameter.c_str();
        localPressureLimit = localPressure;
        // P<step>|<selected target> distinguishes a ramp waypoint from the
        // protocol's pressure limit. Plain P<target> still serves manual moves.
        if (*end == '|') {
          const char *limitStart = end + 1;
          localPressureLimit = strtod(limitStart, &end);
          validTarget = validTarget && end != limitStart;
        }
        if (!validTarget || *end != '\0' ||
            !isfinite(localPressure) || localPressure < 0 ||
            localPressure > MAX_PRESSURE_LBS ||
            !isfinite(localPressureLimit) || localPressureLimit < localPressure ||
            localPressureLimit > MAX_PRESSURE_LBS) {
          tripPressureFault("PRESSURE_TARGET_INVALID");
          return;
        }
      }
      if (localPressure > 0 && rejectIfStopEngaged()) return;
      servicePressure();
      if (pressureFault) return;
      if (!pressureSampleValid || millis() - lastPressureSample > PRESSURE_SAMPLE_TIMEOUT) {
        tripPressureFault("PRESSURE_SENSOR_TIMEOUT");
        return;
      }
      // Only an explicit stable resting-load tare establishes a pressure baseline.
      if (pressure > PRESSURE_HARD_LIMIT) {
        tripPressureFault("PRESSURE_LIMIT");
        return;
      }
      // Repeated commands must not restart a finished move or extend a
      // stalled move's timeout, and must not raise its overshoot ceiling.
      if (pressureGuardActive && desiredPressure == localPressure &&
          protocolPressureLimit == localPressureLimit) {
        if (!measurePressure) reportPressureDone(currentCmdSeq);
        return;
      }
      uint16_t initialAxial = 0;
      bool increasing = pressure < localPressure;
      smcDeviceNumber = 12;
      initialAxial = readPosition();
      if (!positionReadValid) { tripPressureFault("POSITION_FEEDBACK_INVALID"); return; }
      if (pressureFault) return;
      stopPressureMotor();
      measurePressure = false;
      pressureDirection = 0;
      desiredPressure = localPressure;
      protocolPressureLimit = localPressureLimit;
      pressureGuardActive = true;
      pressureDonePending = false;
      pressureCeiling = max(pressure, protocolPressureLimit) + PRESSURE_OVERSHOOT_LIMIT;
      pressureMoveStarted = millis();
      pressureTimeoutWarningIssued = false;
      activeCmdSeq = currentCmdSeq;
      pressureProgressActive = increasing;
      pressureProgressNotified = false;
      pressureStartPosition = initialAxial;
      pressureStartForce = pressure;
      // Do not skip a fresh increase merely because it starts less than 2 lb
      // below target. At/above-target loads inside the band need no movement;
      // P0 still completes within 0-2 lb without driving toward sensor noise.
      if (pressure >= desiredPressure &&
          pressure <= desiredPressure + PRESSURE_TARGET_BAND) {
        pressureCeiling = protocolPressureLimit + PRESSURE_OVERSHOOT_LIMIT;
        reportPressureDone(currentCmdSeq);
        return;
      }
      pressureDirection = pressure < desiredPressure ? 1 : -1;
      measurePressure = true;
      smcDeviceNumber = 12;
      setMotorSpeed((desiredPressure == 0 ? PRESSURE_SPEED : axialSpeed) * pressureDirection);
      break;
    }

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
      Dbg.print(F("Stopped at Position: "));
      Dbg.println(readPosition());
      emitAck("DONE", currentCmdSeq);
      break;

    // Get position
    case 'G':
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      localPosition = readPosition();
      Dbg.print(F("Get Position: "));
      Dbg.print(localPosition);
      Serial1.print("P|");
      Serial1.println(localPosition);
      emitAck("DONE", currentCmdSeq);
      break;

    // Position control
    case 'I':
      if (rejectIfStopEngaged()) return;
      if (bRunning || measurePressure || jerking || releasingPressure) {
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
      Dbg.println(smcDeviceNumber);

      parameter = cmd.substring(3);
      if (!isNumeric(parameter) || parameter.toInt() < 0 || parameter.toInt() > 4095) {
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

      positionCommandKind = 'I';
      positionTolerance = (smcDeviceNumber == 12 && localDesiredPosition == AZERO) ? 25 : 0;
      localPosition = readPosition();
      if (!positionReadValid || pressureFault) {
        emitCmdError("Position read failed");
        return;
      }

      Dbg.print(localDesiredPosition);
      Dbg.print(" ");
      Dbg.println(localPosition);

      // Symmetric close-enough band: small moves in either direction
      // complete immediately instead of one-sided 25-count behavior
      if (localDesiredPosition + positionTolerance >= localPosition &&
          localPosition + positionTolerance >= localDesiredPosition) {
        position = localPosition;
        desiredPosition = localDesiredPosition;
        setMotorSpeed(0);
        reportPositionDone(positionCommandKind, localDesiredPosition, localPosition, currentCmdSeq);
        sendStatus();
        break;
      }
      forward = (localDesiredPosition > localPosition) ? 1 : -1;

      // Copy local variables to globals for use in loop()
      position = localPosition;
      desiredPosition = localDesiredPosition;

      setMotorSpeed(forward * positionMoveSpeed(smcDeviceNumber));

      Dbg.print(AZERO);
      Dbg.print(" ");
      Dbg.print(forward);
      Dbg.print(" ");
      Dbg.print(desiredPosition);
      Dbg.print(" ");
      Dbg.println(position);

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
      if (bRunning || measurePressure || jerking || releasingPressure) {
        emitAck("BUSY", currentCmdSeq);  // never silently drop a motion command
        return;
      }

      smcDeviceNumber = 14;
      Dbg.println(cmd);
      parameter = cmd.substring(1);
      Dbg.println(parameter);

      if (!isNumeric(parameter) || parameter.toInt() < 0 || parameter.toInt() > 4095) {
        // Reject corrupt input: toInt() garbage would drive the lateral
        // actuator to its clamp floor (500); >16-bit values would wrap
        emitCmdError("Invalid K value");
        return;
      }
      localDesiredPosition = parameter.toInt();
      localDesiredPosition = clampPositionTarget(smcDeviceNumber, localDesiredPosition);
      Dbg.println(localDesiredPosition);

      positionCommandKind = 'K';
      positionTolerance = 100;
      localPosition = readPosition();
      if (!positionReadValid || pressureFault) {
        emitCmdError("Position read failed");
        return;
      }
      Dbg.print(localDesiredPosition);
      Dbg.print(" ");
      Dbg.println(localPosition);

      // Symmetric close-enough band (see 'I')
      if (localDesiredPosition + positionTolerance >= localPosition &&
          localPosition + positionTolerance >= localDesiredPosition) {
        desiredPosition = localDesiredPosition;
        position = localPosition;
        setMotorSpeed(0);
        reportPositionDone(positionCommandKind, localDesiredPosition, localPosition, currentCmdSeq);
        sendStatus();
        break;
      }
      forward = (localDesiredPosition > localPosition) ? 1 : -1;

      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;

      setMotorSpeed(forward * positionMoveSpeed(smcDeviceNumber));

      Dbg.print(forward);
      Dbg.print(" ");
      Dbg.print(desiredPosition);
      Dbg.print(" ");
      Dbg.println(position);

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
      if (bRunning || measurePressure || jerking || releasingPressure) {
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
      Dbg.println(smcDeviceNumber);

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

      positionCommandKind = 'A';
      if (localDesiredPosition > 4095) {
        emitCmdError("A value out of range");
        return;
      }
      positionTolerance = (smcDeviceNumber == 12 && inches == 0) ? 25 : 0;
      localPosition = readPosition();
      if (!positionReadValid || pressureFault) {
        emitCmdError("Position read failed");
        return;
      }
      Dbg.print(inches);
      Dbg.print(" ");
      Dbg.print(localDesiredPosition);
      Dbg.print(" ");
      Dbg.println(localPosition);

      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;

      // Symmetric close-enough band (see 'I')
      if (desiredPosition + positionTolerance >= position &&
          position + positionTolerance >= desiredPosition) {
        setMotorSpeed(0);
        reportPositionDone(positionCommandKind, localDesiredPosition, localPosition, currentCmdSeq);
        sendStatus();
        break;
      }
      forward = (desiredPosition > position) ? 1 : -1;

      setMotorSpeed(forward * positionMoveSpeed(smcDeviceNumber));
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
        case 0: {
          if (bRunning || measurePressure || jerking || moveFITForward || releasingPressure ||
              pressureGuardActive || tareActive) { rejectCommand("L0", "MOTION_ACTIVE"); break; }
          parameter = cmd.substring(2);
          float factor = parameter.toFloat();
          if (!isNumeric(parameter) || !isfinite(factor) || fabs(factor) < 1.0 ||
              fabs(factor) > 100000000.0) { rejectCommand("L0", "INVALID_FACTOR"); break; }
          calibration_factor = factor;
          scale.set_scale(factor);
          pressureCalibrated = false;
          Serial1.print("CALIBRATION|SET|"); Serial1.println(factor, 6);
          emitAck("DONE", currentCmdSeq);
          break;
        }
        case 1:
          pressureCalibrated = false;
          if (bRunning || measurePressure || jerking || moveFITForward || releasingPressure ||
              pressureGuardActive || tareActive) { rejectTare("MOTION_ACTIVE"); break; }
          if (cmd != "L1|BASELINE") { rejectTare("BASELINE_REQUEST_REQUIRED"); break; }
          tareActive = true;
          tareStarted = millis();
          tareCount = 0; tareSum = 0; tareCmdSeq = currentCmdSeq;
          Serial1.println("CALIBRATION|TARE|STARTED");
          break;
        case 4:
          servicePressure();
          if (pressureSampleValid) { Serial1.print("weight|"); Serial1.println(pressure); }
          reportSensorDiagnostics();
          break;

        case 5: // Set zero marks
          if (bRunning || measurePressure || jerking || moveFITForward || releasingPressure ||
              pressureGuardActive || tareActive) { rejectCommand("L5", "MOTION_ACTIVE"); break; }
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
            if (newAZero < AXIAL_MIN_POS || newAZero > 4095 ||
                newBZero < HORIZONTAL_MIN_POS || newBZero > 4095) {
              emitCmdError("Invalid L5 zero marks");
              break;
            }
            AZERO = (int)newAZero;
            BZERO = (int)newBZero;
          }
          Dbg.print("AZERO: ");
          Dbg.print(AZERO);
          Dbg.print("BZERO: ");
          Dbg.println(BZERO);
          // Echo parsed values so the host can verify what was applied
          Serial1.print("ZEROS|");
          Serial1.print(AZERO);
          Serial1.print("|");
          Serial1.println(BZERO);
          emitAck("DONE", currentCmdSeq);
          break;

        case 6:
          sendStatus();
          break;

        default:
          Dbg.println(stage);
          break;
      }
      break;

    // Jerking motion control - FIXED
    case 'J':
      parameter = "";
      if (cmd.length() > 1)
          parameter = cmd.substring(1);

      if (parameter == "S") {
          Dbg.println("stop jerking");
          // Stop only the pulsing axial motor, and only if pulsing was
          // active. setMotorSpeed(0) used to hit whichever SMC was last
          // addressed: a JS from the host's live pulse-rate control during
          // a K/I move zeroed THAT actuator mid-travel and left bRunning
          // set forever (no DONE, then BUSY for every command until X).
          if (jerking) {
              smcDeviceNumber = 12;
              setMotorSpeed(0);
          }
          pulseMotorSpeed = 0;
          jerkDirection = 0;
          jerking = false;
          jerksCompleted = 0; // Reset counter
          emitAck("DONE", currentCmdSeq);
      } else {
          if (rejectIfStopEngaged()) return;
          if (!pressureCalibrated) { rejectCommand("J", "TARE_REQUIRED"); return; }
          if (!pressureGuardActive || desiredPressure <= 0) {
            rejectCommand("J", "PRESSURE_TARGET_REQUIRED"); return;
          }
          if (jerking) { emitAck("DONE", currentCmdSeq); return; }
          // Pulsing drives the axial SMC: refuse to overlap an in-flight
          // axial pressure/position move or the E-stop release. The host
          // worker only starts J once those moves have reported DONE, and
          // it treats BUSY as transient.
          if (measurePressure || releasingPressure ||
              bRunning) {
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
          servicePressure();
          if (pressureFault) return;
          Dbg.println("jerking");
          jerking = true;
          // Status stays ON during pulsing: the pressure ceiling check
          // and the Pi both need telemetry exactly when force pulses
          sendStatus();
          jerksCompleted = 0;
          jerkDirection = pressure < desiredPressure ? 1 : -1;
          setPulseSpeed(pulseSpeed * jerkDirection);
          lastJerkTime = millis(); // Initialize jerk timer
          smcDeviceNumber = 12;
          emitAck("DONE", currentCmdSeq);
      }
      break;

    // External actuator control - FIXED: Added break statement
    case 'F':
      {
        String direction = cmd.substring(1, 2);
        Dbg.println(direction);

        if (direction == "0") {
          stopFIT();
          Dbg.println("Fit stopped.");
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
          Dbg.println("Fit extending.");
          digitalWrite(DIR_FIT_FORWARD, LOW);
          digitalWrite(DIR_FIT_REVERSE, HIGH);
        } else if (direction == "-") {
          moveFITForward = true;
          FITDelay = FIT_SLOW_DELAY;
          Dbg.println("Fit reversing.");
          digitalWrite(DIR_FIT_FORWARD, HIGH);
          digitalWrite(DIR_FIT_REVERSE, LOW);
        } else if (direction == "F") {
          moveFITForward = true;
          FITDelay = FIT_FAST_DELAY;
          Dbg.println("Fit fast extending.");
          digitalWrite(DIR_FIT_FORWARD, LOW);
          digitalWrite(DIR_FIT_REVERSE, HIGH);
        } else if (direction == "R") {
          moveFITForward = true;
          FITDelay = FIT_FAST_DELAY;
          Dbg.println("Fit fast reversing.");
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
      Dbg.print("Unknown command: ");
      Dbg.println(commandType);
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
  Dbg.println("All actuators stopped");

  Dbg.println("\n\n\nStarting");
  Dbg.print("VERSION: ");
  Dbg.println(VERSION);

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

  Dbg.print("readPosition ");
  Dbg.println(readPosition());

  // Startup complete
  Dbg.println("Ready to Go");
  Serial1.println("");
  reportFirmwareIdentity();
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
unsigned long lastMoveDebugMs = 0;
#define MOVE_DEBUG_INTERVAL 250  // ms between position-move debug lines

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
  if (!pressureFault && pressure > PRESSURE_WARNING_LBS) {
    if (!pressureWarningIssued) {
      emitSafetyWarning("Pressure warning threshold exceeded");
      pressureWarningIssued = true;
    }
  } else {
    pressureWarningIssued = false;
  }

  // Host heartbeat remains advisory; servicePressure owns latched sensor faults.
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
    Dbg.println("Status processing timeout");
  }

  // Check for status acknowledgment timeout
  if (!statusAcknowledged && millis() - lastStatusTime > STATUS_TIMEOUT) {
    Dbg.println("Status acknowledgment timeout - resetting flag");
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

  if (jerking) {
    // Never sleep through a pulse: sample and accept stop commands throughout.
    unsigned long phaseElapsed = millis() - lastJerkTime;
    if (jerkDirection < 0) {
      // The release may already have stopped at its pressure floor. Never
      // restart that stroke on rebound; its elapsed-time cap still applies.
      if (phaseElapsed >= jerkInterval) {
        jerkDirection = 1;
        lastJerkTime = millis();
        setPulseSpeed(pressure < desiredPressure ? pulseSpeed : 0);
      }
    } else if (pressure >= desiredPressure) {
      setPulseSpeed(0);
      if (phaseElapsed >= jerkInterval) {
        jerkDirection = -1;
        lastJerkTime = millis();
        setPulseSpeed(-pulseSpeed);
      }
    } else if (phaseElapsed >= PULSE_RECOVERY_TIMEOUT) {
      tripPressureFault("PULSE_RECOVERY_TIMEOUT");
    } else {
      // Keep recovering after 500 ms if needed, and recover any droop after
      // an early target stop. Only a recovered load permits the next release.
      setPulseSpeed(pulseSpeed);
    }
  }

  // External actuator timer
  if (moveFITForward) {
    if (timeInFIT > FITDelay) {
      digitalWrite(DIR_FIT_FORWARD, LOW);
      digitalWrite(DIR_FIT_REVERSE, LOW);
      Dbg.println("Fit stopped.");
      Dbg.println("fit done");
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
      // Debug output, rate-limited: this used to print every loop pass
      // (~40 lines/s), and once the tee carried it to the Pi the link
      // showed RX overruns (garbled bytes) during long moves
      if (millis() - lastMoveDebugMs >= MOVE_DEBUG_INTERVAL) {
        lastMoveDebugMs = millis();
        Dbg.print(forward); Dbg.print(" ");
        Dbg.print(CInches); Dbg.print(" ");
        Dbg.print(currentPos); Dbg.print(" ");
        Dbg.print(loopLastPosition); Dbg.print(" ");
        Dbg.println(desiredPosition);
      }

      // Arrival uses the SAME symmetric POSITION_DEADBAND band as the
      // command-time close-enough check (see 'I'/'K'/'A'): an actuator
      // that settles within the deadband of its target has arrived. The
      // old strict compare (>=/<=) never registered arrival when the
      // axial actuator bottomed out at its home a few counts short of
      // AZERO, so the stall detector below fired "Motor stalled" on a
      // reset that had actually reached home.
      bool targetReached =
          (abs((long)desiredPosition - (long)currentPos) <= positionTolerance) ||
          (forward > 0 ? currentPos >= desiredPosition : currentPos <= desiredPosition);

      if (targetReached) {
        Dbg.println("Stopped Moving - Target Reached");
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
    if (!positionReadValid) { tripPressureFault("POSITION_FEEDBACK_INVALID"); }
    // On an invalid position read, skip arrival/stall decisions this
    // iteration rather than acting on garbage (0 was both the error
    // value and a legal position)

    // Cleanup after run complete
    if (!bRunning && !pressureFault) {
      position = currentPos;
      reportPositionDone(positionCommandKind, desiredPosition, currentPos, activeCmdSeq);
      sendStatus();
      activeCmdSeq = -1;
    }
  }

  if (measurePressure || jerking) {
    uint8_t savedDevice = smcDeviceNumber;
    smcDeviceNumber = 12;
    uint16_t currentPos = readPosition();
    smcDeviceNumber = savedDevice;
    if (!positionReadValid) tripPressureFault("POSITION_FEEDBACK_INVALID");
    if (!pressureFault && measurePressure) {
      if (pressureDirection > 0 && currentPos >= min(AXIAL_MAX_POS, 4095))
        tripPressureFault("AXIAL_TRAVEL_LIMIT");
      if (pressureDirection < 0 && currentPos <= AZERO + POSITION_DEADBAND &&
          pressure > desiredPressure + PRESSURE_TARGET_BAND)
        tripPressureFault("AXIAL_HOME_BEFORE_PRESSURE_TARGET");
      if (millis() - pressureMoveStarted >= PRESSURE_MOVE_TIMEOUT &&
          !pressureTimeoutWarningIssued) {
        emitSafetyWarning("Pressure move timeout approaching");
        pressureTimeoutWarningIssued = true;
      }
      long travel = (long)currentPos - pressureStartPosition;
      float rise = pressure - pressureStartForce;
      if (pressureProgressActive && !pressureProgressNotified &&
          travel >= PRESSURE_PROGRESS_TRAVEL && rise < PRESSURE_PROGRESS_MIN_RISE) {
        pressureProgressNotified = true;
        Serial1.print("NOTICE|PRESSURE_NO_PROGRESS|"); Serial1.print(travel);
        Serial1.print("|"); Serial1.print(rise); Serial1.print("|"); Serial1.println(pressure);
      }
    }
  }
  if (pressureDonePending && !pressureFault) {
    pressureDonePending = false;
    reportPressureDone(activeCmdSeq);
    activeCmdSeq = -1;
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
        Dbg.println("Command buffer overflow");
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
