//
//    FILE: HX_kitchen_scale.ino
//  AUTHOR: Rob Tillaart
// VERSION: 0.1.0
// PURPOSE: HX711 demo
//     URL: https://github.com/RobTillaart/HX711
//

// HISTORY:
// 0.1.0    2020-06-16 initial version
//

#include "HX711.h"

HX711 scale;

uint8_t dataPin = 7;
uint8_t clockPin = 6;


void setup()
{
  float weight = 0;


  Serial.begin(9600);
  Serial.println("\n\n\n\n\n\n\n");
  Serial.println(__FILE__);
  Serial.println();

  scale.begin(dataPin, clockPin);

  Serial.println("\nEmpty the scale, press a key to continue");
  while (!Serial.available());
  while (Serial.available()) Serial.read();

  scale.tare();

  Serial.println("\nWhat is weight?");
  while (!Serial.available());
  if (Serial.available())
  {
    weight = Serial.readStringUntil('\n').toFloat();
    Serial.flush();
    Serial.print("weight ");
    Serial.println(weight);
  }

  Serial.println("\nPut weight on the scale, press a key to continue");
  while (!Serial.available());
  while (Serial.available()) Serial.read();

  scale.calibrate_scale(weight, 5);
  Serial.print("UNITS: ");
  Serial.println(scale.get_units(10));

  Serial.println("\nScale is calibrated, press a key to continue");
  float claibration = scale.get_scale();
  while (!Serial.available());
  while (Serial.available()) Serial.read();
  //claibration = -58.19;
  scale.set_scale(claibration);
  Serial.println(scale.get_scale());
}

void loop()
{
  Serial.print("UNITS: ");
  Serial.println(scale.get_units(10));
  delay(500);
}

// END OF FILE
