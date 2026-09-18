// development/tests/firmware/test_status/test_status.cpp
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

#include "../../../../runtime/arduino/motor/motor.ino"

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
    hostV2 = false;
    currentCmdSeq = -1;
    pressureFault = false; pressureCalibrated = false;
    pressureGuardActive = false; pressureSampleValid = false;
    pressurePollStarted = false; lastPressureSample = lastPressurePoll = 0;
    tareActive = false; bRunning = measurePressure = releasingPressure = false;
    scale._ready = true; scale._scale = 1; scale._offset = 0; scale._raw = 0;
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

static void assert_checksummed_report(const std::string &out) {
    size_t start = out.find("STATUS_START|S|");
    TEST_ASSERT_TRUE(start != std::string::npos);
    size_t end = out.find("|STATUS_END", start);
    TEST_ASSERT_TRUE(end != std::string::npos);
    end += std::string("|STATUS_END").length();
    unsigned char checksum = 0;
    for (size_t i = start; i < end; ++i) checksum ^= (unsigned char)out[i];
    char suffix[5];
    snprintf(suffix, sizeof(suffix), "*%02X", checksum);
    TEST_ASSERT_EQUAL_STRING(suffix, out.substr(end, 3).c_str());
    TEST_ASSERT_TRUE(out[end + 3] == '\r' || out[end + 3] == '\n');
}

void test_legacy_status_is_checksummed_without_v2_opt_in(void) {
    Wire.position_14 = 1940;
    sendStatus();
    TEST_ASSERT_FALSE(hostV2);
    assert_checksummed_report(Serial1.getOutput());
    TEST_ASSERT_TRUE(Serial1.outputContains("|1940|"));
}

void test_v2_status_keeps_same_checksum_format(void) {
    hostV2 = true;
    sendStatus();
    assert_checksummed_report(Serial1.getOutput());
}

void test_l6_uses_checksummed_status_format(void) {
    processCommand("L6");
    assert_checksummed_report(Serial1.getOutput());
    TEST_ASSERT_FALSE(Serial1.outputContains("A|1500|"));
}

// USB debug output is tee'd to the Pi as whole "LOG|<line>" frames on
// their own lines, never spliced into a status frame
void test_debug_lines_tee_to_serial1_as_log_frames(void) {
    sendStatus();
    std::string out = Serial1.getOutput();
    size_t log_at = out.find("LOG|status: ");
    TEST_ASSERT_TRUE(log_at != std::string::npos);
    TEST_ASSERT_TRUE(out.find(" 14: 1200") != std::string::npos);
    // The LOG| line is terminated before the status frame starts
    size_t status_at = out.find("STATUS_START|S|");
    TEST_ASSERT_TRUE(status_at != std::string::npos);
    TEST_ASSERT_TRUE(out.find((char)10, log_at) < status_at);
    // Nothing of the tee'd text lands inside the frame itself
    size_t frame_end = out.find("|STATUS_END", status_at);
    TEST_ASSERT_EQUAL(std::string::npos,
                      out.substr(status_at, frame_end - status_at).find("LOG|"));
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
    processCommand("L1|BASELINE");
    TEST_ASSERT_FALSE(Serial1.outputContains("DONE"));
    for (int i=0; i<10; ++i) { _millis_value += 100; servicePressure(); }
    TEST_ASSERT_TRUE(Serial1.outputContains("CALIBRATION|TARE|OK"));
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

void test_update_pressure_reports_first_valid_sample(void) {
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 20;
    updatePressure();
    updatePressure();
    updatePressure();
    TEST_ASSERT_FLOAT_WITHIN(0.01, 20.0, pressure);

    // The control loop must see the first fresh sample, without median lag.
    scale._raw = 5000;
    updatePressure();
    TEST_ASSERT_FLOAT_WITHIN(0.01, 5000.0, pressure);
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
    RUN_TEST(test_legacy_status_is_checksummed_without_v2_opt_in);
    RUN_TEST(test_v2_status_keeps_same_checksum_format);
    RUN_TEST(test_l6_uses_checksummed_status_format);
    RUN_TEST(test_debug_lines_tee_to_serial1_as_log_frames);
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
    RUN_TEST(test_update_pressure_reports_first_valid_sample);
    RUN_TEST(test_update_pressure_rejects_saturated_sample);
    RUN_TEST(test_update_pressure_skips_when_not_ready);

    return UNITY_END();
}

#endif // UNIT_TEST
