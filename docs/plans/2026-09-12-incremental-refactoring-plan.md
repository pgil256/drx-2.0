# Incremental refactoring plan

Created: 2026-09-12  
Revised against critique: 2026-09-12  
Audit and verification baseline: 2026-09-11  
Status: proposed; no application refactoring has been performed

## Objective and boundaries

Reduce unnecessary complexity, technical debt, and unused code while preserving KneeSpa's existing functionality. First establish a committed starting point and repair deployment-state preservation. Then ship a Python-only cleanup using existing controller tests. Reserve the larger real-window fixture for changes to treatment presentation ownership and timer construction.

This plan incorporates the [2026-09-12 critique](2026-09-12-incremental-refactoring-plan-critique.md). Its implementation claims were checked against the working tree, including existing uncommitted calibration and regression work. The historical test results below are observations, not a reproducible committed baseline. Phase 0 supplies that missing baseline. File and line references describe the inspected implementation and should be rechecked before editing. Tests were not rerun for this documentation revision.

Every phase must preserve user workflows, UI interactions, public interfaces, serial commands and responses, persistence formats, integration behavior, error handling, and relevant timing and performance characteristics. Suspected or confirmed bugs are separate work items, not permission to change behavior during refactoring.

Use the existing Python, PyQt5, and Arduino stack. Do not introduce a framework, architectural layer, or dependency to carry out this plan. Prefer small commits that can be reviewed and reverted independently. Uncertainty about external consumers blocks deletion of a compatibility surface, not the rest of the plan.

Implementation order: **Phase 0 (land existing work) → separate B2 deployment repair → Phase 1 (Python cleanup) → Phase 2 (remaining placeholders) → Gate W (window coverage) → Phase 3 (presentation ownership)**. Phase 4's independent tasks and Phase 5's inventory do not depend on Gate W. Firmware-local deletion belongs to the next verified firmware/reflash batch, not the first Python batch. This document does not perform commits, deployments, flashes, or worktree removal.

## Architecture and conventions

| Area | Implementation and responsibility |
| --- | --- |
| Application entry and composition | `main/kneespa.py`, particularly `KneeSpa.__init__` around line 322, constructs the window, configuration, authentication, controllers, timers, and hardware connections. `main/ui/app_shell.py` composes six screens, including Profile, and modal overlays. |
| Orchestration | `main/controllers/` contains authentication, connection/reset, protocol, safety, and calibration controllers. Controllers operate on the window and share its mutable state. |
| Background execution | `Protocols` and `ResetWorker` run through the Qt thread pool. Arduino startup uses a QObject/QThread arrangement; ongoing serial I/O uses a dedicated Python thread and a queue with one serial-port owner. |
| Hardware boundary | `main/helpers/arduino.py` handles serial transport, acknowledgement handling, reconnection, and optional protocol v2 framing. `main/motor/motor.ino` controls the Arduino Mega, Pololu motor controllers over I2C, and HX711 measurements. Timing, acknowledgements, checksums, and pressure release span both sides. |
| Persistence | INI configuration stores calibration and defaults. CSV stores users and password hashes, including legacy compatibility. JSON files store authentication lockout state and pending uploads. |
| Integrations and dependencies | PyQt5, pyserial, RPi.GPIO, python-dotenv, and VLC support the application. Cloud calls use urllib; support messages use SMTP_SSL. Firmware depends on Wire, HX711, and elapsedMillis. |

Major workflows to preserve:

- Login, PIN entry, lockout, and gated navigation.
- Setup jogging, Go commands, and reset.
- Treatment confirmation, live setting changes, pause, resume, completion, and stop.
- Profile calibration capture and save.
- Patient lookup, upload, and offline upload persistence.
- Support email and video playback.

The root `AGENTS.md` specifies Python/PyQt conventions, PEP 8, four-space indentation, a 100-character line limit, Google-style docstrings, type hints, and safety-aware error handling. It documents Python tests, POSIX serial integration tests, and native firmware tests. Some documentation is behind the implementation: the current shell has six screens, and the instruction to import `main.config.constants` differs from the application's existing `config.constants` imports used by the direct entry point. Do not combine a bulk import migration with these refactorings.

The main avoidable complexity comes from:

1. Legacy widget adapters and no-op widgets retained behind the rebuilt UI.
2. Several paths writing treatment presentation and related state.
3. Tests that accept broad MagicMock interfaces and inspect source spelling instead of behavior.
4. Small duplicated integration mechanics and persistence code that temporarily mutates live configuration.

Transport synchronization, hardware safety, and compatibility handling are substantial complexity with demonstrated responsibilities. Their size alone is not evidence that they should be simplified.

## Historical verification results

No application source changes were made during the audit. The working tree already contained changes; these results describe that working tree rather than a clean release checkout. The critique's base commit, `fd7ddc23b1512c1a1e3a330b06100f64df9ce230` on `docs/phase-e-on-device-plan`, was confirmed during this revision. It does not contain the audited implementation: 31 tracked files remain modified, alongside untracked implementation and documentation files. Do not use the historical pass counts as acceptance evidence for a future commit without rerunning its phase gate.

| Check actually run | Result | Interpretation or limitation |
| --- | --- | --- |
| Windows: `.venv/Scripts/python.exe -m pytest -q --disable-warnings --cov=main --cov-report=term-missing --cov-report= --basetemp=.audit-pytest-tmp` | **818 passed, 39 skipped, 1 warning**, 304.33 seconds | Python 3.12.14, pytest 9.1.1, PyQt5 5.15.11. The suppressed warning was not characterized. |
| WSL/Linux: `python3 -m pytest -q -ra --basetemp=/tmp/drx-audit-pytest` | **857 passed**, 329.09 seconds | Includes the POSIX coverage unavailable on Windows. |
| `.venv/Scripts/python.exe scripts/check_limits_sync.py` | **11 checks passed** | Host/firmware limits remain synchronized under this check. |
| `.venv/Scripts/python.exe scripts/validate_fixes.py` | **11 passed, 1 failed** | The failed check requires an old pressure-send source pattern. See F1; this is a pre-existing verification failure, not a demonstrated runtime failure. |
| WSL: `bash main/motor/run_native_tests.sh` | **119 passed** | Clamp: 12; command parsing: 32; safety: 57; status: 18. |
| WSL, from `main/motor/`: `bash -lc 'pio run -e mega'` | **Build passed** | RAM: 2,317/8,192 bytes, 28.3%. Flash: 29,086/253,952 bytes, 11.5%. Compiler diagnostics include eight unused locals and a signed comparison around line 1527. |
| AST parsing of 114 repository Python files | **No syntax failures** | Syntax validation only; this is not linting or type checking. |

Python coverage was **80% overall**: 7,892 statements, 1,543 missed. Important gaps include:

- `main/kneespa.py`: 55%; constructor lines 323–516 and `_connect_shell` lines 521–553 were unexercised.
- `main/controllers/connection_manager.py`: 64%.
- `main/helpers/protocols.py`: 65%.

No configured lint or type-check gate was found, and ruff, mypy, and pyright were unavailable in the Windows environment. No physical-device, native VLC/audio, or deployment verification was performed. GPIO and VLC are mocked globally in the tests; the hardware test directory contains only its package initializer. Passing the suites therefore does not establish physical-device safety or playback correctness.

## Prioritized findings

Priority expresses implementation order, not bug severity. Confidence concerns the evidence for the finding; it does not remove the need for verification. "Repository-unused" means no caller was found in the inspected repository, not that external consumers have been ruled out.

| ID / priority | Files and symbols; evidence | Proposed simplification | Maintenance benefit | Risk / confidence | Required verification |
| --- | --- | --- | --- | --- | --- |
| **F1 / P1 — brittle verification** | All 12 checks in `scripts/validate_fixes.py` inspect source patterns or file presence. The pressure pattern at `:79` requires the old `_send_command(f"P{current_command}")` guard; `main/helpers/protocols.py:494` now delegates through `_send_pressure_command`. CI runs the script before pytest in `.github/workflows/ci.yml:51`. | Keep the command as a thin runner over `check_limits_sync.py` and a bounded behavioral pytest selection. Remove source-pattern assertions entirely. Map each existing check as specified below; CI runs the limit check and full pytest once, without the redundant snapshot step. | Stops source-shape churn while keeping useful checks and a familiar local command. | Low–medium / high | Behavioral coverage inventory, rejected-send/cancellation negative cases, meaningful nonzero exit propagation, and updated CI. No import-free guarantee is retained for this test runner. |
| **F2 / P1 Python; firmware companion — confirmed unused locals** | Compiler diagnostics identify `speedFactor`, `weight`, `calibration`, `limit`, `movement`, `positionA`, `positionB`, and `positionC` around `main/motor/motor.ino:706–714`. In `main/helpers/protocols.py:655` and `:663`, `final_attempt_start` and `max_final_wait_time` are assigned but never read. | Delete the two Python assignments in Phase 1. Bundle the eight firmware declarations with the next verified firmware/reflash batch; do not create a separate flash obligation for them. | Removes misleading timeout hints and unused state with a small, focused diff. | Very low / high | Pressure tests for Python. Native tests, Mega build, and comparison with the same pre-deletion firmware revision for the deferred firmware work. |
| **F3 / P1 subscriptions; P2 placeholders — obsolete widget interactions** | `_NullWidget`, `main/kneespa.py:145`, has a no-op `update_pressure` and always reports invisible. Both subscriptions at `ProtocolController.start_protocol:327–360` end there; `_arduino_pressure_slot` only manages the redundant Arduino lambda. Real telemetry runs through `KneeSpa.status_emit:1706`. The timer guard at controller `:272` is always false; its `start(1000)` body is dead, while the active start is at `:378`. | Delete both pressure subscriptions, disconnect attempts, and slot bookkeeping in Phase 1. In Phase 2 delete the entire dead timer branch, not just its guard. Retire remaining treatment and authentication placeholders separately. | Removes unnecessary signal lifecycle code and fake UI dependencies. | Low for subscriptions; medium for broader cleanup / high | Existing controller/wiring tests with an actual no-op placeholder, repeated starts, live telemetry to SafetyMonitor, and a timer-order assertion. Gate W is not required for these deletions. Preserve the late timer start and public worker signals. |
| **F4 / P1 obsolete fields; P2 presentation ownership** | `ProtocolController.set_state:35`, reset completion, and window pause/resume/stop paths write overlapping presentation. `_StartButtonAdapter:194` interprets button text. The rollback comment at controller `:294–297`, assignments `:298–300`, initializers at `kneespa.py:381–383`, and tests at `test_protocol_controller.py:222–224` refer to unused `_prev_*` fields; real rollback uses `_prev_settings`. `protocol_timer` is constructed at both `kneespa.py:346` and `:1783`. | Remove the obsolete comment, assignments, initializers, and assertions together in Phase 1. After Gate W, centralize lifecycle presentation, replace value proxies at the same read points, and remove the superseded timer construction. Phase 3 explicitly moves the existing phase-text mapping into the controller and keeps its semantics as the accepted design. | Gives state transitions one identifiable presentation path without leaving misleading comments or duplicate timer setup. | Low for unused fields; medium–high for ownership/timer changes / high | Existing Cancel rollback test for deletion. Real-window and transition tests for ownership and timer construction. Preserve phase matching precedence, unknown-text behavior, display text, command ordering, and late input reads. |
| **F5 / P2 — permissive and duplicated test scaffolding** | `tests/conftest.py:24–62` globally patches filesystem behavior and logging. Controller builders use broad MagicMocks; `test_controller_wiring.py:1–8` explicitly says it calls methods unbound without constructing a window. Pressure unit cases around `test_protocol_pressure.py:69` and `:122` wait for real acknowledgement/pressure timeouts. Other builders are repeated or imported from test modules. | Make only the affected test collaborators explicit during Phases 1–2. Timebox Gate W and require it only for Phase 3. Move broader shared builders/scoped patches to Phase 4; bound the slow pressure unit cases as part of F1. | Improves regression detection without making a wholesale fixture migration the critical path for small deletions. | Medium / high | Affected tests alone and together; real-thread POSIX tests remain. Preserve missing-acknowledgement, timeout, and cancellation assertions. |
| **F6 / P2 — duplicated SMTP mechanics** | `KneeSpa.email_admin`, `main/kneespa.py:1113–1147`, and `submit_ticket:1149–1191` duplicate credentials, MIME headers, SSL connection, login, send, error logging, and daemon-thread setup. Their message bodies and recipients are legitimately different. | Extract one small send helper while retaining separate message construction and existing user feedback. | One place to maintain transport and error handling without creating a general notification layer. | Low–medium / high | Mock SMTP and thread execution. Assert recipients, headers, bodies, 15-second timeout, error logging, and immediate ticket acknowledgement. Existing wiring tests do not cover the full SMTP contract. |
| **F7 / P2 — temporary mutation during calibration persistence** | `CalibrationDraft.save`, `main/helpers/calibration.py:89`, builds a candidate and backup, then temporarily replaces `config.config` around `:115` to call the private writer, restoring it on failure. `Configuration._atomic_write`, `main/config/config.py:327`, writes `self.config`; `update_config:366` catches write exceptions. | Allow the existing atomic writer to accept a candidate parser, defaulting to the current parser. Publish the candidate to live state only after a successful write. Preserve backup behavior and the different callers' current error contracts. | Removes temporary shared-state mutation and makes write failure easier to reason about and test. | Medium / high | Existing disk-full calibration test, failed writes without live mutation, backup behavior, unknown sections, and legacy keys/defaults round trips. Keep the separate save-defaults bug out of this refactor. |
| **F8 / P3 — repository-unused compatibility APIs** | No caller in the current checkout was found for `Protocols.apply_continuous_pulse`, `main/helpers/protocols.py:860–927`, but both older `.claude/worktrees` checkouts at `b517d10` contain calls. One of those checkouts has uncommitted work. `Configuration.get_list:20` and six logging wrappers also have no current-checkout callers. The reset polling fallback is still exercised by tests. | Inventory service consumers using the explicit search scope below. Reconcile older worktrees before finalizing the deletion inventory; preserve uncommitted work before any removal. Retire only unsupported APIs or branches, keeping working v1/v2 completion paths. | Reduces compatibility surface only where retirement is supported by evidence. | Medium / high for current-checkout references; external use unknown | Include imports, discovery, exports, scripts, tests, and deployed consumers. Historical worktree calls are recorded separately, not silently ignored or mistaken for current application use. |
| **F9 / P3 — dependency and asset candidates** | `main/requirements.txt:12` pins the configparser backport, while the audited Windows environment imports the standard-library module. Ten button PNGs have no repository references. However, video discovery scans all `.mp4` files, font loading scans all `.ttf`/`.otf` files, and configuration validates the protocol graphics directory at startup. | Confirm supported Pi Python environments before removing the backport. Remove individual assets only after checking packaged/deployed consumers and discovery rules. Preserve directory contracts until intentionally changed. | Trims packaging and support burden without breaking indirect loading or startup validation. | Low–medium / medium | Dependency/import check on the supported Pi environment, fresh startup, all screens, fonts and video discovery, and deployment dry run. |

### Dead-code classification and exclusions

**Confirmed unused within their local implementation:** the eight firmware locals, two pressure-loop locals, and three `_prev_*` window fields have no production reads. The obsolete field comment and test assertions must be deleted with the fields. Python deletion is Phase 1; firmware deletion is deferred to the firmware companion batch.

**Obsolete internal behavior:** the two pressure subscriptions are confirmed dead wiring because both receivers are no-ops; focused controller/telemetry tests suffice for Phase 1. Other placeholder cleanup remains Phase 2 because deleting a guard incorrectly can activate previously unreachable code. This classification does not authorize removing public signals or their active consumers.

**Repository-unused, external use not established:** F8 candidates. The six logging wrappers are `debug_serial`, `debug_protocol`, `debug_thread`, `debug_gpio`, `debug_signal`, and `debug_lock`. Other debugging helpers have actual callers and should remain.

**Asset candidates, not confirmed safe deletions:** `arrow-back.png`, `arrow-forward.png`, `down_1.png`, `down_2.png`, `pause-black.png`, `play-button.png`, `play.png`, `restart.png`, `up_1.png`, and `up_2.png`. By contrast, the avatar, knee image, full logo, and spinner have active uses. `VideoModal._discover_playlist` around `main/ui/modals/video_modal.py:212–228` discovers filenames dynamically. Font loading around `main/ui/theme/qss.py:108–125` also uses directory discovery.

Scripts, calibration tools, support sketches, archived presets, and package re-exports must not be labeled unused simply because the main application does not import them. `UI_PATHS` and `PROTOCOL_IMAGES` in `main/config/constants.py` participate in startup path validation; removing their directories would currently change startup behavior.

### Search scope and older worktrees

Search the current checkout's tracked and untracked source, tests, hidden CI/configuration files, styles, scripts, operational tools, and documentation. Include ignored operational scripts individually if the inventory discovers any. Explicitly exclude dependency/generated trees from current-code reference counts: `.git`, `.venv`, `venv`, `kneespa_env`, `__pycache__`, `.pytest_cache`, `.pio`, `.native-build`, and `.claude/worktrees`. A reproducible starting search is:

```sh
rg -n --hidden --no-ignore -g '!**/.git/**' -g '!**/.venv/**' -g '!**/venv/**' -g '!**/kneespa_env/**' -g '!**/__pycache__/**' -g '!**/.pytest_cache/**' -g '!**/.pio/**' -g '!**/.native-build/**' -g '!.claude/worktrees/**' 'apply_continuous_pulse|get_list|debug_serial|debug_protocol|debug_thread|debug_gpio|debug_signal|debug_lock' .
```

For each candidate, additionally inspect dynamic imports, directory discovery, routing/configuration conventions, launchers, package exports, and external service consumers. A text search is not proof of non-use.

`git worktree list --porcelain` confirmed two older checkouts at `b517d10`: `.claude/worktrees/sad-ritchie-346623` is clean, while `.claude/worktrees/setup-protocols-vlc-fixes-847050` has **19 uncommitted entries**. Both contain calls to `apply_continuous_pulse`. Before the Phase 5 deletion inventory is finalized, determine whether they are still operationally used; preserve or land unique work, then remove retired worktrees normally and prune stale metadata. Do not force-remove the dirty checkout. If a checkout remains active, record it as a compatibility consumer and defer affected deletions. `git worktree prune` alone does not remove existing checkouts. No worktrees were removed during this revision.

## Regression coverage to establish before higher-risk changes

`tests/unit/test_controller_wiring.py:1–8` explicitly documents unbound `KneeSpa` method calls against a MagicMock window. It already covers login delegation, Setup command mapping, treatment pause/resume/stop presentation calls, Cancel rollback through `_prev_settings` (`:454`), defaults clamping, telemetry forwarding to SafetyMonitor (`:521`), and phase/button adapters (`:535`). `test_protocol_controller.py` adds readiness, confirmation races, immediate worker failure/progress, reset/release, and completion outcomes. These are suitable foundations for the bounded deletions in Phases 1–2, with focused assertions for the touched paths.

They do not construct `KneeSpa`, call `_connect_shell`, check the actual widget enabled states, or establish how constructor timers and Qt signal connections interact. MagicMock accepts missing attributes and cannot expose a disconnected real button. That gap gates Phase 3; it does not block the first cleanup, SMTP extraction, or calibration writer work.

1. **Real window wiring (Gate W; Phase 3 only).** Construct `KneeSpa` with hardware/network/storage boundaries controlled, while retaining the actual shell, controllers, `_connect_shell`, and `setup_timers`. Exercise control signals through to observed view state.
2. **Treatment transition matrix.** Cover start, confirmation cancellation, running, pause, resume, stopping, completion, reset failure, and fault. Assert start/pause controls, duration and patient editing, navigation gating, countdown, banners, and stop behavior. Include events delivered while a confirmation dialog is open.
3. **Command failure and timing contracts.** Cover rejected initial, increment, final, and retry pressure commands; lateral rejection; missing telemetry; missing DONE; and cancellation. Use controlled time in unit tests. Preserve the distinct direct-pressure and ramp tolerances and their different timeouts.
4. **Repeated execution and reconnection.** Confirm that old worker and telemetry subscriptions are detached, late completion cannot incorrectly alter a later run, and reconnection preserves the intended state.
5. **Offline SMTP contracts.** Assert both message types' recipients, content, headers, timeout, failure logging, and immediate UI acknowledgement without sending email.
6. **Configuration compatibility.** Cover missing and malformed values, `0` versus `0.0`, marked and unmarked calibration/default values, unknown sections, backups, and write failures. Characterize each caller's current error behavior before changing writer mechanics.

Extend relevant existing tests rather than creating a parallel test suite. Keep real serial/thread integration tests as a separate check on synchronization behavior.

### F1 decision: keep a thin runner, retire source-pattern snapshots

`scripts/validate_fixes.py` remains a supported local command, but becomes a small subprocess runner using the current Python interpreter for `check_limits_sync.py` and an explicit selection of behavioral tests. It must propagate a failing child exit status. It no longer promises to run without test dependencies. Do not replace the stale pressure regex with a different regex or create a new source-snapshot suite.

Map all 12 old checks before removing their assertions:

| Old check or group | Replacement / disposition |
| --- | --- |
| Arduino readiness event and queued send | Reuse `test_arduino_send.py` cases for no inline write, queue priority, failed links, and readiness/timeout behavior; retain POSIX communication tests in the full gate. |
| Window delegation, ConnectionManager ownership, protocol readiness (three checks) | Assert failed readiness prevents worker dispatch and successful readiness permits it in `test_connection_manager.py` and `test_protocol_controller.py`. Retire assertions about the exact forwarding method and which class mentions an Event. |
| Rejected/unverified protocol commands | Extend `test_protocol_pressure.py`, `test_protocol_logic.py`, and `test_protocol_pause.py` only where needed for rejected pressure/lateral sends, cancellation, and failed verification. Control unit-test time and acknowledgements; keep timeout assertions and real-thread integration coverage. |
| Human-unit UI limits | Use boundary and emitted-command cases in `test_actuator_controls.py`, `test_conversions.py`, and `test_controller_wiring.py`, rather than checking imported constant names. |
| Firmware hard clamps | Keep `check_limits_sync.py` and the native clamp/parse suites plus the Mega build. The local Python runner need not build firmware; CI already has firmware jobs. |
| Duplicate firmware path absent | Retire this historical deletion assertion. Record `main/motor/` as the build/deployment source and check the actual build inputs when changing firmware packaging. |
| Authentication uses hashes | Reuse behavior in `test_secure_auth.py` and `test_csv_helper.py`, preserving both current hashing and legacy compatibility; do not require the spelling `hashlib.sha256` as a proxy. |
| Environment-configurable paths and credentials | Add missing isolated environment-override cases to `test_constants.py`, including the documented base/config/SMTP variables. Inspect outcomes, not source identifiers; avoid leaking reloaded constants into other tests. |
| Missing config produces complete defaults | Reuse/extend `test_config.py` and `test_config_defaults.py` to create a fresh temporary config and assert usable A/B/C marks and default values. |
| Documented CLI options | Add `tests/unit/test_kneespa_cli.py` (proposed) to call `kneespa.main` with fake application/window/exit and logging boundaries. Verify `--config`, `--debug`, `--print-logs`, and `--sync-logs` reach the appropriate recipients. This does not require the real-window fixture. |

The implementation commit must list the exact test node IDs selected by the runner and identify coverage additions versus reused tests. In `.github/workflows/ci.yml`, remove the snapshot step and its obsolete comment; retain the separate limit check, the single full pytest invocation, and both firmware jobs. This avoids running the wrapper's pytest subset again inside CI's full suite.

### Verification cost and cadence

**Per commit:** run affected tests and inspect the diff. **Per phase:** run the full applicable gates once against the phase's exact tip. Existing CI remains required; this cadence avoids manually repeating its entire workload for every local commit. Do not weaken CI to save local time.

| Change | Fast local gate per commit | Full gate at phase completion |
| --- | --- | --- |
| Phase 0 landing | Tests for the behavior in each landed unit; native tests/build for firmware units | Windows and Linux full pytest, limits check, native tests, Mega build. Record the known snapshot failure explicitly until Phase 1 replaces it; do not hide or waive unrelated failures. |
| B2 deployment repair | `bash -n rpi/sync_pis.sh`; proposed POSIX deployment-fixture tests with real local rsync | Local fixture preservation/deletion/error-path checks against the production script's arguments. No device sync, Python full-suite rerun, or firmware rebuild is needed for this shell-only fix. |
| Phase 1 verification runner / pressure locals | Selected tests from the F1 mapping; pressure logic/pause tests for the assignments; `check_limits_sync.py` | Windows and Linux full pytest plus the new local runner; existing CI firmware jobs must remain green. No additional manual firmware build is required for this Python-only phase. |
| Phase 1 subscriptions / fields; Phase 2 treatment cleanup | `test_protocol_controller.py`, `test_controller_wiring.py`, `test_treatment_ui.py`, and relevant cases in `test_additional_regressions.py` / `test_reported_regressions.py` | Windows and Linux full pytest and the runner. |
| Phase 2 authentication cleanup | Login/logout cases in `test_controller_wiring.py`, `test_secure_auth.py`, and relevant real-shell/modal tests | Windows and Linux full pytest and the runner. |
| Gate W / Phase 3 | New window-wiring tests and the transition cases touched by each commit, plus existing controller tests | Windows and Linux full pytest and the runner; record remaining device-only limitations. |
| Phase 4 | SMTP contract cases, or calibration/config cases, or tests using the moved fixture, according to the commit | Windows and Linux full pytest and the runner after each independent task is complete; no dependency on other Phase 4 tasks. |
| Firmware companion | Native tests, limit synchronization, and Mega build | Those checks against the final firmware commit, then the existing on-device checklist for the scheduled reflash. |
| Phase 5 | Consumer/import/asset checks relevant to each deletion | Appropriate Python suites, supported Pi startup, resource loading, and packaging/deployment fixture checks; build firmware only if firmware inputs change. |

The measured Python full-suite cost is **633.42 seconds (about 10.6 minutes) sequentially**, before firmware checks. Allow roughly 15 minutes for a combined local phase gate as a planning budget, not a measured total or guarantee. Affected-test times have not been measured. Aim for a sub-two-minute Phase 1 fast gate after bounding the pressure unit waits; if it exceeds that target, report the timing and narrow to relevant cases without removing behavior coverage. New code changes, failures, or unresolved concerns justify repeating checks; an unchanged successful gate does not.

## Bugs and concerns tracked separately

These are not implicit fixes inside refactoring commits. **B2 is a separate operational repair scheduled immediately after Phase 0 and before Phase 1 or any deployment.** B1 and B3 remain separate follow-ups.

| Item | Evidence and status | Separate follow-up |
| --- | --- | --- |
| **B1 — defaults can report success after a failed write** | Confirmed by an in-memory reproduction: `_atomic_write` raised an injected `OSError`, while `update_config` around `main/config/config.py:400–406` swallowed it. `save_protocol_defaults` updated memory and returned normally; the UI path around `main/kneespa.py:1014–1019` reports Saved. No configuration file was changed by the reproduction. | Define the intended UI and rollback behavior, then fix and test it separately. Do not silently make all persistence callers propagate errors during F7. |
| **B2 — deployment sync can delete runtime state; first operational repair** | Confirmed with a temporary-fixture rsync dry run using the exclusions from `rpi/sync_pis.sh:29` and `--delete` around `:48`. Both `data/auth_state.json` and `data/pending_uploads.json` were reported for deletion. The critique also reports stale default hosts at `:24`; the correct bench addresses were not established during this revision. No deployment was performed. | Before Phase 1, protect both files against deletion and overwrite in a separate bug-fix commit, with local fixture tests. Resolve default hosts against a current bench inventory and require explicit verified `PI_HOSTS` for any deployment while that remains unresolved. Do not invent replacement addresses or delay file protection pending host discovery. |
| **B3 — completion acknowledgement may satisfy a different move** | Suspected, not reproduced on the device. `Protocols._on_firmware_done` around `main/helpers/protocols.py:485` sets shared completion state, and the lateral path around `:837` accepts completion as arrival. A delayed acknowledgement from another outstanding command may interleave with a move. | Add an acknowledgement-interleaving test and inspect protocol v1/v2 behavior before deciding whether a defect exists or changing completion handling. |

## Phased implementation plan

### Phase 0 — land the existing work and establish a committed baseline

**Dependencies:** none. Complete this before creating refactoring commits. This phase contains no new cleanup or real-window fixture project.

Tasks:

1. Inventory the current diff and untracked files against `fd7ddc2`. Separate existing calibration, firmware/host protocol changes, UI fixes, regression coverage, and documentation by behavior. Where features overlap in one file, assign hunks explicitly; do not invent an ordering that leaves tests or imports broken.
2. Land coherent, dependency-consistent commits with their relevant tests. Calibration spans the new controller/helper/dialog, config, Profile, and window integration. Firmware work spans `main/motor/` and the matching host transport/protocol changes. Regression tests should accompany the behavior they protect; a separate test-only commit is appropriate only when its parent already passes it. UI changes and documentation should have their own review boundaries where separable.
3. Stage an explicit path allowlist, and use explicit hunks in shared files such as `main/kneespa.py`. Review both staged names and staged content before each commit. Never use blanket `git add -A` or `git add .`. Exclude runtime PIN tables, PIN backups, device configuration, authentication state, pending uploads, credentials, and generated artifacts. The critique's cited PIN-backup history is a reason to keep this review explicit.
4. Record the landed commit IDs, final baseline SHA, changed-file inventory, dependency versions, actual verification commands/results, and any known failure. Use a clean checkout of that SHA for refactoring; do not present a dirty snapshot as a reviewable baseline. Keep unrelated unfinished work separately preserved, not silently discarded or absorbed into a cleanup commit.

**Acceptance criteria:** all implementation being refactored is in inspectable commits; their dependency order is recorded; the refactoring checkout is clean. The full baseline gate runs against its exact SHA. The known F1 snapshot failure is named until repaired in Phase 1; any other failure is investigated separately. No runtime data or credentials are staged.

**Review/revert boundary:** the existing features land before any refactoring. If a feature cannot be split without breaking its parent, land that coherent dependency unit together and explain the coupling. This document does not select, stage, or commit those changes itself.

### Before Phase 1 — repair deployment-state preservation (B2)

**Dependencies:** Phase 0. This is a separate behavior-changing bug fix, prioritized before refactoring and before another deployment.

Tasks:

1. Update `rpi/sync_pis.sh` exclusions to protect `data/auth_state.json` and `data/pending_uploads.json` against both receiver deletion and source overwrite. Preserve existing calibration, user-PIN, log, and cache exclusions and service stop/sync/start behavior.
2. Add a POSIX fixture test, proposed as `tests/integration/test_deploy_sync.py`, that exercises the production script with a stub SSH command and a local rsync shim targeting temporary directories. Use the real rsync engine with the script's effective arguments; do not replace this with source-pattern assertions or connect to a Pi.
3. Test destination-only runtime files and conflicting source copies: device bytes must survive both cases. Also assert that updated code is copied, obsolete code is deleted, and a failed sync does not issue the service-start action.
4. Reconcile the default host list with a current bench inventory. The critique reports stale defaults, but supplies no replacement addresses. Until verified, require an explicitly verified `PI_HOSTS` value in deployment instructions; do not guess IPs. This discovery must not delay the file-preservation fix.

**Acceptance criteria:** shell syntax and local fixture tests pass; protected files survive with identical bytes; code synchronization still works; failure behavior is preserved. Record the fix SHA and unresolved host inventory, if any. No actual deployment is part of these tests.

**Review/revert boundary:** one dedicated deployment-fix commit, outside the behavior-preserving refactoring series. Reverting it requires stopping use of the affected deployment path until equivalent preservation is restored.

### Phase 1 — Python-only verification repair and confirmed cleanup

**Dependencies:** Phase 0 and the B2 file-preservation repair. No real-window fixture or firmware reflash dependency.

Tasks, in reviewable commit order:

1. **1A — repair the gate:** implement the F1 thin-runner decision and coverage mapping, add only missing behavioral cases, and bound the identified pressure unit waits. Update CI to retain one full pytest run and remove source-snapshot assertions. Do not change production behavior to make the new tests pass; route discovered bugs separately.
2. **1B — remove pressure locals:** delete only `final_attempt_start` and `max_final_wait_time` from `main/helpers/protocols.py`. Preserve real pressure timeouts, retries, and command flow.
3. **1C — remove dead pressure wiring:** delete both `pressure_emit`/`status_emit` connections to `_NullWidget.update_pressure`, their disconnect attempts, the lambda, related connection diagnostics, and `_arduino_pressure_slot` bookkeeping from `ProtocolController.start_protocol`. Keep the worker signal API and the active `KneeSpa.status_emit` connection used by the UI and SafetyMonitor. Leave placeholder field retirement for Phase 2.
4. **1D — remove obsolete rollback fields completely:** delete the comment at `protocol_controller.py:294–297`, all three assignments at `:298–300`, all three initializers at `kneespa.py:381–383`, and the three assertions at `test_protocol_controller.py:222–224` together. Keep the test's worker-input assertions and the existing Cancel rollback test through `_prev_settings`.

**Acceptance criteria:** affected controller tests use an actual no-op placeholder or explicitly configure its visibility as false where relevant. Repeated starts no longer attach placeholder pressure receivers, while real telemetry still updates the treatment view and SafetyMonitor. Cancel still restores the previous slider value. The full Python phase gate and runner pass. Production changes are limited to the listed deletions; no firmware, timer-start ordering, safety, or rollback behavior changes are included.

**Review/revert boundary:** 1A–1D are separate commits. No new test is needed solely to prove an unused local or field disappeared; test the meaningful telemetry and rollback contracts instead.

### Firmware companion — fold unused locals into the scheduled reflash batch

**Dependencies:** committed firmware/host baseline from Phase 0 and a verified bench/reflash plan. This work does not gate the Python phases.

The critique reports an owed FAILSAFE-6 / continuous-pulse reflash. Treat the currently flashed revision and that operational status as unverified until checked on the bench. At the next confirmed firmware batch, remove the eight F2 locals as a separate, adjacent cleanup commit and include that commit in the same build/flash record. Do not request a separate reflash for declaration cleanup.

**Acceptance criteria:** native tests, limit synchronization, and the Mega build pass. Compare resource use and diagnostics with the same firmware immediately before the declaration deletion, not an unrelated older release. Record the host commit, firmware commit/build, flashed revision, rollback artifact, and results from the existing Phase E hardware checklist. The signed-comparison warning remains outside this cleanup.

### Phase 2 — retire remaining obsolete widget interactions

**Dependencies:** Phase 1. Use existing controller/wiring tests plus targeted assertions; Gate W is not a prerequisite.

Tasks:

1. Remove remaining treatment placeholder calls, including disabled legacy navigation/time controls, hidden-dialog completion cleanup, and invisible-dialog countdown updates. Account for every consumer before deleting the corresponding window fields.
2. **Delete the entire timer-dialog branch at `protocol_controller.py:272–276`, including its body.** `_NullWidget.isVisible()` is false, so `protocol_timer.start(1000)` there never executes today. Removing only the guard would introduce a timer start before worker construction.
3. Preserve the active `protocol_timer.start()` around `:378`, after worker construction and signal/UI setup and immediately before thread-pool dispatch. Its interval remains 1000 ms as configured by `KneeSpa.setup_timers`. Add an ordered controller assertion with a genuinely false visibility result; a default MagicMock is insufficient.
4. In a separate commit, remove obsolete auth-side calls around `auth_controller.py:92–111` and `:152`, preserving `login_pin` clearing, the actual login modal, login gating, and lockout handling.
5. Delete `_NullWidget` pieces only after all remaining consumers are accounted for. Leave the duplicate `QTimer()` construction at `kneespa.py:346` for Phase 3's constructor coverage; do not merge that lifecycle change into this timer-branch deletion.

**Acceptance criteria:** focused treatment/auth tests and the full phase gate pass. Successful startup still starts the timer once at the existing late point; aborted startup does not start it. Telemetry, countdown, PIN clearing, lockout, and stop behavior are unchanged. Every deleted placeholder has an accounted-for usage search, and required public signals remain.

**Review/revert boundary:** treatment cleanup and authentication cleanup are separate commits. This phase removes dead interactions without changing presentation ownership.

### Gate W — bounded real-window coverage for Phase 3

**Dependencies:** can be developed alongside Phase 2; acceptance must describe the Phase 2 result. This gate applies to Phase 3 only.

**Planning estimate, not measured:** 0.5–1 developer day for a minimal constructor fixture and 1–2 days for the transition/event cases, assuming the current Qt test environment remains usable. Timebox the first feasibility pass to four hours; report the specific constructor dependencies encountered rather than starting a production dependency-injection redesign.

Tasks:

1. Add a proposed `tests/integration/test_window_wiring.py` with the actual `KneeSpa` constructor, shell, controllers, `_connect_shell`, and `setup_timers`. Use temporary configuration/user storage and controlled GPIO, serial startup, cloud, SMTP, and VLC boundaries. Avoid real serial ports, network requests, or persistent operator data. Stop test timers and dispose the window during teardown.
2. Prove one actual treatment control signal reaches its controller and changes visible/enabled widget state. Characterize timer construction, its 1000 ms interval, the existing timeout connection, startup ordering, and cleanup.
3. Add the start/confirmation/pause/resume/stop/completion/reset/fault matrix, including nested confirmation events, immediate worker completion, live edits, and stale callbacks. Reuse existing controller cases where appropriate, adding actual view assertions rather than duplicating their logic.

**Fallback if constructor setup exceeds the timebox:** split out a real AppShell plus real-controller fixture with an explicit window facade to characterize view behavior while diagnosing construction. Keep a separate constructor-smoke task with its blockers listed. The facade fixture does not count as constructor coverage and does not authorize timer-construction cleanup. Phases 1, 2, 4, and the Phase 5 inventory can continue; Phase 3 waits for the relevant gate to pass rather than weakening its acceptance criteria.

**Acceptance criteria:** the real constructor and `_connect_shell` execute, actual control signals are tested, and the transition matrix passes without physical hardware or network access. Record which race conditions are simulated and which still require device verification. Keep fixture construction and transition cases as separate reviewable test commits.

### Phase 3 — simplify treatment presentation and state ownership

**Dependencies:** Phase 2 and Gate W. No unrelated Phase 4/5 work depends on completion of this phase.

Tasks:

1. Replace `_StartButtonAdapter` text-driven behavior with direct view setters through the existing controller. Remove duplicate lifecycle presentation writes one transition at a time from reset, pause, resume, and stop paths.
2. Replace `_ValueProxy` reads at their existing points. Preserve settings changes possible during confirmation and nested Qt events; do not capture all inputs earlier as one immutable snapshot.
3. **Resolve the phase-text adapter in this phase:** move its small mapping into an explicit helper in the existing protocol controller and remove `_PhaseLabelAdapter` indirection. String interpretation is the accepted compatibility design for this refactoring, not an unspecified future migration. Preserve the existing order: `pulsing`, `oscillat`, `moving to`, `complete`, `stopped`, then `started`/`pressure`. Unknown text leaves the phase unchanged. Preserve case handling, full banner text, `lstrip(">")`, and existing error behavior. Extend adapter cases for precedence/unknown text and exercise the controller path. No structured status protocol or new signal layer is proposed.
4. In a separate constructor-focused commit, remove the superseded `self.protocol_timer = QTimer()` at `kneespa.py:346`, after confirming no startup consumer uses that instance. Keep `QTimer(self)`, the interval, and timeout connection in `setup_timers:1783–1789` at their existing point. Do not move timer startup or merge it with the Phase 2 guard deletion.

**Acceptance criteria:** the real-window matrix passes, including confirmation races, faults, reset failure, pause/resume, and completion racing stop. Command order, uploads, countdown timing, phase matching, and visible text remain unchanged. The window has one protocol timer and one intended timeout connection; startup and teardown tests pass. Each lifecycle transition has one identifiable presentation path.

**Review/revert boundary:** migrate one transition group per commit; phase mapping and timer construction are separate commits. Do not combine transport, calibration math, or stop/release semantics with this work.

### Phase 4 — consolidate bounded mechanics

**Dependencies:** the committed baseline and Phase 1's verification repair, plus tests for the individual task. No dependency on Gate W or Phase 3. The following tasks are independent and can ship separately.

Tasks:

1. **SMTP:** add the offline message/transport contract tests, then extract the small shared send helper from F6. Preserve message builders, recipients, background execution, errors, and immediate UI acknowledgement.
2. **Calibration persistence:** verify round-trip/failure contracts, then let `_atomic_write` accept a candidate parser and publish calibration state only after success. Preserve backups, atomic replacement, and caller-specific error behavior; keep B1 separate.
3. **Test support:** move shared builders out of test modules, make required collaborator fields explicit, and narrow global filesystem patches in small groups. Do not require migrating the whole suite to unblock another task.

**Acceptance criteria:** the task-specific tests and its full Python gate pass. SMTP remains offline under test; persistence preserves unknown sections and failure behavior; affected tests pass individually and together. Migrated builders no longer come from another test module. No generic service layer or new dependency is introduced.

**Review/revert boundary:** each task is independently reviewable and revertible, including its own coverage and phase-gate result.

### Phase 5 — remove only verified compatibility, dependency, and asset candidates

**Dependencies:** consumer and supported Pi environment evidence. Inventory can start after Phase 0; complete Phase 2 before finalizing UI asset consumers. No dependency on Gate W.

Tasks:

1. Reconcile the two older worktrees as described under search scope before finalizing the deletion inventory. Preserve the 19 uncommitted entries in the dirty checkout. Remove only retired checkouts and prune stale metadata; retained operational checkouts remain consumers.
2. Run the documented current-checkout search, with exclusions recorded, then inspect operational launchers, discovery rules, scripts, tests, exports, configuration, and external service consumers for F8 and the reset polling fallback.
3. Record the supported Pi Python version and actual `configparser` import source; remove the backport only if its deployment role is disproved.
4. Check each candidate PNG against code, styles, packaging, and deployed consumers, retaining dynamic video/font loading and startup directory contracts.
5. Remove confirmed candidates in small groups with a deletion manifest and verification notes. Leave unresolved candidates in place and state the missing evidence.

**Acceptance criteria:** supported launchers and tools work; persistence and public contracts remain compatible; startup validation, remaining resource loading, and deployment preservation pass. The manifest distinguishes confirmed deletion from deferred compatibility candidates and lists search exclusions. Old worktree calls are accounted for, not erased as evidence.

**Review/revert boundary:** separate API retirement, dependency removal, and asset deletion. Worktree housekeeping and the B2 deployment fix are separate from application refactoring.

## Leave alone for now

- Serial queues, pacing, locks, checksums, protocol v1/v2 handling, and command handles. They implement real concurrency and compatibility requirements.
- Physical versus software stop, pressure release, recovery timers, and advisory versus fault behavior. Changes require stronger race coverage and device validation.
- Calibration math and the differing horizontal/lateral mappings. Preserve operator calibration data and existing `CMarks` interpretation.
- Connection startup's Qt/Python thread arrangement until late-connect, teardown, reset, and shutdown interactions have focused coverage.
- VLC platform/audio fallbacks, dynamically loaded fonts, active design-system re-exports, support sketches, and presets with uncertain operational consumers.
- Separate pressure loops where tolerances, pause handling, retry behavior, or completion semantics differ. Superficial repetition does not justify one generic loop.

## Recommended first production refactoring batch

After Phase 0 has landed the existing implementation and B2 has been fixed in its own commit, implement **Phase 1 only**, as commits 1A–1D. The first batch is Python-only and does not wait for Gate W or a firmware reflash.

**Explicit scope:**

- `scripts/validate_fixes.py` and `.github/workflows/ci.yml`: implement the thin behavioral runner, remove the CI snapshot step, and retain the existing full pytest/limit/firmware checks.
- Tests identified in the F1 replacement mapping: add missing behavior coverage and control the slow pressure unit waits. The proposed CLI test is `tests/unit/test_kneespa_cli.py`; no real-window fixture is required.
- `main/helpers/protocols.py`: remove only `final_attempt_start` and `max_final_wait_time`.
- `main/controllers/protocol_controller.py`: remove only the dead pressure subscription block and its diagnostics/bookkeeping, plus the obsolete rollback comment and three assignments.
- `main/kneespa.py`: remove only the three `_prev_*` initializers.
- `tests/unit/test_protocol_controller.py`: remove the three obsolete field assertions while retaining worker-input coverage; add focused pressure-subscription/telemetry assertions in the appropriate existing controller/wiring tests. Keep the Cancel rollback regression.

The scope excludes firmware edits, placeholder-field retirement, timer changes, presentation ownership changes, persistence changes, and bug fixes. Enumerate exact changed test paths/hunks in the implementation commit rather than staging the whole tests directory.

**Validation steps:**

1. Before each commit, inspect the exact staged paths and diff. Confirm that real timeouts/retries, timer ordering, worker signals, active telemetry, and `_prev_settings` behavior are unchanged.
2. For 1A, run the new runner and its selected behavior cases; demonstrate meaningful failure propagation. For 1B, run the pressure/logic/pause selection. For 1C–1D, run the controller/wiring/treatment selection and relevant regression cases. Example Windows commands, from the repository root:

   ```powershell
   .venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_pressure.py tests/unit/test_protocol_logic.py tests/unit/test_protocol_pause.py
   .venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_controller.py tests/unit/test_controller_wiring.py tests/unit/test_treatment_ui.py tests/unit/test_additional_regressions.py tests/unit/test_reported_regressions.py
   ```

3. At the Phase 1 tip, run the full Windows and WSL/Linux Python suites once, record the commit SHA and results, and run `scripts/check_limits_sync.py` plus the new runner. Confirm all existing CI jobs pass. Do not manually add a firmware build to each Python deletion commit; the firmware companion has its own native/build/device gate.
4. Review the final production diff as a set of deletions. Confirm the misleading rollback comment and test assertions disappeared with their fields, that the pressure signal API remains, and that genuine telemetry still reaches SafetyMonitor.

**Acceptance criteria:** all applicable gates pass against an exact committed baseline; repeated treatment starts do not attach no-op pressure receivers; active telemetry and Cancel rollback retain their behavior. No firmware or flashed-version change is required. Public signals and required diagnostic/error handling remain; only messages announcing the removed no-op connections are retired. Do not add tests solely to assert that unused local variables were removed.

## Context still required

- Supported Raspberry Pi OS/Python versions and the deployed dependency set.
- Whether external service or calibration scripts call repository-unused public helpers.
- Device-based timing, emergency-stop, reconnect, and native VLC/audio verification for later higher-risk phases.
- The currently flashed firmware/build, the reported pending FAILSAFE-6 / continuous-pulse reflash, and verified deployment hosts. The critique reports stale default IPs; this revision does not establish replacements.
- Disposition of the older worktree's 19 uncommitted entries before its retirement or any deletion dependent on its non-use.
- Product decisions for B1. B2 is explicitly scheduled before Phase 1; B3 still needs reproduction.

These gaps do not make Gate W a prerequisite for the Python cleanup. The cleanup's actual prerequisites are the committed baseline and the B2 file-preservation repair. Missing consumer, deployment, or hardware evidence blocks only the dependent deletion or device action.

## Critique resolution record

| Critique | Resolution in this revision |
| --- | --- |
| 1. Dirty tree is not a reviewable baseline | Phase 0 lands existing work in coherent commits by explicit paths/hunks, excludes runtime data, and records an exact tested SHA before refactoring. Historical results are labeled accordingly. |
| 2. First batch is low-value and touches firmware | Phase 1 repairs verification and removes Python locals, dead subscriptions, and obsolete rollback fields. Firmware locals move to the scheduled firmware/reflash batch, whose current device status must first be verified. |
| 3. Subscription and timer risks are reversed | No-op subscriptions move to Phase 1. Phase 2 explicitly removes the entire false timer branch and preserves the later active start after worker/signal setup. |
| 4. Fixture work is an unbounded prerequisite | Existing controller coverage and its limits are documented. Gate W applies only to Phase 3, has an estimate and four-hour feasibility timebox, and offers a partial fixture fallback without misrepresenting it as constructor coverage. |
| 5. B2 is buried; default IPs are stale | B2 becomes a separate operational repair before Phase 1 or deployment, with local rsync preservation tests. Host verification is an explicit task; no replacement IPs are assumed. |
| 6. Obsolete rollback comment remains | Phase 1D deletes the comment, three assignments, three initializers, and three test assertions together, retaining the real Cancel regression. |
| Per-commit verification cost | Focused local checks are specified by change; full gates run at phase boundaries. Measured Python duration and an explicitly estimated combined budget are recorded. Existing CI gates remain required. |
| Unstated search scope and old worktrees | Exclusions and a reproducible search are specified. Both old checkouts/callers are recorded. Blanket pruning is qualified because one checkout has 19 uncommitted entries; preserve its work before retirement and retain active consumers as deletion blockers. |
| F1 repairs only one of many brittle checks | The script's long-term role is a thin runner. All 12 old checks have a behavioral replacement or explicit retirement; CI no longer runs source-pattern snapshots. |
| Phase-text handling is deferred indefinitely | Phase 3 contains an explicit adapter-removal task and accepts the existing string mapping as the compatibility design, with precedence and unknown-text tests. No future architecture migration is implied. |
| Duplicate protocol timer omitted | F4 records both constructions; Phase 3 removes the superseded one only after constructor coverage, preserving interval, ownership, connection, and startup order. |

The dead-code taxonomy is retained. The **Leave alone for now** section is unchanged. Only this plan was edited; the critique remains the review record, and no implementation or operational action was performed.
