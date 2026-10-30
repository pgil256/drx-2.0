// Real sketch interlocks with independently controlled I/O and clock.
void beginHome(uint16_t position = 83) {
    Wire.position_12 = position; scale._offset = -1050203;
    sample(36.61); processCommand("R|012345abcdef");
}
void restHome() { now += 250; sample(36.61); serviceHomeRelease(); }
void startHomeTare() {
    beginHome(); restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
    TEST_ASSERT_EQUAL(-1050203, scale.get_offset());
    processCommand("L1|HOME|012345abcdef");
    TEST_ASSERT_TRUE(tareActive && homeTareActive);
}
void homeSamples(int count) {
    for (int i = 0; i < count; ++i) { now += 100; sample(36.61); }
}
void noHomeSuccess() {
    TEST_ASSERT_FALSE(tareActive || homeReleaseReady);
    TEST_ASSERT_EQUAL(-1050203, scale.get_offset());
    TEST_ASSERT_FALSE(Serial1.outputContains("CALIBRATION|TARE|OK"));
}
void test_home_residual_load_stops_then_separately_zeroes() {
    beginHome(); TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12));
    TEST_ASSERT_FALSE(Serial1.outputContains("HOME_RELEASE|")); restHome();
    TEST_ASSERT_TRUE(Serial1.outputContains("HOME_RELEASE|012345abcdef|100|83|36.61|-1050203|"));
    TEST_ASSERT_FALSE(Serial1.outputContains("DONE"));
    TEST_ASSERT_EQUAL(-1050203, scale.get_offset());
    processCommand("L1|HOME|012345abcdef"); homeSamples(9);
    TEST_ASSERT_EQUAL(-1050203, scale.get_offset()); homeSamples(1);
    TEST_ASSERT_TRUE(pressureCalibrated);
    TEST_ASSERT_NOT_EQUAL(-1050203, scale.get_offset());
    TEST_ASSERT_TRUE(Serial1.outputContains("CALIBRATION|TARE|OK"));
}
void test_home_above_band_retracts_to_margin_inside_band() {
    beginHome(126); TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12)); restHome();
    TEST_ASSERT_FALSE(homeReleaseReady);
    // The band edge is not a stopping point: keep retracting to the margin.
    Wire.position_12 = 125; serviceHomeRelease();
    TEST_ASSERT_FALSE(homeReleaseStopped); TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12));
    Wire.position_12 = 115; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12)); restHome();
    TEST_ASSERT_TRUE(homeReleaseReady);
    TEST_ASSERT_TRUE(Serial1.outputContains("HOME_RELEASE|012345abcdef|100|115|"));
}
void test_home_already_in_band_verifies_without_travel() {
    beginHome(120); TEST_ASSERT_EQUAL(0, speed(12)); TEST_ASSERT_TRUE(homeReleaseStopped);
    restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
    TEST_ASSERT_TRUE(Serial1.outputContains("|100|120|"));
}
void test_home_rebound_above_band_after_stop_retracts_again() {
    beginHome(126); Wire.position_12 = 115; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12));
    now += 100; sample(36.61); Wire.position_12 = 126; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_FALSE(homeReleaseStopped);
    TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12));
    TEST_ASSERT_FALSE(Serial1.outputContains("COMMAND_REJECTED"));
    now += 100; sample(36.61); Wire.position_12 = 110; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12));
    restHome(); TEST_ASSERT_TRUE(homeReleaseReady); TEST_ASSERT_FALSE(pressureFault);
}
void test_home_feedback_dropout_is_not_a_verdict() {
    beginHome(500);
    // One reading near zero mid-travel stops the motor but is not a verdict.
    now += 100; sample(36.61); Wire.position_12 = 40; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_EQUAL(0, speed(12));
    now += 100; sample(36.61); Wire.position_12 = 290; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12));
    // Nor is one reading inside the band.
    now += 100; sample(36.61); Wire.position_12 = 90; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12));
    now += 100; sample(36.61); Wire.position_12 = 280; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_FALSE(homeReleaseStopped);
    TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12));
    TEST_ASSERT_FALSE(Serial1.outputContains("COMMAND_REJECTED"));
    TEST_ASSERT_FALSE(pressureFault);
    now += 100; sample(36.61); Wire.position_12 = 112; serviceHomeRelease();
    restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
}
void test_home_below_band_blip_recovers_when_reading_returns() {
    beginHome(); now += 100; sample(36.61); Wire.position_12 = 74; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_FALSE(homeReleaseStopped);
    now += 100; sample(36.61); Wire.position_12 = 83; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12));
    restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
    TEST_ASSERT_FALSE(Serial1.outputContains("COMMAND_REJECTED"));
}
void test_home_position_read_retries_before_fault() {
    beginHome(); Wire.failTransmissions = POSITION_READ_ATTEMPTS - 1; restHome();
    TEST_ASSERT_TRUE(homeReleaseReady); TEST_ASSERT_FALSE(pressureFault);
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|I2C|POSITION_FAILED|12|1|3"));
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|I2C|POSITION_FAILED|12|2|3"));
    TEST_ASSERT_FALSE(Serial1.outputContains("DIAG|I2C|POSITION_FAILED|12|3|3"));
    TEST_ASSERT_FALSE(Serial1.outputContains("FAULT|"));
}
void test_home_position_read_faults_after_consecutive_failures() {
    beginHome(); Wire.failTransmissions = POSITION_READ_ATTEMPTS; restHome();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|I2C|POSITION_FAILED|12|3|3"));
    TEST_ASSERT_TRUE(Serial1.outputContains("FAULT|POSITION_FEEDBACK_INVALID"));
}
void test_general_position_read_retries_before_invalid() {
    smcDeviceNumber = 14; Wire.position_14 = 1570;
    Wire.failTransmissions = POSITION_READ_ATTEMPTS - 1;
    TEST_ASSERT_EQUAL(1570, readPosition()); TEST_ASSERT_TRUE(positionReadValid);
    TEST_ASSERT_TRUE(Serial1.outputContains("DIAG|I2C|POSITION_FAILED|14|2|3"));
    Wire.failTransmissions = POSITION_READ_ATTEMPTS; readPosition();
    TEST_ASSERT_FALSE(positionReadValid);
}
void test_home_lower_edge_is_inclusive() {
    beginHome(75); restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
}
void test_home_below_band_never_drives_outward() {
    beginHome(74); TEST_ASSERT_FALSE(homeReleaseActive);
    TEST_ASSERT_EQUAL(0, speed(12)); noHomeSuccess();
}
void test_home_configured_mark_is_preserved() {
    AZERO = 321; beginHome(321); restHome();
    TEST_ASSERT_TRUE(Serial1.outputContains("|321|321|")); TEST_ASSERT_EQUAL(321, AZERO);
}
void test_home_duplicate_does_not_extend_deadline() {
    beginHome(500); now += 100; processCommand("R|012345abcdef");
    TEST_ASSERT_EQUAL(0, homeReleaseStarted); processCommand("R|abcdef012345");
    TEST_ASSERT_TRUE(homeReleaseToken == "012345abcdef");
    TEST_ASSERT_TRUE(Serial1.outputContains("HOME_RELEASE_ACTIVE"));
}
void test_home_deadline_with_fresh_samples() {
    beginHome(500);
    for (int i = 0; i < 600; ++i) { now += 100; sample(36.61); serviceHomeRelease(); }
    TEST_ASSERT_TRUE(Serial1.outputContains("FAULT|HOME_RELEASE_TIMEOUT")); noHomeSuccess();
}
void test_home_stop_write_failure() {
    beginHome(500); Wire.motorWriteResult = 2; Wire.position_12 = 83; serviceHomeRelease();
    TEST_ASSERT_TRUE(pressureFault); TEST_ASSERT_TRUE(pendingStopMask); noHomeSuccess();
}
void test_home_short_stop_write() {
    beginHome(500); Wire.shortMotorWrite = true; Wire.position_12 = 83; serviceHomeRelease();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_pending_stop_blocks_start() {
    pendingStopMask = 1; beginHome(); TEST_ASSERT_FALSE(homeReleaseActive); noHomeSuccess();
}
void test_home_accepted_output_blocks_start() {
    smcDeviceNumber = 13; setMotorSpeed(800); beginHome();
    TEST_ASSERT_FALSE(homeReleaseActive); noHomeSuccess();
}
void test_home_invalid_token() {
    processCommand("R|ABCDEF012345"); TEST_ASSERT_FALSE(homeReleaseActive);
    TEST_ASSERT_TRUE(Serial1.outputContains("INVALID_TOKEN"));
}
void test_home_uncalibrated_pressure() {
    pressureCalibrated = false; beginHome(); TEST_ASSERT_FALSE(homeReleaseActive); noHomeSuccess();
}
void test_home_stale_pressure_prevents_start() {
    scale._offset = -1050203; sample(36.61); scale._ready = false; now += 501;
    processCommand("R|012345abcdef"); TEST_ASSERT_FALSE(homeReleaseActive); noHomeSuccess();
}
void test_home_sensor_loss() {
    beginHome(500); scale._ready = false; now += 501; serviceHomeRelease();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_invalid_pressure() {
    beginHome(500); scale._raw = 8388607; serviceHomeRelease();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_pressure_guard() {
    beginHome(500); sample(47); TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_stop_pin() {
    beginHome(500); _pin_levels[STOP_PIN] = LOW; serviceHomeRelease();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_short_position_is_not_cached_home() {
    beginHome(); Wire.responseBytes = 1; restHome();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_timed_out_position() {
    beginHome(); Wire.responseTimeout = true; restHome();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_out_of_range_position() {
    beginHome(); Wire.position_12 = 4096; restHome();
    TEST_ASSERT_TRUE(pressureFault); noHomeSuccess();
}
void test_home_stationary_interval_restarts_on_movement() {
    beginHome(); now += 200; sample(36.61); Wire.position_12 = 90; serviceHomeRelease();
    now += 100; sample(36.61); serviceHomeRelease(); TEST_ASSERT_FALSE(homeReleaseReady);
    restHome(); TEST_ASSERT_TRUE(homeReleaseReady);
}
void test_home_post_stop_overshoot_is_not_corrected() {
    // Held stopped, never driven outward, rejected once the reading persists.
    beginHome(); Wire.position_12 = 74; restHome();
    TEST_ASSERT_TRUE(homeReleaseActive); TEST_ASSERT_EQUAL(0, speed(12));
    TEST_ASSERT_FALSE(Serial1.outputContains("COMMAND_REJECTED"));
    now += HOME_BELOW_CONFIRM_MS; sample(36.61); serviceHomeRelease();
    TEST_ASSERT_TRUE(Serial1.outputContains("COMMAND_REJECTED|R|POSITION_OUT_OF_TOLERANCE"));
    TEST_ASSERT_FALSE(homeReleaseActive); TEST_ASSERT_FALSE(pressureFault);
    TEST_ASSERT_EQUAL(0, speed(12)); noHomeSuccess();
}
void test_home_token_required_for_tare() {
    beginHome(); restHome(); processCommand("L1|HOME|abcdef012345"); noHomeSuccess();
}
void test_home_stop_invalidates_proof() {
    beginHome(); restHome(); processCommand("X");
    processCommand("L1|HOME|012345abcdef"); noHomeSuccess();
}
void test_home_configuration_invalidates_proof() {
    beginHome(); restHome(); processCommand("L5|100|1900");
    processCommand("L1|HOME|012345abcdef"); noHomeSuccess();
}
void test_home_last_tare_sample_checks_position_loss() {
    startHomeTare(); homeSamples(9); Wire.responseBytes = 1; homeSamples(1); noHomeSuccess();
}
void test_home_last_tare_sample_checks_movement() {
    startHomeTare(); homeSamples(9); Wire.position_12 = 86; homeSamples(1); noHomeSuccess();
}
void test_home_last_tare_sample_checks_stop_pin() {
    startHomeTare(); homeSamples(9); _pin_levels[STOP_PIN] = LOW;
    homeSamples(1); noHomeSuccess();
}
void test_home_unstable_keeps_offset_and_allows_same_token_retry() {
    startHomeTare();
    for (int i = 0; i < 300; ++i) { now += 100; sample((i % 2) ? 36 : 38); }
    TEST_ASSERT_FALSE(tareActive || pressureCalibrated); TEST_ASSERT_TRUE(homeReleaseReady);
    TEST_ASSERT_EQUAL(-1050203, scale.get_offset());
    processCommand("L1|HOME|012345abcdef"); homeSamples(10);
    TEST_ASSERT_TRUE(pressureCalibrated);
}
void runHomeReleaseTests() {
    RUN_TEST(test_home_residual_load_stops_then_separately_zeroes);
    RUN_TEST(test_home_above_band_retracts_to_margin_inside_band);
    RUN_TEST(test_home_already_in_band_verifies_without_travel);
    RUN_TEST(test_home_rebound_above_band_after_stop_retracts_again);
    RUN_TEST(test_home_feedback_dropout_is_not_a_verdict);
    RUN_TEST(test_home_below_band_blip_recovers_when_reading_returns);
    RUN_TEST(test_home_position_read_retries_before_fault);
    RUN_TEST(test_home_position_read_faults_after_consecutive_failures);
    RUN_TEST(test_general_position_read_retries_before_invalid);
    RUN_TEST(test_home_lower_edge_is_inclusive);
    RUN_TEST(test_home_below_band_never_drives_outward);
    RUN_TEST(test_home_configured_mark_is_preserved);
    RUN_TEST(test_home_duplicate_does_not_extend_deadline);
    RUN_TEST(test_home_deadline_with_fresh_samples);
    RUN_TEST(test_home_stop_write_failure);
    RUN_TEST(test_home_short_stop_write);
    RUN_TEST(test_home_pending_stop_blocks_start);
    RUN_TEST(test_home_accepted_output_blocks_start);
    RUN_TEST(test_home_invalid_token);
    RUN_TEST(test_home_uncalibrated_pressure);
    RUN_TEST(test_home_stale_pressure_prevents_start);
    RUN_TEST(test_home_sensor_loss);
    RUN_TEST(test_home_invalid_pressure);
    RUN_TEST(test_home_pressure_guard);
    RUN_TEST(test_home_stop_pin);
    RUN_TEST(test_home_short_position_is_not_cached_home);
    RUN_TEST(test_home_timed_out_position);
    RUN_TEST(test_home_out_of_range_position);
    RUN_TEST(test_home_stationary_interval_restarts_on_movement);
    RUN_TEST(test_home_post_stop_overshoot_is_not_corrected);
    RUN_TEST(test_home_token_required_for_tare);
    RUN_TEST(test_home_stop_invalidates_proof);
    RUN_TEST(test_home_configuration_invalidates_proof);
    RUN_TEST(test_home_last_tare_sample_checks_position_loss);
    RUN_TEST(test_home_last_tare_sample_checks_movement);
    RUN_TEST(test_home_last_tare_sample_checks_stop_pin);
    RUN_TEST(test_home_unstable_keeps_offset_and_allows_same_token_retry);
}
