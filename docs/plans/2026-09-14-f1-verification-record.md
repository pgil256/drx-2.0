# F1 verification repair

Implemented: 2026-09-14
Scope: F1 / Phase 1A of [the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting commit: `7aa99974ff9321d738dfdcf4645a9c830450808a` (clean checkout)

## Result and boundaries

`scripts/validate_fixes.py` now runs the existing limit check followed by 72 explicit pytest selectors (81 parametrized cases), using `sys.executable` and the repository working directory. It returns the first failing child's status and stops; launch errors produce a diagnostic and status 1. It requires the dependencies in `requirements-test.txt` and supports invocation from another directory.

CI retains the separate limit check, one full pytest invocation, the native firmware suites, and the Mega build. Only the obsolete snapshot step and its comment were removed.

This implements the requested F1 verification repair only. Application and firmware code are unchanged. F2–F9 and the separate B2 deployment-state repair remain outside this change; this is not completion of all Phase 1 prerequisites or the full Phase 1 cleanup.

## Disposition of all 12 old checks

| Old check | Behavioral replacement or retirement | Coverage change |
| --- | --- | --- |
| 1. Arduino readiness event and queued send | Selected `test_arduino_send.py` cases assert queueing, no inline port writes, stop priority, failed links, successful verification, timeout/retries, and readiness clearing. POSIX transport tests remain in the full suite. | Reused. |
| 2. Window delegates readiness | Controller start tests now execute the actual start chain through worker construction and thread-pool dispatch. Failure prevents construction, dispatch, and timer start; success dispatches the constructed worker. Exact forwarding syntax is retired. | Extended two existing cases in `test_protocol_controller.py`. |
| 3. ConnectionManager owns readiness | `TestEnsureConnection` verifies a working connection succeeds and failed reconnection returns false, alerts, and sends no calibration commands. Class ownership/Event spelling assertions are retired. | Reused. |
| 4. Protocol start requires readiness | The same actual-dispatch cases from check 2 cover this gate. The timer placeholder explicitly reports false visibility, matching the application. | Extended; no duplicate suite. |
| 5. Protocols reject failed/unverified commands | Pressure and lateral rejection, initial/increment/final verification timeouts, final retries, cancellation during pressure/DONE/position waits, cancellation while paused, and permanent send rejection after cancellation. Existing acknowledgement and pause-thread cases remain selected. | Added 15 cases across pressure/logic/pause; bounded existing pressure waits. |
| 6. UI limits use human units | Actuator jog boundaries, conversion clamping, and setup commands (including pressure clamps and calibrated horizontal positions). | Reused from actuator controls, conversions, and controller wiring. |
| 7. Firmware hard clamps | Existing `check_limits_sync.py`, CI native clamp/parse suites, and CI Mega build. | Retained; no additional Python source assertions. |
| 8. Duplicate firmware path absent | Retired historical deletion assertion. `main/motor/` is the firmware build/deployment source; future firmware-packaging changes must inspect actual build inputs. | Explicit retirement. |
| 9. Authentication uses hashes | Salted hash round trips, unique salts, legacy SHA-256 compatibility, malformed hashes, CSV plaintext migration, removal of plaintext fields, and prehashed inputs. | Reused from secure auth and CSV tests. |
| 10. Environment-configurable paths/credentials | Base-directory-derived paths, custom config precedence, and SMTP username/password/server/port plus assistance/ticket recipients. Child imports use synthetic environment values and do not reload the parent's constants. | Added three cases in `test_constants.py`. |
| 11. Missing config creates complete defaults | A fresh temporary file persists numeric, ordered A/B/C marks and reloads matching defaults while remaining uncalibrated. Existing protocol-default values remain checked. | Added one round-trip case in `test_config.py`; reused `test_protocol_defaults_fallbacks`. |
| 12. Documented CLI options | Calls real `kneespa.main` with faked app/window/theme/exit/log boundaries; checks defaults, each documented option, combined options, and post-event-loop log ordering. | Added six cases in `test_kneespa_cli.py`. |

The new opt-in `protocol_clock` fixture replaces only `helpers.protocols.time`. Simulated sleeps advance time; successful pressure sends explicitly acknowledge DONE. Cancellation can be injected on a sleep. Production timeout values, retries, command order, and the bounded continue-on-missing-DONE behavior are unchanged. Existing real-thread missing-DONE and delayed-DONE tests in `test_protocol_live_settings.py` and POSIX integration tests retain real time.

Eight additional cases in `test_validate_fixes.py` verify success, failure propagation, first-failure short-circuiting, current interpreter/repository directory, launch errors, and the shell entry point. Two execute real children in isolated fixture repositories: a limit child exits 7 and prevents pytest from running; a deliberately failing pytest child returns 1. These runner-contract tests run in full pytest and the focused gate, without recursively invoking the real selected suite.

## Verification

Results apply to the F1 working-tree change on the starting commit above, not to a deployed or flashed revision.

| Gate | Result |
| --- | --- |
| Focused changed tests plus runner contracts | 198 passed in 3.47 s. |
| Local runner, launched outside the repository | 11 limits passed; 81 selected cases passed in 2.90 s (3.90 s command wall time). |
| Full Windows pytest | 851 passed, 39 POSIX skips, no warnings, in 25.61 s. |
| Full WSL/Linux pytest | 890 passed, no skips or warnings, in 51.46 s (Python 3.14.4, pytest 9.0.3). |
| Existing firmware CI jobs | Both preserved; not manually rebuilt for this verification-only change. |

The first Windows focused invocation could not use the existing default temp/cache directories due to local permissions (170 passed, 20 fixture setup errors). The successful runs use fresh task-specific temp/cache paths; no tests were disabled to work around this.

Commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_pressure.py tests/unit/test_protocol_logic.py tests/unit/test_protocol_pause.py tests/unit/test_protocol_controller.py tests/unit/test_constants.py tests/unit/test_config.py tests/unit/test_kneespa_cli.py tests/unit/test_validate_fixes.py --durations=8 --basetemp=.f1-focused-tmp -o cache_dir=.f1-pytest-cache
.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f1-windows-full-tmp -o cache_dir=.f1-pytest-cache
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f1-linux-full -o cache_dir=/tmp/drx-f1-linux-cache
```

The local runner was invoked by absolute path from the parent directory, with `PYTEST_ADDOPTS` pointing to fresh absolute `.f1-runner-tmp` and `.f1-pytest-cache` directories. In an environment with writable pytest defaults, the supported command remains:

```text
python scripts/validate_fixes.py
```

## Exact selected cases

`TEST_NODES` names 72 methods, including all parameters for selected parametrized methods. Collection expands to the following 81 exact node IDs. New coverage is identified in the disposition table; all other selected cases are reused.

```text
tests/unit/test_arduino_send.py::TestSendQueuesCommand::test_send_returns_true_and_queues
tests/unit/test_arduino_send.py::TestSendQueuesCommand::test_send_never_writes_inline
tests/unit/test_arduino_send.py::TestSendQueuesCommand::test_emergency_stop_uses_priority_queue
tests/unit/test_arduino_send.py::TestSendNoUsableLink::test_send_returns_false_when_serial_none
tests/unit/test_arduino_send.py::TestSendNoUsableLink::test_send_returns_false_when_port_closed
tests/unit/test_arduino_send.py::TestSendNoUsableLink::test_send_returns_false_when_io_loop_stopped
tests/unit/test_arduino_send.py::TestSendNoUsableLink::test_nothing_queued_on_dead_link
tests/unit/test_arduino_send.py::TestVerifyConnection::test_verify_returns_true_when_ok_received
tests/unit/test_arduino_send.py::TestVerifyConnection::test_verify_returns_false_on_timeout
tests/unit/test_arduino_send.py::TestVerifyConnection::test_verify_retries_until_tries_exhausted
tests/unit/test_arduino_send.py::TestVerifyConnection::test_verify_clears_ready_event_when_not_open
tests/unit/test_connection_manager.py::TestEnsureConnection::test_verified_connection_passes_without_reset
tests/unit/test_connection_manager.py::TestEnsureConnection::test_failed_reconnect_returns_false_and_alerts
tests/unit/test_protocol_controller.py::TestStartGates::test_connection_failure_returns_to_idle
tests/unit/test_protocol_controller.py::TestStartGates::test_successful_start_reaches_running
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_rejects_negative_target
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_rejects_over_max_safe_target
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_returns_true_when_target_reached
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_sends_initial_pressure_command
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_sends_final_target_pressure_command
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_ramps_through_increments_toward_target
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_returns_false_when_initial_pressure_command_fails
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_when_status_never_reaches_target
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_when_later_pressure_command_is_rejected[increment]
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_when_later_pressure_command_is_rejected[final]
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_when_increment_never_stabilizes
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_after_final_pressure_retries_exhausted
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_cancellation_during_wait_aborts_without_escalating[pressure]
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_cancellation_during_wait_aborts_without_escalating[ack]
tests/unit/test_protocol_pressure.py::TestRunPressureSequence::test_aborts_immediately_when_not_running
tests/unit/test_protocol_pressure.py::TestUpdateStatus::test_drives_pressure_loop_to_completion
tests/unit/test_protocol_logic.py::TestSetToCDistance::test_rejected_send_does_not_claim_arrival
tests/unit/test_protocol_logic.py::TestSetToCDistance::test_unverified_position_times_out
tests/unit/test_protocol_logic.py::TestSetToCDistance::test_cancellation_interrupts_position_wait
tests/unit/test_protocol_logic.py::TestSetToCDistance::test_exact_mark_lookup
tests/unit/test_protocol_logic.py::TestSetToPressure::test_rejected_send_returns_false
tests/unit/test_protocol_logic.py::TestSetToPressure::test_unverified_pressure_times_out
tests/unit/test_protocol_logic.py::TestSetToPressure::test_sends_pressure_command
tests/unit/test_protocol_pause.py::test_cancelled_worker_rejects_commands_even_if_running_flag_is_reset[pressure]
tests/unit/test_protocol_pause.py::test_cancelled_worker_rejects_commands_even_if_running_flag_is_reset[lateral]
tests/unit/test_protocol_pause.py::test_cancelled_worker_rejects_commands_even_if_running_flag_is_reset[pulse]
tests/unit/test_protocol_pause.py::test_cancellation_while_paused_aborts_ramp
tests/unit/test_protocol_pause.py::test_ramp_blocks_at_entry_when_paused
tests/unit/test_protocol_pause.py::test_ramp_stops_escalating_when_paused_mid_ramp
tests/unit/test_protocol_live_settings.py::test_set_to_pressure_waits_for_firmware_done
tests/unit/test_protocol_live_settings.py::test_set_to_pressure_proceeds_if_done_never_arrives
tests/unit/test_actuator_controls.py::TestMoveActuatorHorizontal::test_above_max_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorHorizontal::test_below_min_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorHorizontal::test_at_max_boundary_is_inclusive
tests/unit/test_actuator_controls.py::TestMoveActuatorAxial::test_above_max_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorAxial::test_below_min_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorAxial::test_in_range_sends_expected_command
tests/unit/test_actuator_controls.py::TestMoveActuatorLateral::test_above_max_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorLateral::test_below_min_does_not_send
tests/unit/test_actuator_controls.py::TestMoveActuatorLateral::test_in_range_sends_mapped_position_command
tests/unit/test_conversions.py::TestLateralDegreesToPosition::test_clamps_out_of_range_input
tests/unit/test_conversions.py::TestHorizontalDegreesToPosition::test_clamps_below_range
tests/unit/test_conversions.py::TestHorizontalDegreesToPosition::test_clamps_above_range
tests/unit/test_controller_wiring.py::TestSetupGo::test_horizontal_go_uses_calibrated_absolute_position
tests/unit/test_controller_wiring.py::TestSetupGo::test_apply_pressure_clamps_above_max
tests/unit/test_controller_wiring.py::TestSetupGo::test_apply_pressure_clamps_below_min
tests/unit/test_secure_auth.py::TestPinHashing::test_pbkdf2_roundtrip
tests/unit/test_secure_auth.py::TestPinHashing::test_salts_are_unique
tests/unit/test_secure_auth.py::TestPinHashing::test_legacy_sha256_still_verifies
tests/unit/test_secure_auth.py::TestPinHashing::test_malformed_stored_hash_rejected
tests/unit/test_csv_helper.py::TestLoadCsvLegacyPin::test_plaintext_pin_is_hashed
tests/unit/test_csv_helper.py::TestLoadCsvLegacyPin::test_plaintext_pin_removed_from_row
tests/unit/test_csv_helper.py::TestLoadCsvLegacyPin::test_migrated_hash_is_salted_and_verifiable
tests/unit/test_csv_helper.py::TestLoadCsvValidFile::test_loads_all_rows_keyed_by_pin_hash
tests/unit/test_csv_helper.py::TestInitializeDataEnvOverride::test_prehashed_pin_used_as_is
tests/unit/test_constants.py::TestEnvironmentOverrides::test_base_directory_controls_default_paths
tests/unit/test_constants.py::TestEnvironmentOverrides::test_explicit_config_path_overrides_base
tests/unit/test_constants.py::TestEnvironmentOverrides::test_smtp_environment_overrides
tests/unit/test_config.py::TestConfigurationMissingFile::test_missing_file_persists_complete_defaults
tests/unit/test_config_defaults.py::test_protocol_defaults_fallbacks
tests/unit/test_kneespa_cli.py::test_main_routes_options[defaults]
tests/unit/test_kneespa_cli.py::test_main_routes_options[debug]
tests/unit/test_kneespa_cli.py::test_main_routes_options[config]
tests/unit/test_kneespa_cli.py::test_main_routes_options[print-logs]
tests/unit/test_kneespa_cli.py::test_main_routes_options[sync-logs]
tests/unit/test_kneespa_cli.py::test_main_routes_options[combined]
```
