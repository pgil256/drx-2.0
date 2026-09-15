#ifdef UNIT_TEST
#include <unity.h>
#include "../arduino_shim.h"
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

MockWire Wire;
MockSerial Serial;
MockSerial Serial1;
unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) { _millis_value += ms; }
#include "../../motor.ino"

void setUp(void) {
    emergencyStop();
    Serial.reset(); Serial1.reset(); Wire.reset();
    _millis_value = 0;
    releasingPressure = false;
    STOP = true; stopWasPressed = false;
    _pin_levels[STOP_PIN] = HIGH;
    isProcessingStatus = false; statusAcknowledged = true;
    currentCmdSeq = -1; activeCmdSeq = -1;
    pressure = 0; signedPressure = 0; desiredPressure = 0; AZERO = 0;
    Wire.position_12 = 1000; Wire.position_13 = 1000; Wire.position_14 = 1000;
    scale._ready = true; scale._scale = 1; scale._offset = 0; scale._raw = 0;
    pressureSampleCount = 0; pressureSampleIndex = 0;
    lastHostTraffic = 0; lastScaleReady = 0;
    commandBuffer = ""; isCommandComplete = false;
    jerkInterval = 500;
}
void tearDown(void) {}

int lastSpeed(uint8_t device) {
    for (int i = Wire.commandCount - 1; i >= 0; --i) {
        WireCommand &cmd = Wire.commands[i];
        if (cmd.address == device && cmd.dataLen == 3 &&
            (cmd.data[0] == 0x85 || cmd.data[0] == 0x86)) {
            int speed = cmd.data[1] + (cmd.data[2] << 5);
            return cmd.data[0] == 0x86 ? -speed : speed;
        }
    }
    return -9999;
}

void test_configuration_does_not_start_motion(void) {
    processCommand("V75,90,60");
    TEST_ASSERT_EQUAL(1200, axialSpeed);
    TEST_ASSERT_EQUAL(1440, lateralSpeed);
    TEST_ASSERT_EQUAL(960, pulseSpeed);
    TEST_ASSERT_EQUAL(0, Wire.commandCount);
    TEST_ASSERT_FALSE(bRunning); TEST_ASSERT_FALSE(measurePressure); TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(Serial1.outputContains("SPEED|75|90|60"));
    TEST_ASSERT_FALSE(Serial1.outputContains("DONE"));
}

void test_invalid_configuration_is_atomic(void) {
    const char *bad[] = {"V", "V75,50", "V75,50,49", "V101,50,100", "V75,50,100,60",
                         "V75.5,50,100", "V-75,50,100", "V75,,100", "V75,50,100junk",
                         "V9999999999999999999999999,50,100"};
    for (auto cmd : bad) {
        Serial1.reset();
        processCommand(cmd);
        TEST_ASSERT_TRUE(Serial1.outputContains("Invalid V speeds"));
        TEST_ASSERT_EQUAL(800, axialSpeed);
        TEST_ASSERT_EQUAL(800, lateralSpeed);
        TEST_ASSERT_EQUAL(1600, pulseSpeed);
    }
}

void test_position_and_pressure_use_independent_speeds(void) {
    processCommand("V75,90,60");
    processCommand("I121600");
    TEST_ASSERT_EQUAL(1200, lastSpeed(12));
    bRunning = false;
    processCommand("A121");
    TEST_ASSERT_EQUAL(-1200, lastSpeed(12));
    bRunning = false;
    processCommand("I131600");
    TEST_ASSERT_EQUAL(800, lastSpeed(13));
    bRunning = false;
    processCommand("K1800");
    TEST_ASSERT_EQUAL(1440, lastSpeed(14));
    bRunning = false;
    processCommand("I141800");
    TEST_ASSERT_EQUAL(1440, lastSpeed(14));
    bRunning = false;
    processCommand("P40");
    TEST_ASSERT_EQUAL(1200, lastSpeed(12));
}

void test_pulse_output_changes_without_changing_cadence(void) {
    processCommand("V75,90,60");
    processCommand("J500");
    _millis_value = 500;
    loop();
    TEST_ASSERT_EQUAL(960, lastSpeed(12));
    TEST_ASSERT_EQUAL(500, jerkInterval);
    _millis_value = 1000;
    loop();
    TEST_ASSERT_EQUAL(-960, lastSpeed(12));
}

void test_release_and_stop_keep_fixed_behavior(void) {
    processCommand("V100,100,50");
    pressure = 40;
    processCommand("P0");
    TEST_ASSERT_EQUAL(-800, lastSpeed(12));
    processCommand("X");
    TEST_ASSERT_EQUAL(0, lastSpeed(12));
    TEST_ASSERT_EQUAL(0, lastSpeed(14));
    TEST_ASSERT_EQUAL(800, axialSpeed);
    TEST_ASSERT_EQUAL(800, lateralSpeed);
    TEST_ASSERT_EQUAL(1600, pulseSpeed);
}

void test_v2_configuration_has_correlated_ack(void) {
    currentCmdSeq = 42;
    processCommand("V50,50,100");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK|42"));
    TEST_ASSERT_FALSE(Serial1.outputContains("SPEED|"));
}

void test_configuration_refused_during_axial_motion(void) {
    measurePressure = true;
    processCommand("V100,100,50");
    TEST_ASSERT_TRUE(Serial1.outputContains("BUSY"));
    TEST_ASSERT_EQUAL(800, axialSpeed);
    measurePressure = false; jerking = true;
    processCommand("V100,100,50");
    TEST_ASSERT_EQUAL(1600, pulseSpeed);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_configuration_does_not_start_motion);
    RUN_TEST(test_invalid_configuration_is_atomic);
    RUN_TEST(test_position_and_pressure_use_independent_speeds);
    RUN_TEST(test_pulse_output_changes_without_changing_cadence);
    RUN_TEST(test_release_and_stop_keep_fixed_behavior);
    RUN_TEST(test_v2_configuration_has_correlated_ack);
    RUN_TEST(test_configuration_refused_during_axial_motion);
    return UNITY_END();
}
#endif
