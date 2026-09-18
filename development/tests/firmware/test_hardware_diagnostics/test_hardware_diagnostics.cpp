#ifdef UNIT_TEST
#include <unity.h>
#include "../arduino_shim.h"
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

MockWire Wire;
MockSerial Serial, Serial1;
unsigned long now = 0;
unsigned long millis() { return now; }
void delay(unsigned long ms) { now += ms; }
#include "../../../../runtime/arduino/motor/motor.ino"

void setUp() {
    pressureFault = false;
    emergencyStop();
    Serial.reset(); Serial1.reset(); Wire.reset(); now = 0;
    Wire.position_12 = 1000; Wire.position_13 = 1900; Wire.position_14 = 1500;
    smcDeviceNumber = 13; positionReadValid = false;
    lastGoodPosition[0] = 123; lastGoodPosition[1] = 234; lastGoodPosition[2] = 345;
    pressureCalibrated = false; pressureGuardActive = false; pressureSampleValid = false;
    pressurePollStarted = false; lastPressurePoll = lastPressureSample = 0;
    tareActive = false; pressureDonePending = false;
    scale._ready = false; scale._scale = 1; scale._offset = 0; scale._raw = 0;
    STOP = true; _pin_levels[STOP_PIN] = HIGH;
    _pin_levels[DIR_FIT_FORWARD] = _pin_levels[DIR_FIT_REVERSE] = LOW;
    currentCmdSeq = activeCmdSeq = activeFitCmdSeq = -1; hostV2 = false;
    isProcessingStatus = false;
}

void tearDown() {}

void assert_read_only() {
    for (int i = 0; i < Wire.commandCount; ++i) {
        const WireCommand &command = Wire.commands[i];
        TEST_ASSERT_EQUAL(2, command.dataLen);
        TEST_ASSERT_EQUAL(0xA1, command.data[0]);
        TEST_ASSERT_EQUAL(12, command.data[1]);
    }
    TEST_ASSERT_FALSE(bRunning || measurePressure || jerking || moveFITForward);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_REVERSE]);
}

void test_probe_reads_all_feedback_without_motion_or_legacy_ack() {
    processCommand("D");
    TEST_ASSERT_EQUAL_STRING("DIAG|HARDWARE|1|1|1|0|0\n", Serial1.getOutput().c_str());
    TEST_ASSERT_EQUAL(3, Wire.commandCount);
    TEST_ASSERT_EQUAL(13, smcDeviceNumber);
    TEST_ASSERT_FALSE(positionReadValid);
    assert_read_only();
}

void test_failed_fresh_read_never_uses_cached_health() {
    Wire.failTransmissions = 2;
    processCommand("D");
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|0|1|1|0|0"));
    TEST_ASSERT_EQUAL(123, lastGoodPosition[0]);
    assert_read_only();
}

void test_retry_recovers_transient_i2c_failure() {
    Wire.failTransmissions = 1;
    processCommand("D");
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|1|1|0|0"));
    TEST_ASSERT_EQUAL(4, Wire.commandCount);
    assert_read_only();
}

void test_invalid_feedback_is_reported_for_its_own_axis() {
    Wire.position_13 = 4096;
    Wire.position_14 = 65535;
    processCommand("D");
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|0|0|0|0"));
    assert_read_only();
}

void test_stop_is_sampled_from_pin_even_before_cached_state_updates() {
    _pin_levels[STOP_PIN] = LOW;
    processCommand("D");
    TEST_ASSERT_TRUE(STOP);
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|1|1|1|0"));
    assert_read_only();
}

void test_probe_is_available_with_latched_fault_without_clearing_it() {
    pressureFault = true;
    processCommand("D");
    TEST_ASSERT_TRUE(pressureFault);
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|1|1|0|0"));
    assert_read_only();
}

void test_fit_active_reports_output_pin_without_changing_it() {
    _pin_levels[DIR_FIT_REVERSE] = HIGH;
    processCommand("D");
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|1|1|0|1"));
    TEST_ASSERT_EQUAL(HIGH, _pin_levels[DIR_FIT_REVERSE]);
    TEST_ASSERT_FALSE(moveFITForward);
}

void test_pressure_fault_during_probe_stops_motion_and_keeps_axis_identity() {
    pressureCalibrated = true;
    scale._ready = true; scale._raw = 101;
    Wire.position_12 = 5000;  // Invalid axial feedback, valid C feedback.
    bRunning = moveFITForward = true;
    _pin_levels[DIR_FIT_FORWARD] = HIGH;
    processCommand("D");
    TEST_ASSERT_TRUE(pressureFault);
    TEST_ASSERT_FALSE(bRunning || moveFITForward);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_TRUE(Serial1.outputContains("FAULT|PRESSURE_LIMIT"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|0|1|1|0|0"));
}

void test_v2_probe_retains_framing_and_returns_its_own_sequence() {
    String body = "731:D";
    char suffix[5];
    snprintf(suffix, sizeof(suffix), "*%02X", xorChecksum(body, 0, body.length()));
    String frame = "#"; frame += body; frame += suffix;
    String inner;
    TEST_ASSERT_TRUE(parseV2Frame(frame, inner));
    processCommand(inner);
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|HARDWARE|1|1|1|0|0\nOK|731\n"));
    assert_read_only();
}

void test_probe_rejects_parameters() {
    processCommand("D1");
    TEST_ASSERT_FALSE(Serial1.outputContains("DIAG|HARDWARE"));
    TEST_ASSERT_TRUE(Serial1.outputContains("Invalid D diagnostics"));
    TEST_ASSERT_EQUAL(0, Wire.commandCount);
    assert_read_only();
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_probe_reads_all_feedback_without_motion_or_legacy_ack);
    RUN_TEST(test_failed_fresh_read_never_uses_cached_health);
    RUN_TEST(test_retry_recovers_transient_i2c_failure);
    RUN_TEST(test_invalid_feedback_is_reported_for_its_own_axis);
    RUN_TEST(test_stop_is_sampled_from_pin_even_before_cached_state_updates);
    RUN_TEST(test_probe_is_available_with_latched_fault_without_clearing_it);
    RUN_TEST(test_fit_active_reports_output_pin_without_changing_it);
    RUN_TEST(test_pressure_fault_during_probe_stops_motion_and_keeps_axis_identity);
    RUN_TEST(test_v2_probe_retains_framing_and_returns_its_own_sequence);
    RUN_TEST(test_probe_rejects_parameters);
    return UNITY_END();
}
#endif
