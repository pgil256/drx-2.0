// main/motor/test/test_status/test_status.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../arduino_shim.h"
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

MockWire Wire;
MockSerial Serial;
MockSerial Serial1;
// Note: HX711 scale is declared in motor.ino

unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) { _millis_value += ms; }  // advance mock clock (firmware timeout loops spin on millis())

#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    Wire.position_12 = 1500;
    Wire.position_13 = 2000;
    Wire.position_14 = 1200;
    scale.setUnits(45.3);
    noStatus = false;
    isProcessingStatus = false;
    statusAcknowledged = true;
    highFrequencyStatus = false;
    _millis_value = 0;
}

void tearDown(void) {}

void test_status_format(void) {
    sendStatus();
    std::string out = Serial1.getOutput();
    TEST_ASSERT_TRUE(out.find("STATUS_START|S|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|STATUS_END") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|1500|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|2000|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|1200|") != std::string::npos);
}

void test_status_skipped_when_nostatus(void) {
    noStatus = true;
    bool sent = sendStatus();
    TEST_ASSERT_FALSE(sent);
}

void test_status_skipped_when_processing(void) {
    isProcessingStatus = true;
    bool sent = sendStatus();
    TEST_ASSERT_FALSE(sent);
}

void test_q_acknowledges_status(void) {
    statusAcknowledged = false;
    processCommand("Q");
    TEST_ASSERT_TRUE(statusAcknowledged);
}

void test_s_command_triggers_status(void) {
    processCommand("S");
    std::string out = Serial1.getOutput();
    TEST_ASSERT_TRUE(out.find("STATUS_START") != std::string::npos);
}

void test_calibration_l0_sends_done(void) {
    processCommand("L0-4360.14");
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_calibration_l1_tare(void) {
    processCommand("L1");
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_calibration_l4_weight(void) {
    scale.setUnits(32.1);
    processCommand("L4");
    TEST_ASSERT_TRUE(Serial1.outputContains("weight|"));
}

void test_calibration_l5_zero_marks(void) {
    processCommand("L5100 200");
    TEST_ASSERT_EQUAL(100, AZERO);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_status_format);
    RUN_TEST(test_status_skipped_when_nostatus);
    RUN_TEST(test_status_skipped_when_processing);
    RUN_TEST(test_q_acknowledges_status);
    RUN_TEST(test_s_command_triggers_status);
    RUN_TEST(test_calibration_l0_sends_done);
    RUN_TEST(test_calibration_l1_tare);
    RUN_TEST(test_calibration_l4_weight);
    RUN_TEST(test_calibration_l5_zero_marks);

    return UNITY_END();
}

#endif // UNIT_TEST
