// main/motor/test/test_command_parse/test_command_parse.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

// Instantiate mock globals
MockWire Wire;
MockSerial Serial;
MockSerial Serial1;

// Provide stubs for Arduino functions used in motor.ino
unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) {}

// Include the main firmware
// (processCommand and related functions will be available)
#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    bRunning = false;
    measurePressure = false;
    jerking = false;
    desiredPressure = 0;
    desiredPosition = 0;
    highFrequencyStatus = false;
    _millis_value = 0;
}

void tearDown(void) {}

// --- Test command ---
void test_T_responds_OK(void) {
    processCommand("T");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK"));
}

// --- Pressure command ---
void test_P_sets_desired_pressure(void) {
    processCommand("P50");
    TEST_ASSERT_EQUAL_FLOAT(50.0, desiredPressure);
    TEST_ASSERT_TRUE(measurePressure);
}

void test_P_ignored_when_running(void) {
    bRunning = true;
    processCommand("P50");
    TEST_ASSERT_EQUAL_FLOAT(0.0, desiredPressure);
}

// --- Position command ---
void test_I_sets_position(void) {
    Wire.position_12 = 100;
    processCommand("I121500");
    TEST_ASSERT_EQUAL(1500, desiredPosition);
    TEST_ASSERT_TRUE(bRunning);
}

void test_I_ignored_when_running(void) {
    bRunning = true;
    processCommand("I121500");
    TEST_ASSERT_EQUAL(3, desiredPosition);  // unchanged from default
}

// --- K command (lateral) ---
void test_K_sets_c_position(void) {
    Wire.position_14 = 1000;
    processCommand("K1800");
    TEST_ASSERT_EQUAL(14, smcDeviceNumber);
    TEST_ASSERT_EQUAL(1800, desiredPosition);
    TEST_ASSERT_TRUE(bRunning);
}

// --- Jerk commands ---
void test_J_starts_jerking(void) {
    processCommand("J");
    TEST_ASSERT_TRUE(jerking);
}

void test_JS_stops_jerking(void) {
    jerking = true;
    processCommand("JS");
    TEST_ASSERT_FALSE(jerking);
}

// --- High frequency status ---
void test_HF1_enables(void) {
    processCommand("HF1");
    TEST_ASSERT_TRUE(highFrequencyStatus);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_HF0_disables(void) {
    highFrequencyStatus = true;
    processCommand("HF0");
    TEST_ASSERT_FALSE(highFrequencyStatus);
}

// --- Emergency stop ---
void test_X_stops_everything(void) {
    bRunning = true;
    measurePressure = true;
    jerking = true;
    processCommand("X");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// --- Buffer overflow protection ---
void test_long_command_rejected(void) {
    // Create a command longer than MAX_COMMAND_LENGTH
    char longCmd[150];
    memset(longCmd, 'A', 149);
    longCmd[149] = '\0';
    processCommand(String(longCmd));
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR"));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_T_responds_OK);
    RUN_TEST(test_P_sets_desired_pressure);
    RUN_TEST(test_P_ignored_when_running);
    RUN_TEST(test_I_sets_position);
    RUN_TEST(test_I_ignored_when_running);
    RUN_TEST(test_K_sets_c_position);
    RUN_TEST(test_J_starts_jerking);
    RUN_TEST(test_JS_stops_jerking);
    RUN_TEST(test_HF1_enables);
    RUN_TEST(test_HF0_disables);
    RUN_TEST(test_X_stops_everything);
    RUN_TEST(test_long_command_rejected);

    return UNITY_END();
}

#endif // UNIT_TEST
