# KneeSpa Issues 1-12 Remediation Plan

**Date:** 2026-07-09  
**Repository:** `drx-2.0`  
**Baseline commit:** `176b9db`  
**Scope:** Issues 1 through 12 from the current application bug audit. Issue 13, concerning the bundled configuration presets, is intentionally excluded.

## Objectives

- Make every emergency-stop path stop every actuator, including the leg-length/FIT actuator.
- Guarantee that stop and pressure-release commands are not discarded during shutdown.
- Use calibrated motion targets consistently.
- Correlate protocol-v2 acknowledgements with the command that produced them.
- Keep protocol, fault, connection, and UI states synchronized.
- Ensure Setup controls remain safe and recover correctly after rejected or failed commands.
- Shut down all communication threads deterministically.

## Phase 1: Capture the Bugs With Failing Tests

Before changing behavior, add regression tests for every reproducible defect:

- Native firmware tests for FIT emergency stopping, heartbeat coverage, delayed FIT completion, and motion bounds.
- Python unit tests for shutdown queue draining, sequence matching, fault-state persistence, failed sends, and start-state recovery.
- Qt tests for enabled Stop controls, Leg Length Go behavior, and thread cleanup.
- POSIX integration tests for ordered serial writes and acknowledgement correlation.

These tests should fail against the baseline and become the acceptance criteria for the fixes below.

## Issue 1: Emergency Stop Does Not Stop the FIT Actuator

### Changes

1. Refactor the firmware into a single `stopAllMotion()` operation.
2. Make it:
   - Stop SMC actuators 12, 13, and 14.
   - Clear `moveFITForward`.
   - Reset the FIT timer and active FIT command state.
   - Drive both FIT direction pins low.
3. Include FIT activity in `activeMotion`.
4. Apply the same stop operation to:
   - Serial `X` commands.
   - The physical STOP input.
   - Heartbeat expiration.
   - Firmware fault paths.
5. Keep the separate GPIO16 hardware-interlock path, but do not depend on it as the only way to stop FIT motion.

### Verification

- Start FIT motion in every direction and speed.
- Invoke serial `X`, physical STOP, and heartbeat expiration separately.
- Assert that both FIT pins are low and all motion flags are cleared.
- Confirm the existing SMC stop behavior remains intact.

## Issue 2: Shutdown Discards Stop and Release Commands

### Changes

1. Replace the current `worker.stop(); disconnect()` sequence with a coordinated shutdown state.
2. Stop protocol work without immediately closing the transport.
3. Queue the safety stop/release operation on the priority path.
4. Track when the safety command has actually been written to the serial port.
5. Keep the application in a visible `RELEASING TRACTION` state until one of the following occurs:
   - Firmware emits `RELEASED`.
   - Measured pressure falls below the release threshold.
   - A bounded timeout expires.
6. Only then close serial and terminate communication threads.
7. Change `disconnect()` so it cannot silently clear an undelivered safety batch.
8. On timeout, retain a persistent safety warning and the hardware-stop state while teardown completes.

### Verification

- Confirm `X`/release traffic is written before the serial port closes.
- Confirm the priority safety queue is not cleared prematurely.
- Test healthy release, disconnected transport, release timeout, and repeated close requests.
- Verify no shutdown path blocks indefinitely.

## Issue 3: Horizontal Movement Ignores Calibrated BMarks

### Changes

1. Make `horizontal_degrees_to_position()` the single horizontal conversion path.
2. Replace manual `A13<inches>` commands with calibrated `I13<position>` commands.
3. Apply the same conversion to:
   - Setup Go.
   - Normal jog.
   - Fast jog.
   - Horizontal reset/home.
4. Remove the duplicated degree-to-inch approximation.
5. Keep displayed degrees separate from the raw calibrated position sent to firmware.

### Verification

- Verify -25, -10, 0, and +5 degrees against exact `BMarks` entries.
- Verify interpolation for values between marks.
- Confirm Reset, Go, and Jog produce the same target for the same angle.
- Validate the resulting positions on the physical device.

## Issue 4: Pressure Reset Changes Only the Display

### Changes

1. Make pressure Reset issue a real release command.
2. Do not immediately display zero.
3. Display a `RELEASING` state until measured feedback confirms release.
4. Update the displayed pressure from device status rather than the requested target.
5. If the command cannot be queued, show a persistent connection/safety fault.
6. If release times out, keep the measured value visible and require operator acknowledgement.

### Verification

- Assert that Reset sends the release command.
- Confirm the display remains on the measured value until feedback changes.
- Cover successful release, rejected send, firmware error, and timeout.

## Issue 5: Protocol-v2 Acknowledgements Are Not Correlated

### Changes

1. Add a pending-command registry keyed by protocol-v2 sequence number.
2. Add a tracked-send API that returns a command handle containing:
   - Sequence number.
   - Completion event.
   - Result type.
   - Error or BUSY reason.
3. Resolve `DONE`, `OK`, `BUSY`, and `ERR` only when their sequence matches a pending command.
4. Log and ignore unknown, duplicate, or stale acknowledgements.
5. Change `ResetWorker` to wait for its command's handle instead of the shared `I2Cstatus_event` when v2 is enabled.
6. Retain a clearly isolated v1 compatibility path until v2 is mandatory.
7. Require checksummed status frames whenever protocol v2 is enabled.

### Verification

- Send sequence 1 and inject `DONE|999`; sequence 1 must remain pending.
- Confirm `DONE|1` resolves only sequence 1.
- Test BUSY, ERR, timeout, duplicate acknowledgement, sequence wraparound, and disconnect cleanup.

## Issue 6: Firmware Faults Are Converted Back to Idle

### Changes

1. Replace the boolean completion result with explicit outcomes:
   - `completed`
   - `user_stopped`
   - `faulted`
2. Do not call `set_state("idle")` for a faulted completion.
3. Keep the fault banner visible and keep Start gated after a safety failure.
4. Clear fault state only after:
   - A successful recovery reset, or
   - An explicit operator acknowledgement where safe.
5. Ensure a normal operator stop does not generate the abnormal-completion safety alert.
6. Route every protocol exit through the same state-transition method.

### Verification

- Trigger a firmware error followed by worker completion.
- Confirm state remains `fault`, the banner stays visible, and Start remains unavailable.
- Confirm a normal Stop produces `user_stopped`, not `faulted`.
- Confirm a successful reset returns the application to idle.

## Issue 7: Stop Controls and FIT Completion Are Incorrect

### Changes

1. Split Setup widgets into:
   - Motion controls that may be locked.
   - Safety controls that must remain enabled.
2. Never disable row Stop or Emergency Stop controls during motion.
3. In firmware, retain the sequence number for the active FIT command.
4. Emit FIT `DONE` only when the timed movement physically completes.
5. Return `BUSY` for conflicting FIT movement commands.
6. Keep `F0` immediately actionable and make it complete the interrupted FIT command safely.
7. Do not re-enable conflicting motion controls until actual completion or stop.

### Verification

- During a six-second FIT move, confirm Stop stays enabled.
- Confirm other FIT motion controls remain locked.
- Confirm conflicting commands receive BUSY.
- Confirm DONE occurs at physical completion rather than command acceptance.

## Issue 8: Leg-Length Bounds Are Checked After Movement Starts

### Changes

1. Centralize leg-length movement validation in one helper.
2. Validate direction, current estimated position, requested speed, and remaining range before:
   - Sending a serial command.
   - Driving GPIO pins.
   - Updating the displayed position.
3. Apply the same checks to normal and fast movement.
4. Restore the spinner and control state on every early return.
5. Update the estimated leg position only after the command is accepted.
6. Where possible, shorten an open-loop movement near the boundary instead of always running the full fixed duration.

### Verification

- At 0 inches, Reverse and Reverse Fast send nothing.
- At 6 inches, Forward and Forward Fast send nothing.
- Rejected commands leave the spinner hidden and controls usable.
- Accepted movement never updates the estimate outside the configured range.

## Issue 9: Arduino QThread Never Stops

### Changes

1. Add a single connection teardown method that:
   - Stops Arduino I/O.
   - Calls `thread.quit()`.
   - Waits with a bounded timeout.
   - Calls `deleteLater()` where appropriate.
   - Clears references only after the thread stops.
2. Call this teardown method before reconnection and during application cleanup.
3. Emit `Arduino.finished` from `Arduino.run()` in a `finally` block.
4. Prevent setup from overwriting an existing live thread.
5. Consider removing the redundant QThread entirely after the safe minimal fix, since Arduino already owns a Python I/O thread.

### Verification

- Reconnect repeatedly and confirm each previous QThread stops.
- Close the application and assert no Arduino QThread or I/O thread remains alive.
- Test teardown during connection attempts, normal operation, and link loss.

## Issue 10: Leg Length Go Locks the Interface

### Changes

1. Treat Leg Length as open-loop because it has no absolute-position sensor.
2. Remove or disable the Leg Length Go button.
3. Expose only bounded jog, Stop, and Reset controls for that row.
4. Guard `_on_setup_go("leg_length")` so it returns before showing the spinner or disabling controls.
5. Add row capabilities to the Setup configuration instead of leaving a `pass` branch in the controller.

### Verification

- Confirm the Leg Length Go button is unavailable.
- Direct handler invocation must leave controls enabled and the spinner hidden.
- Confirm other rows retain functional Go buttons.

## Issue 11: Failed Sends Still Update the Interface

### Changes

1. Add a shared `_send_motion_command()` helper.
2. Require every Setup motion path to check its return value.
3. On failure:
   - Do not mutate commanded or displayed position.
   - Restore controls and spinner state.
   - Mark Arduino offline.
   - Show an operator-visible error.
4. Update actual-position displays only from status feedback.
5. If useful, display an explicit `Target` value separately from measured position.
6. Make movement handlers return a consistent success/failure result.

### Verification

- Force `send()` to return false for each actuator and pressure control.
- Confirm state and display remain unchanged.
- Confirm controls recover and an error is shown.
- Confirm successful commands update targets without pretending they are measured positions.

## Issue 12: Start Exceptions Leave the Protocol in Starting State

### Changes

1. Treat protocol start as a state-machine transaction.
2. Route all failures through one recovery method.
3. On any exception before worker launch:
   - Stop protocol timers.
   - Clear partial worker state.
   - Restore navigation and control availability.
   - Transition to `idle` for recoverable input/connection failures.
   - Transition to `fault` for safety or unknown failures.
4. Stop directly changing button text in exception handlers; the state transition must drive the UI.
5. Guard against late callbacks from a partially created worker.

### Verification

- Force connection verification, worker construction, and thread-pool launch to raise.
- Confirm `protocol_running` is false.
- Confirm state, button, banner, and navigation agree.
- Confirm a subsequent valid start can proceed.

## Recommended Implementation Order

1. **Firmware safety:** Issues 1, 7, and 8.
2. **Stop/release lifecycle:** Issues 2 and 4.
3. **Transport correctness:** Issues 5 and 9.
4. **Protocol state machine:** Issues 6 and 12.
5. **Calibrated Setup controls:** Issues 3, 10, and 11.
6. **Full regression and physical-device validation.**

This order avoids building UI and state changes on top of unsafe firmware or an unreliable transport lifecycle.

## Final Verification

Run the full automated baseline:

```text
python -m pytest
bash main/motor/run_native_tests.sh
python scripts/validate_fixes.py
python scripts/check_limits_sync.py
```

Also run the POSIX serial integration suite under WSL/Linux and perform repeated connect/disconnect and application-close stress tests.

## Physical-Device Acceptance Checklist

- Every emergency-stop route stops FIT and all three SMC actuators.
- FIT direction pins remain low after stop, fault, heartbeat loss, and shutdown.
- Traction release completes before application shutdown.
- Pressure Reset reflects measured release rather than immediately displaying zero.
- Horizontal -25, -10, 0, and +5 degree targets match physical calibration.
- Stop remains accessible during every Setup movement.
- Leg-length bounds prevent outward movement at both limits.
- Disconnects, stale acknowledgements, and firmware faults cannot return the UI to treatment-ready state without recovery.
- Reconnection and application shutdown leave no live communication threads.

## Definition of Done

- All new regression tests pass.
- The existing Python and native firmware suites remain green.
- No safety-control path depends solely on UI state or an unverified acknowledgement.
- Protocol-v2 commands have one-to-one acknowledgement correlation.
- Fault banners remain persistent until valid recovery.
- Displayed actual values come from device feedback.
- The physical-device checklist is completed and recorded before deployment.
