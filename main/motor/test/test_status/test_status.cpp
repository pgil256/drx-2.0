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
void delay(unsigned long ms) { _millis_value += ms; }  // advance mock clock

#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    Wire.position_12 = 1500;
    Wire.position_13 = 2000;
    Wire.position_14 = 1200;
    scale.setUnits(45.3);
    isProcessingStatus = false;
    statusAcknowledged = true;
    highFrequencyStatus = false;
    jerking = false;
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

void test_status_sent_while_jerking(void) {
    // Pulsing used to set noStatus and blind both the Pi and the
    // pressure ceiling check for the whole pulse phase; status must
    // keep flowing now
    jerking = true;
    bool sent = sendStatus();
    TEST_ASSERT_TRUE(sent);
    TEST_ASSERT_TRUE(Serial1.outputContains("STATUS_START"));
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

void test_l5_legacy_four_digit_corruption_documented(void) {
    // The legacy fixed-width format cannot carry a 4-digit AZERO; the
    // delimited form below is the fix. This documents the constraint.
    processCommand("L5160 1900");
    TEST_ASSERT_EQUAL(160, AZERO);
    TEST_ASSERT_EQUAL(190, BZERO);  // truncated! use delimited form
}

void test_l5_delimited_zero_marks(void) {
    processCommand("L5|160|1900");
    TEST_ASSERT_EQUAL(160, AZERO);
    TEST_ASSERT_EQUAL(1900, BZERO);
    TEST_ASSERT_TRUE(Serial1.outputContains("ZEROS|160|1900"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_update_pressure_median_filters_spike(void) {
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 20;
    updatePressure();
    updatePressure();
    updatePressure();
    TEST_ASSERT_FLOAT_WITHIN(0.01, 20.0, pressure);

    // One spike sample cannot move the median
    scale._raw = 5000;
    updatePressure();
    TEST_ASSERT_FLOAT_WITHIN(0.01, 20.0, pressure);
}

void test_update_pressure_rejects_saturated_sample(void) {
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 20;
    updatePressure();
    updatePressure();
    updatePressure();

    // A saturated ADC reading (the documented 1923-lbs spike symptom)
    // must be discarded entirely
    scale._raw = 8388607L;
    updatePressure();
    updatePressure();
    TEST_ASSERT_FLOAT_WITHIN(0.01, 20.0, pressure);
}

void test_update_pressure_skips_when_not_ready(void) {
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 20;
    updatePressure();
    unsigned long readyBefore = lastScaleReady;

    scale._ready = false;
    _millis_value += 1000;
    updatePressure();
    TEST_ASSERT_EQUAL(readyBefore, lastScaleReady);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_status_format);
    RUN_TEST(test_status_sent_while_jerking);
    RUN_TEST(test_status_skipped_when_processing);
    RUN_TEST(test_q_acknowledges_status);
    RUN_TEST(test_s_command_triggers_status);
    RUN_TEST(test_calibration_l0_sends_done);
    RUN_TEST(test_calibration_l1_tare);
    RUN_TEST(test_calibration_l4_weight);
    RUN_TEST(test_calibration_l5_zero_marks);
    RUN_TEST(test_l5_legacy_four_digit_corruption_documented);
    RUN_TEST(test_l5_delimited_zero_marks);
    RUN_TEST(test_update_pressure_median_filters_spike);
    RUN_TEST(test_update_pressure_rejects_saturated_sample);
    RUN_TEST(test_update_pressure_skips_when_not_ready);

    return UNITY_END();
}

#endif // UNIT_TEST
