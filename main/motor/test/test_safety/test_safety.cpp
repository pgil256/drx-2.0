// main/motor/test/test_safety/test_safety.cpp
#ifdef UNIT_TEST

#include <unity.h>
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
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    bRunning = false;
    measurePressure = false;
    jerking = false;
    _millis_value = 0;
}

void tearDown(void) {}

void test_emergency_stop_clears_all_state(void) {
    bRunning = true;
    measurePressure = true;
    jerking = true;
    jerksCompleted = 5;

    emergencyStop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_EQUAL(0, jerksCompleted);
}

void test_emergency_stop_sets_motor_speeds_to_zero(void) {
    emergencyStop();

    // Should have sent speed=0 to all 3 motor controllers
    // Each emergencyStop sets smcDeviceNumber and calls setMotorSpeed(0)
    // Wire should have received commands for devices 12, 13, 14
    bool found_12 = false, found_13 = false, found_14 = false;
    for (int i = 0; i < Wire.commandCount; i++) {
        if (Wire.commands[i].address == 12) found_12 = true;
        if (Wire.commands[i].address == 13) found_13 = true;
        if (Wire.commands[i].address == 14) found_14 = true;
    }
    TEST_ASSERT_TRUE(found_12);
    TEST_ASSERT_TRUE(found_13);
    TEST_ASSERT_TRUE(found_14);
}

void test_x_command_triggers_emergency_stop(void) {
    bRunning = true;
    processCommand("X");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
}

void test_commands_accepted_after_emergency_stop(void) {
    emergencyStop();

    // System should be recoverable - commands should still work
    Serial1.reset();
    processCommand("T");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK"));
}

void test_emergency_stop_during_jerking(void) {
    jerking = true;
    jerkDirection = 1;
    jerksCompleted = 3;

    emergencyStop();

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_EQUAL(0, jerksCompleted);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_emergency_stop_clears_all_state);
    RUN_TEST(test_emergency_stop_sets_motor_speeds_to_zero);
    RUN_TEST(test_x_command_triggers_emergency_stop);
    RUN_TEST(test_commands_accepted_after_emergency_stop);
    RUN_TEST(test_emergency_stop_during_jerking);

    return UNITY_END();
}

#endif // UNIT_TEST
