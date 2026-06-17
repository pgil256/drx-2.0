// main/motor/test/test_clamp/test_clamp.cpp
//
// Unit tests for the pure value-handling helpers in motor.ino:
//   - clampPressureTarget()  : clamps a pressure target to [MIN, MAX]_PRESSURE_LBS
//   - clampPositionTarget()  : clamps a position to the per-actuator safe range
//   - getValue()             : splits a delimited String and returns one field
//
// These functions are not exercised by the other suites. They are
// deterministic and side-effect free, so they make a good fast smoke test of
// the firmware's safety-clamping and parsing primitives.
#ifdef UNIT_TEST

#include <unity.h>
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

// Instantiate mock globals (same pattern as the other suites).
MockWire Wire;
MockSerial Serial;
MockSerial Serial1;

// Provide stubs for Arduino timing functions used in motor.ino.
unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) {}

// Include the main firmware (clampPressureTarget, clampPositionTarget,
// getValue and friends become available).
#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    _millis_value = 0;
}

void tearDown(void) {}

// --- clampPressureTarget ---
void test_pressure_within_range_unchanged(void) {
    TEST_ASSERT_EQUAL_FLOAT(40.0, clampPressureTarget(40.0));
}

void test_pressure_below_min_clamped(void) {
    TEST_ASSERT_EQUAL_FLOAT((float)MIN_PRESSURE_LBS, clampPressureTarget(-10.0));
}

void test_pressure_above_max_clamped(void) {
    TEST_ASSERT_EQUAL_FLOAT((float)MAX_PRESSURE_LBS, clampPressureTarget(999.0));
}

void test_pressure_at_max_boundary_unchanged(void) {
    TEST_ASSERT_EQUAL_FLOAT((float)MAX_PRESSURE_LBS,
                            clampPressureTarget((float)MAX_PRESSURE_LBS));
}

// --- clampPositionTarget ---
void test_position_axial_below_min_clamped(void) {
    // Device 12 (axial) min is AXIAL_MIN_POS.
    TEST_ASSERT_EQUAL(AXIAL_MIN_POS, clampPositionTarget(12, 0));
}

void test_position_axial_above_max_clamped(void) {
    TEST_ASSERT_EQUAL(AXIAL_MAX_POS, clampPositionTarget(12, 60000));
}

void test_position_horizontal_below_min_clamped(void) {
    // Device 13 (horizontal) min is HORIZONTAL_MIN_POS (non-zero).
    TEST_ASSERT_EQUAL(HORIZONTAL_MIN_POS, clampPositionTarget(13, 0));
}

void test_position_lateral_within_range_unchanged(void) {
    // Device 14 (lateral) range is [LATERAL_MIN_POS, LATERAL_MAX_POS];
    // 1500 sits inside it for the configured firmware constants.
    TEST_ASSERT_EQUAL(1500, clampPositionTarget(14, 1500));
}

void test_position_lateral_above_max_clamped(void) {
    TEST_ASSERT_EQUAL(LATERAL_MAX_POS, clampPositionTarget(14, 65000));
}

// --- getValue ---
void test_getvalue_extracts_first_field(void) {
    String result = getValue(String("100 200"), ' ', 0);
    TEST_ASSERT_EQUAL_STRING("100", result.c_str());
}

void test_getvalue_extracts_second_field(void) {
    String result = getValue(String("100 200"), ' ', 1);
    TEST_ASSERT_EQUAL_STRING("200", result.c_str());
}

void test_getvalue_missing_index_returns_empty(void) {
    String result = getValue(String("100 200"), ' ', 5);
    TEST_ASSERT_EQUAL_STRING("", result.c_str());
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_pressure_within_range_unchanged);
    RUN_TEST(test_pressure_below_min_clamped);
    RUN_TEST(test_pressure_above_max_clamped);
    RUN_TEST(test_pressure_at_max_boundary_unchanged);

    RUN_TEST(test_position_axial_below_min_clamped);
    RUN_TEST(test_position_axial_above_max_clamped);
    RUN_TEST(test_position_horizontal_below_min_clamped);
    RUN_TEST(test_position_lateral_within_range_unchanged);
    RUN_TEST(test_position_lateral_above_max_clamped);

    RUN_TEST(test_getvalue_extracts_first_field);
    RUN_TEST(test_getvalue_extracts_second_field);
    RUN_TEST(test_getvalue_missing_index_returns_empty);

    return UNITY_END();
}

#endif // UNIT_TEST
