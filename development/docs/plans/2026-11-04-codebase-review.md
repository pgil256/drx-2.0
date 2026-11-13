# DRx 2.0 codebase review: what to improve first (2026-11-04)

This review covers the whole repository at commit `cda2c2b` (main after PR #51).
It ranks the areas that would gain the most from improvement. Line numbers are
as of that commit.

## How the review was done

- Four focused read-only reviews ran in parallel:
  - Arduino firmware
  - the Pi hardware and treatment layer
  - application architecture and UI
  - cloud, auth and release code
- Every finding listed under "Findings" was then checked by reading the code.
  Reviewer claims that were not checked are listed separately under
  "Reported but not yet verified".
- A claim about dropped Qt signals was tested with a small PyQt5 probe and
  ruled out (see "Ruled out").
- The full Python suite ran on Windows with coverage.
- `ruff` was run with the repository's config and with extra rules
  (`BLE001`, `S110`, `C901`) to measure exception handling and complexity.
- `development/docs/plans/2026-09-30-remaining-decisions.md` was read first, so
  items already known or decided there are not re-reported. The most important
  is the warning-only host heartbeat.

## Summary

The codebase is in good shape.

- All tests pass, line coverage is 88%, and CI covers:
  - Python 3.7, the Pi's interpreter
  - the Mega firmware build
  - firmware native tests
  - shellcheck
  - host/firmware limit sync
- The biggest gaps are in how the device stops and how the kiosk recovers from
  errors, not in code style.

The ranked areas:

1. Firmware stop and fault paths
2. Pi-side stop logic spread over many paths that disagree
3. The kiosk can get stuck or fail to restart
4. Software update integrity and crash safety
5. `kneespa.py` does too much
6. Errors are hidden instead of logged
7. Patient data and credentials stored on the device
8. Platform and test gaps

## Test and coverage baseline

- `python -m pytest` with coverage on Windows (Python 3.12, PyQt 5.15.11):
  1798 passed, 114 skipped (POSIX-only), 8 min 9 s.
- Line coverage of `runtime/raspberry-pi/main`: 88% (14,726 statements).
- Lowest-covered modules with at least 80 statements:

| Module | Coverage |
| --- | --- |
| `helpers/device_system.py` | 53% |
| `controllers/release_controller.py` | 53% |
| `controllers/connection_manager.py` | 66% |
| `ui/modals/device_dialogs.py` | 68% |
| `ui/modals/vlc_engine.py` | 71% |
| `controllers/device_controller.py` | 73% |
| `ui/modals/patient_reconcile.py` | 74% |
| `helpers/release_installer.py` | 75% |

Line coverage is high overall. The gaps that matter are untested fault
scenarios, mainly in the firmware (section 1), not uncovered lines.

## Findings

### 1. Firmware stop and fault paths (highest priority)

All in `runtime/arduino/motor/motor.ino`.

**1a. Ordinary stop commands ignore a failed I2C write.**
- `setMotorSpeed()` returns the I2C result, but only `stopDeviceOrReport`
  (line 486) checks it, on the E-stop path.
- These stops drop the result:
  - `stopPressureMotor` (770)
  - `setPulseSpeed` (777)
  - the position-arrival stop (1880)
  - the `JS` handler (1504)
  - the same-position stops in `I`, `K` and `A` (1214, 1282, 1387)
  - the end of the release (1759)
- `setPulseSpeed` records the new speed even when the write failed (783). A
  later `setPulseSpeed(0)` then returns early and sends nothing.
- Scenario: a position move reaches its target and the stop write fails. The
  firmware reports DONE while the actuator keeps driving toward its end stop.
- Fix: send every zero-speed write through one checked, retrying helper. Update
  cached speed only after the write is acknowledged.

**1b. The physical stop button can't release the load during a latched pressure fault.**
- When `pressureFault` is set, `setMotorSpeed` returns 0 ("success") for any
  non-zero speed without sending anything (308).
- `tripPressureFault` (786) stops the motors but does not release.
- A physical stop with load present runs `emergencyStopAndRelease` (538). Its
  back-off at line 552 does nothing. The release loop (1750) then waits out its
  timeout and prints `ERROR: Release incomplete`.
- Scenario: a pressure-limit or load-cell timeout fault latches while the
  patient is loaded. Pressing the physical stop does not back off. The load
  stays on until the Pi sends a reset.
- Fix: give the release back-off an explicit way past the fault gate. Keep it
  bounded by the existing load, travel (`AZERO`) and time limits.

**1c. No axial travel limits while pulsing.**
- The `AXIAL_TRAVEL_LIMIT` and home checks run only during a pressure move
  (1923: `if (!pressureFault && measurePressure)`). They do not run while
  `jerking` (1806).
- Scenario: the load drops during pulsing, for example because the patient pulls
  away or the load cell reads low. The push then runs at pulse speed for up to
  `PULSE_RECOVERY_TIMEOUT` (5 s) with no position bound.
- Fix: apply the same bounds in both pulse directions.

**1d. A stalled position move only warns.**
- A stall emits `WARNING: Motor stalled` (1898). `I`, `K` and `A` moves have no
  timeout.
- The Pi treats firmware warnings as advisory and never stops on them
  (`controllers/safety_monitor.py:144`, `_present_warning`: "without changing
  device/protocol state").
- Scenario: a jam or a stuck but valid encoder reading. The motor keeps driving
  until the operator presses stop.
- This looks like a deliberate design choice: the code comments mention false
  limit warnings seen on the bench unit. It is worth revisiting for
  unambiguous conditions, such as a stall that lasts several times
  `POSITION_STALL_MS`.

**Test gap.** The native suites `#include` the real `motor.ino`, which is good.
Fault injection (`Wire.failTransmissions`) is used only for the E-stop retry.
None of the scenarios in 1a-1d has a test.

### 2. Pi-side stop logic is spread over about 7 paths that disagree

**2a. On-screen STOP without a treatment worker sends only `X`.**
- `emergency_stop_clicked` (`controllers/protocol_controller.py:677`) sends `X`
  through `stop_actuators` (`kneespa.py:1497`).
- The pressure release (`P0`) is sent only by `window.worker.stop()` in phase 2
  (`protocol_controller.py:728`). `window.worker` is `None` until a treatment
  has been created.
- The `X` handler in the firmware does not release.
- Scenario: pressure is applied manually from the Setup screen, then STOP is
  pressed. The load stays on until `_reset_after_release` (512) gives up
  waiting (`RELEASE_WAIT_S = 20.0`, line 34) and the reset re-homes the axial
  actuator.
- Fix: the stop chain should send `P0` itself, independent of the worker. Keep
  the existing exception for physical stops.

**2b. Fault stops send `X` and `HF1` but never `P0`.**
- `stop_without_recovery` (450) does this by design: "without any automatic
  movement".
- Combined with 1b, a faulted, loaded patient can only be unloaded by an
  operator-initiated reset.

**2c. Recovery is inconsistent.**
- After an on-screen STOP, phase 3 (`_emergency_stop_phase3`, 732) releases the
  hardware stop line and runs the recovery reset. The machine re-homes with no
  operator action.
- After a physical stop it waits for the operator (523).

**Structural fix.**
- Stop handling is duplicated across:
  - `stop_protocol`
  - `emergency_stop_clicked`
  - `stop_without_recovery`
  - `on_physical_stop`
  - the command-rejection branch of `on_firmware_error`
  - `Protocols.stop`
  - `KneeSpa.cleanup`
- These paths disagree on `P0`, `HF`, recovery and which flags they set.
- Replace them with one stop owner, for example `StopController.stop(kind)`,
  with kinds `operator`, `estop`, `physical`, `fault` and `shutdown`. Each kind
  defines the commands sent, whether recovery runs, and the resulting screen
  state.

### 3. The kiosk can get stuck or fail to restart

**3a. A failed Setup "Go" leaves the controls locked.**
- `_on_setup_go` (`kneespa.py:874`) disables the controls at line 889.
- Several failure paths return without re-enabling them:
  - `set_to_distance` on invalid axial calibration (147)
  - `set_to_c_distance` on any exception (183)
  - an exception from `horizontal_degrees_to_position`, which lands in the
    `except` that only shows a message
- Only `_send_motion_command` failures re-enable the controls.
- `_block_active_treatment_exit` (1168) treats `actuator_command_in_progress`
  as busy, so logout and exit are blocked too.
- Scenario: corrupt `AMarks`, the operator taps Go on the axial row. The Setup
  screen stays dead and logout is refused. The only way out is a power cycle.
- Fix: re-enable the controls on every unsuccessful return. A single-shot
  "motion watchdog" timer, started in `disable_actuator_controls`, would also
  cover a lost DONE.

**3b. A startup crash exits with code 0, so systemd never restarts the app.**
- `main()` logs and re-raises. The `__main__` block (`kneespa.py:1949`) catches
  `Exception`, prints it and returns normally.
- `devices/templates/raspberry-pi/kneespa.service.example:9` uses
  `Restart=on-failure`, which does not fire on a clean exit.
- Fix: `sys.exit(1)` in that `except`.

**3c. Shutdown has no overall deadline.**
- `closeEvent` (1293) re-polls `cleanup()` (1229) every 50 ms until it returns
  True. `cleanup()` keeps returning False while the serial I/O thread, the
  Arduino `QThread`, the thread pool or the cloud-close thread is still alive.
  Only the transmit-queue drain has a 2 s cap.
- Because the Qt event loop keeps running, the systemd watchdog is probably
  still being pinged, so a stuck thread can hang exit or restart indefinitely.
- Fix: after about 10 s from `_shutdown_began`, log what is still running and
  return True.

**3d. The UI freezes while reconnecting on Start.**
- Pressing Start with the link down calls `ensure_arduino_connection`
  (`protocol_controller.py:225`). It runs on the GUI thread and loops on
  `processEvents()` plus `sleep(0.1)` for up to 30 s
  (`controllers/connection_manager.py:104`).
- The nested event loop means other handlers, including STOP, can run in the
  middle of it. The code already re-checks state after it
  (`protocol_controller.py` around 211-237).
- Fix: drive reconnection from a worker thread or a timer-based state machine
  and signal back.

### 4. Software updates

**4a. No signature on releases.**
- A downloaded release is checked against a sha256 supplied by the same server
  (`helpers/release_client.py:87`, `:110`), and re-checked against the same
  value at install (`helpers/release_installer.py:231`).
- No signing key or signature check exists anywhere in the app.
- Anyone who can publish a release can run code on every device.
- Fix: sign releases (for example detached ed25519) and verify them against a
  public key shipped with the app. Optionally refuse version rollback.

**4b. The software swap is not crash-safe.**
- `_software()` (`release_installer.py`, around 349-353) does
  `os.replace(target, retired)` and then `os.replace(candidate, target)`.
- Power loss between the two renames leaves no `runtime/raspberry-pi`. Nothing
  outside the installer looks for `.software-old-*` to recover it.
- Fix: write a journal before the swap, restore a leftover `.software-old-*` in
  `launch.sh` when the target is missing, and fsync the parent directory.

These are also the least-tested modules (53% and 75%).

### 5. `kneespa.py` does too much

Measurements:
- 1957 lines, one `KneeSpa` class with 103 methods and 73 distinct attributes.
- Controllers contain 501 `window.` references, about 210 of them in
  `protocol_controller.py`. 115 references in controllers and UI touch private
  window attributes, most often `window._show_timed_error`, `_closing`,
  `_no_automatic_recovery` and `_paused_at`.
- Busy and fault state is spread across flags read as
  `getattr(self, "...", False) is True`: `_closing`, `_calibration_active`,
  `_device_maintenance_active`, `reset_in_progress`,
  `actuator_command_in_progress`, `_physical_stop_active`,
  `_no_automatic_recovery` and `protocol_state`.
- Tests make 154 unbound `KneeSpa.method(fake_self)` calls, so any extraction
  also breaks tests.

Suggested incremental order, one commit per step:
1. A plain `DeviceState` class with no Qt, owning the flags above and exposing
   `can_move()`, `can_exit()` and `busy_reason()`.
2. A `MotionController` that takes over `move_actuator`, `set_to_distance`,
   `set_to_c_distance`, the Setup "Go" and stop handlers, and the
   enable/disable debounce. It gets a narrow view interface instead of the
   window.
3. A `ShutdownCoordinator` that takes over `cleanup()`, with the deadline from
   3c.
4. Patient lookup state. This is already noted as partial in the
   remaining-decisions plan.
5. Move `main()`, the excepthook and the log helpers into their own module.

### 6. Errors are hidden instead of logged

- `ruff --select BLE001,S110` finds 84 catch-all `except Exception` handlers in
  `runtime/`. 29 of them are `except ...: pass`.
- They are concentrated in:
  - `kneespa.py` (29)
  - `controllers/protocol_controller.py` (25)
  - `ui/modals/vlc_engine.py` (24)
  - `helpers/protocols.py` (11)
- In `protocol_controller.py` every treatment-screen update is wrapped in
  `except Exception: pass` (lines 80, 94, 101, 186, 780, 796, 815, 828).
- Scenario: a refactor breaks `shell.treatment.set_run_state`. After a STOP the
  screen keeps showing the running controls, and nothing is logged.
- Fix:
  - Route screen updates through a helper that calls `logger.exception` and
    never re-raises, which keeps the "never delay safety work" intent.
  - Enable `BLE001` and `S110` in `ruff.toml` one file at a time.

### 7. Patient data and credentials stored on the device

These all need local file access, so they rank below the items above.

- **Upload queue permissions and retention.** `pending_uploads.json` holds
  treatment records with patient IDs. It is written with default permissions
  (`helpers/cloud_client.py:314`). Entries rejected with a non-retryable 4xx and
  quarantined `.corrupt-*` files (307) are kept forever. The corrupt files also
  make the sync summary report an error permanently (249). Fix: create the file
  as 0600 in a 0700 directory, and add an age and count limit with an operator
  purge action.
- **Old PIN hashes.** Unsalted SHA-256 PIN hashes are still accepted
  (`helpers/secure_auth.py:112`). Fix: rehash to PBKDF2 on the next successful
  login, then drop support.
- **Lockout fails open.** The login lockout resets if `auth_state.json` can't
  be read (`controllers/auth_controller.py:40`). It also uses wall-clock time,
  and the Pi has no real-time clock. Fix: treat an unreadable state file as
  locked, and use a monotonic clock.

### 8. Platform and test gaps

- **Old platform.** The Pi runs Raspbian Buster (Debian 10 LTS ended
  2024-06-30) and Python 3.7. Staying on Buster is a recorded decision
  (`devices/maintenance/raspberry-pi/buster-updates.md`).
- **CI tests a different Qt than the device.**
  - The Python 3.7 CI jobs install pip's `PyQt5==5.15.9`, but the Pi uses
    Buster's apt `python3-pyqt5`, believed to be 5.11 (not checked on a device).
  - So CI never runs against the Qt the device ships with.
  - Consider recording the exact device version (`devices/collect_pi_info.sh`)
    and testing against it.
- **Firmware tests vs. the real chip.**
  - The native tests compile on a 64-bit PC, where `int` is 32-bit; on the Mega
    it is 16-bit. Integer-width bugs will not show up.
  - The shim `String` also never fails to allocate.
  - Consider adding a `-m32` build or explicit width tests.
- **No coverage threshold.** CI reports coverage but does not enforce a
  minimum.
- **Viewer tests not in CI.** The simulator viewer's `vitest` tests
  (`development/simulator/viewer`) have no CI job.
- **Unpinned test dependencies.** `pytest>=7.0`, `pytest-mock`, `pytest-qt`,
  `pytest-cov` and `pytest-timeout` are unpinned, so CI results can change
  without a code change.
- **Large repository.** The repository pack is about 520 MB. Eight videos
  (about 116 MB) are plain Git blobs; only the HCT/P video is in LFS.

## Reported but not yet verified

These came from the parallel reviews and were not checked line by line. Confirm
each one before acting on it.

| Area | Claim |
| --- | --- |
| Firmware | `X` can wait up to about 200 ms behind a rate-limited command (`MIN_COMMAND_INTERVAL`), because bytes stop being read while a command is pending. |
| Firmware | Load sign is discarded (`pressure = fabs(signedPressure)`). A negative reading, meaning tension or offset drift, is treated as positive pressure. |
| Firmware | Debug prints at 9600 baud before each I2C stop write may delay a full three-axis stop by tens of milliseconds once the TX buffer fills. |
| Firmware | Heap `String` is used throughout the command path on the Mega's 8 KB RAM, which risks fragmentation over long sessions. |
| Firmware | A malformed `P` target latches `PRESSURE_TARGET_INVALID` instead of being rejected with an error. |
| Firmware | The checksum parse is lenient: `strtol` accepts partial or non-hex input. |
| Pi transport | `_handle_link_lost` gives up without a best-effort `X` write (`helpers/arduino.py`, around 477-485). |
| Pi transport | `teardown_arduino` never sets `_connect_cancel`, so a background connect loop can outlive a teardown. |
| Pi transport | `readline()` with a 1 s serial timeout can delay the priority (stop) queue by up to 1 s on a partial line. |
| Pi UI | `_show_safety_alert` creates `QMessageBox` objects without `WA_DeleteOnClose`, so each alert stays in memory. |
| Release | Prepared update directories under `state/updates` are never pruned. Each can be up to 1 GB. |
| Secrets | `.env` and `cloud.env` permissions are not enforced. `migrate_state.py` keeps the source file's mode. |
| Dev scripts | `development/sync/*.sh` use `StrictHostKeyChecking=accept-new` when copying device state. |

## Ruled out

- **Signals from the serial thread being dropped.**
  - The claim: signals emitted from the serial reader thread to slots on
    non-QObject classes (`ConnectionManager`, `SafetyMonitor`,
    `Protocols(QRunnable)`) are queued to the Arduino `QThread`. That thread's
    event loop exits right after `run()` returns, so the slots would never run.
  - A probe reproduced the wiring on PyQt 5.15.11 / Qt 5.15.2. All three
    connection styles were delivered on the GUI thread:
    - connected before `moveToThread`
    - connected after `moveToThread`
    - bound method of a GUI-thread QObject
  - Not re-tested on the Pi's PyQt build.
- **Wi-Fi configuration.** It is not open to shell injection: it uses argument
  lists and passes the password on stdin (`helpers/device_system.py`).
- **ZIP extraction.** Release ZIP extraction rejects path traversal, symlinks
  and device files.
- **TLS.** The cloud client uses urllib's default certificate verification and
  refuses redirects. Plain HTTP is allowed only for localhost.

## Suggested order of work

1. Firmware stop-path fixes 1a-1c, with fault-injection native tests, added to
   the queued flash batch in `2026-09-30-remaining-decisions.md` §1. Ask the
   owner about 1d, stall auto-stop.
2. Pi kiosk-recovery fixes 3a-3c: small, host-only, no flash needed.
3. Make the on-screen STOP send `P0` independent of the worker (2a). Then build
   the single stop owner (2, structural).
4. Release signing and a crash-safe swap (4). This needs a cloud-side signing
   step as well.
5. `DeviceState`, then extract `MotionController` (5). Combine this with the
   logging helper from 6.
6. Data-at-rest and auth hardening (7), then the platform and test items (8).
