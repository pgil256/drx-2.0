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
  `VERSION` is `2026-09-30-DRX2-NB2-SERVICE`.
- **Image:** Mega hex sha256 `fb840258d10a49e41b341f6cf6100d2eee3b1f386b0082b4c3d1cafbc9bf6306`,
  flash 33,974 bytes, RAM 2,688 bytes. Only the `L5` change alters behavior; the
  cleanup commits leave the code identical (at most the LTO trampoline order moves).
- **The Pi does not need this flash:** it already sends only `L5|a|b`, and it
  checks the HX711 driver identity, not the version string.
- **Decide:** when to flash, after the deployment bench checks in
  `development/docs/hardware-service.md#verification-before-deployment`.

## 2. UI changes to look at on the Pi or simulator

- **Pressed state:** the top-bar knee logo and wordmark now dim to 50% while
  pressed. GUI plan rule 7 bans graphics effects only on the video card; check
  that the effect feels responsive on the Pi.
- **Patient-name keyboard:** it now uses the shared `TextKeyboard`. It shows a
  "Patient name" heading and a character count, is 880 px wide instead of 860,
  uses 48 px minimum keys instead of 60, and opens in capitals every time (it
  used to keep the previous Shift state). Keep this, or add options to restore
  the old look?
- **Wi-Fi password keyboard:** it has never offered the symbols
  `` #$%&*()=[]{}";<>\|`~^ ``, although real Wi-Fi passwords can contain them.
  Probably a bug. The fix is one argument, `keys=ASCII_KEYS`, in
  `ui/modals/device_dialogs.py`. Apply it?
- **Video modal:** split into `video_modal.py` and `vlc_engine.py` with no
  intended visual change. Releases must ship the new `ui/modals/vlc_engine.py`;
  the release installer extracts the whole tree, so this matters only for
  hand-copied files.

## 3. Deletions held for the owner

| Item | Why it was held | Options |
| --- | --- | --- |
| `kneespa-pi-desktop-setup.tar.gz` | A hand-made snapshot of 7 tracked files. It is identical today but will drift. Four docs link to it: `devices/README.md`, `devices/maintenance/raspberry-pi/desktop/README.md`, `devices/maintenance/raspberry-pi/firmware.md`, `development/docs/rpi/setup-and-maintenance.md`. | Generate it in the sync or release script, have the sync script deliver the launchers, or keep it |
| `drx.code-workspace` | Personal editor settings at the repo root | Delete, or move to a personal location |
| `development/docs/rpi/*.txt` | `kneespa_url`, `rpi_config`, `ser-connection-fix`, `ssh_setup`, `sync`, `vnc_start` and the display baseline have no references (`dev-path` and `startup_version` are referenced). `display-baseline-20260712-161506.txt` is a device dump with USB serial numbers. | Delete or archive. Deleting does not remove the serial numbers from git history. |
| `development/docs/archive/audits/` | Already archived; the handoff suggested deleting it | Keep or delete |
| Orphan plans: `2026-01-09-kneespa-web-demo-design.md` with `development/docs/reference/demo/`, and `2026-09-01-admin-dashboard-poc-plan.md` | No incoming links. They may describe future work. | Archive, delete, or keep as active ideas |
| `development/tools/calibrate.py` | Works with current firmware again, but the in-app Hardware Tests & Calibration wizard supersedes it | Keep as a serial-console fallback, or retire to the archive |
| `development/tools/ds_gallery.py` | Unreferenced but working | Keep, or delete |

## 4. Repository and CI changes that cannot be verified locally

- **Other videos in Git LFS:** only `Next Level Integrative Medicine HCT_P Details.mp4`
  (392 MB) is in LFS. The other 8 mp4s (about 121 MB) are plain blobs. Moving
  them to LFS for new commits only is cheap; converting existing history needs
  `git lfs migrate` and a force-push.
- **`xvfb-run` in CI:** probably unnecessary, since `QT_QPA_PLATFORM=offscreen`
  is set in CI and in `tests/conftest.py`. Removing it needs a CI run to confirm.
- **Separate `check_limits_sync.py` CI step:** it repeats
  `unit/test_limits_sync.py` but fails faster. Keep as is unless CI time matters.
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

## 7. Cleanup after merge

- The agent branches `claude/video-modal-split` and `claude/one-keyboard`, and
  their worktrees under `.claude/worktrees/agent-*`, are fully cherry-picked
  into this branch and can be deleted.
- `claude/dead-code-refactoring-review-1dcc8e` is contained in this branch.
