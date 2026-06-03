/*
  Load Cell Scale Testing and Diagnostics
  For KneeSpa System - HX711 Load Cell Amplifier

  This script helps diagnose and fix scale reading issues:
  - Jumping to high values (1923.3) then dropping to 0
  - Connection problems
  - Calibration issues

  Wiring:
  - HX711 DT/DOUT -> Arduino Pin 7
  - HX711 SCK/CLK -> Arduino Pin 6
  - HX711 VCC -> 5V
  - HX711 GND -> GND

  Load Cell to HX711:
  - RED -> E+
  - BLACK -> E-
  - WHITE -> A-
  - GREEN -> A+
*/

#include "HX711.h"

// Pin definitions - MUST match motor.ino
#define LOADCELL_DOUT_PIN  7
#define LOADCELL_SCK_PIN   6

// Create scale object
HX711 scale;

// Calibration values
float calibration_factor = -4360.14;  // Default from motor.ino
float last_valid_reading = 0;
bool scale_ready = false;

// Monitoring variables
unsigned long last_reading_time = 0;
int consecutive_zeros = 0;
int consecutive_errors = 0;
float readings_buffer[10];
int buffer_index = 0;

// Test modes
bool continuous_mode = false;
bool raw_mode = false;
bool debug_mode = false;
bool stability_test = false;

void setup() {
  Serial.begin(115200);

  Serial.println(F("========================================"));
  Serial.println(F("    Load Cell Scale Diagnostic Tool"));
  Serial.println(F("========================================"));
  Serial.println(F("Initializing..."));
  Serial.println();

  // Initialize the scale
  Serial.print(F("Connecting to HX711 on pins DOUT="));
  Serial.print(LOADCELL_DOUT_PIN);
  Serial.print(F(", SCK="));
  Serial.println(LOADCELL_SCK_PIN);

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);

  delay(1000);  // Let HX711 stabilize

  // Check if scale is connected
  if (scale.is_ready()) {
    Serial.println(F("✓ HX711 detected and ready"));
    scale_ready = true;

    // Set initial calibration
    scale.set_scale(calibration_factor);

    // Initial tare
    Serial.println(F("Performing initial tare (remove all weight)..."));
    delay(2000);
    scale.tare();
    Serial.println(F("✓ Tare complete"));

  } else {
    Serial.println(F("✗ ERROR: HX711 not detected!"));
    Serial.println(F("Check wiring:"));
    Serial.println(F("  - DOUT -> Pin 7"));
    Serial.println(F("  - SCK  -> Pin 6"));
    Serial.println(F("  - VCC  -> 5V"));
    Serial.println(F("  - GND  -> GND"));
  }

  Serial.println();
  Serial.println(F("Commands:"));
  Serial.println(F("  R - Read single value"));
  Serial.println(F("  C - Continuous reading mode (toggle)"));
  Serial.println(F("  T - Tare/Zero the scale"));
  Serial.println(F("  W - Raw value reading mode (toggle)"));
  Serial.println(F("  D - Debug mode (toggle)"));
  Serial.println(F("  S - Stability test (10 readings)"));
  Serial.println(F("  F - Set calibration factor"));
  Serial.println(F("  A - Auto-calibrate with known weight"));
  Serial.println(F("  I - Show scale info"));
  Serial.println(F("  X - Check connections"));
  Serial.println(F("  H - Help"));
  Serial.println(F("========================================"));
}

void loop() {
  // Handle serial commands
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    processCommand(cmd);
  }

  // Continuous reading mode
  if (continuous_mode && scale_ready) {
    if (millis() - last_reading_time > 500) {  // Read every 500ms
      last_reading_time = millis();

      if (raw_mode) {
        long raw_value = scale.read_average(5);
        Serial.print(F("Raw: "));
        Serial.println(raw_value);
      } else {
        float reading = scale.get_units(5);

        // Check for issues
        if (reading == 0 && last_valid_reading > 100) {
          consecutive_zeros++;
          Serial.print(F("WARNING: Zero reading ("));
          Serial.print(consecutive_zeros);
          Serial.println(F(" consecutive)"));
        } else if (reading < -1000 || reading > 1000) {
          Serial.print(F("ERROR: Out of range: "));
          Serial.println(reading);
          consecutive_errors++;
        } else {
          consecutive_zeros = 0;
          consecutive_errors = 0;
          last_valid_reading = reading;

          Serial.print(F("Weight: "));
          Serial.print(reading, 1);
          Serial.println(F(" lbs"));
        }

        // Auto-recovery attempt
        if (consecutive_zeros > 10 || consecutive_errors > 5) {
          Serial.println(F("Attempting recovery..."));
          reinitialize_scale();
        }
      }
    }
  }

  // Stability test mode
  if (stability_test) {
    performStabilityTest();
    stability_test = false;
  }
}

void processCommand(String cmd) {
  if (cmd.length() == 0) return;

  char command = cmd[0];

  switch (command) {
    case 'R':  // Read single value
      readSingleValue();
      break;

    case 'C':  // Toggle continuous mode
      continuous_mode = !continuous_mode;
      Serial.print(F("Continuous mode: "));
      Serial.println(continuous_mode ? F("ON") : F("OFF"));
      break;

    case 'T':  // Tare
      tareScale();
      break;

    case 'W':  // Toggle raw mode
      raw_mode = !raw_mode;
      Serial.print(F("Raw mode: "));
      Serial.println(raw_mode ? F("ON") : F("OFF"));
      break;

    case 'D':  // Toggle debug mode
      debug_mode = !debug_mode;
      Serial.print(F("Debug mode: "));
      Serial.println(debug_mode ? F("ON") : F("OFF"));
      break;

    case 'S':  // Stability test
      stability_test = true;
      break;

    case 'F':  // Set calibration factor
      setCalibrationFactor();
      break;

    case 'A':  // Auto-calibrate
      autoCalibrate();
      break;

    case 'I':  // Info
      showInfo();
      break;

    case 'X':  // Check connections
      checkConnections();
      break;

    case 'H':  // Help
      showHelp();
      break;

    default:
      Serial.println(F("Unknown command. Type 'H' for help"));
  }
}

void readSingleValue() {
  if (!scale_ready) {
    Serial.println(F("Scale not ready!"));
    return;
  }

  Serial.println(F("Reading..."));

  // Read raw value
  long raw = scale.read_average(10);

  // Read calibrated value
  float weight = scale.get_units(10);

  Serial.println(F("----------------------------------------"));
  Serial.print(F("Raw ADC Value:     "));
  Serial.println(raw);

  Serial.print(F("Calibrated Weight: "));
  Serial.print(weight, 2);
  Serial.println(F(" lbs"));

  Serial.print(F("Calibration Factor: "));
  Serial.println(calibration_factor);

  // Diagnose issues
  if (raw == 0 || raw == -1) {
    Serial.println(F("⚠ ERROR: No data from HX711"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - Loose connection"));
    Serial.println(F("  - Power issue"));
    Serial.println(F("  - Damaged HX711"));
  } else if (raw == 8388607 || raw == -8388608) {
    Serial.println(F("⚠ ERROR: HX711 saturated/overload"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - Load cell wiring issue"));
    Serial.println(F("  - Damaged load cell"));
    Serial.println(F("  - Wrong excitation voltage"));
  } else if (abs(raw) < 1000) {
    Serial.println(F("⚠ WARNING: Very low signal"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - Load cell not connected"));
    Serial.println(F("  - Wrong gain setting"));
  } else if (weight > 500 || weight < -500) {
    Serial.println(F("⚠ WARNING: Reading out of expected range"));
    Serial.println(F("  Try re-taring (T command)"));
  } else {
    Serial.println(F("✓ Reading appears normal"));
  }

  Serial.println(F("----------------------------------------"));
}

void tareScale() {
  if (!scale_ready) {
    Serial.println(F("Scale not ready!"));
    return;
  }

  Serial.println(F("Taring scale (remove all weight)..."));
  Serial.println(F("Taring in 3 seconds..."));
  delay(3000);

  scale.tare();

  Serial.println(F("✓ Tare complete"));

  // Verify tare worked
  delay(500);
  float check = scale.get_units(5);
  Serial.print(F("Verification reading: "));
  Serial.print(check, 2);
  Serial.println(F(" lbs"));

  if (abs(check) > 0.5) {
    Serial.println(F("⚠ WARNING: Tare may have failed"));
  }
}

void setCalibrationFactor() {
  Serial.print(F("Current calibration factor: "));
  Serial.println(calibration_factor);
  Serial.println(F("Enter new calibration factor:"));

  while (!Serial.available()) {
    delay(100);
  }

  float new_factor = Serial.parseFloat();

  if (new_factor != 0) {
    calibration_factor = new_factor;
    scale.set_scale(calibration_factor);
    Serial.print(F("✓ Calibration factor set to: "));
    Serial.println(calibration_factor);
  } else {
    Serial.println(F("Invalid factor"));
  }
}

void autoCalibrate() {
  Serial.println(F("========================================"));
  Serial.println(F("Auto-Calibration Procedure"));
  Serial.println(F("========================================"));
  Serial.println(F("Step 1: Remove all weight from scale"));
  Serial.println(F("Press any key when ready..."));

  while (!Serial.available()) {
    delay(100);
  }
  while (Serial.available()) Serial.read();  // Clear buffer

  Serial.println(F("Taring..."));
  scale.tare();
  delay(2000);

  Serial.println(F("Step 2: Place known weight on scale"));
  Serial.println(F("Enter the weight value (in lbs):"));

  while (!Serial.available()) {
    delay(100);
  }

  float known_weight = Serial.parseFloat();

  if (known_weight <= 0) {
    Serial.println(F("Invalid weight"));
    return;
  }

  Serial.print(F("Calibrating for "));
  Serial.print(known_weight);
  Serial.println(F(" lbs..."));

  delay(2000);

  // Get raw reading
  long raw_reading = scale.read_average(20);

  // Calculate calibration factor
  float new_factor = (float)raw_reading / known_weight;

  Serial.print(F("Raw reading: "));
  Serial.println(raw_reading);

  Serial.print(F("Calculated factor: "));
  Serial.println(new_factor);

  // Apply new factor
  calibration_factor = new_factor;
  scale.set_scale(calibration_factor);

  // Verify
  delay(500);
  float verify = scale.get_units(10);

  Serial.print(F("Verification reading: "));
  Serial.print(verify, 2);
  Serial.print(F(" lbs (should be "));
  Serial.print(known_weight);
  Serial.println(F(")"));

  float error = abs(verify - known_weight) / known_weight * 100;

  if (error < 5) {
    Serial.println(F("✓ Calibration successful!"));
    Serial.print(F("✓ New calibration factor: "));
    Serial.println(calibration_factor);
  } else {
    Serial.print(F("⚠ WARNING: "));
    Serial.print(error, 1);
    Serial.println(F("% error"));
  }

  Serial.println(F("========================================"));
}

void performStabilityTest() {
  if (!scale_ready) {
    Serial.println(F("Scale not ready!"));
    return;
  }

  Serial.println(F("========================================"));
  Serial.println(F("Stability Test (10 readings)"));
  Serial.println(F("========================================"));

  float readings[10];
  float sum = 0;
  float min_val = 999999;
  float max_val = -999999;

  for (int i = 0; i < 10; i++) {
    readings[i] = scale.get_units(5);
    sum += readings[i];

    if (readings[i] < min_val) min_val = readings[i];
    if (readings[i] > max_val) max_val = readings[i];

    Serial.print(F("Reading "));
    Serial.print(i + 1);
    Serial.print(F(": "));
    Serial.print(readings[i], 2);
    Serial.println(F(" lbs"));

    delay(500);
  }

  float average = sum / 10.0;
  float variance = 0;

  for (int i = 0; i < 10; i++) {
    variance += pow(readings[i] - average, 2);
  }
  variance /= 10.0;
  float std_dev = sqrt(variance);

  Serial.println(F("----------------------------------------"));
  Serial.print(F("Average:  "));
  Serial.print(average, 2);
  Serial.println(F(" lbs"));

  Serial.print(F("Std Dev:  "));
  Serial.print(std_dev, 3);
  Serial.println(F(" lbs"));

  Serial.print(F("Min:      "));
  Serial.print(min_val, 2);
  Serial.println(F(" lbs"));

  Serial.print(F("Max:      "));
  Serial.print(max_val, 2);
  Serial.println(F(" lbs"));

  Serial.print(F("Range:    "));
  Serial.print(max_val - min_val, 2);
  Serial.println(F(" lbs"));

  // Diagnose stability
  if (std_dev < 0.1) {
    Serial.println(F("✓ Excellent stability"));
  } else if (std_dev < 0.5) {
    Serial.println(F("✓ Good stability"));
  } else if (std_dev < 1.0) {
    Serial.println(F("⚠ Moderate stability - may need attention"));
  } else {
    Serial.println(F("✗ Poor stability - check connections"));
  }

  // Check for common issues
  if (min_val == 0 && max_val > 0) {
    Serial.println(F("⚠ Intermittent connection detected"));
  }

  if (abs(average) > 100 && min_val == 0) {
    Serial.println(F("⚠ Possible loose wire"));
  }

  Serial.println(F("========================================"));
}

void checkConnections() {
  Serial.println(F("========================================"));
  Serial.println(F("Connection Diagnostics"));
  Serial.println(F("========================================"));

  // Check if HX711 is responding
  Serial.print(F("HX711 Status: "));
  if (scale.is_ready()) {
    Serial.println(F("✓ Ready"));
  } else {
    Serial.println(F("✗ Not responding"));
    Serial.println(F("  Check: DOUT and SCK connections"));
  }

  // Check for data
  Serial.print(F("Data Test: "));
  long test_read = scale.read();

  if (test_read == 0) {
    Serial.println(F("✗ No data (0)"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - DOUT not connected"));
    Serial.println(F("  - HX711 not powered"));
  } else if (test_read == -1) {
    Serial.println(F("✗ Timeout"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - SCK not connected"));
    Serial.println(F("  - Wrong pin assignments"));
  } else if (test_read == 8388607 || test_read == -8388608) {
    Serial.println(F("⚠ Saturated/Overload"));
    Serial.println(F("  Possible causes:"));
    Serial.println(F("  - Load cell wires swapped"));
    Serial.println(F("  - Damaged load cell"));
  } else {
    Serial.println(F("✓ Receiving data"));
    Serial.print(F("  Raw value: "));
    Serial.println(test_read);
  }

  // Test multiple reads
  Serial.print(F("Consistency Test: "));
  bool consistent = true;
  long last_val = scale.read();

  for (int i = 0; i < 5; i++) {
    long val = scale.read();
    if (abs(val - last_val) > 10000) {
      consistent = false;
    }
    last_val = val;
    delay(100);
  }

  if (consistent) {
    Serial.println(F("✓ Stable readings"));
  } else {
    Serial.println(F("✗ Unstable readings"));
    Serial.println(F("  Check for loose connections"));
  }

  // Pin voltage test (basic)
  Serial.print(F("Pin States: "));
  Serial.print(F("DOUT="));
  Serial.print(digitalRead(LOADCELL_DOUT_PIN));
  Serial.print(F(", SCK="));
  Serial.println(digitalRead(LOADCELL_SCK_PIN));

  Serial.println(F("========================================"));
  Serial.println(F("Wiring Checklist:"));
  Serial.println(F("HX711 to Arduino:"));
  Serial.println(F("  □ VCC  -> 5V"));
  Serial.println(F("  □ GND  -> GND"));
  Serial.println(F("  □ DOUT -> Pin 7"));
  Serial.println(F("  □ SCK  -> Pin 6"));
  Serial.println(F("Load Cell to HX711:"));
  Serial.println(F("  □ RED   -> E+"));
  Serial.println(F("  □ BLACK -> E-"));
  Serial.println(F("  □ WHITE -> A-"));
  Serial.println(F("  □ GREEN -> A+"));
  Serial.println(F("========================================"));
}

void showInfo() {
  Serial.println(F("========================================"));
  Serial.println(F("Scale Information"));
  Serial.println(F("========================================"));

  Serial.print(F("HX711 Ready: "));
  Serial.println(scale.is_ready() ? F("Yes") : F("No"));

  Serial.print(F("Calibration Factor: "));
  Serial.println(calibration_factor);

  Serial.print(F("Current Reading: "));
  if (scale.is_ready()) {
    Serial.print(scale.get_units(5), 2);
    Serial.println(F(" lbs"));
  } else {
    Serial.println(F("N/A"));
  }

  Serial.print(F("Raw ADC Value: "));
  if (scale.is_ready()) {
    Serial.println(scale.read_average(5));
  } else {
    Serial.println(F("N/A"));
  }

  Serial.print(F("Tare Offset: "));
  Serial.println(scale.get_offset());

  Serial.print(F("Scale Factor: "));
  Serial.println(scale.get_scale());

  Serial.println(F("========================================"));
}

void reinitialize_scale() {
  Serial.println(F("Reinitializing scale..."));

  scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);
  delay(500);

  if (scale.is_ready()) {
    Serial.println(F("✓ Scale reconnected"));
    scale.set_scale(calibration_factor);
    scale.tare();
    scale_ready = true;
    consecutive_zeros = 0;
    consecutive_errors = 0;
  } else {
    Serial.println(F("✗ Failed to reconnect"));
    scale_ready = false;
  }
}

void showHelp() {
  Serial.println(F("========================================"));
  Serial.println(F("Available Commands:"));
  Serial.println(F("========================================"));
  Serial.println(F("Basic:"));
  Serial.println(F("  R - Read single weight value"));
  Serial.println(F("  C - Toggle continuous reading"));
  Serial.println(F("  T - Tare/zero the scale"));
  Serial.println(F(""));
  Serial.println(F("Diagnostics:"));
  Serial.println(F("  S - Stability test (10 readings)"));
  Serial.println(F("  X - Check connections"));
  Serial.println(F("  I - Show scale information"));
  Serial.println(F("  W - Toggle raw ADC value mode"));
  Serial.println(F("  D - Toggle debug mode"));
  Serial.println(F(""));
  Serial.println(F("Calibration:"));
  Serial.println(F("  F - Set calibration factor manually"));
  Serial.println(F("  A - Auto-calibrate with known weight"));
  Serial.println(F(""));
  Serial.println(F("  H - Show this help"));
  Serial.println(F("========================================"));
  Serial.println(F(""));
  Serial.println(F("Troubleshooting Tips:"));
  Serial.println(F("- If reading 1923.3 then 0:"));
  Serial.println(F("  1. Check all connections (use X)"));
  Serial.println(F("  2. Try re-taring (T)"));
  Serial.println(F("  3. Check power supply voltage"));
  Serial.println(F("- If readings unstable:"));
  Serial.println(F("  1. Run stability test (S)"));
  Serial.println(F("  2. Check for loose wires"));
  Serial.println(F("  3. Shield cables from interference"));
  Serial.println(F("========================================"));
}