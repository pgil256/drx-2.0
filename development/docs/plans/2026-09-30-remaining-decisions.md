# DRx 2.0: decisions left after the 2026-09-30 cleanup

The cleanup branch `claude/drx-remaining-work-c7dd10` finished the handoff in
`drx-remaining-work.md` except for the items below. Each one needs an owner
decision, a device, or a CI run; none blocks merging the branch.

Verified on the branch: Windows pytest 1703 passed, 111 skipped (POSIX-only);
WSL pytest 1773 passed, 24 failed (all missing `qrcode`, same as baseline);
firmware native tests 8 suites / 165 tests; Mega build warning-free;
`validate_fixes.py` and `check_limits_sync.py` pass.

## 1. Firmware flash batch (needs a device)

- **What is queued:** the `L5` fixed-width form is now rejected with
  `COMMAND_REJECTED|L5|INVALID_FORMAT`, plus dead-code and comment cleanup.
  Added 2026-10-28: after a serial line overflows the 100-byte command buffer,
  the rest of that line is discarded instead of running as a command, and the
  rejection is reported once. Also added 2026-10-28: a pulse release travels
  back for the whole Pulse Rate interval and stops early only when pressure
  reaches zero (it used to stop 2 lb under target), and a push releases as soon
  as it reaches target (it used to hold there until the interval ended).
  `VERSION` is `2026-10-28-DRX2-NB2-SERVICE`.
- **Image:** Mega hex sha256 `4f60c34727418eb6b55a02d3ed39a3a4c8e69415a61b7d7e37d8f784e6c9d2bf`,
  flash 34,148 bytes, RAM 2,689 bytes, built with the pinned `atmelavr@5.3.0`.
  CI's firmware job uploads the same image with its checksum. The `L5`,
  overflow and pulse changes alter behavior; the cleanup commits leave the code
  identical (at most the LTO trampoline order moves).
- **The Pi does not need this flash:** it already sends only `L5|a|b`, and it
  checks the HX711 driver identity, not the version string.
- **Decide:** when to flash, after the deployment bench checks in
  `development/docs/hardware-service.md#verification-before-deployment`.
  For the pulse change, also run the slowest Pulse Rates (0.2/sec is a
  5-second release): a release that unloads the leg must get back to target
  within 5 seconds, or the firmware latches `PULSE_RECOVERY_TIMEOUT`.
- **Also decide:** whether motion should continue when the app dies. The
  host heartbeat only warns, so after an app abort a pressure ramp runs to its
  target or its 90-second deadline, and pulsing continues until the restarted
  app's reset sends `Y`. `development/docs/deployment.md` describes the
  current behavior. Making the heartbeat stop pulsing again would be a
  firmware change for this batch.

### Batch 2026-11: stop hardening (queued, not flashed)

These items come from the checklist in
`development/docs/plans/2026-11-04-improvement-checklist.md` (F1–F4, then
the owner-approved firmware findings V1–V6). The
image is built from `main`, so it also contains everything in the
2026-10-28 batch above. A device still on an older image gets both changes
with this flash.

- **F1, checked stop writes (2026-11-05).**
  - Every zero-speed write to an SMC is checked: up to 3 attempts. An
    unacknowledged stop is reported once, as
    `ERROR: Motor stop not acknowledged <n>`, until a later stop on that SMC
    is acknowledged.
  - A position arrival, a pressure arrival and the end of a release complete
    (`DONE` or `RELEASED`) only once the stop is acknowledged. The next pass
    retries it. Before this, a NACKed stop left the SMC driving while the
    firmware reported it stopped.
  - The pulse speed cache only updates when the SMC acknowledges the write.
  - Stops on SMCs that no move owns are retried every 200 ms: E-stop, `JS`,
    boot, and the stop sent when a target is already in band.
  - No Pi change is needed; the error text is the one the E-stop already used.
- **`VERSION`:** `2026-11-05-DRX2-STOP-CHECKS`.
- **Image after F1:** flash 34,162 bytes, RAM 2,694 bytes, with the pinned
  `atmelavr@5.3.0` (sha256
  `d35640beff4a37ab134b1e3867059ed09bab104c4b194519416fa0e81bccb11b` from a
  local WSL build; CI's firmware job uploads its own image and checksum).
- **Bench checks for F1:**
  - Normal Setup moves on all three axes, a pressure Go and a pulsed
    treatment complete as before.
  - The Arduino log for that session has no
    `Motor stop not acknowledged` lines.
  - Optional, with the device unoccupied: power the Mega with one SMC's I2C
    lead disconnected. Boot reports `ERROR: Motor stop not acknowledged <n>`
    once and keeps retrying, then stops reporting once the lead is
    reconnected.
- **F2, release past a latched pressure fault (2026-11-06).**
  - **The bug:** after a pressure fault latched (for example
    `PRESSURE_LIMIT` or `PRESSURE_SENSOR_TIMEOUT`), the physical stop
    button's release was a no-op:
    - `setMotorSpeed` ignored the back-off while `pressureFault` was set;
    - `servicePressure` stopped sampling, so the release could not see the
      load clear and idled to `ERROR: Release incomplete`.
  - **The fix:**
    - The release back-off writes past the fault gate (`writeMotorSpeed`).
    - Pressure sampling continues while a release runs.
    - The release is still bounded by load, travel (`AZERO`) and
      `RELEASE_TIMEOUT`.
    - Every other motion stays blocked while the fault is latched, and the
      fault stays latched until the host's reset.
  - **`VERSION`** is unchanged. It is the same batch.
- **Image after F2:** flash 34,178 bytes, RAM 2,694 bytes (local WSL build,
  sha256 `b0e3843061c2bf0583f0967e3d8b7078ef4aba61f7b166230ab68265facbeaf4`).
- **Bench check for F2** (device unoccupied, a test load on the axial
  actuator):
  1. Trip a fault, for example with `P` targets that force the overshoot
     ceiling, or by unplugging the load cell during a hold.
  2. Press the physical stop.
  3. The axial actuator backs off. The log shows `RELEASED` once the load is
     under 5 lb, or `ERROR: Release incomplete` only at home or after 15 s.
- **F3, travel limits while pulsing (2026-11-06).**
  - **The bug:** the axial travel checks ran only during a pressure move,
    not while pulsing. If the load dropped mid-pulse (the patient pulled
    away, or the load cell read low), the push ran at pulse speed for up to
    `PULSE_RECOVERY_TIMEOUT` (5 s) with no position bound.
  - **The fix:** the pressure move's two checks now also apply to pulsing,
    using the pulse direction:
    - a push that reaches the axial travel limit (feedback 4095) latches
      `FAULT|AXIAL_TRAVEL_LIMIT`;
    - a release that reaches home (`AZERO` + 25 counts) while pressure is
      still above target + 2 lb latches
      `FAULT|AXIAL_HOME_BEFORE_PRESSURE_TARGET`.
  - Both latch through `tripPressureFault`, which stops every axis. A release
    that reaches home with the load gone keeps pulsing as before.
  - No Pi change is needed: `helpers/firmware_protocol.py` turns every
    `FAULT|<reason>|<target>|<pressure>` line into a controller fault,
    whatever the reason.
  - **`VERSION`** is unchanged. It is the same batch.
- **Image after F3:** flash 34,202 bytes, RAM 2,694 bytes (local WSL build,
  sha256 `416eabfa23edb9530cb1b5867a0a27a2828e2bde8aa8d5ed80f0fae3cbf1f26a`).
- **Bench check for F3:** a pulsed treatment on a test load completes as
  before, with no `AXIAL_` faults in the Arduino log. Do not provoke the
  limits with a patient on the device.
- **F4, a long stall ends the move (2026-11-06).**
  - **The bug:** a position move (`I`, `K`, `A`) that stopped making
    progress only sent `WARNING: Motor stalled` after 20 s
    (`POSITION_STALL_MS`). The Pi treats that warning as advisory, so a jam,
    or a stuck but valid encoder reading, kept the motor driving until the
    operator pressed stop.
  - **The fix:**
    - The 20 s warning stays.
    - With still no progress at 60 s (`POSITION_STALL_TIMEOUT_MS`,
      3 × `POSITION_STALL_MS`), the firmware calls `emergencyStop()` and
      sends `ERROR: Motor stall timeout <device>`, for example
      `ERROR: Motor stall timeout 13`.
    - The stopped move never reports `MOTION_DONE` or `DONE`.
    - Progress toward the target (4 counts or more) still restarts both
      timers.
  - **Pi change (ships with the app, not the flash):**
    `controllers/safety_monitor.py` handles `Motor stall timeout …` as a
    controller fault: the treatment or reset stops, there is no automatic
    homing, and a `CONTROLLER FAULT` alert asks for Reset.
    - An app on this change that talks to older firmware is unchanged,
      because older firmware never sends the new error.
    - Older firmware has no timeout, so flashing this image is what makes
      the motor stop.
  - **`VERSION`** is unchanged. It is the same batch.
- **Image after F4:** flash 34,288 bytes, RAM 2,694 bytes (local WSL build,
  sha256 `452cc0fb03d190729c478ea4e29cba25548c395ee5d429a811f8e09be63326e7`).
  The message string is kept in flash with `F()`, so RAM is unchanged.
- **Bench check for F4** (device unoccupied):
  1. Block one actuator mechanically, or hold its SMC disabled, and command
     a Setup move on that axis.
  2. At about 20 s the operator sees the `Motor stalled` warning.
  3. At about 60 s the motor stops. The Arduino log shows
     `ERROR: Motor stall timeout <n>`, and the app shows
     `CONTROLLER FAULT: Motor stall timeout <n>` and requires Reset.
  4. A normal long move, for example homing during Reset, still completes.
- **V1, a status ack no longer holds up a stop (2026-11-06).**
  - **The bug:** the firmware stops reading serial bytes while a complete
    command waits out the 200 ms rate limit (`MIN_COMMAND_INTERVAL`). Only
    `X` was exempt. The Pi writes each status ack `Q` as soon as a status
    frame arrives, outside its own 0.22 s pacing, so a `Q` within 200 ms of
    a paced command waited, and an `X` right behind it waited too, for up
    to about 200 ms.
  - **The fix:** `Q` is exempt from the rate limit as well, and it does not
    restart the limit's window, so it never holds up the next paced command
    either. The Pi already assumed both `X` and `Q` bypass the limiter, so
    no Pi change is needed.
  - **`VERSION`** is unchanged. It is the same batch.
- **Image after V1:** flash 34,304 bytes, RAM 2,694 bytes (local WSL build,
  sha256 `6a391aaaf68c173f9c6903766ecbe609fd6f65f9284e5c058eab73169dc6b48f`).
- **Bench check for V1:** none beyond the F1 checks; a normal session's
  stops and status updates behave as before. The timing is covered by a
  native test.

## 2. UI changes to look at on the Pi or simulator

- **Pressed state:** the top-bar knee logo and wordmark now dim to 50% while
  pressed. GUI plan rule 7 bans graphics effects only on the video card; check
  that the effect feels responsive on the Pi.
- **Patient-name keyboard:** it now uses the shared `TextKeyboard`. It shows a
  "Patient name" heading and a character count, is 880 px wide instead of 860,
  uses 48 px minimum keys instead of 60, and opens in capitals every time (it
  used to keep the previous Shift state). Keep this, or add options to restore
  the old look?
- **Wi-Fi password keyboard:** it did not offer the symbols
  `` #$%&*()=[]{}";<>\|`~^ ``, although real Wi-Fi passwords can contain them.
  Fixed on 2026-10-02 with `keys=ASCII_KEYS` in
  `ui/modals/device_dialogs.py` (PR #24).
- **Video modal:** split into `video_modal.py` and `vlc_engine.py` with no
  intended visual change. Releases must ship the new `ui/modals/vlc_engine.py`;
  the release installer extracts the whole tree, so this matters only for
  hand-copied files.

## 3. Deletions held for the owner (decided 2026-10-06: delete all)

Each item is its own commit, so any one can be reverted alone.

| Item | What was done |
| --- | --- |
| `kneespa-pi-desktop-setup.tar.gz` | Deleted and ignored again. `development/docs/rpi/setup-and-maintenance.md` gives the `git archive` command that builds it from the current commit; the three other docs link to that section. |
| `drx.code-workspace` | Deleted |
| `development/docs/rpi/*.txt` | Deleted `kneespa_url`, `ssh_setup`, `sync`, `vnc_start` and the display baseline. The baseline's USB serial numbers remain in git history. `rpi_config` and `ser-connection-fix` are deleted in a separate commit: they were the only record of the Pi's `/boot/config.txt` and UART setup. `dev-path` and `startup_version` stay. |
| `development/docs/archive/audits/` | Deleted. The README's E-stop pointer now goes to §8 of the archived improvement plan, where that section actually is. |
| Orphan plans: `2026-01-09-kneespa-web-demo-design.md` with `development/docs/reference/demo/`, and `2026-09-01-admin-dashboard-poc-plan.md` | Deleted |
| `development/tools/calibrate.py` | Deleted; `development/docs/archive/tools/README.md` records the removal |
| `development/tools/ds_gallery.py` | Deleted |

## 4. Repository and CI changes that cannot be verified locally

- **Other videos in Git LFS:** done 2026-11-05, for new commits only. All nine
  `.mp4` files under `runtime/raspberry-pi/main/ui/media/videos/` are now LFS
  pointers: the other 8 (about 116 MB) joined `Next Level Integrative Medicine
  HCT_P Details.mp4`. Older commits keep the plain blobs. Shrinking the pack
  would need `git lfs migrate` and a force-push, which the owner declined.
- **`xvfb-run` in CI:** probably unnecessary, since `QT_QPA_PLATFORM=offscreen`
  is set in CI and in `tests/conftest.py`. Removing it needs a CI run to confirm.
- **Separate `check_limits_sync.py` CI step:** it repeats
  `unit/test_limits_sync.py` but fails faster. Keep as is unless CI time matters.
- **Python 3.7 import job (added 2026-10-09):** `python37-imports` runs
  `development/scripts/check_runtime_imports.py` in a `python:3.7-slim-bookworm`
  container and gates the PR: run 38168318618 on 2026-10-11 imported 98 of 98
  modules on Python 3.7.17. The job pins `PyQt5==5.15.9` / `PyQt5-sip==12.12.2`,
  the last pair with 3.7 wheels; the Pi itself uses apt's PyQt5, not pip.
  Running the full test suite on 3.7 is a separate decision: about 80 test
  lines use `call_args.kwargs`, which needs Python 3.8.
- **Python 3.7 test job (added 2026-10-12):** `python37-tests` runs the whole
  suite in the same container and gates the PR: run 38262400584 passed 1839
  tests on Python 3.7.17. `requirements-test.txt` carries version markers for
  it (`aiohttp==3.8.6`, `PyQt5==5.15.9`, `PyQt5-sip==12.12.2` below 3.8/3.9).
  Its first run found that `DiagnosticFileHandler` disabled itself on 3.7, so
  the Pi wrote no application or Arduino log files; fixed in the same branch.
  Check on a device that `devices/local/raspberry-pi/logs` fills again.
- **WSL test gaps:** installing `qrcode` would clear the 24 known WSL failures,
  and `aiohttp` would let the two simulator test files run. Neither is installed.

## 5. Refactors left partial on purpose

- **Linked-patient state:** `controllers/linked_patient.py` now holds the one
  link/unlink implementation. Its storage (`cloud_patient`,
  `_patient_lookup_id`, `_patient_lookup_pending`) still lives on the window:
  moving it into `PatientController` would touch 44 test references and the
  simulator's `verify_ux.py`, and needs a simulator run to verify.
- **`print()` to logger:** only `connection_manager.py` and `protocols.py` are
  converted. About 150 `print()` calls remain elsewhere.
- **Kept on purpose:**
  - `Protocols._configure_motor_speeds`'s `motor_speeds is None` branch:
    removing it would make every test worker acknowledge `V`.
  - `Arduino.checksum_failures` and `link_retries`: diagnostics.
  - `HardwareServiceController.report_path`: the natural observable of
    `export_report`.

## 6. Still deferred by the owner (F9)

- `configparser==5.3.0` in `runtime/raspberry-pi/main/requirements.txt`: the
  stdlib module is what gets imported. Confirm the Pi's Python (Buster 3.7)
  before removing it.
- Ten unreferenced button PNGs in `ui/media/images/buttons/`: `arrow-back`,
  `arrow-forward`, `down_1`, `down_2`, `pause-black`, `play-button`, `play`,
  `restart`, `up_1`, `up_2`. Check deployed and packaged consumers first.
- `ui/media/images/graphics/1-4.png` are never loaded; startup only checks that
  `UI_PATHS["PROTOCOL_IMAGES"]` exists. Add them to this F9 asset list.

## 7. Cleanup after merge (done 2026-10-02)

- The agent branches `claude/video-modal-split` and `claude/one-keyboard`, and
  their worktrees under `.claude/worktrees/agent-*`, were fully cherry-picked
  into this branch and are deleted.
- `claude/dead-code-refactoring-review-1dcc8e` was contained in this branch and
  is deleted locally and on GitHub.
