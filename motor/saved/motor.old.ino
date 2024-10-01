/*
  Arduino Slave for Raspberry Pi Master
  i2c_slave_ard.ino
  Connects to Raspberry Pi via I2C

  DroneBot Workshop 2019
  https://dronebotworkshop.com
*/

#include "HX711.h"

#define LOADCELL_DOUT_PIN  7
#define LOADCELL_SCK_PIN  6

#define DEBUG

#define noA true
#define noB true
#define noC false

# define LOOPPOSITION_DELAY 3000

HX711 scale;

float calibration_factor = -4360.14; //-26594.13; // worked for test weight 3lbs
float basePressure = 0.0;
float pressure = 0;
bool measurePressure = false;
bool cdRunning = false;
bool bRunning = false;
bool forward = false;
bool aRunning = false;

// Include the Wire library for I2C
#include <Wire.h>

uint8_t smcDeviceNumber = 13;


int dir = 1;

int Speed;

// https://s3.amazonaws.com/actuonix/Actuonix+LAC+Datasheet.pdf
// C actuator relay
int speedPinA = 9; // Needs to be a PWM pin to be able to control motor speed
int dir1PinA = 4;
int dir2PinA = 5;

int FITENABLE = 44; // Needs to be a PWM pin to be able to control motor speed
int FITFORWARD = 43;
int FITREVERSE = 42;

volatile long steps = 0;   // Pulses from  Hall Effect sensors
volatile int sensor = 0;  //
volatile int lastSensor = -1;  //

#define FULLINCH  620 //620

// global volatile variables are needed to pass data between the

// main program and the ISR's

volatile byte signalA;
volatile byte signalB;
volatile byte signalPi;

volatile bool limitHit = false;

volatile bool STOP = false;

// are using
const byte inputA = 3;
const byte inputB = 24;
const byte Pi = 2;

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



  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  // scale.set_scale();
  // scale.tare(); //Reset the scale to 0

  //  long zero_factor = scale.read_average(); //Get a baseline reading
  scale.set_scale(calibration_factor); //Adjust to this calibration factor


  delay(1000);

  Serial1.begin(115200);

  // declare Relay as output
  pinMode(dir1PinA, OUTPUT);
  pinMode(dir2PinA, OUTPUT);
  pinMode(speedPinA, OUTPUT);

  // declare Relay as output
  pinMode(FITENABLE, OUTPUT);
  pinMode(FITFORWARD, OUTPUT);
  pinMode(FITREVERSE, OUTPUT);

  steps = 0;

  // enable internal resistors on the input pins
  pinMode(inputA, INPUT_PULLUP);
  pinMode(inputB, INPUT_PULLUP);
  pinMode(Pi, INPUT_PULLUP);
  // read the initial state of the inputs
  signalA = digitalRead(inputA);
  signalB = digitalRead(inputB);
  signalPi = digitalRead(Pi);

#ifndef DEBUG
  // will detect a rising or a falling edge
  attachInterrupt(digitalPinToInterrupt(inputA), signalA_ISR, RISING);
#endif

  int movement = -3000;
  if (noA)
    Serial.println("A actuator skipped");
  else
  {
    smcDeviceNumber = 12; // position actuator
    setMotorSpeed(movement);  // full-speed reverse

    int lastPosition = -1;
    int  position = readPosition();

    while (position != lastPosition)  // 1 inch = 0 degrees
    {
      lastPosition = position;
      position = readPosition();
      Serial.println(position);
      delay(100);
    }
    delay(1000);

    Serial.print("out ");
    Serial.println(position);

    setMotorSpeed(0);  // stop
    Serial.println("A actuator positioned");
  }

  if (noB)
    Serial.println("B actuator skipped");
  else
  {
    smcDeviceNumber = 13; // position actuator
    setMotorSpeed(movement);  // full-speed reverse

    int lastPosition = -1;
    int  position = readPosition();

    while (position != lastPosition)  // 1 inch = 0 degrees
    {
      lastPosition = position;
      position = readPosition();
      delay(100);
    }
    delay(1000);

    setMotorSpeed(-movement / 2); // move out

    position = readPosition();
    while (position < FULLINCH * 2) // 2 inch 3460/6
    {
      position = readPosition();
    }
    Serial.print("out ");
    Serial.println(position);

    setMotorSpeed(0);  // stop
    Serial.println("B actuator positioned");
  }

  Serial.println("C actuator positioning");
  smcDeviceNumber = 14; //blue bullet actuator

  setMotorSpeed(movement);  // full-speed reverse

#ifdef DEBUG
  int lastPosition = -1;
  int  position = readPosition();

  while (position != lastPosition)  // 1 inch = 0 degrees
  {
    lastPosition = position;
    position = readPosition();
    delay(100);
  }
  delay(1000);

  setMotorSpeed(-movement / 2); // move out

  position = readPosition();
  while (position < FULLINCH) // 1 inch 3460/6
  {
    position = readPosition();
  }
  Serial.print("out ");
  Serial.println(position);

#else
  dir = -1;
  steps = 10000;
  delay(1000);

  int lastStep = -1;
  while (steps != lastStep)  // 1 inch = 0 degrees
  {
    lastStep = steps;
    //   Serial.print("steps ");
    //   Serial.println(steps);
    delay(100);
  }
  delay(1000);
  steps = 0;

  dir = 1;
  setMotorSpeed((-movement) / 2); // start to find forward 1 inch
  while (steps <= CLimit - 5) // 1 inch = 0 degrees
  {
    //    Serial.print("steps ");
    //  Serial.println(steps);
    int hit = digitalRead(inputB);
    if (hit == LOW)
    {
      Serial.println("hit");
      break;
    }
    delay(100);
  }
#endif

  setMotorSpeed(0);  // stop
  Serial.println("C actuator positioned");


  // delay(10000);
  Serial.print("readPosition ");
  Serial.print(readPosition());
  Serial.print(" steps ");
  Serial.println(steps);

  Serial.println("Ready to Go");

  Serial1.println("Ready to Go");
}

unsigned long lastStepTime = 0; // Time stamp of last pulse
unsigned long lastStepBTime = 0; // Time stamp of last pulse
int trigDelay = 300;            // Delay bewteen pulse in microseconds


void signalA_ISR() {
  // when a change is detected it will always be

  // to the opposite of the current state

  signalA = !signalA;
  steps = steps + dir;
  //    Serial.print("steps ");
  //   Serial.println(steps);
  if (steps < 0)
    steps = 0;
}

void limit_ISR() {
  if (micros() - lastStepTime > trigDelay) {
    limitHit = true;
    Serial.println("limit hit");

    lastStepTime = micros();
  }

}


void countSteps(void) {
  if (micros() - lastStepTime > trigDelay) {
    steps = steps + dir;
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
#ifndef DEBUG
  if (smcDeviceNumber == 14)
  {
    int newSpeed = int((speed / 3200.0) * 255);
    newSpeed = 128;
    Serial.print("speed ");
    Serial.println(speed);
    Serial.println(newSpeed);
    if (speed == 0)
    {
      analogWrite(speedPinA, 0);
      digitalWrite(dir1PinA, HIGH);
      digitalWrite(dir2PinA, LOW);
      Serial.print("Motor ");
      Serial.print(smcDeviceNumber);
      Serial.println(" Stop");
    }
    else if (speed < 0)
    {
      analogWrite(speedPinA, newSpeed);//Sets speed variable via PWM
      digitalWrite(dir1PinA, HIGH);
      digitalWrite(dir2PinA, LOW);
      Serial.print("Motor ");
      Serial.print(smcDeviceNumber);
      Serial.println(" Reverse");
    }
    else
    {
      analogWrite(speedPinA, newSpeed);//Sets speed variable via PWM
      digitalWrite(dir1PinA, LOW);
      digitalWrite(dir2PinA, HIGH);
      Serial.print("Motor ");
      Serial.print(smcDeviceNumber);
      Serial.println(" Forward");
    }
    return;
  }
#endif

  if (noA && smcDeviceNumber == 12)
    return;
  if (noB && smcDeviceNumber == 13)
    return;
  if (noC && smcDeviceNumber == 14)
    return;

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
#ifdef DEBUG
  if (noC && smcDeviceNumber == 14)
    return position;
#else
  if (smcDeviceNumber == 14)
    return steps;
#endif

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

  if (position <= 60 || position > 65000)
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

/************************* sendStatus() ************/
void sendStatus()
{
  uint8_t lastSmcDeviceNumber = 0;
  uint16_t positionA = 0;
  uint16_t positionB = 0;
  uint16_t positionC = 0;
  //  float pressure = 0;

  lastSmcDeviceNumber = smcDeviceNumber;

  smcDeviceNumber = 12;
  positionA = readPosition();
  smcDeviceNumber = 13;
  positionB = readPosition();
#ifdef DEBUG
  smcDeviceNumber = 14;
  positionC = readPosition();
#endif
  pressure = abs(scale.get_units(10));


  Serial.print(F("Status: "));
  Serial.print(F(" 12: "));
  Serial.print(positionA);
  Serial.print(F(" 13: "));
  Serial.print(positionB);
#ifdef DEBUG
  Serial.print(F(" 14: "));
  Serial.print(positionC);
#else
  Serial.print(F(" steps: "));
  Serial.print(steps);
#endif
  Serial.print(F(" pressure: "));
  Serial.println(pressure);

  Serial1.print("S|");
  Serial1.print(positionA);

  Serial1.print("|");
  Serial1.print(positionB);

  Serial1.print("|");
  Serial1.print(steps);

  Serial1.print("|");
  Serial1.println(pressure);

  smcDeviceNumber = lastSmcDeviceNumber;

}

void loop() {

  static int status = 0;
  static String command = "n";
  static int index = 0; //ascii value of command

  static uint16_t position = 0;
  static uint16_t lastPosition = -1;
  static uint16_t desiredPosition = 3;
  static int inches = 3;

  static float desiredPressure = 0;
  static float lastStep = -1;
  String c;
  int lastStatus = -1;
  bool ok;
  static unsigned long loopPosition = millis() - LOOPPOSITION_DELAY;  //initial start time
#ifdef DEBUG
  if (Serial.available())
  {
    c = Serial.readStringUntil('\n');
    Serial.flush();
    Serial.print("sc ");
    Serial.println(c);

    if (c == "f")
    {
      analogWrite(speedPinA, 255);//Sets speed variable via PWM
      digitalWrite(dir1PinA, LOW);
      digitalWrite(dir2PinA, HIGH);
      Serial.print("Motor ");
      Serial.println(" Forward");
    }
    if (c == "r")
    {
      analogWrite(speedPinA, 128);//Sets speed variable via PWM
      digitalWrite(dir1PinA, HIGH);
      digitalWrite(dir2PinA, LOW);
      Serial.print("Motor ");
      Serial.println(" Reverse");
    }
    pressure = c.toFloat();
    Serial.print("sc ");
    Serial.println(pressure);
  }
#endif

  if ((millis() - loopPosition) > LOOPPOSITION_DELAY)
  {
    ////    Serial.print(F("Loop Status: "));
    loopPosition = millis();

    if (bRunning)
      return;
    if (cdRunning)
      return;

    sendStatus();

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
      cdRunning = false;

    }
    else
    {
      position = readPosition();
      ok = position >= desiredPosition;
      if (!forward)
        ok = position <= desiredPosition;
      if (lastPosition == position)
      {
        position = desiredPosition;
        ok = true;
      }
/*
      Serial.print(ok);
      Serial.print(" ");
      Serial.print(position);
      Serial.print(" ");
      Serial.println(desiredPosition);
*/
      lastPosition = position;
      if (ok)
      {
        Serial.println("Stopped Moving");

        setMotorSpeed(0);   // full-stop

        command = "a";
        index = -1;
        status = 0;   // shows waiting (done)
        Serial1.println("DONE");

        bRunning = false;

        position = readPosition();
        Serial.print(F("Stopped at position: "));
        Serial.println(position);
        //     delay(10000);
      }
    }
  }
  if (cdRunning)
  {
    ok = steps >= desiredPosition;
    if (forward)
    {
      int hit = digitalRead(inputB);
      if (hit == LOW)
      {
        Serial.println("hit limit");
        ok = true;
      }
    }
    else
      ok = steps <= desiredPosition;
    if (lastStep == steps)
    {
      steps = desiredPosition;
      ok = true;
    }
    lastStep = steps;

    Serial.print(smcDeviceNumber);
    Serial.print(" ");
    Serial.print(ok);
    Serial.print(" ");
    Serial.print(steps);
    Serial.print(" ");
    Serial.println(desiredPosition);

    if (ok)
    {
      Serial.println("stopping");
      smcDeviceNumber = 14;
      setMotorSpeed(0);   // stop
      Serial.print(F("Stopped at step: "));
      Serial.println(steps);

      Serial1.println("DONE");

      index = -1;
      status = 0;   // shows waiting (done)
      cdRunning = false;
    }
  }

  if (measurePressure)
  {
    smcDeviceNumber = 12;

    pressure = abs(scale.get_units(1));

    if (pressure >= desiredPressure)
    {
      basePressure =  pressure;
      //    Serial.println(">pressure");
      setMotorSpeed(-500);   // slow-speed backward
      if (pressure >= desiredPressure)
      {
        pressure = abs(scale.get_units(10));
        //      Serial.print(">pressure ");
        //         Serial.print(pressure);

        if (abs(desiredPressure - pressure) < 0.2)
          measurePressure = false;
        basePressure = pressure;
        //         Serial.println(measurePressure);
      }
    }
    else if (pressure < desiredPressure)
    {
      //      Serial.println("<pressure");
      setMotorSpeed(500);   // slow-speed forward
      if (abs(desiredPressure - pressure) > 0.2)
      {
        pressure = abs(scale.get_units(10));
        //   Serial.println(pressure);
      }
      else
        measurePressure = false;
    }
    if (!measurePressure)
    {
      setMotorSpeed(0);   // full-stop
      sendStatus();
      Serial1.println("DONE");
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
    //    Serial.print(" ");
    //      Serial.println(status);
    //  command = "s";
  }
  else
  {
    command = c;
    index = (int)c[0];
  }



  if (index == (int)'I') {
    String parameter = command.substring(1);
    smcDeviceNumber = parameter.toInt();
    Serial.print("I smcDeviceNumber ");
    Serial.println(smcDeviceNumber);

    command = "i";
    status = 0;
    index = -1;
  }


  if (index == (int)'P') {
    String parameter = command.substring(1);
    desiredPressure = parameter.toInt();
    Serial.print("desiredPressure ");
    Serial.println(desiredPressure);
    command = "p";
    index = -1;
    status = 0;   // shows waiting (done)

    smcDeviceNumber = 12;

    pressure = abs(scale.get_units(10));

    Serial.println(pressure);

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
    cdRunning = false;

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
    Serial.print(F(" Steps: "));
    Serial.println(steps);
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

  if (index == (int)'Z') {
    static bool forward;
    bool ok;

    //    Serial.println(command);
    if (status == 0)
    {

      String parameter = command.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);
      parameter = command.substring(3);
      desiredPosition = parameter.toInt();
      Serial.println(desiredPosition);
      command = "r";
      forward = true;
      if (desiredPosition >= steps)
      {
        dir = 1;
        setMotorSpeed(1500);   // moderate-speed forward
      }
      else
      {
        forward = false;
        dir = -1;
        setMotorSpeed(-1500);   // moderate-speed reverse
      }

      status = 1;   // shows moving
    }
    else
    {
      bool ok = steps >= desiredPosition;
      if (!forward)
        ok = steps <= desiredPosition;

      if (ok)
      {
        Serial.println("stopping");
        //     delay(10000);
        setMotorSpeed(0);   // stop
        Serial.println(desiredPosition);
        Serial.println(steps);

        Serial.println("digitalWrite(STATUSI2C, HIGH);");
        index = -1;
        status = 0;   // shows waiting (done)

      }
    }

  }

  if (index == (int)'R') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    Serial.println(smcDeviceNumber);
    command = "r";
    index = 0;
    status = 0;   // shows waiting (done)

    int movement = 3200 / 3;
#ifndef DEBUG
    if (smcDeviceNumber == 14)
    {
      int hit = 0;
      Serial.println("C actuator positioning");
      dir = -1;
      steps = 10000;
      setMotorSpeed(-movement / 2); // start in reverse to find forward 1 inch
      delay(1000);

      int lastStep = -1;
      while (steps != lastStep)  // 1 inch = 0 degrees
      {
        lastStep = steps;
        //           Serial.println(steps);
        delay(100);
      }
      delay(1000);
      steps = 0;
      Serial.println(steps);

      if (steps > CLimit)
      {
        Serial.println("moving in");
        //      Serial.println(steps);
        dir = -1;
        setMotorSpeed(-movement / 2); // start in reverse to find forward 1 inch
        while (steps >= CLimit) // 1 inch = 0 degrees
        {
          /*
            hit = digitalRead(inputB);
            if (hit == LOW)
            {
            Serial.println("hit");
            break;
            }*/
          delay(100);
        }
      }
      else
      {
        dir = 1;
        setMotorSpeed(-movement / 2); // start to find forward 1 inch
        Serial.println("moving out");
        setMotorSpeed(movement / 2); // start to find forward 1 inch
        while (steps <= CLimit)  // 1 inch = 0 degrees
        {
          //         Serial.println(steps);
          int hit = digitalRead(inputB);
          if (hit == LOW)
          {
            Serial.println("hit");
            break;
          }
          delay(100);
        }
      }
      setMotorSpeed(0);  // stop
      Serial.println("C actuator positioned");
      Serial.print(" after :");
      Serial.println(steps);
    }
    else
#endif
    {
      if (smcDeviceNumber == 13)
      {

        position = readPosition();
        if (position > FULLINCH * 2)
        {
          setMotorSpeed(-movement); // move in
          while (position >= FULLINCH * 2) // 2 inch 3460/6
          {
            position = readPosition();
          }
        }
        else
        {
          setMotorSpeed(movement); // move out
          while (position <= FULLINCH * 2) // 2 inch 3460/6
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
#ifdef DEBUG
      if (smcDeviceNumber == 14)
      {

        position = readPosition();
        if (position > FULLINCH)
        {
          setMotorSpeed(-movement); // move in
          while (position >= FULLINCH) // 1 inch 3460/6
          {
            position = readPosition();
          }
        }
        else
        {
          setMotorSpeed(movement); // move out
          while (position <= FULLINCH) // 1 inch 3460/6
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
#endif
      if (smcDeviceNumber == 12)
      {
        setMotorSpeed(-movement);  // full-speed reverse

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
  /****************** NOT USED ************/
  if (index == (int)'H') {
    String parameter = command.substring(1, 3);
    smcDeviceNumber = parameter.toInt();
    Serial.println(smcDeviceNumber);
    command = "r";
    index = 0;
    Serial.print("steps:");
    Serial.print(steps);
    int movement = 3200 / 2;

    if (smcDeviceNumber == 14)
    {
      Serial.println("C actuator positioning");

      setMotorSpeed(movement / 2); // start to find forward 1 inch
      while (steps <= CLimit)  // 1 inch = 0 degrees
      {
        int hit = digitalRead(inputB);
        if (hit == LOW)
        {
          Serial.println("hit");
          break;
        }
      }
      setMotorSpeed(0);  // stop
      Serial.println("C actuator positioned");
      Serial.print(" after :");
      Serial.println(steps);
    }
    else
    {
      setMotorSpeed(movement);  // full-speed reverse
      delay(5000);

      Serial.println(readPosition());
    }
    Serial.println(F("Start Position: "));
    Serial1.println(F("DONE"));

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

#ifdef DEBUG
    desiredPosition = 10;
    limit = FULLINCH / 2;
    if (speedFactor > 4)
      limit = FULLINCH;
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
#else
    Serial.println(steps);
    limit = CLimit / 2;
    if (speedFactor > 4)
      limit = CLimit;

    dir = 1;
    if (direction == "+")
    {
      limit = min(CLimit * 6, limit + steps); // two inch max
      //     limit = CLimit * 6;
      setMotorSpeed(3200 / 2); // full-speed forward
      while (steps <= limit)
      {
        int hit = digitalRead(inputB);
        //        Serial.println(steps);
        if (hit == LOW)
        {
          Serial.println("hit limit");
          break;
        }
        delay(100);
      }
    }
    else if (direction == "-")
    {
      dir = -1;
      limit = max(5, steps - limit); // 0 min (little slop)
      setMotorSpeed(-3200 / 2); // full-speed reverse
      Serial.print("limit ");
      Serial.print(limit);
      Serial.print(" steps ");
      Serial.println(steps);

      while (limit <= steps)
      {
        int hit = digitalRead(inputB);
        if (hit == LOW)
        {
          Serial.println("hit limit");
          break;
        }
        delay(100);
      }
    }
    Serial.println(steps);
#endif
    setMotorSpeed(0);  // stop

    status = 0;
    index = -1;

    position = readPosition();
    Serial.print("Position: ");
    Serial.print(position);
    Serial.print(" Steps: ");
    Serial.println(steps);

    Serial1.print("E|");
    Serial1.print(position);
    Serial1.print("|");
    Serial1.print(steps);
    Serial1.print("|");
    Serial1.print(String(pressure, 1));
    Serial1.print("|");
    Serial1.println(smcDeviceNumber);


  }

  if (index == (int)'F') {
    String direction = command.substring(1, 2);
    Serial.println(direction);
    command = "x";
    index = 0;
    int movement = 3200 / 2;

    digitalWrite(FITENABLE, HIGH);
    if (direction == "+")
    {
      Serial.println("Fit extending.");
      digitalWrite(FITFORWARD, HIGH);
      digitalWrite(FITREVERSE, LOW);
      delay(500);
      digitalWrite(FITFORWARD, LOW);
      digitalWrite(FITREVERSE, LOW);
    }
    if (direction == "-")
    {
      Serial.println("Fit reversing.");
      digitalWrite(FITFORWARD, LOW);
      digitalWrite(FITREVERSE, HIGH);
      delay(500);
      digitalWrite(FITFORWARD, LOW);
      digitalWrite(FITREVERSE, LOW);
    }
    if (direction == "F")
    {
      Serial.println("Fit extending.");
      digitalWrite(FITFORWARD, HIGH);
      digitalWrite(FITREVERSE, LOW);
    }
    if (direction == "R")
    {
      Serial.println("Fit reversing.");
      digitalWrite(FITFORWARD, LOW);
      digitalWrite(FITREVERSE, HIGH);
    }
    if (direction == "0")
    {
      Serial.println("Fit stopped.");
      digitalWrite(FITFORWARD, LOW);
      digitalWrite(FITREVERSE, LOW);
    }
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
    int position = 0;

#ifndef DEBUG
    if (smcDeviceNumber == 14)
    {
      Serial.println(steps);
      limit = 2100 / 2;
      if (speedFactor > 4)
        limit = 2100;

      dir = 1;
      if (direction == "+")
      {
        limit = min(2100 * 2, limit + steps); // two inch max
        setMotorSpeed(3200 / 2); // full-speed forward
        while (steps < limit)
        {
          int hit = digitalRead(inputB);
          if (hit == LOW)
          {
            Serial.println("hit limit");
            break;
          }
          delay(100);
        }
      }
      else if (direction == "-")
      {
        dir = -1;
        limit = max(5, steps - limit); // 0 min (little slop)
        setMotorSpeed(-3200 / 2); // full-speed reverse
      }
      Serial.println(steps);
    }
    else  // the A, B actuators
#endif
    {
      desiredPosition = 10;
      limit = FULLINCH;
      if (speedFactor > 4)
        limit = FULLINCH * 2;
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
    Serial.print(" Steps: ");
    Serial.println(steps);

    Serial1.print("E|");
    Serial1.print(position);
    Serial1.print("|");
    Serial1.print(steps);
    Serial1.print("|");
    Serial1.print(String(pressure, 1));
    Serial1.print("|");
    Serial1.println(smcDeviceNumber);


  }

  /*************** ?????????????? ********/
  if (index == (int)'K') {
    bool ok;
    int motorSpeed = 600;

    if (status == 0)
    {
      smcDeviceNumber = 14;
      Serial.println(command);

      String parameter = command.substring(1);
      Serial.println(parameter);

      desiredPosition = parameter.toInt();
      Serial.println(desiredPosition);

#ifdef DEBUG
      //     Serial.println(desiredPosition);
      if (desiredPosition >= 3575)
        desiredPosition = 3575;

      position = readPosition();
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);

      if (desiredPosition >= (position + 25))
      {
        forward = true;
        setMotorSpeed(1500);   // moderate-speed forward
      }
      else
      {
        forward = false;
        setMotorSpeed(-1500);   // moderate-speed reverse
      }
      bRunning = true;
      status = 1;   // shows moving
#else
      Serial.println(steps);

      if (desiredPosition >= steps)
      {
        forward = true;
        dir = 1;
        setMotorSpeed(motorSpeed);   // moderate-speed forward
        Serial.print("steps ");
        Serial.println(steps);
      }
      else
      {
        forward = false;
        dir = -1;
        setMotorSpeed(-motorSpeed);   // moderate-speed reverse
      }
      Serial.print("forward ");
      Serial.println(forward);

      cdRunning = true;

#endif
      status = 1;   // shows waiting (done)
      command = "k";
      index = 0;
    }

  }



  if (index == (int)'A') {
    bool ok;
    //    Serial.println(command);
    if (status == 0)
    {

      //     digitalWrite(STATUSI2C, LOW);

      String parameter = command.substring(1, 3);
      smcDeviceNumber = parameter.toInt();
      Serial.println(smcDeviceNumber);
      parameter = command.substring(3);
      desiredPosition = parameter.toInt();
      //     Serial.println(desiredPosition);
      if (desiredPosition >= 3575)
        desiredPosition = 3575;


      position = readPosition();
      Serial.print(desiredPosition);
      Serial.print(" ");
      Serial.println(position);

      if (desiredPosition >= (position + 25))
      {
        forward = true;
        setMotorSpeed(1500);   // moderate-speed forward
      }
      else
      {
        forward = false;
        setMotorSpeed(-1500);   // moderate-speed reverse
      }
      bRunning = true;
      status = 1;   // shows moving
    }
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
        scale.tare();
        Serial.print("UNITS: ");
        Serial.println(scale.get_units(10));

        Serial1.println("step 1");
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
      default:
        Serial.println(stage);
        break;
    }

    command = "l";
    index = 0;
    status = 0;

  }
}
