#!/usr/bin/env python3
"""Run the local audit regression gate with the current Python interpreter.

Requires requirements-test.txt. Run from any directory. The first failing
child's exit status is returned unchanged. CI runs the limit check and full
pytest suite separately, so it does not repeat this selection.

See docs/plans/2026-09-14-f1-verification-record.md for the coverage inventory.
Firmware builds and deployment use main/motor/; this Python gate does not build
firmware or assert the absence of historical firmware paths.
"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# Explicit behavioral node IDs; parametrized nodes run all their cases.
TEST_NODES = (
    "tests/unit/test_arduino_send.py::"
    "TestSendQueuesCommand::test_send_returns_true_and_queues",
    "tests/unit/test_arduino_send.py::"
    "TestSendQueuesCommand::test_send_never_writes_inline",
    "tests/unit/test_arduino_send.py::"
    "TestSendQueuesCommand::test_emergency_stop_uses_priority_queue",
    "tests/unit/test_arduino_send.py::"
    "TestSendNoUsableLink::test_send_returns_false_when_serial_none",
    "tests/unit/test_arduino_send.py::"
    "TestSendNoUsableLink::test_send_returns_false_when_port_closed",
    "tests/unit/test_arduino_send.py::"
    "TestSendNoUsableLink::test_send_returns_false_when_io_loop_stopped",
    "tests/unit/test_arduino_send.py::"
    "TestSendNoUsableLink::test_nothing_queued_on_dead_link",
    "tests/unit/test_arduino_send.py::"
    "TestVerifyConnection::test_verify_returns_true_when_ok_received",
    "tests/unit/test_arduino_send.py::"
    "TestVerifyConnection::test_verify_returns_false_on_timeout",
    "tests/unit/test_arduino_send.py::"
    "TestVerifyConnection::test_verify_retries_until_tries_exhausted",
    "tests/unit/test_arduino_send.py::"
    "TestVerifyConnection::test_verify_clears_ready_event_when_not_open",
    "tests/unit/test_connection_manager.py::"
    "TestEnsureConnection::test_verified_connection_passes_without_reset",
    "tests/unit/test_connection_manager.py::"
    "TestEnsureConnection::test_failed_reconnect_returns_false_and_alerts",
    "tests/unit/test_protocol_controller.py::"
    "TestStartGates::test_connection_failure_returns_to_idle",
    "tests/unit/test_protocol_controller.py::"
    "TestStartGates::test_successful_start_reaches_running",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_rejects_negative_target",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_rejects_over_max_safe_target",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_returns_true_when_target_reached",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_sends_initial_pressure_command",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_sends_final_target_pressure_command",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_ramps_through_increments_toward_target",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_returns_false_when_initial_pressure_command_fails",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_aborts_when_status_never_reaches_target",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_aborts_when_later_pressure_command_is_rejected",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_aborts_when_increment_never_stabilizes",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_aborts_after_final_pressure_retries_exhausted",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_cancellation_during_wait_aborts_without_escalating",
    "tests/unit/test_protocol_pressure.py::"
    "TestRunPressureSequence::test_aborts_immediately_when_not_running",
    "tests/unit/test_protocol_pressure.py::"
    "TestUpdateStatus::test_drives_pressure_loop_to_completion",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToCDistance::test_rejected_send_does_not_claim_arrival",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToCDistance::test_unverified_position_times_out",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToCDistance::test_cancellation_interrupts_position_wait",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToCDistance::test_exact_mark_lookup",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToPressure::test_rejected_send_returns_false",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToPressure::test_unverified_pressure_times_out",
    "tests/unit/test_protocol_logic.py::"
    "TestSetToPressure::test_sends_pressure_command",
    "tests/unit/test_protocol_pause.py::"
    "test_cancelled_worker_rejects_commands_even_if_running_flag_is_reset",
    "tests/unit/test_protocol_pause.py::"
    "test_cancellation_while_paused_aborts_ramp",
    "tests/unit/test_protocol_pause.py::"
    "test_ramp_blocks_at_entry_when_paused",
    "tests/unit/test_protocol_pause.py::"
    "test_ramp_stops_escalating_when_paused_mid_ramp",
    "tests/unit/test_protocol_live_settings.py::"
    "test_set_to_pressure_waits_for_firmware_done",
    "tests/unit/test_protocol_live_settings.py::"
    "test_set_to_pressure_proceeds_if_done_never_arrives",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorHorizontal::test_above_max_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorHorizontal::test_below_min_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorHorizontal::test_at_max_boundary_is_inclusive",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorAxial::test_above_max_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorAxial::test_below_min_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorAxial::test_in_range_sends_expected_command",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorLateral::test_above_max_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorLateral::test_below_min_does_not_send",
    "tests/unit/test_actuator_controls.py::"
    "TestMoveActuatorLateral::test_in_range_sends_mapped_position_command",
    "tests/unit/test_conversions.py::"
    "TestLateralDegreesToPosition::test_clamps_out_of_range_input",
    "tests/unit/test_conversions.py::"
    "TestHorizontalDegreesToPosition::test_clamps_below_range",
    "tests/unit/test_conversions.py::"
    "TestHorizontalDegreesToPosition::test_clamps_above_range",
    "tests/unit/test_controller_wiring.py::"
    "TestSetupGo::test_horizontal_go_uses_calibrated_absolute_position",
    "tests/unit/test_controller_wiring.py::"
    "TestSetupGo::test_apply_pressure_clamps_above_max",
    "tests/unit/test_controller_wiring.py::"
    "TestSetupGo::test_apply_pressure_clamps_below_min",
    "tests/unit/test_secure_auth.py::"
    "TestPinHashing::test_pbkdf2_roundtrip",
    "tests/unit/test_secure_auth.py::"
    "TestPinHashing::test_salts_are_unique",
    "tests/unit/test_secure_auth.py::"
    "TestPinHashing::test_legacy_sha256_still_verifies",
    "tests/unit/test_secure_auth.py::"
    "TestPinHashing::test_malformed_stored_hash_rejected",
    "tests/unit/test_csv_helper.py::"
    "TestLoadCsvLegacyPin::test_plaintext_pin_is_hashed",
    "tests/unit/test_csv_helper.py::"
    "TestLoadCsvLegacyPin::test_plaintext_pin_removed_from_row",
    "tests/unit/test_csv_helper.py::"
    "TestLoadCsvLegacyPin::test_migrated_hash_is_salted_and_verifiable",
    "tests/unit/test_csv_helper.py::"
    "TestLoadCsvValidFile::test_loads_all_rows_keyed_by_pin_hash",
    "tests/unit/test_csv_helper.py::"
    "TestInitializeDataEnvOverride::test_prehashed_pin_used_as_is",
    "tests/unit/test_constants.py::"
    "TestEnvironmentOverrides::test_base_directory_controls_default_paths",
    "tests/unit/test_constants.py::"
    "TestEnvironmentOverrides::test_explicit_config_path_overrides_base",
    "tests/unit/test_constants.py::"
    "TestEnvironmentOverrides::test_smtp_environment_overrides",
    "tests/unit/test_config.py::"
    "TestConfigurationMissingFile::test_missing_file_persists_complete_defaults",
    "tests/unit/test_config_defaults.py::"
    "test_protocol_defaults_fallbacks",
    "tests/unit/test_kneespa_cli.py::"
    "test_main_routes_options",
)


def validate_fixes() -> int:
    """Run limits, then selected regressions, returning the first failing status."""
    checks = (
        ("host/firmware limits", [sys.executable, str(ROOT / "scripts" / "check_limits_sync.py")]),
        ("selected behavioral regressions", [sys.executable, "-m", "pytest", "-q", *TEST_NODES]),
    )
    for label, command in checks:
        print(f"Running {label}...", flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, check=False)
        except OSError as error:
            print(f"Could not start validation: {error}", file=sys.stderr)
            return 1
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(validate_fixes())
