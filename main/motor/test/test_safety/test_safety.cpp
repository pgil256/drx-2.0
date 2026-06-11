// main/motor/test/test_safety/test_safety.cpp
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
void delay(unsigned long ms) { _millis_value += ms; }  // advance mock clock

#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    Wire.position_12 = 2000;
    Wire.position_13 = 2000;
    Wire.position_14 = 1200;
    bRunning = false;
    measurePressure = false;
    jerking = false;
    releasingPressure = false;
    isCommandComplete = false;
    commandBuffer = "";
    isProcessingStatus = false;
    statusAcknowledged = true;
    highFrequencyStatus = false;
    pressure = 0;
    signedPressure = 0;
    pressureSampleIndex = 0;
    pressureSampleCount = 0;
    pressureDirection = 0;
    lastCommandTime = 0;
    AZERO = 0;
    desiredPosition = 0;
    forward = 1;
    _millis_value = 0;
    lastHostTraffic = 0;
    lastScaleReady = 0;
    // Reset every time anchor: setUp rewinds the mock clock to zero, and
    // a stale anchor from the previous test would underflow millis()-anchor
    lastStatusTime = 0;
    lastActiveStatus = 0;
    loopPosition = 0;
    timeSinceLastStatus = 0;
    loopLastPosition = -1;
    loopStallCount = 0;
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 0;
    _pin_levels[STOP_PIN] = HIGH;  // button not pressed
    _wdt_enabled = false;
}

void tearDown(void) {}

// Keep host traffic and the scale "fresh" so unrelated fail-safes do
// not fire during a test
static void keepAlive(void) {
    lastHostTraffic = _millis_value;
    lastScaleReady = _millis_value;
}

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

// --- Fail-safe core (Phase 1) ---

void test_stop_pin_honored_during_pressure(void) {
    measurePressure = true;
    scale._raw = 30;  // load present, so the release stays active
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;  // button pressed

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Stop button pressed"));
}

void test_stop_pin_honored_during_jerking(void) {
    jerking = true;
    scale._raw = 30;
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;

    loop();

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(releasingPressure);
}

void test_pressure_ceiling_enforced_during_jerking(void) {
    jerking = true;
    keepAlive();
    scale._raw = 85;  // 85 lbs with scale=1, offset=0

    loop();

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Pressure limit exceeded"));
}

void test_pressure_ceiling_enforced_during_position_move(void) {
    bRunning = true;
    keepAlive();
    scale._raw = 85;

    loop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Pressure limit exceeded"));
}

void test_heartbeat_loss_stops_and_releases(void) {
    bRunning = true;
    desiredPosition = 60000;  // unreachable: move stays active
    scale._raw = 30;          // load present, so the release stays active
    lastHostTraffic = 0;
    _millis_value = HEARTBEAT_TIMEOUT + 1000;
    lastScaleReady = _millis_value;

    loop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Host heartbeat lost"));
}

void test_heartbeat_not_tripped_when_idle(void) {
    // No motion: a silent host is fine (nothing to stop)
    lastHostTraffic = 0;
    _millis_value = HEARTBEAT_TIMEOUT + 1000;
    lastScaleReady = _millis_value;

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
}

void test_load_cell_fault_during_pressure(void) {
    measurePressure = true;
    scale._ready = false;
    lastScaleReady = 0;
    _millis_value = SCALE_READ_TIMEOUT + 100;
    lastHostTraffic = _millis_value;  // host alive

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Load cell not responding"));
}

void test_release_drives_axial_backward(void) {
    keepAlive();
    emergencyStopAndRelease("test fault");

    TEST_ASSERT_TRUE(releasingPressure);
    // The last Wire command should be a reverse (0x86) on device 12
    bool foundReverse12 = false;
    for (int i = 0; i < Wire.commandCount; i++) {
        if (Wire.commands[i].address == 12 &&
            Wire.commands[i].dataLen >= 1 &&
            Wire.commands[i].data[0] == 0x86) {
            foundReverse12 = true;
        }
    }
    TEST_ASSERT_TRUE(foundReverse12);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: test fault"));
}

void test_release_completes_when_load_clears(void) {
    keepAlive();
    emergencyStopAndRelease("test fault");
    TEST_ASSERT_TRUE(releasingPressure);

    // Load cell reads ~0 lbs; position well above the travel floor
    scale._raw = 0;
    Wire.position_12 = 2000;
    keepAlive();

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("RELEASED"));
}

void test_release_bounded_by_timeout(void) {
    keepAlive();
    emergencyStopAndRelease("test fault");

    // Dead load cell keeps `released` false; position above the floor
    scale._ready = false;
    pressure = 50;
    Wire.position_12 = 2000;
    _millis_value = RELEASE_TIMEOUT + 1000;

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Release incomplete"));
}

void test_release_bounded_by_travel_limit(void) {
    keepAlive();
    emergencyStopAndRelease("test fault");

    // Pressure still high but axial is at its travel floor
    scale._raw = 50;
    pressure = 50;
    pressureSampleCount = 3;
    pressureSamples[0] = pressureSamples[1] = pressureSamples[2] = 50;
    AZERO = 160;
    Wire.position_12 = 100;  // below AZERO + deadband
    keepAlive();

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Release incomplete"));
}

void test_watchdog_enabled_by_setup(void) {
    setup();
    TEST_ASSERT_TRUE(_wdt_enabled);
    TEST_ASSERT_EQUAL(WDTO_2S, _wdt_timeout);
}

void test_x_bypasses_rate_limiter(void) {
    bRunning = true;
    desiredPosition = 60000;  // unreachable: the move cannot self-complete
    keepAlive();
    // A command was just processed; the limiter window is still closed
    lastCommandTime = _millis_value;
    Serial1.injectCommand("X");

    loop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_commands_not_merged_under_rate_limit(void) {
    // "Q" then "X" arriving back-to-back used to merge into "QX",
    // silently discarding the emergency stop
    bRunning = true;
    desiredPosition = 60000;  // unreachable: the move cannot self-complete
    statusAcknowledged = false;
    keepAlive();
    Serial1.injectCommand("Q");
    Serial1.injectCommand("X");

    loop();  // reads "Q", rate limiter may hold it
    _millis_value += MIN_COMMAND_INTERVAL + 50;
    keepAlive();
    loop();  // processes "Q"
    loop();  // reads "X" -> emergency bypass -> processed
    TEST_ASSERT_TRUE(statusAcknowledged);   // Q ran as Q, before X arrived
    _millis_value += MIN_COMMAND_INTERVAL + 50;
    keepAlive();
    loop();

    TEST_ASSERT_FALSE(bRunning);            // X ran as X
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_pressure_move_time_bound(void) {
    keepAlive();
    measurePressure = true;
    pressureDirection = 1;
    pressureMoveStart = 0;
    pressureProgressTime = _millis_value;
    scale._raw = 20;
    desiredPressure = 50;
    _millis_value = PRESSURE_MOVE_TIMEOUT + 1000;
    keepAlive();
    pressureProgressTime = _millis_value;  // isolate the time-bound check

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Pressure move timeout"));
}

void test_pressure_stall_detected(void) {
    keepAlive();
    measurePressure = true;
    pressureDirection = 1;
    desiredPressure = 50;
    scale._raw = 20;  // frozen well below target
    pressureMoveStart = _millis_value;
    pressureProgressTime = 0;
    pressureProgressValue = 20;
    pressureSampleCount = 3;
    pressureSamples[0] = pressureSamples[1] = pressureSamples[2] = 20;
    pressure = 20;
    _millis_value = PRESSURE_STALL_MS + 500;
    keepAlive();
    pressureMoveStart = _millis_value;  // isolate the stall check

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: No pressure progress"));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_emergency_stop_clears_all_state);
    RUN_TEST(test_emergency_stop_sets_motor_speeds_to_zero);
    RUN_TEST(test_x_command_triggers_emergency_stop);
    RUN_TEST(test_commands_accepted_after_emergency_stop);
    RUN_TEST(test_emergency_stop_during_jerking);

    RUN_TEST(test_stop_pin_honored_during_pressure);
    RUN_TEST(test_stop_pin_honored_during_jerking);
    RUN_TEST(test_pressure_ceiling_enforced_during_jerking);
    RUN_TEST(test_pressure_ceiling_enforced_during_position_move);
    RUN_TEST(test_heartbeat_loss_stops_and_releases);
    RUN_TEST(test_heartbeat_not_tripped_when_idle);
    RUN_TEST(test_load_cell_fault_during_pressure);
    RUN_TEST(test_release_drives_axial_backward);
    RUN_TEST(test_release_completes_when_load_clears);
    RUN_TEST(test_release_bounded_by_timeout);
    RUN_TEST(test_release_bounded_by_travel_limit);
    RUN_TEST(test_watchdog_enabled_by_setup);
    RUN_TEST(test_x_bypasses_rate_limiter);
    RUN_TEST(test_commands_not_merged_under_rate_limit);
    RUN_TEST(test_pressure_move_time_bound);
    RUN_TEST(test_pressure_stall_detected);

    return UNITY_END();
}

#endif // UNIT_TEST
