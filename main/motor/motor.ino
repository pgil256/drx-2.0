/*
  Arduino Motor Controller for KneeSpa
  Controls axial, horizontal, and lateral actuators
  Based on DroneBot Workshop 2019 i2c_slave_ard.ino
*/

#define VERSION "2025-03-20"
#define DEBUG_MODE true  // Set to true to enable debug printing

// Debug print macro - only prints when DEBUG_MODE is true
#define DEBUG_PRINT(msg) if(DEBUG_MODE) { Serial.print("[DEBUG] "); Serial.println(msg); }
#define DEBUG_PRINTF(fmt, ...) if(DEBUG_MODE) { Serial.print("[DEBUG] "); char buf[128]; snprintf(buf, sizeof(buf), fmt, __VA_ARGS__); Serial.println(buf); }

#include "HX711.h"
#include <elapsedMillis.h>
#include <Wire.h>
#include <avr/wdt.h>

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

// Status protection
volatile bool isProcessingStatus = false;
unsigned long lastCommandTime = 0;
const unsigned long MIN_COMMAND_INTERVAL = 200; // ms
unsigned long statusStartTime = 0;
bool statusAcknowledged = true; // Start with true so first status is sent


// Load cell setup
HX711 scale;
float calibration_factor = -4360.14;
float pressure = 0;

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
bool noStatus = false;
int forward = 1;
float desiredPressure = 0;
int pressureDirection = 0;
uint16_t position = 0;
uint16_t desiredPosition = 3;

// Command handling
String commandBuffer = "";
bool isCommandComplete = false;

// Timer tracking
unsigned long loopPosition = 0;

// Protocol variables
elapsedMillis timeInFIT = 0;
int FITDelay = 0;
bool moveFITForward = false;

// Jerking variables
bool jerking = false;
int jerkDirection = 1;
int jerksCompleted = 0;

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
  // Skip if actuator is disabled
  if ((smcDeviceNumber == 12 && false) || 
      (smcDeviceNumber == 13 && false) || 
      (smcDeviceNumber == 14 && false))
    return;

  // Normalize speed to max/min values
  if (speed > 0) speed = 3200;
  if (speed < 0) speed = -3200;
  
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

// Read actuator position
uint16_t readPosition() {
  uint16_t position = 0;

  // Skip if actuator is disabled
  if ((smcDeviceNumber == 12 && false) || 
      (smcDeviceNumber == 13 && false) || 
      (smcDeviceNumber == 14 && false))
    return position;

  // Request position from controller
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0xA1);  // Command: Get variable
  Wire.write(12);    // Variable ID: position signed
  Wire.endTransmission();

  // Read response
  delay(100);
  int returned = Wire.requestFrom(smcDeviceNumber, (uint8_t)2);
  if (returned != 2) {
    Serial.print(" Ret ");
    Serial.println(smcDeviceNumber);
    Serial.println(returned);
  }

  // Process position data
  position = Wire.read();
  position = (position + Wire.read() * 256);
  
  // Sanity check on position value
  if (position <= 0 || position > 65000)
    position = 0;

  return position;
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
  if (noStatus || isProcessingStatus || !statusAcknowledged)
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

  // Read pressure
  pressure = abs(scale.get_units(5));

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
}

// Process a fully received command
void processCommand(String cmd) {
  if (cmd.length() == 0) return;
  
  char commandType = cmd[0];
  String parameter = "";
  
  DEBUG_PRINTF("Received command: %s", cmd.c_str());
  
  // Wait if we're sending status
  unsigned long waitStart = millis();
  if (isProcessingStatus) {
    DEBUG_PRINT("Status in progress, waiting...");
    while (isProcessingStatus && millis() - waitStart < 500) {
      delay(10);
    }
    DEBUG_PRINT("Done waiting for status");
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
        DEBUG_PRINT("Sent test command acknowledgment");
        break;
        
    // Status acknowledgment
    case 'Q': 
        statusAcknowledged = true;
        DEBUG_PRINT("Status acknowledged");
        break;
      
    // Status request
    case 'S':
      DEBUG_PRINT("Status request received");
      sendStatus();
      Serial1.println("DONE");
      DEBUG_PRINT("Status sent");
      break;

    // Pressure control
    case 'P':
      if (bRunning) {
        DEBUG_PRINT("Ignoring pressure command - system already running");
        return;
      }
      
      parameter = cmd.substring(1);
      desiredPressure = parameter.toInt();
      Serial.print("desiredPressure ");
      Serial.println(desiredPressure);
      DEBUG_PRINTF("Setting pressure to %d lbs", desiredPressure);
      
      sendStatus();
      noStatus = true;
      smcDeviceNumber = 12;
      
      Serial.print("pressure desired: ");
      Serial.print(desiredPressure);
      
      pressure = abs(scale.get_units(5));
      Serial.print(" pressure now: ");
      Serial.println(pressure);
      DEBUG_PRINTF("Current pressure: %.2f lbs", pressure);
      
      pressureDirection = 1;
      if (pressure >= desiredPressure)
        pressureDirection = -1;  // move back
        
      Serial.print(" pressureDirection: ");
      Serial.println(pressureDirection);
      DEBUG_PRINTF("Setting pressure direction: %d", pressureDirection);
      
      setMotorSpeed(PRESSURE_SPEED * pressureDirection);
      DEBUG_PRINTF("Motor speed set to %d", PRESSURE_SPEED * pressureDirection);
      measurePressure = true;
      break;

    // Reset/restart
    case 'Y':
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      Serial1.println("Reset|");
      resetFunc();
      Serial1.println("DONE");
      break;

    // Emergency stop
    case 'X':
      emergencyStop();
      Serial.print(F("Stopped at Position: "));
      Serial.println(readPosition());
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
      if (bRunning) return;
      
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);
      
      parameter = cmd.substring(3);
      localDesiredPosition = parameter.toInt();
      localPosition = readPosition();
      
      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);
      
      if (localDesiredPosition >= (localPosition + 25)) {
        forward = 1;
      } else {
        forward = -1;
      }
      
      if (smcDeviceNumber == 12)
        if (localDesiredPosition <= AZERO)
          localDesiredPosition = AZERO;
      
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
      if (bRunning) {
        DEBUG_PRINT("Ignoring position command - system already running");
        return;
      }
      
      smcDeviceNumber = 14;
      Serial.println(cmd);
      parameter = cmd.substring(1);
      Serial.println(parameter);
      
      localDesiredPosition = parameter.toInt();
      Serial.println(localDesiredPosition);
      DEBUG_PRINTF("Setting angle position to %d", localDesiredPosition);
      
      localPosition = readPosition();
      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);
      DEBUG_PRINTF("Current position: %d, Target position: %d", localPosition, localDesiredPosition);
      
      if (localDesiredPosition >= (localPosition + 25)) {
        forward = 1;
        DEBUG_PRINT("Moving forward");
      } else {
        forward = -1;
        DEBUG_PRINT("Moving backward");
      }
      
      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;
      
      setMotorSpeed(forward * C_SPEED);
      DEBUG_PRINTF("Motor speed set to %d", forward * C_SPEED);
      
      Serial.print(forward);
      Serial.print(" ");
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);
      
      bRunning = true;
      break;

    // Position in inches
    case 'A':
      if (bRunning) return;
      
      parameter = cmd.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);
      
      parameter = cmd.substring(3);
      inches = parameter.toFloat();
      
      if (smcDeviceNumber == 12) {
        localDesiredPosition = AFULLINCH * inches;
        AInches = inches;
        if (inches == 0)
          localDesiredPosition = AZERO;
      } else if (smcDeviceNumber == 13) {
        localDesiredPosition = BFULLINCH * inches;
        BInches = inches;
        if (inches == 0)
          localDesiredPosition = BZERO;
      } else if (smcDeviceNumber == 14) {
        localDesiredPosition = CFULLINCH * inches;
        CInches = inches;
        if (inches == 0)
          localDesiredPosition = CZERO;
      }
      
      localPosition = readPosition();
      Serial.print(inches);
      Serial.print(" ");
      Serial.print(localDesiredPosition);
      Serial.print(" ");
      Serial.println(localPosition);
      
      // Copy to globals
      desiredPosition = localDesiredPosition;
      position = localPosition;
      
      if (desiredPosition >= (position + 25)) {
        forward = 1;
      } else {
        forward = -1;
      }
      
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
          Serial1.println("step 0");
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
          AZERO = cmd.substring(2, 5).toInt();
          BZERO = cmd.substring(5, 9).toInt();
          Serial.print("AZERO: ");
          Serial.print(AZERO);
          Serial.print("BZERO: ");
          Serial.println(BZERO);
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

    // Jerking motion control
    case 'J':
      parameter = "";
      if (cmd.length() > 1)
          parameter = cmd.substring(1);
      
      if (parameter == "") {
          Serial.println("jerking");
          jerking = true;
          sendStatus();
          noStatus = true;
          jerksCompleted = 0;
          jerkDirection = 1;  // Start with a consistent direction
          smcDeviceNumber = 12;
          Serial1.println("DONE");  // Acknowledge command receipt but don't stop
      }

      if (parameter == "S") {
          Serial.println("stop jerking");
          jerkDirection = 0;
          jerking = false;
          noStatus = false;
          setMotorSpeed(0);
          Serial1.println("DONE");
      }
      break;

    // External actuator control
    case 'F':
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
      break;
  }
}

// Setup function
void setup() {
  // Join I2C bus as slave
  Wire.begin(0x8);

  // Initialize serial communication
  Serial.begin(9600);
  Serial.setTimeout(5000);
  Serial1.begin(115200);

  // Wait for serial to initialize - helpful for debugging
  delay(3000);

  exitSafeStart();

  Serial.println("\n\n\nStarting");
  Serial.print("VERSION: "); 
  Serial.println(VERSION);
  
  DEBUG_PRINT("Debug mode is enabled");
  DEBUG_PRINT("Initialization sequence started");

  // Initialize load cell
  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  scale.set_scale(calibration_factor);
  delay(1000);

  // Configure pins
  pinMode(STOP_PIN, INPUT);
  pinMode(DIR_FIT_FORWARD, OUTPUT);
  pinMode(DIR_FIT_REVERSE, OUTPUT);
  pinMode(SPEED_PIN_A, OUTPUT);
  pinMode(DIR_A_FORWARD, OUTPUT);
  pinMode(DIR_A_REVERSE, OUTPUT);

  // Initialize actuators
  DEBUG_PRINT("Starting actuator initialization");
  int movement = -3000;
  AInches = 0;
  smcDeviceNumber = 12; // position actuator
  setMotorSpeed(0);  // stop
  Serial.println("A actuator positioned");
  DEBUG_PRINTF("Actuator A initialized at position %d", readPosition());

  BInches = 2;
  smcDeviceNumber = 13; // position actuator
  setMotorSpeed(0);  // stop
  Serial.println("B actuator positioned");
  DEBUG_PRINTF("Actuator B initialized at position %d", readPosition());

  smcDeviceNumber = 14; // position actuator
  setMotorSpeed(0);  // stop
  Serial.println("C actuator ready");
  uint16_t pos = readPosition();
  Serial.print("readPosition ");
  Serial.println(pos);
  DEBUG_PRINTF("Actuator C initialized at position %d", pos);

  // Startup complete
  Serial.println("Ready to Go");
  Serial1.println("");
  Serial1.println("Ready to Go");
  
  loopPosition = millis() - LOOP_STATUS_DELAY;
}

// Main loop function
void loop() {
  static int lastPosition = -1;
  static unsigned long lastDebugTime = 0;
  
  // Simple heartbeat debug - log every 15 seconds
  if (DEBUG_MODE && (millis() - lastDebugTime > 15000)) {
    lastDebugTime = millis();
    DEBUG_PRINT("Arduino heartbeat");
    DEBUG_PRINTF("System state: bRunning=%d, jerking=%d, measurePressure=%d", 
                bRunning, jerking, measurePressure);
  }

  // Read stop pin
  STOP = digitalRead(STOP_PIN);
  if (STOP) {
    DEBUG_PRINT("STOP pin activated!");
  }

  // Reset if processing status took too long
  if (isProcessingStatus && (millis() - statusStartTime > 500)) {
    isProcessingStatus = false;
    Serial.println("Status processing timeout");
    DEBUG_PRINT("Status processing timeout - reset isProcessingStatus flag");
  }
  
  // Periodic status update
  if ((millis() - loopPosition) > LOOP_STATUS_DELAY) {
    loopPosition = millis();
    if (!bRunning) {
      DEBUG_PRINT("Sending periodic status update");
      sendStatus();
    }
  }

  if (jerking) {
    // Jerking motion handler
    DEBUG_PRINTF("Jerking: count=%d, direction=%d", jerksCompleted, jerkDirection);
    
    if (jerksCompleted >= MAX_JERKS) {
      // Reset counter but continue jerking
      jerksCompleted = 0;
      DEBUG_PRINT("Jerking counter reset");
      
      // Send a status update periodically
      if (jerksCompleted % 2 == 0) {
        DEBUG_PRINT("Sending status during jerking");
        sendStatus();
      }
    } else {
      smcDeviceNumber = 12;
      int speed = 3200 * jerkDirection;
      setMotorSpeed(speed);
      DEBUG_PRINTF("Jerk pulse: direction=%d, speed=%d", jerkDirection, speed);
      
      jerkDirection = -jerkDirection;
      jerksCompleted++;
      delay(200);
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
  if (bRunning) {
    DEBUG_PRINT("Position control active");
    
    if (STOP) {
      DEBUG_PRINT("STOP pin triggered during position control");
      emergencyStop();
    } else {
      int motorSpeed = forward * BC_SPEED;
      setMotorSpeed(motorSpeed);
      DEBUG_PRINTF("Running motor at speed %d", motorSpeed);
      
      uint16_t position = readPosition();
      
      // Debug output
      Serial.print(forward); Serial.print(" ");
      Serial.print(CInches); Serial.print(" ");
      Serial.print(position); Serial.print(" ");
      Serial.print(lastPosition); Serial.print(" ");
      Serial.println(desiredPosition);
      
      DEBUG_PRINTF("Position control: current=%d, target=%d, direction=%d", 
                  position, desiredPosition, forward);
      
      // Check if position reached
      if (forward > 0) {
        if (position >= desiredPosition) {
          Serial.println("Stopped Moving");
          DEBUG_PRINTF("Position reached (forward): %d >= %d", position, desiredPosition);
          setMotorSpeed(0);
          bRunning = false;
          forward = 0;
        }
      } else if (position <= desiredPosition) {
        Serial.println("Stopped Moving");
        DEBUG_PRINTF("Position reached (reverse): %d <= %d", position, desiredPosition);
        setMotorSpeed(0);
        bRunning = false;
        forward = 0;
      }
      
      // Handle stalling
      if (lastPosition == position) {
        DEBUG_PRINTF("Possible stall detected: position stuck at %d", position);
        delay(500);
      }
      else
        lastPosition = position;
    }

    // Cleanup after run complete
    if (!bRunning) {
      position = readPosition();
      DEBUG_PRINT("Position control complete, sending final status");
      sendStatus();
      Serial.println(position);
      Serial1.println("DONE");
    }
  }

  // Pressure monitoring and control
  if (measurePressure) {
    DEBUG_PRINT("Pressure control active");
    
    smcDeviceNumber = 12;
    uint16_t position = readPosition();
    pressure = abs(scale.get_units(5));
    
    Serial.print("desiredPressure: ");
    Serial.print(desiredPressure);
    Serial.print(" pressureDirection: ");
    Serial.print(pressureDirection);
    Serial.print(" pressure: ");
    Serial.println(pressure);
    
    DEBUG_PRINTF("Pressure control: current=%.2f, target=%.2f, direction=%d", 
                pressure, desiredPressure, pressureDirection);

    if (pressure < 0.5) {
      pressure = 0;
      DEBUG_PRINT("Low pressure reading adjusted to 0");
    }

    // Check if target pressure reached
    if (pressureDirection > 0) {
      if (pressure >= desiredPressure) {
        DEBUG_PRINTF("Target pressure reached (increasing): %.2f >= %.2f", 
                    pressure, desiredPressure);
        setMotorSpeed(0);
        measurePressure = false;
        pressureDirection = 0;
      }
    } else if (pressure <= desiredPressure) {
      DEBUG_PRINTF("Target pressure reached (decreasing): %.2f <= %.2f", 
                  pressure, desiredPressure);
      setMotorSpeed(0);
      measurePressure = false;
      pressureDirection = 0;
    }

    // Cleanup after pressure adjustment complete
    if (!measurePressure) {
      pressure = abs(scale.get_units(5));
      DEBUG_PRINT("Pressure control complete, sending final status");
      sendStatus();
      Serial1.println("DONE");
      noStatus = false;
    }
  }

  // Command reading and processing
  while (Serial1.available() > 0) {
    char incomingByte = Serial1.read();

    if (incomingByte == '\n') {  // Command complete
      isCommandComplete = true;
      DEBUG_PRINTF("Command received: %s", commandBuffer.c_str());
      break;
    } else {
      // Limit buffer size to prevent overflows
      if (commandBuffer.length() < 50) {
        commandBuffer += incomingByte;  // Append character to buffer
      } else {
        DEBUG_PRINT("Command buffer overflow - discarding data");
      }
    }
  }

  // Process complete commands with rate limiting
  if (isCommandComplete && millis() - lastCommandTime > MIN_COMMAND_INTERVAL && !isProcessingStatus) {
    lastCommandTime = millis();
    DEBUG_PRINTF("Processing command: %s", commandBuffer.c_str());
    processCommand(commandBuffer);
    commandBuffer = "";
    isCommandComplete = false;
  } else if (isCommandComplete && isProcessingStatus) {
    DEBUG_PRINT("Command waiting - status in progress");
  } else if (isCommandComplete && millis() - lastCommandTime <= MIN_COMMAND_INTERVAL) {
    DEBUG_PRINT("Command waiting - rate limiting");
  }
}