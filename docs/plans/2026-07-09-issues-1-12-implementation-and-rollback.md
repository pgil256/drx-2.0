# KneeSpa Issues 1-12 Implementation and Rollback

**Date:** 2026-07-09  
**Baseline:** `176b9db`  
**Companion plan:** `docs/plans/2026-07-09-issues-1-12-remediation-plan.md`  
**Scope:** Audit issues 1 through 12. Configuration-preset issue 13 is not part of this change.

## Implemented Changes

### 1. FIT is covered by every firmware stop path

- Added one firmware FIT-stop operation that clears timed-motion state and drives both FIT direction pins low.
- `emergencyStop()` now stops FIT in addition to SMC devices 12, 13, and 14.
- FIT is included in `activeMotion`, so the physical STOP input and host-heartbeat timeout cover it.
- Added native tests for serial stop, physical STOP, and heartbeat loss during FIT motion.

### 2. Application shutdown drains safety traffic

- Added observable command-write state and a bounded `wait_for_drain()` transport operation.
- `disconnect()` can now wait for queued writes before closing and reports a drain timeout.
- Application cleanup gives the queued `X`, `P0`, and `HF0` stop sequence time to reach the serial driver before teardown.
- Pending protocol-v2 command handles are resolved as disconnected instead of hanging forever.

### 3. Horizontal motion uses calibrated BMarks

- Setup Go and horizontal jog now convert degrees through `horizontal_degrees_to_position()`.
- Horizontal movement uses absolute `I13<position>` commands instead of the uncalibrated `A13<inches>` approximation.
- Reset, Go, and Jog now share the same calibrated coordinate system.

### 4. Pressure Reset performs a real release

- Pressure Reset now sends `P0` instead of immediately changing the display to zero.
- The UI enters a releasing state and keeps showing measured feedback.
- `RELEASED` and status feedback update the Setup pressure readout and restore controls.

### 5. Protocol-v2 acknowledgements are sequence matched

- Added `CommandHandle` with written/completed events, sequence, result, and reason.
- Added `send_tracked()` while retaining the existing boolean `send()` API.
- `DONE`, `OK`, `BUSY`, and `ERR` resolve only their matching pending sequence.
- Unknown and stale acknowledgements are logged and ignored.
- ResetWorker waits on its specific command handle when protocol v2 is active.
- Protocol-v2 mode rejects status frames without a valid checksum trailer.

### 6. Fault state persists until recovery

- Protocol completion now distinguishes success, an operator-requested stop, and failure using the stop-request state.
- Failed completion remains in `fault`; it no longer hides the red banner by transitioning to idle.
- Start is disabled in fault state and direct restart attempts are refused until recovery.
- Successful reset returns the application to idle; failed reset remains faulted.

### 7. Stop stays reachable and FIT DONE means completion

- Setup Stop buttons are excluded from the motion-control lock group.
- Leg Length Go is disabled because FIT has no absolute-position sensor.
- Firmware retains the active FIT sequence and sends DONE only when timed movement physically completes.
- Conflicting FIT movement commands receive BUSY; `F0` remains immediately actionable.
- The PTY FakeArduino mirrors the delayed FIT completion behavior.

### 8. Leg-length bounds are checked before motion

- Added one bounded FIT movement helper for normal and fast directions.
- Serial and GPIO writes occur only after the requested movement passes range validation.
- Rejected movements do not show a spinner, change the estimate, or drive GPIO.
- Failed sends restore the UI and leave the position estimate unchanged.

### 9. Arduino QThread teardown is deterministic

- `Arduino.run()` emits `finished` in a `finally` block.
- Added one teardown path that disconnects transport, quits the QThread, waits up to three seconds, and releases stopped objects.
- Reconnection refuses to overwrite a thread that did not stop.
- References are retained if a QThread remains live, preventing destruction of a running wrapper.

### 10. Leg Length Go no longer locks Setup

- The Leg Length row declares that absolute Go is unsupported.
- Its Go button is disabled with an explanatory tooltip.
- Direct handler calls return before spinner or control-lock activation.

### 11. Failed motion sends no longer fabricate success

- Added a shared Setup send helper that checks the transport result.
- Failure leaves displayed/commanded position unchanged, restores controls, marks Arduino offline, and alerts the operator.
- Axial, horizontal, lateral, pressure, reset, and FIT paths use the checked send behavior.
- Setup pressure and lateral live values are refreshed from device status.

### 12. Start exceptions restore coherent state

- The start/stop exception path now clears partial worker/timer state and transitions through the state machine.
- Recoverable start exceptions return to idle with `protocol_running=False`.
- Button and navigation state are driven by `set_state()` instead of direct exception-path styling.

## Files Changed

### Runtime and firmware

- `main/motor/motor.ino`
- `main/helpers/arduino.py`
- `main/helpers/reset_worker.py`
- `main/helpers/protocols.py`
- `main/controllers/connection_manager.py`
- `main/controllers/protocol_controller.py`
- `main/kneespa.py`
- `main/ui/screens/setup.py`

### Test infrastructure and coverage

- `tests/fixtures/fake_arduino.py`
- `main/motor/test/test_safety/test_safety.cpp`
- Arduino transport, reset, connection, protocol-state, Setup wiring, actuator-control, treatment UI, and screen integration tests under `tests/`.

## Deployment Notes

The host and firmware changes should be deployed together. In particular, the new host assumes that FIT DONE represents physical completion, while the previous firmware emitted DONE immediately at command acceptance.

Before treating a patient:

1. Flash the updated `main/motor/motor.ino`.
2. Deploy the matching Python application.
3. Run the physical-device checklist from the companion remediation plan.
4. Verify GPIO16 emergency-stop polarity separately; that measurement remains a hardware acceptance item.
5. Keep `KNEESPA_PROTOCOL_V2=0` until the matching v2 firmware/host round-trip has been validated on the target device.

## Rollback Strategy

### Preferred release rollback

Use a normal Git revert of the remediation commit rather than rewriting history:

```text
git revert <remediation-commit>
```

Build and deploy the resulting host package, then flash the firmware from the same pre-remediation release. Host and firmware must be rolled back as a pair because FIT acknowledgement timing changed.

### Device rollback procedure

1. Remove the device from clinical use and ensure no patient is attached.
2. Use the physical power/interlock path to guarantee all actuators are stopped.
3. Save the current runtime config, auth data, and logs; this change does not require a configuration migration.
4. Deploy the previous Python release from the baseline or last known-good tag.
5. Flash the corresponding previous firmware image.
6. Restore the previous environment flags. `KNEESPA_PROTOCOL_V2=0` is the immediate compatibility fallback for v2-specific problems.
7. Power-cycle the controller and Arduino.
8. Verify serial connection, physical STOP, on-screen E-stop, pressure release, and actuator homing with no patient attached.
9. Return the device to service only after the prior release's acceptance checklist passes.

### Subsystem rollback guidance

- **V2 acknowledgement matching:** Set `KNEESPA_PROTOCOL_V2=0` for an immediate operational fallback, then investigate before re-enabling.
- **Horizontal calibration:** Do not fall back to `A13<inches>` on a patient device. If BMarks are suspect, disable horizontal manual motion and restore a previously verified host/config pair.
- **FIT timing/stop behavior:** Roll back host and firmware together. Mixing the new host with old immediate-DONE firmware reintroduces the unsafe control-unlock window.
- **Thread/drain behavior:** If shutdown or reconnect regresses, take the device out of service and roll back the complete host application; do not bypass bounded safety draining locally.
- **Protocol state/UI behavior:** A UI-only rollback is technically possible, but the complete host revert is preferred so state-machine tests and runtime behavior remain aligned.

## Rollback Validation

After any rollback, run:

```text
python -m pytest
bash main/motor/run_native_tests.sh
python scripts/validate_fixes.py
python scripts/check_limits_sync.py
```

Then perform an unoccupied-device check of every stop path and pressure release before clinical use.

## Verification Record

- Targeted Python remediation tests: **261 passed**.
- Native firmware tests after FIT additions: **95 passed**.
- Audit validation script: **12 passed, 0 failed**.
- Host/firmware safety-limit sync: **10 checks passed**.
- Full Python suite: **586 passed, 39 skipped**.
- WSL/POSIX suite including PTY serial integration: **625 passed**.
- Physical Raspberry Pi/Arduino validation: required before deployment; not available in this Windows workspace.
