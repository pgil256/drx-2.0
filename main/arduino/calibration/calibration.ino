/*
  Actuator Calibration Script for KneeSpa

  This standalone script helps calibrate and record actuator positions
  for the A (axial), B (horizontal), and C (lateral) actuators.

  Usage:
  1. Upload this script to Arduino Mega 2560
  2. Open Serial Monitor at 115200 baud
  3. Use commands to move and record positions
  4. Copy the output calibration data to kneespa.cfg

  Commands:
  - A+/A-  : Move axial actuator forward/backward
  - B+/B-  : Move horizontal actuator forward/backward
  - C+/C-  : Move lateral actuator forward/backward
  - S      : Stop all movement
  - P      : Print current positions
  - R A/B/C: Record current position for actuator
  - Z A/B/C: Set zero position for actuator
  - E      : Export calibration data for kneespa.cfg
  - H      : Show help/commands
  - M A/B/C <speed>: Set movement speed (100-3200)
  - G A/B/C <position>: Go to specific position
*/

#include <Wire.h>
#include <elapsedMillis.h>

// Pin definitions (same as motor.ino)
#define STOP_PIN 3

// Actuator IDs
#define ACTUATOR_A 12  // Axial
#define ACTUATOR_B 13  // Horizontal
#define ACTUATOR_C 14  // Lateral

// Speed settings
int speedA = 800;
int speedB = 800;
int speedC = 800;

// Zero positions
int zeroA = 160;  // Default from kneespa.cfg
int zeroB = 80;   // Default from kneespa.cfg
int zeroC = 1400; // Default from kneespa.cfg (0 degrees)

// Calibration data storage
struct CalibrationPoint {
  float measurement;  // inches or degrees
  uint16_t position;  // encoder position
  bool recorded;
};

// Calibration arrays
CalibrationPoint calibA[10];  // For 0-4 inches
CalibrationPoint calibB[10];  // For degrees
CalibrationPoint calibC[20];  // For -20 to +20 degrees

int calibACount = 0;
int calibBCount = 0;
int calibCCount = 0;

// Current positions
uint16_t currentA = 0;
uint16_t currentB = 0;
uint16_t currentC = 0;

// Movement state
uint8_t currentActuator = 0;
bool isMoving = false;
int moveDirection = 0;

elapsedMillis timeSinceLastStatus = 0;

// Function prototypes
void exitSafeStart(uint8_t device);
void setMotorSpeed(uint8_t device, int16_t speed);
uint16_t readPosition(uint8_t device);
void stopAll();
void printPositions();
void recordPosition(char actuator);
void setZeroPosition(char actuator);
void exportCalibration();
void showHelp();
void goToPosition(char actuator, uint16_t targetPos);
void processCommand(String cmd);

void setup() {
  Serial.begin(115200);
  Wire.begin();

  pinMode(STOP_PIN, INPUT);

  // Initialize actuators
  exitSafeStart(ACTUATOR_A);
  exitSafeStart(ACTUATOR_B);
  exitSafeStart(ACTUATOR_C);

  // Stop all motors initially
  stopAll();

  // Initialize calibration arrays
  for (int i = 0; i < 10; i++) {
    calibA[i].recorded = false;
    calibB[i].recorded = false;
  }
  for (int i = 0; i < 20; i++) {
    calibC[i].recorded = false;
  }

  Serial.println(F("====================================="));
  Serial.println(F("KneeSpa Actuator Calibration Tool"));
  Serial.println(F("====================================="));
  Serial.println(F("Type 'H' for help"));
  Serial.println();

  delay(1000);
  printPositions();
}

void loop() {
  // Check emergency stop
  if (digitalRead(STOP_PIN) == HIGH) {
    stopAll();
    Serial.println(F("EMERGENCY STOP ACTIVATED!"));
  }

  // Update positions periodically
  if (timeSinceLastStatus > 1000) {
    timeSinceLastStatus = 0;
    currentA = readPosition(ACTUATOR_A);
    currentB = readPosition(ACTUATOR_B);
    currentC = readPosition(ACTUATOR_C);

    if (isMoving) {
      printPositions();
    }
  }

  // Process serial commands
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    processCommand(cmd);
  }
}

void processCommand(String cmd) {
  if (cmd.length() == 0) return;

  char command = cmd[0];

  switch (command) {
    case 'A':
      if (cmd.length() > 1) {
        if (cmd[1] == '+') {
          Serial.println(F("Moving A (axial) forward..."));
          setMotorSpeed(ACTUATOR_A, speedA);
          isMoving = true;
          currentActuator = ACTUATOR_A;
        } else if (cmd[1] == '-') {
          Serial.println(F("Moving A (axial) backward..."));
          setMotorSpeed(ACTUATOR_A, -speedA);
          isMoving = true;
          currentActuator = ACTUATOR_A;
        }
      }
      break;

    case 'B':
      if (cmd.length() > 1) {
        if (cmd[1] == '+') {
          Serial.println(F("Moving B (horizontal) forward..."));
          setMotorSpeed(ACTUATOR_B, speedB);
          isMoving = true;
          currentActuator = ACTUATOR_B;
        } else if (cmd[1] == '-') {
          Serial.println(F("Moving B (horizontal) backward..."));
          setMotorSpeed(ACTUATOR_B, -speedB);
          isMoving = true;
          currentActuator = ACTUATOR_B;
        }
      }
      break;

    case 'C':
      if (cmd.length() > 1) {
        if (cmd[1] == '+') {
          Serial.println(F("Moving C (lateral) forward..."));
          setMotorSpeed(ACTUATOR_C, speedC);
          isMoving = true;
          currentActuator = ACTUATOR_C;
        } else if (cmd[1] == '-') {
          Serial.println(F("Moving C (lateral) backward..."));
          setMotorSpeed(ACTUATOR_C, -speedC);
          isMoving = true;
          currentActuator = ACTUATOR_C;
        }
      }
      break;

    case 'S':
      stopAll();
      Serial.println(F("All motors stopped"));
      break;

    case 'P':
      printPositions();
      break;

    case 'R':
      if (cmd.length() > 2) {
        recordPosition(cmd[2]);
      } else {
        Serial.println(F("Usage: R A/B/C <measurement>"));
        Serial.println(F("Example: R A 2.5  (record A at 2.5 inches)"));
        Serial.println(F("Example: R C -10  (record C at -10 degrees)"));
      }
      break;

    case 'Z':
      if (cmd.length() > 2) {
        setZeroPosition(cmd[2]);
      } else {
        Serial.println(F("Usage: Z A/B/C"));
      }
      break;

    case 'E':
      exportCalibration();
      break;

    case 'H':
      showHelp();
      break;

    case 'M':
      if (cmd.length() > 4) {
        char actuator = cmd[2];
        int newSpeed = cmd.substring(4).toInt();
        if (newSpeed >= 100 && newSpeed <= 3200) {
          switch (actuator) {
            case 'A':
              speedA = newSpeed;
              Serial.print(F("A speed set to: "));
              Serial.println(speedA);
              break;
            case 'B':
              speedB = newSpeed;
              Serial.print(F("B speed set to: "));
              Serial.println(speedB);
              break;
            case 'C':
              speedC = newSpeed;
              Serial.print(F("C speed set to: "));
              Serial.println(speedC);
              break;
          }
        } else {
          Serial.println(F("Speed must be between 100 and 3200"));
        }
      }
      break;

    case 'G':
      if (cmd.length() > 4) {
        char actuator = cmd[2];
        uint16_t targetPos = cmd.substring(4).toInt();
        goToPosition(actuator, targetPos);
      } else {
        Serial.println(F("Usage: G A/B/C <position>"));
      }
      break;

    default:
      Serial.println(F("Unknown command. Type 'H' for help"));
  }
}

void exitSafeStart(uint8_t device) {
  Wire.beginTransmission(device);
  Wire.write(0x83);  // Exit safe start
  Wire.endTransmission();
}

void setMotorSpeed(uint8_t device, int16_t speed) {
  // Limit speed
  if (speed > 3200) speed = 3200;
  if (speed < -3200) speed = -3200;

  uint8_t cmd = 0x85;  // Motor forward
  if (speed < 0) {
    cmd = 0x86;  // Motor reverse
    speed = -speed;
  }

  exitSafeStart(device);
  Wire.beginTransmission(device);
  Wire.write(cmd);
  Wire.write(speed & 0x1F);
  Wire.write(speed >> 5 & 0x7F);
  Wire.endTransmission();
}

uint16_t readPosition(uint8_t device) {
  uint16_t position = 0;

  Wire.beginTransmission(device);
  Wire.write(0xA1);  // Get variable command
  Wire.write(12);    // Position variable ID
  Wire.endTransmission();

  delay(50);

  int returned = Wire.requestFrom(device, (uint8_t)2);
  if (returned == 2) {
    position = Wire.read();
    position = position + (Wire.read() * 256);
  }

  if (position <= 0 || position > 65000) {
    position = 0;
  }

  return position;
}

void stopAll() {
  setMotorSpeed(ACTUATOR_A, 0);
  setMotorSpeed(ACTUATOR_B, 0);
  setMotorSpeed(ACTUATOR_C, 0);
  isMoving = false;
  currentActuator = 0;
}

void printPositions() {
  Serial.println(F("-------------------------------------"));
  Serial.print(F("A (axial):      "));
  Serial.print(currentA);
  Serial.print(F(" (zero: "));
  Serial.print(zeroA);
  Serial.println(F(")"));

  Serial.print(F("B (horizontal): "));
  Serial.print(currentB);
  Serial.print(F(" (zero: "));
  Serial.print(zeroB);
  Serial.println(F(")"));

  Serial.print(F("C (lateral):    "));
  Serial.print(currentC);
  Serial.print(F(" (zero: "));
  Serial.print(zeroC);
  Serial.println(F(")"));
  Serial.println(F("-------------------------------------"));
}

void recordPosition(char actuator) {
  // Parse the full command to get measurement value
  String fullCmd = Serial.readStringUntil('\n');
  fullCmd.trim();
  float measurement = fullCmd.toFloat();

  switch (actuator) {
    case 'A':
      currentA = readPosition(ACTUATOR_A);
      Serial.print(F("Recording A at "));
      Serial.print(measurement);
      Serial.print(F(" inches, position: "));
      Serial.println(currentA);

      if (calibACount < 10) {
        calibA[calibACount].measurement = measurement;
        calibA[calibACount].position = currentA;
        calibA[calibACount].recorded = true;
        calibACount++;
      } else {
        Serial.println(F("Max calibration points reached for A"));
      }
      break;

    case 'B':
      currentB = readPosition(ACTUATOR_B);
      Serial.print(F("Recording B at "));
      Serial.print(measurement);
      Serial.print(F(" degrees, position: "));
      Serial.println(currentB);

      if (calibBCount < 10) {
        calibB[calibBCount].measurement = measurement;
        calibB[calibBCount].position = currentB;
        calibB[calibBCount].recorded = true;
        calibBCount++;
      } else {
        Serial.println(F("Max calibration points reached for B"));
      }
      break;

    case 'C':
      currentC = readPosition(ACTUATOR_C);
      Serial.print(F("Recording C at "));
      Serial.print(measurement);
      Serial.print(F(" degrees, position: "));
      Serial.println(currentC);

      if (calibCCount < 20) {
        calibC[calibCCount].measurement = measurement;
        calibC[calibCCount].position = currentC;
        calibC[calibCCount].recorded = true;
        calibCCount++;
      } else {
        Serial.println(F("Max calibration points reached for C"));
      }
      break;

    default:
      Serial.println(F("Invalid actuator. Use A, B, or C"));
  }
}

void setZeroPosition(char actuator) {
  switch (actuator) {
    case 'A':
      zeroA = readPosition(ACTUATOR_A);
      Serial.print(F("A zero position set to: "));
      Serial.println(zeroA);
      break;

    case 'B':
      zeroB = readPosition(ACTUATOR_B);
      Serial.print(F("B zero position set to: "));
      Serial.println(zeroB);
      break;

    case 'C':
      zeroC = readPosition(ACTUATOR_C);
      Serial.print(F("C zero position set to: "));
      Serial.println(zeroC);
      break;

    default:
      Serial.println(F("Invalid actuator. Use A, B, or C"));
  }
}

void exportCalibration() {
  Serial.println(F("\n====================================="));
  Serial.println(F("CALIBRATION DATA FOR kneespa.cfg"));
  Serial.println(F("=====================================\n"));

  // Calculate factors based on recorded positions
  float aFactor = 0, bFactor = 0, cFactor = 0;

  // Calculate A factor (inches to position)
  if (calibACount >= 2) {
    float totalFactor = 0;
    int count = 0;
    for (int i = 1; i < calibACount; i++) {
      float inchDiff = calibA[i].measurement - calibA[i-1].measurement;
      float posDiff = calibA[i].position - calibA[i-1].position;
      if (inchDiff != 0) {
        totalFactor += posDiff / inchDiff;
        count++;
      }
    }
    if (count > 0) {
      aFactor = totalFactor / count;
    }
  }

  // Calculate B factor (degrees to position)
  if (calibBCount >= 2) {
    float totalFactor = 0;
    int count = 0;
    for (int i = 1; i < calibBCount; i++) {
      float degDiff = calibB[i].measurement - calibB[i-1].measurement;
      float posDiff = calibB[i].position - calibB[i-1].position;
      if (degDiff != 0) {
        totalFactor += posDiff / degDiff;
        count++;
      }
    }
    if (count > 0) {
      bFactor = totalFactor / count;
    }
  }

  // Calculate C factor (degrees to position)
  if (calibCCount >= 2) {
    float totalFactor = 0;
    int count = 0;
    for (int i = 1; i < calibCCount; i++) {
      float degDiff = calibC[i].measurement - calibC[i-1].measurement;
      float posDiff = calibC[i].position - calibC[i-1].position;
      if (degDiff != 0) {
        totalFactor += posDiff / degDiff;
        count++;
      }
    }
    if (count > 0) {
      cFactor = totalFactor / count;
    }
  }

  // Print calculated factors
  Serial.println(F("[Options]"));
  Serial.print(F("a_factor = "));
  Serial.println(aFactor > 0 ? (int)aFactor : 3640);
  Serial.print(F("b_factor = "));
  Serial.println(bFactor > 0 ? (int)bFactor : 3640);
  Serial.print(F("c_factor = "));
  Serial.println(cFactor > 0 ? (int)cFactor : 3640);
  Serial.println();

  // Print A marks
  Serial.println(F("[AMarks]"));
  Serial.print(F("0.0 = "));
  Serial.println(zeroA);
  for (int i = 0; i < calibACount; i++) {
    Serial.print(calibA[i].measurement);
    Serial.print(F(" = "));
    Serial.println(calibA[i].position);
  }
  Serial.println();

  // Print B marks
  Serial.println(F("[BMarks]"));
  Serial.print(F("0.0 = "));
  Serial.println(zeroB);
  for (int i = 0; i < calibBCount; i++) {
    Serial.print(calibB[i].measurement);
    Serial.print(F(" = "));
    Serial.println(calibB[i].position);
  }
  Serial.println();

  // Print C marks
  Serial.println(F("[CMarks]"));
  // Sort C marks by measurement value
  for (int i = 0; i < calibCCount - 1; i++) {
    for (int j = i + 1; j < calibCCount; j++) {
      if (calibC[i].measurement > calibC[j].measurement) {
        CalibrationPoint temp = calibC[i];
        calibC[i] = calibC[j];
        calibC[j] = temp;
      }
    }
  }

  for (int i = 0; i < calibCCount; i++) {
    Serial.print(calibC[i].measurement);
    Serial.print(F(" = "));
    Serial.println(calibC[i].position);
  }

  Serial.println(F("\n====================================="));
  Serial.println(F("Copy the above sections to kneespa.cfg"));
  Serial.println(F("=====================================\n"));
}

void goToPosition(char actuator, uint16_t targetPos) {
  uint16_t currentPos = 0;
  uint8_t device = 0;
  int speed = 0;

  switch (actuator) {
    case 'A':
      device = ACTUATOR_A;
      currentPos = readPosition(device);
      speed = speedA;
      break;
    case 'B':
      device = ACTUATOR_B;
      currentPos = readPosition(device);
      speed = speedB;
      break;
    case 'C':
      device = ACTUATOR_C;
      currentPos = readPosition(device);
      speed = speedC;
      break;
    default:
      Serial.println(F("Invalid actuator"));
      return;
  }

  Serial.print(F("Moving "));
  Serial.print(actuator);
  Serial.print(F(" from "));
  Serial.print(currentPos);
  Serial.print(F(" to "));
  Serial.println(targetPos);

  int direction = (targetPos > currentPos) ? 1 : -1;
  setMotorSpeed(device, speed * direction);

  // Monitor movement
  while (true) {
    delay(100);
    currentPos = readPosition(device);

    // Check if reached target (with tolerance)
    if ((direction > 0 && currentPos >= targetPos - 10) ||
        (direction < 0 && currentPos <= targetPos + 10)) {
      setMotorSpeed(device, 0);
      Serial.print(F("Reached position: "));
      Serial.println(currentPos);
      break;
    }

    // Check for emergency stop
    if (digitalRead(STOP_PIN) == HIGH) {
      stopAll();
      Serial.println(F("Movement aborted - emergency stop"));
      break;
    }

    // Check for serial interrupt
    if (Serial.available() > 0) {
      char c = Serial.read();
      if (c == 'S' || c == 's') {
        setMotorSpeed(device, 0);
        Serial.println(F("Movement stopped by user"));
        break;
      }
    }
  }
}

void showHelp() {
  Serial.println(F("\n====================================="));
  Serial.println(F("CALIBRATION COMMANDS"));
  Serial.println(F("====================================="));
  Serial.println(F("Movement:"));
  Serial.println(F("  A+/A-  : Move axial actuator forward/backward"));
  Serial.println(F("  B+/B-  : Move horizontal actuator forward/backward"));
  Serial.println(F("  C+/C-  : Move lateral actuator forward/backward"));
  Serial.println(F("  S      : Stop all movement"));
  Serial.println();
  Serial.println(F("Position:"));
  Serial.println(F("  P      : Print current positions"));
  Serial.println(F("  G A/B/C <pos> : Go to specific position"));
  Serial.println(F("    Example: G A 500"));
  Serial.println();
  Serial.println(F("Calibration:"));
  Serial.println(F("  R A/B/C : Record position after typing measurement"));
  Serial.println(F("    Example for A at 2.5 inches:"));
  Serial.println(F("      1. Move A to 2.5 inches"));
  Serial.println(F("      2. Type: R A"));
  Serial.println(F("      3. Type: 2.5"));
  Serial.println(F("  Z A/B/C : Set current position as zero"));
  Serial.println();
  Serial.println(F("Settings:"));
  Serial.println(F("  M A/B/C <speed> : Set movement speed (100-3200)"));
  Serial.println(F("    Example: M A 1000"));
  Serial.println();
  Serial.println(F("Export:"));
  Serial.println(F("  E      : Export calibration data for kneespa.cfg"));
  Serial.println(F("  H      : Show this help"));
  Serial.println(F("=====================================\n"));

  Serial.println(F("CALIBRATION PROCEDURE:"));
  Serial.println(F("1. Set zero positions for each actuator (Z command)"));
  Serial.println(F("2. Move actuator to measured positions"));
  Serial.println(F("3. Record each position (R command)"));
  Serial.println(F("4. Export data (E command)"));
  Serial.println(F("5. Copy output to kneespa.cfg"));
  Serial.println(F("=====================================\n"));
}