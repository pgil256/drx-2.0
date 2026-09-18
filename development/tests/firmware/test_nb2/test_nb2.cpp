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
    pressureFault = false; emergencyStop();
    Serial.reset(); Serial1.reset(); Wire.reset(); now = 0;
    pressureCalibrated = true; pressureSampleValid = true;
    pressurePollStarted = false; lastPressurePoll = lastPressureSample = 0;
    maxPressurePollGap = 0; tareActive = false; tareCount = 0;
    pressureDonePending = false; pressureProgressNotified = false;
    scale._ready = true; scale._scale = 100; scale._offset = 0; scale._raw = 0;
    desiredPressure = pressure = 0; pressureCeiling = 100; protocolPressureLimit = 0;
    AZERO = 100; BZERO = 1900;
    STOP = true; stopWasPressed = false; _pin_levels[STOP_PIN] = HIGH;
    Wire.position_12 = 1000; Wire.position_13 = 1900; Wire.position_14 = 1500;
    commandBuffer = ""; isCommandComplete = false;
    highFrequencyStatus = false; isProcessingStatus = false; statusAcknowledged = true;
    lastStatusTime = lastActiveStatus = loopPosition = 0; timeSinceLastStatus = 0;
    lastHostTraffic = lastScaleReady = 0; currentCmdSeq = activeCmdSeq = -1;
    jerkInterval = 200; pulseMotorSpeed = 0;
}
void tearDown() {}
void sample(float value) { scale.setRawForUnits(value); servicePressure(); }
void tick(unsigned long ms=100) { now += ms; lastHostTraffic = now; loop(); }
int speed(uint8_t device) {
    for (int i=Wire.commandCount-1; i>=0; --i) {
        auto &c = Wire.commands[i];
        if (c.address == device && c.dataLen == 3 && (c.data[0]==0x85 || c.data[0]==0x86)) {
            int value = c.data[1] + (c.data[2]<<5);
            return c.data[0]==0x86 ? -value : value;
        }
    }
    return 0;
}
void stopped() {
    TEST_ASSERT_FALSE(bRunning || measurePressure || jerking || moveFITForward);
    TEST_ASSERT_EQUAL(0, speed(12)); TEST_ASSERT_EQUAL(0, speed(13));
    TEST_ASSERT_EQUAL(0, speed(14));
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_REVERSE]);
}
void test_l0_changes_factor_without_taring() {
    scale._offset = 222; sample(5);
    processCommand("L0-28369");
    TEST_ASSERT_EQUAL(222, scale.get_offset());
    TEST_ASSERT_FALSE(pressureCalibrated || tareActive);
    TEST_ASSERT_TRUE(Serial1.outputContains("CALIBRATION|SET|-28369"));
    processCommand("P40");
    TEST_ASSERT_TRUE(Serial1.outputContains("TARE_REQUIRED"));
}
void test_stable_resting_load_requires_ten_samples_and_900ms() {
    scale._raw = 1234; processCommand("L1|BASELINE");
    TEST_ASSERT_TRUE(tareActive); TEST_ASSERT_FALSE(pressureCalibrated);
    for (int i=0; i<9; ++i) { servicePressure(); now += 100; }
    TEST_ASSERT_FALSE(Serial1.outputContains("TARE|OK"));
    servicePressure();
    TEST_ASSERT_FALSE(tareActive); TEST_ASSERT_TRUE(pressureCalibrated);
    TEST_ASSERT_EQUAL(1234, scale.get_offset());
    TEST_ASSERT_EQUAL_FLOAT(0, pressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("TARE|OK|1234|100"));
    stopped();
}
void test_unstable_tare_has_fixed_eight_second_deadline() {
    scale._offset = 321; processCommand("L1|BASELINE");
    for (int i=0; i<80; ++i) { scale._raw = (i%2)*100; now += 100; servicePressure(); }
    TEST_ASSERT_FALSE(tareActive || pressureCalibrated);
    TEST_ASSERT_EQUAL(321, scale.get_offset());
    TEST_ASSERT_TRUE(Serial1.outputContains("TARE|REJECTED|UNSTABLE"));
}
void test_gap_resets_candidate_without_extending_tare_deadline() {
    processCommand("L1|BASELINE");
    for (int i=0; i<5; ++i) { now += 100; servicePressure(); }
    now += 600; servicePressure();
    TEST_ASSERT_EQUAL(1, tareCount);
    TEST_ASSERT_EQUAL(0, tareStarted);
    TEST_ASSERT_FALSE(pressureCalibrated);
}
void test_tare_is_rejected_while_fit_is_active() {
    moveFITForward = true; processCommand("L1|BASELINE");
    TEST_ASSERT_FALSE(tareActive || pressureCalibrated);
    TEST_ASSERT_TRUE(Serial1.outputContains("TARE|REJECTED|"));
}
void test_stop_cancels_tare_without_committing() {
    scale._offset = 321; processCommand("L1|BASELINE");
    for (int i=0; i<5; ++i) { now += 100; servicePressure(); }
    processCommand("X"); now += 1000; servicePressure();
    TEST_ASSERT_FALSE(tareActive || pressureCalibrated);
    TEST_ASSERT_EQUAL(321, scale.get_offset());
    TEST_ASSERT_TRUE(Serial1.outputContains("TARE|CANCELLED|STOP"));
}
void test_sensor_loss_trips_after_500ms_even_during_static_hold() {
    sample(40); processCommand("P40"); scale._ready = false;
    tick(500); TEST_ASSERT_FALSE(pressureFault);
    tick(1); TEST_ASSERT_TRUE(pressureFault); stopped();
    TEST_ASSERT_TRUE(Serial1.outputContains("PRESSURE_SENSOR_TIMEOUT"));
}
void test_fresh_sample_does_not_hide_a_service_gap() {
    sample(40); processCommand("P40"); now += 501; sample(40);
    TEST_ASSERT_TRUE(pressureFault); stopped();
}
void test_invalid_sample_stops_all_axes_and_fit() {
    sample(40); processCommand("P40");
    bRunning = moveFITForward = true;
    _pin_levels[DIR_FIT_FORWARD] = HIGH;
    scale._raw = 8388607; servicePressure();
    TEST_ASSERT_TRUE(pressureFault); stopped();
    TEST_ASSERT_TRUE(Serial1.outputContains("PRESSURE_INVALID"));
}
void test_repeated_pressure_command_does_not_extend_deadline() {
    processCommand("P40");
    for (int i=0; i<10; ++i) tick();
    processCommand("P40");
    TEST_ASSERT_EQUAL(0, pressureMoveStarted);
    TEST_ASSERT_TRUE(measurePressure);
}
void test_pulse_recovery_must_finish_before_release_and_duplicates_do_not_reset() {
    sample(40); processCommand("P40"); processCommand("J200");
    sample(38); TEST_ASSERT_EQUAL(0, speed(12));
    sample(39); TEST_ASSERT_EQUAL(0, speed(12)); // no rebound restart
    tick(200); TEST_ASSERT_EQUAL(1, jerkDirection);
    unsigned long recoveryStart=lastJerkTime;
    for (int i=0; i<49; ++i) { tick(); processCommand("J200"); }
    TEST_ASSERT_TRUE(jerking); TEST_ASSERT_EQUAL(recoveryStart, lastJerkTime);
    tick(); TEST_ASSERT_TRUE(pressureFault); stopped();
    TEST_ASSERT_TRUE(Serial1.outputContains("PULSE_RECOVERY_TIMEOUT"));
}
void test_recovery_reapplies_droop_before_next_release() {
    sample(40); processCommand("P40"); processCommand("J500");
    sample(38); tick(500);
    sample(40); TEST_ASSERT_EQUAL(0, speed(12));
    sample(39); tick(100); TEST_ASSERT_TRUE(speed(12)>0);
    TEST_ASSERT_EQUAL(1, jerkDirection);
    sample(40); tick(400); TEST_ASSERT_EQUAL(-1, jerkDirection);
}
void test_notice_is_once_and_advisory() {
    Wire.position_12 = 100; sample(0); processCommand("P40");
    Wire.position_12 = 2250; sample(1); loop();
    TEST_ASSERT_TRUE(Serial1.outputContains("NOTICE|PRESSURE_NO_PROGRESS|2150"));
    TEST_ASSERT_TRUE(measurePressure); TEST_ASSERT_FALSE(pressureFault);
    Serial1.reset(); loop();
    TEST_ASSERT_FALSE(Serial1.outputContains("NOTICE|"));
}
void test_position_bands_and_feedback_range() {
    Wire.position_14 = 1600; processCommand("K1500");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("MOTION_DONE|K|1500|1600"));
    Wire.position_14 = 1601; processCommand("K1500"); TEST_ASSERT_TRUE(bRunning);
    processCommand("X"); Wire.position_12 = 125; processCommand("I120");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("MOTION_DONE|I|100|125"));
    processCommand("I124096"); TEST_ASSERT_FALSE(bRunning);
    Wire.position_12 = 65535; smcDeviceNumber = 12; readPosition();
    TEST_ASSERT_FALSE(positionReadValid);
}
int main() {
    UNITY_BEGIN();
    RUN_TEST(test_l0_changes_factor_without_taring);
    RUN_TEST(test_stable_resting_load_requires_ten_samples_and_900ms);
    RUN_TEST(test_unstable_tare_has_fixed_eight_second_deadline);
    RUN_TEST(test_gap_resets_candidate_without_extending_tare_deadline);
    RUN_TEST(test_tare_is_rejected_while_fit_is_active);
    RUN_TEST(test_stop_cancels_tare_without_committing);
    RUN_TEST(test_sensor_loss_trips_after_500ms_even_during_static_hold);
    RUN_TEST(test_fresh_sample_does_not_hide_a_service_gap);
    RUN_TEST(test_invalid_sample_stops_all_axes_and_fit);
    RUN_TEST(test_repeated_pressure_command_does_not_extend_deadline);
    RUN_TEST(test_pulse_recovery_must_finish_before_release_and_duplicates_do_not_reset);
    RUN_TEST(test_recovery_reapplies_droop_before_next_release);
    RUN_TEST(test_notice_is_once_and_advisory);
    RUN_TEST(test_position_bands_and_feedback_range);
    return UNITY_END();
}
#endif
