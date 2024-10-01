/*
  Arduino Slave for Raspberry Pi Master
  i2c_slave_ard.ino
  Connects to Raspberry Pi via I2C

  DroneBot Workshop 2019
  https://dronebotworkshop.com
*/

#define VERSION "4/27/2022 11:21"


#include "HX711.h"
#include <elapsedMillis.h>
elapsedMillis timeElapsed;
elapsedMillis endTimeElapsed;
int w;

#define LOADCELL_DOUT_PIN  7
#define LOADCELL_SCK_PIN  6

#define DEBUGx

#define AFULLINCH  430 //620
#define BFULLINCH  620
#define CFULLINCH  1880

int AZERO = 0;
int BZERO = 0;
int CZERO = 0;

#define noA false
#define noB false
#define noC false

# define LOOPPOSITION_DELAY 5000

HX711 scale;

float calibration_factor = -4360.14; //-26594.13; // worked for test weight 3lbs
float basePressure = 0.0;
float pressure = 0;
bool measurePressure = false;
bool bRunning = false;
int forward = 1;
bool aRunning = false;
bool noStatus = false;

#define pressureSpeed 500
#define BCSpeed 1600/2
#define CSpeed 800

int AInches = 0;
int BInches = 0;
float CInches = 0;

// Include the Wire library for I2C
#include <Wire.h>

uint8_t smcDeviceNumber = 13;


int dir = 1;

int Speed;

int stopPin = 3;
volatile bool STOP = false;

#define MAXJERK 10

// https://s3.amazonaws.com/actuonix/Actuonix+LAC+Datasheet.pdf
// C actuator relay
#define FITSLOWDELAY (0.5 * 1000)
#define FITFASTDELAY (6 * 1000)

int speedPinA = 9; // Needs to be a PWM pin to be able to control motor speed
int dirFitFoward = 4;
int dirFitReverse = 5;

int dirAFoward = 30;
int dirAReverse = 31;
#define AAnalog A0

// global volatile variables are needed to pass data between the

// main program and the ISR's

volatile byte signalA;
volatile byte signalB;
volatile byte signalPi;

volatile bool limitHit = false;


// are using
const int CLimit = 1822;

// Makes Arduino restart
void(* resetFunc) (void) = 0;//declare reset function at address 0

void setup() {
  // Join I2C bus as slave with address 8
  Wire.begin(0x8);

  // initialize serial communication:
  Serial.begin(9600);
  Serial.setTimeout(5000);

  exitSafeStart();

  Serial.println("\n\n\n\n\n\n\n\n\n\n\n\nStarting");

  Serial.print("VERSION: "); Serial.println(VERSION);

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  // scale.set_scale();
  // scale.tare(); //Reset the scale to 0

  //  long zero_factor = scale.read_average(); //Get a baseline reading
  scale.set_scale(calibration_factor); //Adjust to this calibration factor


  delay(1000);

  Serial1.begin(115200);


  // stop limit switch
  pinMode(stopPin, INPUT);

  // declare Relay as output
  pinMode(dirFitFoward, OUTPUT);
  pinMode(dirFitReverse, OUTPUT);
  pinMode(speedPinA, OUTPUT);

  // declare Relay as output
  pinMode(dirAFoward, OUTPUT);
  pinMode(dirAReverse, OUTPUT);

  int movement = -3000;
  AInches = 0;
  if (noA)
    Serial.println("A actuator skipped");
  else
  {
    smcDeviceNumber = 12; // position actuator
    /*
       setMotorSpeed(movement);  // full-speed reverse

       AZERO = moveToLimit(-1);

       int lastPosition = -1;
       int  position = readPosition();

       delay(1000);

       Serial.print("A Zero ");
       Serial.println(AZERO);
    */
    setMotorSpeed(0);  // stop
    Serial.println("A actuator positioned");
  }

  BInches = 2;
  if (noB)
    Serial.println("B actuator skipped");
  else
  {
    smcDeviceNumber = 13; // position actuator
    /*
      setMotorSpeed(movement);  // full-speed reverse

      BZERO = moveToLimit(-1);

      int lastPosition = -1;
      int  position = readPosition();
      delay(1000);

      setMotorSpeed(-movement / 2); // move out

      position = readPosition();
      while (position < BFULLINCH * 2) // 2 inch 3460/6
      {
      position = readPosition();
      }
      Serial.print("B Zero ");
      Serial.println(BZERO);
    */
    setMotorSpeed(0);  // stop
    Serial.println("B actuator positioned");
  }

  if (noC)
    Serial.println("C actuator skipped");
  else
  {
    smcDeviceNumber = 14; // position actuator

    setMotorSpeed(0);  // stop
    Serial.println("C actuator ready");

    Serial.print("readPosition ");
    Serial.println(readPosition());
  }

  Serial.println("Ready to Go");

  Serial1.println("");
  Serial1.println("step 1");
  Serial1.println("Ready to Go");
  Serial1.println("step 1");

}

unsigned long lastStepTime = 0; // Time stamp of last pulse
unsigned long lastStepBTime = 0; // Time stamp of last pulse
int trigDelay = 300;            // Delay bewteen pulse in microseconds



void limit_ISR() {
  if (micros() - lastStepTime > trigDelay) {
    limitHit = true;
    Serial.println("limit hit");

    lastStepTime = micros();
  }

}


// Required to allow motors to move.
// Must be called when controller restarts and after any error.
void exitSafeStart()
{
  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0x83);  // Exit safe start
  Wire.endTransmission();
}

/***************** setMotorSpeed ***************/

void setMotorSpeed(int16_t speed)
{

  if (noA && smcDeviceNumber == 12)
    return;
  if (noB && smcDeviceNumber == 13)
    return;
  if (noC && smcDeviceNumber == 14)
    return;

  if (speed > 0)
    speed = 3200;
  if (speed < 0)
    speed = -3200;
  /*
    Serial.print("set motor speed on ");
    Serial.print(smcDeviceNumber);
    Serial.print(" at ");
    Serial.println(speed);
  */
  uint8_t cmd = 0x85;  // Motor forward
  if (speed < 0)
  {
    cmd = 0x86;  // Motor reverse
    speed = -speed;
  }

  exitSafeStart();


  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(cmd);
  Wire.write(speed & 0x1F);
  Wire.write(speed >> 5 & 0x7F);
  Wire.endTransmission();
}

/* **************** readPosition() ***********/

uint16_t readPosition()
{
  uint16_t position = 0;

  if (noA && smcDeviceNumber == 12)
    return position;
  if (noB && smcDeviceNumber == 13)
    return position;
  if (noC && smcDeviceNumber == 14)
    return position;

  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0xA1);  // Command: Get variable
  Wire.write(12);    // Variable ID: position signed
  Wire.endTransmission();

  delay(100);
  int returned = Wire.requestFrom(smcDeviceNumber, (uint8_t)2);
  if (returned != 2)
  {
    Serial.print(" ret ");
    Serial.println(smcDeviceNumber);
    Serial.println(returned);

  }

  position = Wire.read();

  //  position |= Wire.read() << 8;
  position = (position + Wire.read() * 256);
  /*
    Serial.print(" smc ");
    Serial.print(smcDeviceNumber);
    Serial.print(" pos ");
    Serial.println(position);
  */
  if (position <= 0 || position > 65000)
    position = 0;

  return position;
}

/************************ NOT USED ************/
uint16_t readSpeed()
{

  Wire.beginTransmission(smcDeviceNumber);
  Wire.write(0xA1);  // Command: Get variable
  Wire.write(43);    // Variable ID: Current Limit
  Wire.endTransmission();

  Wire.requestFrom(smcDeviceNumber, (uint8_t)2);
  int16_t speed = Wire.read();
  speed |= Wire.read() << 8;
  Serial.println(speed);

  return speed;
}

/**************** find limits ****************/

int moveToLimit(int Direction) {
  int prevReading = 0;
  int currReading = 0;
  if (smcDeviceNumber == 14)
    setMotorSpeed(Direction * CSpeed);   // slow-speed backward
  else
    setMotorSpeed(Direction * BCSpeed);   // slow-speed backward

  do {
    prevReading = currReading;
    timeElapsed = 0;
    while (timeElapsed < 200 * 5) {
      delay(1); //keep moving until analog reading remains the same for 200ms
    }
    currReading = readPosition();
    //  Serial.println(currReading);
  } while (prevReading != currReading);
  setMotorSpeed(0);   // stop motor

  return currReading + 10;
}

/****************** getValue ***********************/
// https://stackoverflow.com/questions/9072320/split-string-into-string-array
String getValue(String data, char separator, int index)
{
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



/************************* sendStatus() ************/
void sendStatus()
{
  if (noStatus)
    return;
  uint8_t lastSmcDeviceNumber = 0;
  uint16_t positionA = 0;
  uint16_t positionB = 0;
  uint16_t positionC = 0;
  //  float pressure = 0;

  lastSmcDeviceNumber = smcDeviceNumber;

  // read the analog in value:
  //  positionA = analogRead(AAnalog);

  smcDeviceNumber = 12;
  positionA = readPosition();
  smcDeviceNumber = 13;
  positionB = readPosition();
  smcDeviceNumber = 14;
  positionC = readPosition();

  pressure = abs(scale.get_units(5));


  Serial.print(F("status: "));
  Serial.print(F(" 12: "));
  Serial.print(positionA);
  Serial.print(F(" 13: "));
  Serial.print(positionB);
  Serial.print(F(" 14: "));
  Serial.print(positionC);
  Serial.print(F(" pressure: "));
  Serial.println(pressure);

  Serial1.print("S|");
  Serial1.print(positionA);

  Serial1.print("|");
  Serial1.print(positionB);

  Serial1.print("|");
  Serial1.print(positionC);

  Serial1.print("|");
  Serial1.println(pressure);

  smcDeviceNumber = lastSmcDeviceNumber;

}

/* ******************************* MAIN LOOP *****************************************/
void loop() {

  static int status = 0;
  static String command = "n";
  static int index = 0; //ascii value of command

  static uint16_t position = 0;
  static int lastPosition = -1;
  static uint16_t desiredPosition = 3;

  static float desiredPressure = 0;
  static int pressureDirection = 0;

  static float lastStep = -1;
  String c;
  int lastStatus = -1;
  bool ok;
  static unsigned long loopPosition = millis() - LOOPPOSITION_DELAY;  //initial start time

  static elapsedMillis timeInFIT = 0;
  static int FITDelay = 0;
  static bool moveFITForward = false;
  static bool moveFITReverse = false;

  static elapsedMillis timeInA = 0;
  static int ADelay = 0;
  static bool moveAForward = false;
  static bool moveAReverse = false;
  static int APosition = 0;

  static String protocol = "";
  static String subProtocol = "";
  static int horizontalPosition = 0;
  static int horizontalStartPosition = 0;
  static int cycles = 0;
  static int cycle = 0;
  static unsigned long protocolHold;
  static bool protocolRunning = false;

  static bool jerking  = false;
  static bool jerkingx  = false;
  static int jerkDirection = 1;
  static int jerkDuation = 0;
  static int jerkPause = 5 * 1000;  // 5 second pause between jerks
  static elapsedMillis elapsedJerk = 0;
  static int inJerk = 0;
  static int maxJerks = MAXJERK;
  static int jerksCompleted = 0;

  STOP = digitalRead(stopPin);   // read the limit pin

  if ((millis() - loopPosition) > LOOPPOSITION_DELAY)
  {
    ////    Serial.print(F("Loop Status: "));
    loopPosition = millis();

    if (bRunning)
      return;

    sendStatus();

  }

  if (jerking)
  {
    if (jerksCompleted++ > maxJerks)
    {
      jerking = false;
      jerksCompleted = 0;
      setMotorSpeed(0);  // full-speed stop
      //      Serial.println("jerking done");
      Serial1.println("DONE");
      noStatus = false;
      sendStatus();
    }
    else
    {
      smcDeviceNumber = 12;
      setMotorSpeed(3200 * jerkDirection);  // full-speed stop
      jerkDirection = -jerkDirection;
      delay(200);
      jerksCompleted += 1;
    }
  }

  if (jerkingx)
  {

    if (inJerk > maxJerks)
    {
      if (elapsedJerk > jerkPause)
      {
        smcDeviceNumber = 12;
        setMotorSpeed(0);  // full-speed stop
        elapsedJerk = 0;
        inJerk = 0;
        if (jerksCompleted++ > maxJerks)
        {
          jerking = false;
          Serial.println("jerking done");
          Serial1.println("DONE");
        }
      }
    }
    else
    {
      smcDeviceNumber = 12;
      setMotorSpeed(3200 * jerkDirection);  // full-speed stop
      jerkDirection = -jerkDirection;
      delay(200);
      elapsedJerk = 0;
      inJerk += 1;
      setMotorSpeed(0);  // full-speed stop
    }
  }

  if (moveFITForward)
  {
    if (timeInFIT > FITDelay)
    {
      digitalWrite(dirFitFoward, LOW);
      digitalWrite(dirFitReverse, LOW);
      Serial.println("Fit stopped.");

      Serial.println("fit done");
      moveFITForward = false;
    }
  }

  if (moveAForward)
  {
    // read the analog in value:
    APosition = analogRead(AAnalog);
    if (abs(APosition - 5) == desiredPosition)
      //  if (timeInA > ADelay)
    {

      digitalWrite(dirAFoward, LOW);
      digitalWrite(dirAReverse, LOW);
      Serial.println("A stopped.");

      Serial.println("A done");
      moveAForward = false;
      Serial.print(F("Status: "));
      Serial.print(F(" 12: "));
      Serial.print(APosition);
    }
  }


  if (bRunning)
  {
    if (STOP)
    {
      Serial.println("Emergency Stop");
      smcDeviceNumber = 12;
      setMotorSpeed(0);  // full-speed stop
      Serial.println("A stopped");
      smcDeviceNumber = 13;
      setMotorSpeed(0);  // full-speed stop
      Serial.println("B stopped");
      smcDeviceNumber = 14;
      setMotorSpeed(0);  // full-speed stop
      Serial.println("C stopped");

      measurePressure = false;
      bRunning = false;
    }
    else
    {
      setMotorSpeed(forward * BCSpeed);   // slow-speed backward
      position = readPosition();
      /*
            Serial.print(forward);
            Serial.print(" ");
            Serial.print(CInches);
            Serial.print(" ");
            Serial.print(position);
            Serial.print(" ");
            Serial.print(lastPosition);
            Serial.print(" ");
            Serial.println(desiredPosition);

      */

      if (position == lastPosition)
      {
        //       desiredPosition = position;
      }
      if (forward > 0)
      {
        if (position >= desiredPosition)
        {

          Serial.print(smcDeviceNumber);
          Serial.print(" ");
          Serial.print(forward);
          Serial.print(" ");
          Serial.print(ok);
          Serial.print(" ");
          Serial.print(position);
          Serial.print(" ");
          Serial.println(desiredPosition);

          Serial.println("Stopped Moving");
          setMotorSpeed(0);   // full-stop
          bRunning = false;
          forward = 0;
        }
      }
      else if (position <= desiredPosition)
      {
        Serial.println("Stopped Moving");
        setMotorSpeed(0);   // full-stop
        bRunning = false;
        forward = 0;
      }
      if (lastPosition == position)
        delay(500);
      else
        lastPosition = position;
    }

    if (!bRunning)
    {
      position = readPosition();
      sendStatus();
      Serial.println(position);
      Serial1.println("DONE");

      if (smcDeviceNumber == 12)
      {
        uint16_t positionA = 0;
        uint16_t positionB = 0;
        uint16_t positionC = 0;
        float pressure = 0;

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
    }
  }


  if (measurePressure)
  {

    smcDeviceNumber = 12;
    position = readPosition();

    //   setMotorSpeed(0);   // full-stop
    pressure = abs(scale.get_units(5));
    ////    setMotorSpeed(pressureDirection * pressureSpeed);   // slow-speed backward

    Serial.print("desiredPressure: ");
    Serial.print(desiredPressure);
    Serial.print(" pressureDirection: ");
    Serial.print(pressureDirection);
    Serial.print(" pressure: ");
    Serial.println(pressure);

    if (pressure < 0.5)
      pressure = 0;

    //////
#ifdef DEBUG
    pressure = desiredPressure;
#endif
    ///////
    if (pressureDirection > 0)
    {
      if (pressure >= desiredPressure)
      {
        setMotorSpeed(0);   // full-stop
        measurePressure = false;
        pressureDirection = 0;
      }
    }
    else if (pressure <= desiredPressure)
    {
      setMotorSpeed(0);   // full-stop
      measurePressure = false;
      pressureDirection = 0;
    }

    if (!measurePressure)
    {
      pressure = abs(scale.get_units(5));
      sendStatus();
      Serial1.println("DONE");
      noStatus = false;

      if (smcDeviceNumber == 120)
      {
        uint16_t positionA = 0;
        uint16_t positionB = 0;
        uint16_t positionC = 0;
        float pressure = 0;

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
      //      measurePressure = true;
    }
  }


  if (Serial1.available())
  {
    c = Serial1.readStringUntil('\n');
    Serial1.flush();
    Serial.print("c ");
    Serial.println(c);
  }


  if (index == (int)'S') {
    //      int16_t speed = readSpeed();
    //   if (lastStatus != status)
    {

      sendStatus();

      Serial1.println("DONE");

      lastStatus = status;
      status = 1;   // shows waiting (done)
      command = "s";
      index = 0;

    }
  }
  else
  {
    command = c;
    index = (int)c[0];
  }


  if (index == (int)'M') {

    Serial.println("M protocols");
    String protocolValue = getValue(command, '|', 1);
    protocol = protocolValue.substring(0, 1);
    subProtocol = protocolValue.substring(1);
    Serial.print("protocol ");
    Serial.print(protocol);
    Serial.println(subProtocol);


    /************* B protocol ************/
    if (protocol == "B")
    {
      smcDeviceNumber = 13;
      horizontalPosition  = getValue(command, '|', 2).toInt();
      horizontalStartPosition = getValue(command, '|', 3).toInt();
      cycles = getValue(command, '|', 4).toInt();
      desiredPosition = horizontalStartPosition;

      position = readPosition();

      Serial.print("B protocol ");
      Serial.print(subProtocol);
      Serial.print(" desiredPosition ");
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.print(position);
      Serial.print(" ");
      Serial.print(horizontalPosition);
      Serial.print(" : ");
      Serial.print(horizontalStartPosition);
      Serial.print(" cycles ");
      Serial.println(cycles);


      if (desiredPosition >= (position + 25))
      {
        forward = 1;
      }
      else
      {
        forward = -1;
      }
      bRunning = true;


    }


    command = "m";
    index = -1;
    status = 0;   // shows waiting (done)
  }


  if (protocol == "B")
  {
    smcDeviceNumber = 13;

    if (subProtocol == "1")
    {

      if (protocolRunning)
      {
        if ((millis() - protocolHold) > 5000) // 5 second hold
        {
          protocolRunning = false;
          Serial.println("stopped timer");
        }

      }
      else
      {
        if (!bRunning)
        {
          protocolRunning = true;
          cycle = 1;
          desiredPosition = horizontalPosition;
          protocolHold = millis();
        }
      }
    }
  }



  if (index == (int)'I') {
    if (bRunning)
      return;

    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    Serial.println(smcDeviceNumber);
    parameter = command.substring(3);
    desiredPosition = parameter.toInt();

    position = readPosition();
    Serial.print(desiredPosition);
    Serial.print(" ");
    Serial.println(position);


    if (desiredPosition >= (position + 25))
    {
      forward = 1;
      //    desiredPosition -= 30;
    }
    else
    {
      forward = -1;
      //     desiredPosition += 30;
    }

    if (smcDeviceNumber == 12)
      if (desiredPosition <= AZERO)
        desiredPosition = AZERO;

    setMotorSpeed(forward * CSpeed);   // All speed managed by G2

    Serial.print(AZERO);
    Serial.print(" ");
    Serial.print(forward);
    Serial.print(" ");
    Serial.print(desiredPosition);
    Serial.print(" ");
    Serial.println(position);

    bRunning = true;
    status = 1;   // shows moving
    command = "i";
    index = 0;

  }



  if (index == (int)'P') {
    if (bRunning)
      return;

    String parameter = command.substring(1);
    desiredPressure = parameter.toInt();
    Serial.print("desiredPressure ");
    Serial.println(desiredPressure);
    command = "p";
    index = -1;
    status = 0;   // shows waiting (done)

    sendStatus();
    noStatus = true;

    smcDeviceNumber = 12;
    Serial.print("pressure desired: ");
    Serial.print(desiredPressure);

    pressure = abs(scale.get_units(5));
    //   Serial.print(" pressure now: ");
    //   Serial.println(pressure);

    pressureDirection = 1;
    if (pressure >= desiredPressure)
      pressureDirection = -1;	// means move back
    // Serial.print(" pressureDirection: ");
    //   Serial.println(pressureDirection);

    setMotorSpeed(pressureSpeed * pressureDirection);  // start moving
    //    delay(500);

    measurePressure = true;
  }

  if (index == (int)'Y') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();

    command = "x";
    index = 0;
    status = 0;

    Serial1.println("Reset|");

    resetFunc();
    Serial1.println("DONE");

  }

  if (index == (int)'X') {

    command = "x";
    index = 0;
    status = 0;

    smcDeviceNumber = 12;
    setMotorSpeed(0);  // full-speed stop
    Serial.println("A stopped");
    smcDeviceNumber = 13;
    setMotorSpeed(0);  // full-speed stop
    Serial.println("B stopped");
    smcDeviceNumber = 14;
    setMotorSpeed(0);  // full-speed stop
    Serial.println("C stopped");

    uint16_t position = readPosition();

    measurePressure = false;
    bRunning = false;
    jerking = false;

    //    STOP = true;

    Serial.print(F("Stopped at Position: "));
    Serial.println(position);

  }

  if (index == (int)'G') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();

    command = "g";
    index = 0;
    status = 0;

    uint16_t position = readPosition();


    Serial.print(F("Get Position: "));
    Serial.print(position);
    Serial1.print("P|");
    Serial1.println(position);
    Serial1.println("DONE");

  }


  if (command.startsWith("B")) {
    command = "b";

    String parameter = "-";
    if (command.length() > 1)
      parameter = command.substring(1);
    if (parameter == "+")
      setMotorSpeed(3200);  // full-speed reverse
    else
      setMotorSpeed(-3200);  // full-speed reverse

    desiredPosition = 21;

    while (true)
    {
      uint16_t position = readPosition();

      Serial.print(desiredPosition);
      Serial.print (" ");
      Serial.println(position);

      if (desiredPosition >= position)
      {
        setMotorSpeed(0);   // stop
        status = 0;
        Serial.println("B done");

        break;
      }
    }
  }


  if (index == (int)'R') {
    if (bRunning)
      return;

    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    Serial.println(smcDeviceNumber);
    command = "r";
    index = 0;
    status = 0;   // shows waiting (done)

    int movement = 3200 / 1;
    {
      if (smcDeviceNumber == 13)
      {
        BInches = 2;
        position = readPosition();
        if (position > BFULLINCH * 2)
        {
          setMotorSpeed(-movement); // move in
          while (position >= BFULLINCH * 2) // 2 inch 3460/6
          {
            position = readPosition();
          }
        }
        else
        {
          setMotorSpeed(movement); // move out
          while (position <= BFULLINCH * 2) // 2 inch 3460/6
          {
            position = readPosition();
          }
        }
        Serial.print("out ");
        Serial.println(position);
        bRunning = false;

        setMotorSpeed(0);  // stop
        Serial.println("B actuator positioned");
      }

      if (smcDeviceNumber == 14)
      {
        CInches = 1.0;
        position = readPosition();
        if (position > CFULLINCH)
        {
          setMotorSpeed(-movement); // move in
          while (position >= CFULLINCH) // 1 inch 3460/6
          {
            position = readPosition();
          }
        }
        else
        {
          setMotorSpeed(movement); // move out
          while (position <= CFULLINCH) // 1 inch 3460/6
          {
            position = readPosition();
          }
        }
        Serial.print("out ");
        Serial.println(position);
        bRunning = false;

        setMotorSpeed(0);  // stop
        Serial.println("C actuator positioned");
      }

      if (smcDeviceNumber == 12)
      {
        setMotorSpeed(-movement);  // full-speed reverse
        AInches = 0;
        int lastPosition = -1;
        int  position = readPosition();
        while (position != lastPosition)  // 1 inch = 0 degrees
        {
          lastPosition = position;
          position = readPosition();
          delay(100);
        }
      }
      delay(1000);
    }

    Serial1.println("DONE");

  }

  if (index == (int)'C') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    String direction = command.substring(3, 4);
    parameter = command.substring(4, 6);
    int speedFactor = parameter.toInt();

    command = "e";

    int limit = 0;
    int position = 0;

    desiredPosition = 10;
    limit = AFULLINCH / 2;
    if (speedFactor > 4)
      limit = AFULLINCH;
    desiredPosition = limit;

    Serial.print(" limit");
    Serial.println(limit);

    dir = 1;
    if (direction == "+")
    {
      forward = true;

      setMotorSpeed(3200 / 2); // full-speed forward
      //          delay(230 * speedFactor);// - 200);

      position = readPosition();
      limit = limit + position;
      Serial.println(position);
      Serial.println(limit);
      desiredPosition = limit;

      bRunning = true;
      return;

      while (position < limit)
      {
        position = readPosition();
        Serial.print("position: ");
        Serial.println(position);
        delay(100);
      }
      Serial.println(position);
      Serial.println("out");
    }
    else
    {
      setMotorSpeed(-3200 / 2); // full-speed forward
      forward = false;

      position = readPosition();
      Serial.println(position);
      Serial.println(limit);
      limit = max(5, position - limit); // 0 min (little slop)
      Serial.println(position);
      Serial.println(limit);
      desiredPosition = limit;

      bRunning = true;
      return;

      while (limit < position)
      {
        position = readPosition();
        delay(100);
      }
      Serial.println(position);
      Serial.println("out");

    }
    setMotorSpeed(0);  // stop

    status = 0;
    index = -1;

    position = readPosition();
    Serial.print("Position: ");
    Serial.print(position);
    Serial1.print("E|");
    Serial1.print(position);
    Serial1.print("|");
    Serial1.print(String(pressure, 1));
    Serial1.print("|");
    Serial1.println(smcDeviceNumber);


  }

  if (index == (int)'F') {
    String direction = command.substring(1, 2);
    Serial.println(direction);
    command = "f";
    index = 0;
    status = 0;   // shows waiting (done)

    if (direction == "+")
    {
      moveFITForward = true;
      FITDelay = FITSLOWDELAY;
      Serial.println("Fit extending.");
      digitalWrite(dirFitFoward, LOW);
      digitalWrite(dirFitReverse, HIGH);
    }
    if (direction == "-")
    {
      moveFITForward = true;
      FITDelay = FITSLOWDELAY;
      Serial.println("Fit reversing.");
      digitalWrite(dirFitFoward, HIGH);
      digitalWrite(dirFitReverse, LOW);
    }
    if (direction == "F")
    {
      moveFITForward = true;
      FITDelay = FITFASTDELAY;
      Serial.println("Fit fast extending.");
      digitalWrite(dirFitFoward, LOW);
      digitalWrite(dirFitReverse, HIGH);
    }
    if (direction == "R")
    {
      moveFITForward = true;
      FITDelay = FITFASTDELAY;
      Serial.println("Fit fast reversing.");
      digitalWrite(dirFitFoward, HIGH);
      digitalWrite(dirFitReverse, LOW);
    }
    if (direction == "0")
    {
      moveFITForward = false;
      Serial.println("Fit stopped.");
      digitalWrite(dirFitFoward, LOW);
      digitalWrite(dirFitReverse, LOW);
    }
    timeInFIT = 0;
    Serial1.println(F("DONE"));

  }

  if (index == (int)'E') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    String direction = command.substring(3, 4);
    parameter = command.substring(4, 6);
    int speedFactor = parameter.toInt();
    Serial.println(speedFactor);

    command = "e";

    int limit = 0;

    dir = 1;
    if (direction == "+")
      forward = 1;
    else
      forward = -1;

    if (smcDeviceNumber == 12)
    {
      if (speedFactor > 4)
      {
        limit = AFULLINCH * (AInches + (2 * forward));
        AInches += 2 * forward;
      }
      else
      {
        limit = AFULLINCH * (AInches + forward);
        AInches += forward;
      }
      if (limit <= AZERO)
        limit = AZERO;
      desiredPosition = limit;

      Serial.print(" limit ");
      Serial.print(limit);
      Serial.print(" forward ");
      Serial.print(forward);
      Serial.print(" Ainches ");
      Serial.println(AInches);
    }
    if (smcDeviceNumber == 13)
    {
      if (speedFactor > 4)
      {
        limit = BFULLINCH * (BInches + (2 * forward));
        BInches += 2 * forward;
      }
      else
      {
        limit = BFULLINCH * (BInches + forward);
        BInches += forward;
      }
      if (limit <= BZERO)
        limit = BZERO;
      desiredPosition = limit;

      Serial.print(" limit ");
      Serial.print(limit);
      Serial.print(" forward ");
      Serial.print(forward);
      Serial.print(" Binches ");
      Serial.println(BInches);
    }
    if (smcDeviceNumber == 14)
    {
      if (speedFactor > 4)
      {
        limit = CFULLINCH * (CInches + forward);
        CInches += forward;
      }
      else
      {
        limit = CFULLINCH * (CInches + forward * 0.5);
        CInches += forward * 0.5;
      }
      if (limit <= CZERO)
        limit = CZERO;
      desiredPosition = limit;

      Serial.print(" limit ");
      Serial.print(limit);
      Serial.print(" forward ");
      Serial.print(forward);
      Serial.print(" Cinches ");
      Serial.println(CInches);
    }



    command = "a";
    index = -1;
    status = 0;   // shows waiting (done)
    bRunning = true;
    lastPosition = -1;
  }

  if (index == (int)'?') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    String direction = command.substring(3, 4);
    parameter = command.substring(4, 6);
    int speedFactor = parameter.toInt();
    Serial.println(speedFactor);

    command = "e";

    int limit = 0;
    int position = 0;

    {
      desiredPosition = 10;
      limit = AFULLINCH;
      if (speedFactor > 4)
        limit = AFULLINCH * 2;
      desiredPosition = limit;

      Serial.print(" limit");
      Serial.println(limit);

      dir = 1;
      if (direction == "+")
      {
        forward = true;

        setMotorSpeed(3200 / 2); // full-speed forward
        //          delay(230 * speedFactor);// - 200);

        position = readPosition();
        limit = limit + position;
        Serial.println(position);
        Serial.println(limit);
        desiredPosition = limit;

        bRunning = true;
        return;

        while (position < limit)
        {
          position = readPosition();
          Serial.print("position: ");
          Serial.println(position);
          delay(100);
        }
        Serial.println(position);
        Serial.println("out");
      }
      else
      {
        setMotorSpeed(-3200 / 2); // full-speed forward
        forward = false;

        position = readPosition();
        Serial.println(position);
        Serial.println(limit);
        limit = max(5, position - limit); // 0 min (little slop)
        Serial.println(position);
        Serial.println(limit);
        desiredPosition = limit;

        bRunning = true;
        return;

        while (limit < position)
        {
          position = readPosition();
          delay(100);
        }
        Serial.println(position);
        Serial.println("out");

      }
    }
    // delay(230 * speedFactor);// - 200);
    setMotorSpeed(0);  // stop
    //    delay(230);

    status = 0;
    index = -1;

    pressure = abs(scale.get_units(10));

    position = readPosition();
    Serial.print("Position: ");
    Serial.print(position);
    Serial1.print("E|");
    Serial1.print(position);
    Serial1.print("|");
    Serial1.print(String(pressure, 1));
    Serial1.print("|");
    Serial1.println(smcDeviceNumber);


  }

  /*************** ?????????????? ********/
  if (index == (int)'K') {

    if (bRunning)
      return;

    smcDeviceNumber = 14;
    Serial.println(command);

    String parameter = command.substring(1);
    Serial.println(parameter);

    desiredPosition = parameter.toInt();
    Serial.println(desiredPosition);

    position = readPosition();
    Serial.print(desiredPosition);
    Serial.print(" ");
    Serial.println(position);

    if (desiredPosition >= (position + 25))
    {
      forward = 1;
      //    desiredPosition -= 30;
    }
    else
    {
      forward = -1;
      //     desiredPosition += 30;
    }
    setMotorSpeed(forward * CSpeed);   // slow-speed backward

    Serial.print(forward);
    Serial.print(" ");
    Serial.print(desiredPosition);
    Serial.print(" ");
    Serial.println(position);

    bRunning = true;
    status = 1;   // shows moving
    command = "k";
    index = 0;

  }



  if (index == (int)'A') {
    if (bRunning)
      return;

    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    Serial.println(smcDeviceNumber);
    parameter = command.substring(3);
    float inches = parameter.toFloat();

    if (smcDeviceNumber == 120)
    {
      desiredPosition = AFULLINCH * inches;
      AInches = inches;
      if (inches == 0)
        desiredPosition = AZERO;
      // read the analog in value:
      APosition = analogRead(AAnalog);

      if (desiredPosition >= APosition)
      {
        digitalWrite(dirAFoward, LOW);
        digitalWrite(dirAReverse, HIGH);
        moveAForward = true;
      }
      if (desiredPosition <= APosition)
      {
        digitalWrite(dirAFoward, HIGH);
        digitalWrite(dirAReverse, LOW);
        moveAForward = true;
      }
    }
    else
    {
      if (smcDeviceNumber == 12)
      {
        desiredPosition = AFULLINCH * inches;
        AInches = inches;
        if (inches == 0)
          desiredPosition = AZERO;
      }
      if (smcDeviceNumber == 13)
      {
        desiredPosition = BFULLINCH * inches;
        BInches = inches;
        if (inches == 0)
          desiredPosition = BZERO;
      }

      if (smcDeviceNumber == 14)
      {
        desiredPosition = CFULLINCH * inches;
        CInches = inches;
        if (inches == 0)
          desiredPosition = CZERO;
      }

      position = readPosition();
      Serial.print(inches);
      Serial.print(" ");
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);

      if (desiredPosition >= (position + 25))
      {
        forward = 1;
      }
      else
      {
        forward = -1;
      }
      bRunning = true;
    }
    command = "a";
    index = -1;
    status = 0;   // shows waiting (done)
    lastPosition = -1;
  }



  if (index == (int)'L') {
    String parameter = command.substring(1, 2);
    int stage = parameter.toInt();
    int weight = 0;
    float measuredWeight = 0.0;

    float calibration = 0;
    switch (stage)
    {
      case 0:
        if (command.length() > 2)
          calibration_factor = command.substring(2).toFloat();
        Serial.print("calibration_factor: ");
        Serial.println(calibration_factor);
        scale.set_scale(calibration_factor); //Adjust to this calibration factor
        scale.tare(); //Reset the scale to 0

        basePressure = scale.get_units();
        Serial.print(basePressure);
        Serial1.println("step 0");
        position = 0;
        break;
      case 1:
        Serial.print("calibration_factor: ");
        Serial.println(calibration_factor);
        scale.set_scale(calibration_factor); //Adjust to this calibration factor
        scale.tare();
        Serial.print("UNITS: ");
        Serial.println(scale.get_units(10));

        Serial1.println("DONE");

        delay(2000);

        break;
      case 2:
        if (command.length() > 2)
          weight = command.substring(2).toInt();

        Serial.println(weight);
        scale.calibrate_scale(weight, 5);
        Serial.print("UNITS: ");
        Serial.println(scale.get_units(10));

        Serial1.println("step 2");
        break;
      case 3:
        calibration = scale.get_scale();
        Serial.println(calibration);

        scale.set_scale(calibration);
        Serial.println(scale.get_scale());

        Serial1.print("step 3|");
        Serial1.println(calibration);

        break;
      case 4:
        pressure = abs(scale.get_units(10));

        Serial.println(pressure);

        Serial1.print("weight|");
        Serial1.println(pressure);
        break;

      case 5:
        //        if (command.length() > 2)
        {
          AZERO = command.substring(2, 5).toInt();
          BZERO = command.substring(5, 9).toInt();


          Serial.print("AZERO: ");
          Serial.print(AZERO);
          Serial.print("BZERO: ");
          Serial.println(BZERO);
          Serial1.println("DONE");
        }
        break;

      case 6:
        {
          uint16_t positionA = 0;
          uint16_t positionB = 0;
          uint16_t positionC = 0;
          float pressure = 0;

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
      default:
        Serial.println(stage);
        break;
    }

    command = "l";
    index = 0;
    status = 0;

  }

  if (index == (int)'J') {
    String parameter = "";

    if (command.length() > 1)
      parameter = command.substring(1);

    if (parameter == "")
    {
      Serial.println("jerking");
      //      jerkDirection = -1;
      jerking = true;
      sendStatus();
      noStatus = true;
      inJerk = 0;
      maxJerks = 15;
      jerkPause = 100;
      jerksCompleted = 0;
      smcDeviceNumber = 12;
      //     setMotorSpeed(3200 * jerkDirection);  // full-speed stop
    }

    if (parameter == "S")
    {
      Serial.println("stop jerking");
      jerkDirection = 0;
      jerking = false;
      noStatus = false;
      setMotorSpeed(0);  // stop the jerk
      inJerk = 0;
      Serial1.println("DONE");
    }


    command = "j";
    index = 0;
    status = 0;

  }

}
