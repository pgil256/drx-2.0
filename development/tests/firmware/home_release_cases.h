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
void test_home_above_band_retracts_until_first_in_band_read() {
    beginHome(126); TEST_ASSERT_EQUAL(-PRESSURE_SPEED, speed(12)); restHome();
    TEST_ASSERT_FALSE(homeReleaseReady); Wire.position_12 = 125; serviceHomeRelease();
    TEST_ASSERT_TRUE(homeReleaseStopped); TEST_ASSERT_EQUAL(0, speed(12)); restHome();
    TEST_ASSERT_TRUE(homeReleaseReady);
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
    beginHome(); Wire.position_12 = 74; restHome();
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
    RUN_TEST(test_home_above_band_retracts_until_first_in_band_read);
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
