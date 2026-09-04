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
    pressureWarningIssued = false;
    heartbeatWarningIssued = false;
    scaleWarningIssued = false;
    axialTravelWarningIssued = false;
    pressureTimeoutWarningIssued = false;
    pressureProgressWarningIssued = false;
    positionStallWarningIssued = false;
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
    loopStallStart = 0;
    scale._ready = true;
    scale._scale = 1.0;
    scale._offset = 0.0;
    scale._raw = 0;
    _pin_levels[STOP_PIN] = HIGH;  // button not pressed
    STOP = true;                   // loop() mirrors the pin; direct processCommand tests need it too
    stopWasPressed = false;
    runningDevice = 12;
    BZERO = 0;
    _wdt_enabled = false;
    hostV2 = false;
    currentCmdSeq = -1;
    activeCmdSeq = -1;
    activeFitCmdSeq = -1;
    moveFITForward = false;
    FITDelay = 0;
    timeInFIT = 0;
    _pin_levels[DIR_FIT_FORWARD] = LOW;
    _pin_levels[DIR_FIT_REVERSE] = LOW;
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

void test_emergency_stop_stops_fit_motion(void) {
    moveFITForward = true;
    FITDelay = FIT_FAST_DELAY;
    activeFitCmdSeq = 41;
    _pin_levels[DIR_FIT_FORWARD] = HIGH;
    _pin_levels[DIR_FIT_REVERSE] = LOW;

    emergencyStop();

    TEST_ASSERT_FALSE(moveFITForward);
    TEST_ASSERT_EQUAL(-1, activeFitCmdSeq);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_REVERSE]);
}

void test_fit_done_is_emitted_only_after_physical_completion(void) {
    processCommand("F+");

    TEST_ASSERT_TRUE(moveFITForward);
    TEST_ASSERT_FALSE(Serial1.outputContains("DONE"));

    _millis_value = (unsigned long)FIT_SLOW_DELAY + 1;
    keepAlive();
    loop();

    TEST_ASSERT_FALSE(moveFITForward);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_REVERSE]);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_fit_rejects_conflicting_motion_command(void) {
    processCommand("FF");
    TEST_ASSERT_TRUE(moveFITForward);
    Serial1.reset();

    processCommand("FR");

    TEST_ASSERT_TRUE(moveFITForward);
    TEST_ASSERT_TRUE(Serial1.outputContains("BUSY"));
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

void test_stop_pin_honored_during_fit_motion(void) {
    moveFITForward = true;
    FITDelay = FIT_FAST_DELAY;
    _pin_levels[DIR_FIT_FORWARD] = HIGH;
    scale._raw = 30;
    pressure = 30;
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;

    loop();

    TEST_ASSERT_FALSE(moveFITForward);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_EQUAL(LOW, _pin_levels[DIR_FIT_REVERSE]);
    TEST_ASSERT_TRUE(releasingPressure);
}

void test_treatment_pressure_does_not_raise_warning(void) {
    jerking = true;
    keepAlive();
    scale._raw = 85;  // 85 lbs with scale=1, offset=0

    loop();

    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_FALSE(Serial1.outputContains("WARNING: Pressure"));
}

void test_pressure_warning_does_not_stop_position_move(void) {
    bRunning = true;
    desiredPosition = 4000;
    forward = 1;
    smcDeviceNumber = 12;
    Wire.position_12 = 800;
    loopLastPosition = 800;
    loopStallStart = _millis_value;
    keepAlive();
    scale._raw = PRESSURE_WARNING_LBS + 10;

    loop();

    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains(
        "WARNING: Pressure warning threshold exceeded"));
}

void test_pressure_warning_is_emitted_once_per_excursion(void) {
    jerking = true;
    keepAlive();
    scale._raw = PRESSURE_WARNING_LBS + 10;

    loop();
    keepAlive();
    loop();

    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_FALSE(releasingPressure);
    std::string output = Serial1.getOutput();
    std::string warning = "WARNING: Pressure warning threshold exceeded";
    size_t first = output.find(warning);
    TEST_ASSERT_TRUE(first != std::string::npos);
    TEST_ASSERT_TRUE(output.find(warning, first + 1) == std::string::npos);
}

void test_heartbeat_loss_warns_without_stopping(void) {
    bRunning = true;
    desiredPosition = 60000;  // unreachable: move stays active
    scale._raw = 30;          // load present, so the release stays active
    lastHostTraffic = 0;
    _millis_value = HEARTBEAT_TIMEOUT + 1000;
    lastScaleReady = _millis_value;

    loop();

    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Host heartbeat lost"));
}

void test_heartbeat_loss_does_not_stop_fit_motion(void) {
    moveFITForward = true;
    FITDelay = FIT_FAST_DELAY;
    _pin_levels[DIR_FIT_FORWARD] = HIGH;
    scale._raw = 30;
    pressure = 30;
    lastHostTraffic = 0;
    _millis_value = HEARTBEAT_TIMEOUT + 1000;
    timeInFIT = 0;  // isolate heartbeat behavior from the FIT duration timer
    lastScaleReady = _millis_value;

    loop();

    TEST_ASSERT_TRUE(moveFITForward);
    TEST_ASSERT_EQUAL(HIGH, _pin_levels[DIR_FIT_FORWARD]);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Host heartbeat lost"));
}

void test_heartbeat_not_tripped_when_idle(void) {
    // No motion: a silent host is fine (nothing to stop)
    lastHostTraffic = 0;
    _millis_value = HEARTBEAT_TIMEOUT + 1000;
    lastScaleReady = _millis_value;

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
}

void test_load_cell_warning_does_not_stop_pressure_move(void) {
    measurePressure = true;
    pressureDirection = 1;
    desiredPressure = 50;
    pressure = 20;
    Wire.position_12 = 2000;
    scale._ready = false;
    lastScaleReady = 0;
    _millis_value = SCALE_READ_TIMEOUT + 100;
    lastHostTraffic = _millis_value;  // host alive

    loop();

    TEST_ASSERT_TRUE(measurePressure);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Load cell not responding"));
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

void test_pressure_move_timeout_warns_without_stopping(void) {
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

    TEST_ASSERT_TRUE(measurePressure);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Pressure move timeout"));
}

// Owner policy: warnings never stop a pressure move -- only an E-stop does.
void test_axial_travel_warning_does_not_stop_pressure_move(void) {
    keepAlive();
    measurePressure = true;
    pressureDirection = 1;
    pressure = 20;
    desiredPressure = 50;
    pressureMoveStart = _millis_value;
    smcDeviceNumber = 12;
    Wire.position_12 = AXIAL_MAX_POS;

    loop();

    TEST_ASSERT_TRUE(measurePressure);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains(
        "WARNING: Axial travel limit during pressure move"));
}

void test_pressure_progress_fault_is_disabled(void) {
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

    TEST_ASSERT_TRUE(measurePressure);
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR: No pressure progress"));
}

// A position move that settles within POSITION_DEADBAND of its target has
// arrived and must complete with DONE -- never be misreported as a stall.
// Repro for the reset "Motor stalled" fault: the axial actuator homes toward
// AZERO=0 but bottoms out at its physical home a few counts short of 0.
void test_axial_home_within_deadband_not_stalled(void) {
    keepAlive();
    _millis_value = 300;             // past the rate-limit window
    keepAlive();
    AZERO = 0;
    Wire.position_12 = 800;          // start well away from home
    Serial1.injectCommand("I120");   // home the axial actuator

    loop();                          // command accepted, move starts
    TEST_ASSERT_TRUE(bRunning);

    // Actuator reaches its physical home 15 counts short of AZERO and can
    // move no further. The old strict `currentPos <= desiredPosition` never
    // registered arrival, so the stall detector eventually reported a stall.
    Wire.position_12 = 15;
    for (int i = 0; i < 8; i++) {
        keepAlive();
        loop();
    }

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR: Motor stalled"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// A frozen motor warns after the sustained no-progress interval but continues
// until E-stop.
void test_genuine_stall_warns_after_sustained_interval_without_stopping(void) {
    keepAlive();
    smcDeviceNumber = 12;
    desiredPosition = 4000;          // far from the frozen position below
    forward = 1;
    Wire.position_12 = 800;          // frozen, well outside the deadband
    bRunning = true;
    activeCmdSeq = -1;
    loopLastPosition = 800;
    loopStallStart = _millis_value;

    // Rapid repeated reads are not a stall; the encoder needs time to update.
    for (int i = 0; i < 50; i++) {
        keepAlive();
        loop();
    }
    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_FALSE(Serial1.outputContains("WARNING: Motor stalled"));

    _millis_value = POSITION_STALL_MS - 100;
    lastActiveStatus = _millis_value;
    keepAlive();
    loop();
    TEST_ASSERT_TRUE(bRunning);

    _millis_value = POSITION_STALL_MS;
    lastActiveStatus = _millis_value;
    keepAlive();
    loop();

    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Motor stalled"));
}

void test_position_progress_restarts_stall_timer(void) {
    keepAlive();
    desiredPosition = 4000;
    forward = 1;
    Wire.position_12 = 800;
    bRunning = true;
    activeCmdSeq = -1;
    loopLastPosition = 800;
    loopStallStart = _millis_value;

    _millis_value = POSITION_STALL_MS - 100;
    Wire.position_12 += POSITION_PROGRESS_COUNTS;
    lastActiveStatus = _millis_value;
    keepAlive();
    loop();

    _millis_value += POSITION_STALL_MS - 100;
    lastActiveStatus = _millis_value;
    keepAlive();
    loop();
    TEST_ASSERT_TRUE(bRunning);

    _millis_value += 100;
    lastActiveStatus = _millis_value;
    keepAlive();
    loop();
    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("WARNING: Motor stalled"));
}

// --- P0 release semantics (2026-07-08 on-device finding) ---
// The host sends X + P0 after every aborted protocol. When no load was
// ever applied, the old code started a backward move whose first loop
// iteration hit the axial-at-zero guard and emitted "ERROR: Axial at
// zero, pressure target not reached" -- which the host escalates to a
// DEVICE SAFETY STOP over what was actually a no-op.

void test_p0_with_no_load_completes_done_without_error(void) {
    keepAlive();
    AZERO = 0;
    Wire.position_12 = 10;  // axial at home
    pressure = 0;           // no load ever applied

    processCommand("P0");

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR: Axial at zero"));
    // A no-op release must not drive the motor at all
    bool motorDriven = false;
    for (int i = 0; i < Wire.commandCount; i++) {
        if (Wire.commands[i].address == 12 && Wire.commands[i].dataLen >= 1 &&
            (Wire.commands[i].data[0] == 0x85 || Wire.commands[i].data[0] == 0x86)) {
            motorDriven = true;
        }
    }
    TEST_ASSERT_FALSE(motorDriven);
}

// A release that reaches the travel floor just as the load clears must
// complete DONE via the reached-check, not fault on the at-zero guard.
void test_release_reaching_zero_with_target_met_completes_done(void) {
    keepAlive();
    AZERO = 0;
    Wire.position_12 = 10;   // within AZERO + POSITION_DEADBAND
    measurePressure = true;
    pressureDirection = -1;
    desiredPressure = 0;
    scale._raw = 0;          // load fully cleared
    pressureMoveStart = _millis_value;
    pressureProgressTime = _millis_value;
    pressureProgressValue = 5;

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR: Axial at zero"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// Reaching the travel floor before the requested pressure no longer raises
// a device safety fault. The move ends cleanly and reports DONE while the
// firmware continues to enforce the axial travel floor.
void test_release_at_zero_with_load_ends_without_fault(void) {
    keepAlive();
    AZERO = 0;
    Wire.position_12 = 10;
    measurePressure = true;
    pressureDirection = -1;
    desiredPressure = 0;
    scale._raw = 20;         // 20 lbs still applied
    pressure = 20;
    pressureSampleCount = 3;
    pressureSamples[0] = pressureSamples[1] = pressureSamples[2] = 20;
    pressureMoveStart = _millis_value;
    pressureProgressTime = _millis_value;
    pressureProgressValue = 20;

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR: Axial at zero"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// --- Protocol v2 framing (loop-driven) ---

static String v2Frame(int seq, const char *cmd) {
    String body = String(seq);
    body += ":";
    body += cmd;
    char buf[64];
    snprintf(buf, sizeof(buf), "#%s*%02X", body.c_str(),
             xorChecksum(body, 0, body.length()));
    return String(buf);
}

void test_v2_framed_T_acks_with_seq(void) {
    keepAlive();
    _millis_value = 300;  // past the rate-limit window
    keepAlive();
    Serial1.injectCommand(std::string(v2Frame(7, "T").c_str()));

    loop();

    TEST_ASSERT_TRUE(Serial1.outputContains("OK|7"));
}

void test_v2_framed_X_bypasses_rate_limiter(void) {
    bRunning = true;
    desiredPosition = 60000;  // unreachable: the move cannot self-complete
    keepAlive();
    lastCommandTime = _millis_value;  // limiter window closed
    Serial1.injectCommand(std::string(v2Frame(9, "X").c_str()));

    loop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE|9"));
}

void test_v2_corrupt_command_does_not_execute(void) {
    keepAlive();
    _millis_value = 300;
    keepAlive();
    // Frame for P10 with a flipped payload digit (P70)
    String frame = v2Frame(11, "P10");
    int colon = frame.indexOf(':');
    String corrupted = frame.substring(0, colon + 2);
    corrupted += "7";
    corrupted += frame.substring(colon + 3);
    Serial1.injectCommand(std::string(corrupted.c_str()));

    loop();

    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERR|11|Checksum mismatch"));
}

void test_v2_deferred_done_carries_seq(void) {
    keepAlive();
    _millis_value = 300;
    keepAlive();
    Wire.position_12 = 100;
    Serial1.injectCommand(std::string(v2Frame(15, "I121500").c_str()));

    loop();  // command accepted, move starts
    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_EQUAL(15, (int)activeCmdSeq);

    Wire.position_12 = 1500;  // target reached
    keepAlive();
    loop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE|15"));
    TEST_ASSERT_EQUAL(-1, (int)activeCmdSeq);
}

void test_v2_status_carries_checksum(void) {
    hostV2 = true;
    sendStatus();
    std::string out = Serial1.getOutput();
    size_t start = out.find("STATUS_START");
    size_t star = out.find('*', start);
    TEST_ASSERT_TRUE(start != std::string::npos);
    TEST_ASSERT_TRUE(star != std::string::npos);
    // Recompute the checksum over the frame and compare
    std::string frame = out.substr(start, star - start);
    uint8_t expected = 0;
    for (char c : frame) expected ^= (uint8_t)c;
    unsigned int got = (unsigned int)strtol(out.substr(star + 1, 2).c_str(), NULL, 16);
    TEST_ASSERT_EQUAL((int)expected, (int)got);
}

void test_v1_status_has_no_checksum(void) {
    hostV2 = false;
    sendStatus();
    std::string out = Serial1.getOutput();
    TEST_ASSERT_TRUE(out.find("STATUS_END") != std::string::npos);
    TEST_ASSERT_TRUE(out.find('*') == std::string::npos);
}

// --- FAILSAFE-6: STOP during a static hold / held-button behavior ---

// The hold phase (motor zeroed, patient under load) sets no motion flag, so
// the physical STOP used to be ignored for the longest phase of a treatment.
void test_stop_pin_honored_during_static_hold(void) {
    scale._raw = 30;  // 30 lbs applied, nothing moving
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;

    loop();

    TEST_ASSERT_TRUE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Stop button pressed"));
}

void test_stop_pin_idle_without_load_is_inert(void) {
    scale._raw = 0;
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;

    loop();

    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_FALSE(Serial1.outputContains("ERROR:"));
}

// A button held past an incomplete release must not re-fire a new release
// (and a new ERROR) on every loop iteration.
void test_held_stop_does_not_refire_after_incomplete_release(void) {
    scale._raw = 30;
    keepAlive();
    _pin_levels[STOP_PIN] = LOW;
    loop();
    TEST_ASSERT_TRUE(releasingPressure);

    // Release ends incomplete: axial already at its travel floor, load remains
    AZERO = 0;
    Wire.position_12 = 10;
    keepAlive();
    loop();
    TEST_ASSERT_FALSE(releasingPressure);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Release incomplete"));

    keepAlive();
    loop();
    keepAlive();
    loop();

    TEST_ASSERT_FALSE(releasingPressure);
    std::string out = Serial1.getOutput();
    std::string needle = "ERROR: Stop button pressed";
    size_t first = out.find(needle);
    TEST_ASSERT_TRUE(first != std::string::npos);
    TEST_ASSERT_TRUE(out.find(needle, first + 1) == std::string::npos);
}

void test_motion_commands_refused_while_stop_engaged(void) {
    STOP = false;  // loop() read the pin LOW
    Wire.position_12 = 100;

    processCommand("P50");
    TEST_ASSERT_FALSE(measurePressure);
    processCommand("I121000");
    TEST_ASSERT_FALSE(bRunning);
    processCommand("K1500");
    TEST_ASSERT_FALSE(bRunning);
    processCommand("A122");
    TEST_ASSERT_FALSE(bRunning);
    processCommand("J");
    TEST_ASSERT_FALSE(jerking);
    processCommand("F+");
    TEST_ASSERT_FALSE(moveFITForward);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Stop button engaged"));

    // Non-motion commands still work
    Serial1.reset();
    processCommand("X");
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
    processCommand("T");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK"));
}

// The host's e-stop chain asserts the stop line, then sends X + P0. The
// release must still be accepted while the line is held.
void test_pressure_release_allowed_while_stop_engaged(void) {
    STOP = false;
    pressure = 30;
    Wire.position_12 = 2000;

    processCommand("P0");

    TEST_ASSERT_TRUE(measurePressure);
    TEST_ASSERT_EQUAL(-1, pressureDirection);
    TEST_ASSERT_FALSE(Serial1.outputContains("Stop button engaged"));
}

// --- FAILSAFE-6: JS / per-move device targeting ---

static int countSpeedZeroWrites(uint8_t device) {
    int n = 0;
    for (int i = 0; i < Wire.commandCount; i++) {
        if (Wire.commands[i].address == device && Wire.commands[i].dataLen == 3 &&
            Wire.commands[i].data[0] == 0x85 && Wire.commands[i].data[1] == 0 &&
            Wire.commands[i].data[2] == 0)
            n++;
    }
    return n;
}

void test_js_only_stops_axial_when_pulsing(void) {
    jerking = true;
    smcDeviceNumber = 14;  // something else was addressed last
    Wire.reset();

    processCommand("JS");

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_EQUAL(1, countSpeedZeroWrites(12));
    TEST_ASSERT_EQUAL(0, countSpeedZeroWrites(14));
}

void test_js_leaves_in_flight_lateral_move_running(void) {
    bRunning = true;
    runningDevice = 14;
    smcDeviceNumber = 14;
    jerking = false;
    Wire.reset();

    processCommand("JS");

    TEST_ASSERT_TRUE(bRunning);
    for (int i = 0; i < Wire.commandCount; i++) {
        bool speedCmd = Wire.commands[i].dataLen == 3 &&
                        (Wire.commands[i].data[0] == 0x85 ||
                         Wire.commands[i].data[0] == 0x86);
        TEST_ASSERT_FALSE(Wire.commands[i].address == 14 && speedCmd);
    }
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_position_move_tracks_its_own_device_during_pressure_move(void) {
    keepAlive();
    // Lateral move in flight on SMC 14, already at target
    bRunning = true;
    runningDevice = 14;
    desiredPosition = 1500;
    forward = 1;
    Wire.position_14 = 1500;
    loopLastPosition = 1200;
    loopStallStart = _millis_value;
    // Concurrent axial pressure move, far from done
    measurePressure = true;
    pressureDirection = 1;
    desiredPressure = 50;
    scale._raw = 20;
    Wire.position_12 = 100;
    pressureMoveStart = _millis_value;

    loop();

    TEST_ASSERT_FALSE(bRunning);        // judged on SMC 14, not SMC 12
    TEST_ASSERT_TRUE(measurePressure);  // pressure move continues
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_pulse_start_refused_during_axial_pressure_move(void) {
    measurePressure = true;

    processCommand("J");

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(Serial1.outputContains("BUSY"));
}

void test_pulse_status_slot_rests_motor(void) {
    keepAlive();
    jerking = true;
    jerksCompleted = MAX_JERKS;
    lastJerkTime = 0;
    _millis_value = jerkInterval + 1;
    keepAlive();
    Wire.reset();

    loop();

    TEST_ASSERT_TRUE(jerking);
    TEST_ASSERT_EQUAL(0, jerksCompleted);
    TEST_ASSERT_EQUAL(1, countSpeedZeroWrites(12));
}

// --- FAILSAFE-6: input validation ---

void test_l5_rejects_out_of_range_zero_marks(void) {
    AZERO = 100;
    BZERO = 1900;

    processCommand("L5|16000|1900");
    TEST_ASSERT_EQUAL(100, AZERO);
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid L5 zero marks"));
    TEST_ASSERT_FALSE(Serial1.outputContains("ZEROS|"));

    processCommand("L5|-5|1900");
    TEST_ASSERT_EQUAL(100, AZERO);

    processCommand("L5|150|-20");  // BZERO below HORIZONTAL_MIN_POS
    TEST_ASSERT_EQUAL(1900, BZERO);

    processCommand("L5|150|5000");  // BZERO above HORIZONTAL_MAX_POS
    TEST_ASSERT_EQUAL(1900, BZERO);

    Serial1.reset();
    processCommand("L5|150|1900");
    TEST_ASSERT_EQUAL(150, AZERO);
    TEST_ASSERT_TRUE(Serial1.outputContains("ZEROS|150|1900"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_axial_floor_applied_before_clamp(void) {
    AZERO = 160;
    Wire.position_12 = 2000;

    processCommand("I1210");  // below the floor -> AZERO

    TEST_ASSERT_TRUE(bRunning);
    TEST_ASSERT_EQUAL(160, desiredPosition);
}

void test_l0_rejects_zero_or_garbage_factor(void) {
    scale._scale = 1.0;

    processCommand("L0abc");
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Invalid L0 factor"));
    TEST_ASSERT_EQUAL_FLOAT(1.0, scale._scale);

    processCommand("L00");
    TEST_ASSERT_EQUAL_FLOAT(1.0, scale._scale);

    Serial1.reset();
    processCommand("L0-4360.14");
    TEST_ASSERT_FLOAT_WITHIN(0.01, -4360.14, scale._scale);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// --- FAILSAFE-6: e-stop I2C acknowledgement, misc ---

void test_emergency_stop_retries_unacknowledged_write(void) {
    Wire.reset();
    Wire.failTransmissions = 2;  // exitSafeStart + speed write of attempt 1

    emergencyStop();

    TEST_ASSERT_EQUAL(2, countSpeedZeroWrites(12));
    TEST_ASSERT_FALSE(Serial1.outputContains("Motor stop not acknowledged"));
}

void test_emergency_stop_reports_persistent_i2c_failure(void) {
    Wire.reset();
    Wire.failTransmissions = 100;

    emergencyStop();

    TEST_ASSERT_EQUAL(3, countSpeedZeroWrites(12));
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR: Motor stop not acknowledged 12"));
}

void test_v2_ack_seq_survives_beyond_int16(void) {
    emitAck("DONE", 40000L);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE|40000"));
}

void test_position_read_does_not_burn_dead_wait(void) {
    _millis_value = 0;
    smcDeviceNumber = 12;
    readPosition();
    TEST_ASSERT_EQUAL(0, (int)_millis_value);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_emergency_stop_clears_all_state);
    RUN_TEST(test_emergency_stop_sets_motor_speeds_to_zero);
    RUN_TEST(test_x_command_triggers_emergency_stop);
    RUN_TEST(test_commands_accepted_after_emergency_stop);
    RUN_TEST(test_emergency_stop_during_jerking);
    RUN_TEST(test_emergency_stop_stops_fit_motion);
    RUN_TEST(test_fit_done_is_emitted_only_after_physical_completion);
    RUN_TEST(test_fit_rejects_conflicting_motion_command);

    RUN_TEST(test_stop_pin_honored_during_pressure);
    RUN_TEST(test_stop_pin_honored_during_jerking);
    RUN_TEST(test_stop_pin_honored_during_fit_motion);
    RUN_TEST(test_treatment_pressure_does_not_raise_warning);
    RUN_TEST(test_pressure_warning_does_not_stop_position_move);
    RUN_TEST(test_pressure_warning_is_emitted_once_per_excursion);
    RUN_TEST(test_heartbeat_loss_warns_without_stopping);
    RUN_TEST(test_heartbeat_loss_does_not_stop_fit_motion);
    RUN_TEST(test_heartbeat_not_tripped_when_idle);
    RUN_TEST(test_load_cell_warning_does_not_stop_pressure_move);
    RUN_TEST(test_release_drives_axial_backward);
    RUN_TEST(test_release_completes_when_load_clears);
    RUN_TEST(test_release_bounded_by_timeout);
    RUN_TEST(test_release_bounded_by_travel_limit);
    RUN_TEST(test_watchdog_enabled_by_setup);
    RUN_TEST(test_x_bypasses_rate_limiter);
    RUN_TEST(test_commands_not_merged_under_rate_limit);
    RUN_TEST(test_pressure_move_timeout_warns_without_stopping);
    RUN_TEST(test_axial_travel_warning_does_not_stop_pressure_move);
    RUN_TEST(test_pressure_progress_fault_is_disabled);
    RUN_TEST(test_axial_home_within_deadband_not_stalled);
    RUN_TEST(test_genuine_stall_warns_after_sustained_interval_without_stopping);
    RUN_TEST(test_position_progress_restarts_stall_timer);
    RUN_TEST(test_p0_with_no_load_completes_done_without_error);
    RUN_TEST(test_release_reaching_zero_with_target_met_completes_done);
    RUN_TEST(test_release_at_zero_with_load_ends_without_fault);

    RUN_TEST(test_stop_pin_honored_during_static_hold);
    RUN_TEST(test_stop_pin_idle_without_load_is_inert);
    RUN_TEST(test_held_stop_does_not_refire_after_incomplete_release);
    RUN_TEST(test_motion_commands_refused_while_stop_engaged);
    RUN_TEST(test_pressure_release_allowed_while_stop_engaged);
    RUN_TEST(test_js_only_stops_axial_when_pulsing);
    RUN_TEST(test_js_leaves_in_flight_lateral_move_running);
    RUN_TEST(test_position_move_tracks_its_own_device_during_pressure_move);
    RUN_TEST(test_pulse_start_refused_during_axial_pressure_move);
    RUN_TEST(test_pulse_status_slot_rests_motor);
    RUN_TEST(test_l5_rejects_out_of_range_zero_marks);
    RUN_TEST(test_axial_floor_applied_before_clamp);
    RUN_TEST(test_l0_rejects_zero_or_garbage_factor);
    RUN_TEST(test_emergency_stop_retries_unacknowledged_write);
    RUN_TEST(test_emergency_stop_reports_persistent_i2c_failure);
    RUN_TEST(test_v2_ack_seq_survives_beyond_int16);
    RUN_TEST(test_position_read_does_not_burn_dead_wait);

    RUN_TEST(test_v2_framed_T_acks_with_seq);
    RUN_TEST(test_v2_framed_X_bypasses_rate_limiter);
    RUN_TEST(test_v2_corrupt_command_does_not_execute);
    RUN_TEST(test_v2_deferred_done_carries_seq);
    RUN_TEST(test_v2_status_carries_checksum);
    RUN_TEST(test_v1_status_has_no_checksum);

    return UNITY_END();
}

#endif // UNIT_TEST
