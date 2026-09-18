# Test Results

**Date:** 2026-02-12
**Total:** 105 tests | **Passed:** 105 | **Failed:** 0 | **Duration:** 115.00s (1m 54s)
**Pytest timeout:** 45s per test

## Summary

| Category | Tests | Status |
|----------|-------|--------|
| Unit - Arduino Parse | 14 | All passing |
| Unit - Config | 12 | All passing |
| Unit - Constants | 16 | All passing |
| Unit - Fake Arduino | 6 | All passing |
| Unit - Protocol Logic | 13 | All passing |
| Integration - Arduino Comm | 7 | All passing |
| Integration - Pressure Dialog | 8 | All passing |
| Integration - Protocols | 8 | All passing |
| Integration - Reset Worker | 3 | All passing |

## Code Fixes Applied

### Test Fix
- **`test_finished_signal_emitted`** - Changed `duration=1` (60s) to `duration=0.1` (6s) so hold phase completes within pytest timeout.

### Safety Fixes (`main/helpers/protocols.py`)

1. **Pressure overshoot** - Added `min(current_command, target_pressure)` clamp in `run_pressure_sequence()` to prevent floating-point increment from exceeding target pressure.
2. **Emergency stop in pressure ramp** - Added `is_running` checks in all wait loops within `run_pressure_sequence()` (initial build, increment stabilization, final verification). Protocol now aborts immediately on emergency stop instead of continuing to pressurize.
3. **Emergency stop in set_to_pressure** - Added `is_running` check in the pressure stabilization wait loop. Prevents 5-second hang during emergency stop.
4. **Dead return in protocol_1** - Changed `return False` (ignored by `run()`) to `self.signals.finished.emit(False); return` so callers are properly notified of pulse failure.

### Reliability Fixes (`main/helpers/arduino.py`)

5. **Buffer flush dropping responses** - Removed `reset_input_buffer()` call in `send()` that was discarding pending status updates and acknowledgments before every command.
6. **Bounds checking on parsed tokens** - Added `len(tokens) >= N` checks for `P`, `PR`, `E`, and `weight` message types in `handle_com()` to prevent `IndexError` crashes on malformed serial data.
7. **Reader thread race condition** - Added `_reader_ready` threading event. Reader thread signals readiness; `connect_to_arduino()` waits up to 5s for it before calling `verify_connection()`.
8. **Duplicate verify_connection** - Removed redundant first `verify_connection()` call in `connect_to_arduino()` that wasted up to 10 seconds at startup.

### Threading Fix (`main/helpers/protocols.py`)

9. **Shared state race condition** - Added `_state_lock` with property accessors for `current_pressure` and `current_pos_c`, ensuring thread-safe reads/writes between the Arduino reader thread and protocol execution thread.

## Detailed Results

### Unit Tests

#### `tests/unit/test_arduino_parse.py` (14 tests - all passing)
- [x] `TestStatusParsing::test_valid_status_emits_signal`
- [x] `TestStatusParsing::test_truncated_status_no_crash`
- [x] `TestStatusParsing::test_status_with_zero_pressure`
- [x] `TestStatusParsing::test_status_too_few_fields`
- [x] `TestDoneResponse::test_done_emits_signal`
- [x] `TestOKResponse::test_ok_sets_event`
- [x] `TestOKResponse::test_ok_in_longer_string`
- [x] `TestPositionResponse::test_position_p_format`
- [x] `TestPositionResponse::test_position_e_format`
- [x] `TestPressureResponse::test_pressure_response`
- [x] `TestWeightResponse::test_weight_response`
- [x] `TestReadyToGo::test_ready_to_go`
- [x] `TestGarbageInput::test_empty_string`
- [x] `TestGarbageInput::test_random_garbage`
- [x] `TestGarbageInput::test_partial_status_delimiter`

#### `tests/unit/test_config.py` (12 tests - all passing)
- [x] `TestConfigurationValidFile::test_cmarks_loaded`
- [x] `TestConfigurationValidFile::test_amarks_loaded`
- [x] `TestConfigurationValidFile::test_bmarks_loaded`
- [x] `TestConfigurationValidFile::test_options_loaded`
- [x] `TestConfigurationMissingFile::test_creates_file`
- [x] `TestConfigurationMissingFile::test_has_default_flexion`
- [x] `TestConfigurationCorruptFile::test_falls_back_to_default_cmarks`
- [x] `TestConfigurationCorruptFile::test_no_crash`
- [x] `TestConfigurationMissingSections::test_default_cmarks_used`
- [x] `TestConfigurationMissingSections::test_default_amarks_used`
- [x] `TestConfigurationMissingSections::test_default_bmarks_used`
- [x] `TestConfigurationRoundTrip::test_write_read_roundtrip`

#### `tests/unit/test_constants.py` (16 tests - all passing)
- [x] `TestSafetyLimits::test_pressure_max`
- [x] `TestSafetyLimits::test_min_pressure`
- [x] `TestSafetyLimits::test_min_less_than_max_pressure`
- [x] `TestSafetyLimits::test_axial_max`
- [x] `TestSafetyLimits::test_lateral_range`
- [x] `TestSafetyLimits::test_horizontal_range`
- [x] `TestGPIOPins::test_emergency_stop_pin`
- [x] `TestGPIOPins::test_extra_forward_pin`
- [x] `TestGPIOPins::test_extra_backward_pin`
- [x] `TestGPIOPins::test_extra_enable_pin`
- [x] `TestGPIOPins::test_no_duplicate_pins`
- [x] `TestActuatorConfig::test_all_actuators_defined`
- [x] `TestActuatorConfig::test_actuator_limits_ordered`
- [x] `TestActuatorConfig::test_actuator_ids_unique`
- [x] `TestActuatorConfig::test_actuator_command_prefixes`
- [x] `TestProtocolConfig::test_protocol_mapping_has_four_protocols`
- [x] `TestProtocolConfig::test_protocol_defaults_pressure_range`
- [x] `TestProtocolConfig::test_pressure_increment_positive`
- [x] `TestArduinoSettings::test_port`
- [x] `TestArduinoSettings::test_buffer_warning_threshold`
- [x] `TestArduinoSettings::test_connection_timeout_positive`

#### `tests/unit/test_config.py` additional (3 tests - all passing)
- [x] `TestConfigurationDefaults::test_default_cmarks_values`
- [x] `TestConfigurationDefaults::test_default_amarks_values`
- [x] `TestConfigurationDefaults::test_default_bmarks_values`
- [x] `TestConfigurationDefaults::test_default_c_factor`

#### `tests/unit/test_fake_arduino.py` (6 tests - all passing)
- [x] `TestFakeArduinoBasic::test_creates_pty`
- [x] `TestFakeArduinoBasic::test_responds_to_test_command`
- [x] `TestFakeArduinoBasic::test_tracks_commands`
- [x] `TestFakeArduinoBasic::test_pressure_ramp`
- [x] `TestFakeArduinoBasic::test_emergency_stop`
- [x] `TestFakeArduinoBasic::test_position_movement`

#### `tests/unit/test_protocol_logic.py` (13 tests - all passing)
- [x] `TestCheckDuration::test_returns_true_within_duration`
- [x] `TestCheckDuration::test_returns_false_after_duration`
- [x] `TestCheckDuration::test_returns_false_without_start_time`
- [x] `TestCheckDuration::test_updates_elapsed_time`
- [x] `TestSetToCDistance::test_exact_mark_lookup`
- [x] `TestSetToCDistance::test_negative_degree`
- [x] `TestSetToCDistance::test_positive_degree`
- [x] `TestSetToCDistance::test_interpolation_between_marks`
- [x] `TestSetToCDistance::test_clamps_below_minus_20`
- [x] `TestSetToCDistance::test_clamps_above_max_mark`
- [x] `TestProtocolInit::test_max_left_forced_negative`
- [x] `TestProtocolInit::test_max_right_forced_positive`
- [x] `TestProtocolInit::test_duration_converted_to_seconds`
- [x] `TestProtocolInit::test_initial_state`
- [x] `TestSetToPressure::test_rejects_negative_pressure`
- [x] `TestSetToPressure::test_rejects_over_max_pressure`
- [x] `TestSetToPressure::test_rejects_when_not_running`
- [x] `TestSetToPressure::test_sends_pressure_command`
- [x] `TestProtocolConstants::test_min_pressure`
- [x] `TestProtocolConstants::test_max_safe_pressure`
- [x] `TestProtocolConstants::test_pressure_increment`

### Integration Tests

#### `tests/integration/test_arduino_comm.py` (7 tests - all passing)
- [x] `TestArduinoConnection::test_verify_connection_sends_T`
- [x] `TestArduinoSend::test_send_pressure_command`
- [x] `TestArduinoSend::test_send_position_command`
- [x] `TestArduinoSend::test_send_emergency_stop`
- [x] `TestArduinoSend::test_send_when_disconnected`
- [x] `TestArduinoStatusSignals::test_status_emit_on_status_response`
- [x] `TestArduinoCorruptData::test_corrupt_status_no_crash`

#### `tests/integration/test_pressure_dialog.py` (8 tests - all passing)
- [x] `TestPressureDialogDisplay::test_initial_state`
- [x] `TestPressureDialogDisplay::test_update_shows_pressure`
- [x] `TestPressureDialogDisplay::test_green_under_50`
- [x] `TestPressureDialogDisplay::test_orange_between_50_and_70`
- [x] `TestPressureDialogDisplay::test_red_above_70`
- [x] `TestPressureDialogDisplay::test_small_change_not_updated`
- [x] `TestPressureDialogDisplay::test_large_change_updated`
- [x] `TestPressureDialogDisplay::test_none_pressure_handled`

#### `tests/integration/test_protocols.py` (8 tests - all passing)
- [x] `TestProtocol1Axial::test_sends_pressure_commands`
- [x] `TestProtocol1Axial::test_finished_signal_emitted`
- [x] `TestProtocol2LeftLateral::test_moves_c_actuator_left`
- [x] `TestProtocol3RightLateral::test_moves_c_actuator_right`
- [x] `TestProtocol4Oscillating::test_sends_multiple_k_commands`
- [x] `TestProtocolStop::test_stop_sends_emergency_stop`
- [x] `TestProtocolPulseToggle::test_pulse_sends_j_command`
- [x] `TestProtocolPulseToggle::test_pulse_toggle_off_sends_js`

#### `tests/integration/test_reset_worker.py` (3 tests - all passing)
- [x] `TestResetWorkerSequence::test_sends_y_command`
- [x] `TestResetWorkerSequence::test_sends_calibration_command`
- [x] `TestResetWorkerSequence::test_finished_signal_emitted`
