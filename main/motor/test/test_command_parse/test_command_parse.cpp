// main/motor/test/test_command_parse/test_command_parse.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../arduino_shim.h"
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
void delay(unsigned long ms) { _millis_value += ms; }  // advance mock clock

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
    releasingPressure = false;
    desiredPressure = 0;
    desiredPosition = 0;
    highFrequencyStatus = false;
    statusAcknowledged = true;
    isProcessingStatus = false;
    AZERO = 0;
    hostV2 = false;
    currentCmdSeq = -1;
    activeCmdSeq = -1;
    _millis_value = 0;
    jerkInterval = 200;  // mutable since Phase 3.5 (J<ms>); reset between tests
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

void test_P_busy_reply_when_running(void) {
    // Dropped commands must be visible to the host, never silent
    bRunning = true;
    processCommand("P50");
    TEST_ASSERT_TRUE(Serial1.outputContains("BUSY"));
}

void test_P_garbage_rejected(void) {
    processCommand("Pabc");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid P value"));
    TEST_ASSERT_FALSE(measurePressure);
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
    desiredPosition = 3;  // sentinel: must remain untouched
    processCommand("I121500");
    TEST_ASSERT_EQUAL(3, desiredPosition);  // unchanged
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

// J<ms> sets the pulse cadence and starts jerking (Phase 3.5 §15.2).
void test_J_with_interval_sets_interval(void) {
    processCommand("J500");
    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_EQUAL_UINT32(500, jerkInterval);
}

void test_J_bare_keeps_interval(void) {
    jerkInterval = 350;
    processCommand("J");
    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_EQUAL_UINT32(350, jerkInterval);
}

void test_J_interval_below_min_ignored(void) {
    processCommand("J50");
    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_EQUAL_UINT32(200, jerkInterval);
}

void test_J_interval_above_max_ignored(void) {
    processCommand("J99999");
    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_EQUAL_UINT32(200, jerkInterval);
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

// --- Input rejection (corrupt commands must not move anything) ---

void test_A_negative_inches_rejected(void) {
    // A corrupted negative value used to wrap through uint16_t to a
    // huge number and get clamped to FULL EXTENSION
    Wire.position_12 = 1000;
    processCommand("A12-1.0");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: A value out of range"));
    TEST_ASSERT_FALSE(bRunning);
}

void test_A_overrange_inches_rejected(void) {
    processCommand("A1220.0");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: A value out of range"));
    TEST_ASSERT_FALSE(bRunning);
}

void test_A_garbage_rejected(void) {
    processCommand("A12xyz");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid A value"));
    TEST_ASSERT_FALSE(bRunning);
}

void test_I_invalid_device_rejected(void) {
    processCommand("I991000");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid device"));
    TEST_ASSERT_FALSE(bRunning);
}

void test_K_garbage_rejected(void) {
    // toInt() garbage used to become 0 and drive the lateral actuator
    // to its clamp floor (position 500)
    Wire.position_14 = 1200;
    processCommand("Kabc");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid K value"));
    TEST_ASSERT_FALSE(bRunning);
}

void test_I_busy_replies_busy(void) {
    bRunning = true;
    processCommand("I121500");
    TEST_ASSERT_TRUE(Serial1.outputContains("BUSY"));
}

// --- Symmetric deadband ---

void test_I_within_deadband_completes_immediately(void) {
    Wire.position_12 = 1500;
    processCommand("I121510");  // 10 counts away: inside the band
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_K_within_deadband_completes_immediately(void) {
    Wire.position_14 = 1500;
    processCommand("K1490");  // small backward move: also in the band now
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// --- Protocol v2 framing (function level) ---

static String makeFrame(int seq, const char *cmd) {
    String body = String(seq);
    body += ":";
    body += cmd;
    char buf[64];
    snprintf(buf, sizeof(buf), "#%s*%02X", body.c_str(),
             xorChecksum(body, 0, body.length()));
    return String(buf);
}

void test_v2_parse_valid_frame(void) {
    String inner = "";
    String frame = makeFrame(42, "P50");
    TEST_ASSERT_TRUE(parseV2Frame(frame, inner));
    TEST_ASSERT_TRUE(inner == "P50");
    TEST_ASSERT_EQUAL(42, (int)currentCmdSeq);
    TEST_ASSERT_TRUE(hostV2);
    currentCmdSeq = -1;
}

void test_v2_rejects_corrupt_checksum(void) {
    String inner = "UNTOUCHED";
    // Valid frame for "P10" but flip a payload digit -> "P70"
    String frame = makeFrame(7, "P10");
    int colon = frame.indexOf(':');
    String corrupted = frame.substring(0, colon + 2);
    corrupted += "7";
    corrupted += frame.substring(colon + 3);
    TEST_ASSERT_FALSE(parseV2Frame(corrupted, inner));
    TEST_ASSERT_TRUE(inner == "UNTOUCHED");
    TEST_ASSERT_EQUAL(-1, (int)currentCmdSeq);
    TEST_ASSERT_TRUE(Serial1.outputContains("Checksum mismatch"));
}

void test_v2_emitAck_formats(void) {
    emitAck("DONE", 13);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE|13"));
    Serial1.reset();
    emitAck("DONE", -1);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
    TEST_ASSERT_FALSE(Serial1.outputContains("DONE|"));
}

void test_v2_emitCmdError_formats(void) {
    currentCmdSeq = 21;
    emitCmdError("Invalid P value");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERR|21|Invalid P value"));
    currentCmdSeq = -1;
    Serial1.reset();
    emitCmdError("Invalid P value");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid P value"));
}

void test_v2_emergency_buffer_detection(void) {
    TEST_ASSERT_TRUE(isEmergencyBuffer(String("X")));
    TEST_ASSERT_TRUE(isEmergencyBuffer(makeFrame(5, "X")));
    TEST_ASSERT_FALSE(isEmergencyBuffer(String("K1500")));
    TEST_ASSERT_FALSE(isEmergencyBuffer(makeFrame(5, "K1500")));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_T_responds_OK);
    RUN_TEST(test_P_sets_desired_pressure);
    RUN_TEST(test_P_ignored_when_running);
    RUN_TEST(test_P_busy_reply_when_running);
    RUN_TEST(test_P_garbage_rejected);
    RUN_TEST(test_I_sets_position);
    RUN_TEST(test_I_ignored_when_running);
    RUN_TEST(test_K_sets_c_position);
    RUN_TEST(test_J_starts_jerking);
    RUN_TEST(test_JS_stops_jerking);
    RUN_TEST(test_J_with_interval_sets_interval);
    RUN_TEST(test_J_bare_keeps_interval);
    RUN_TEST(test_J_interval_below_min_ignored);
    RUN_TEST(test_J_interval_above_max_ignored);
    RUN_TEST(test_HF1_enables);
    RUN_TEST(test_HF0_disables);
    RUN_TEST(test_X_stops_everything);
    RUN_TEST(test_long_command_rejected);
    RUN_TEST(test_A_negative_inches_rejected);
    RUN_TEST(test_A_overrange_inches_rejected);
    RUN_TEST(test_A_garbage_rejected);
    RUN_TEST(test_I_invalid_device_rejected);
    RUN_TEST(test_K_garbage_rejected);
    RUN_TEST(test_I_busy_replies_busy);
    RUN_TEST(test_I_within_deadband_completes_immediately);
    RUN_TEST(test_K_within_deadband_completes_immediately);
    RUN_TEST(test_v2_parse_valid_frame);
    RUN_TEST(test_v2_rejects_corrupt_checksum);
    RUN_TEST(test_v2_emitAck_formats);
    RUN_TEST(test_v2_emitCmdError_formats);
    RUN_TEST(test_v2_emergency_buffer_detection);

    return UNITY_END();
}

#endif // UNIT_TEST
