# Phase B, Session 2 — Pickup Prompt

> **STATUS (end of session 2, 2026-07-02): PHASE B COMPLETE — Checkpoint B reached, awaiting owner review/push approval.**
> Branch `feat/gui-on-failsafe`, 7 replay commits on `improvement-plan` tip (`ec0e18a`), local only:
> `75a0d6d` replay(1) view layer · `39642fc` replay(2) B1 firmware+config/csv · `63a8654` replay(3) protocols.py pause union + tests + AGENTS.md · `fb83316` replay(4) ci.yml · `c1d4d68` replay(5) B2 AppShell swap + B3 e-stop GPIO · `06fb641` replay(6) legacy view deletions · `75825ae` replay(7) deferred-test re-enable.
> Verified at tip: WSL 513 passed/0 failed · Windows 474 passed/39 skipped (pty) · firmware natives all green · **AVR `pio run -e mega` SUCCESS** (registry reachable again; RAM 25.9%, Flash 10.6%).
> B6 verified: `KNEESPA_PROTOCOL_V2` and `KNEESPA_PULSE_RATE_FIRMWARE` both default off; H4 (single I/O thread owns the port) and H5 (flush per write + RX-silence watchdog) are the base contracts.
> The protocols.py re-verification flagged below CAME BACK CLEAN (pause core byte-identical to GUI source; only deliberate base improvements differ).
> Still pending (owner): push/PR approval, PIN re-provision + secret purge (Phase D), hardware measurements (Phase E). `main/config/kneespa.cfg` + `main/data/user_pins.csv` remain uncommitted runtime state.
> The plan below is retained for history.

*Hand this to a fresh Claude Code session in `C:\Users\patri\Documents\Projects\drx-2.0`. It continues Phase B (branch reconciliation) of the audit remediation. Read these first, in order:*

1. `docs/plans/2026-07-01-implementation-prompt.md` — ground rules (all still in force) + Phase B/C/D/E/F definitions.
2. `docs/adr/2026-07-02-branch-reconciliation.md` — the decided strategy: replay `9b23e11..feat/gui-modernization` onto `improvement-plan` via new branch `feat/gui-on-failsafe`.
3. `docs/plans/2026-07-02-current-state-and-decisions.md` — owner decisions still pending.
4. This file — exact mid-B4 state and next steps.

## Where things stand (end of session 1, 2026-07-02)

**Branch `feat/gui-on-failsafe`** (local only, NOT pushed — pushing needs owner approval):

| Commit | Content | Verified |
|---|---|---|
| `ec0e18a` | = `improvement-plan` tip (base) | baseline: 207/208 pytest (1 pure flake: `test_corrupt_frame_rejected_not_executed`, passes 5/5 alone), natives green |
| `75a0d6d` | replay(1/n): GUI view layer (`main/ui/**`), DS library, docs, angles.py, test plumbing, `.gitattributes` (LF for *.sh — autocrlf CRLF broke the runner), constants.py additive union | WSL 291 passed / 0 failed (= base 208 + 83 GUI tests); natives green |
| `39642fc` | replay(2/n): B1 firmware union (FAILSAFE-2 + `J<ms>` parse w/ clamps, 4 new tests) + config.py union (ProtocolDefaults/Device → atomic writes) + csv.py union (`_report_load_error`) + csv/secure-auth test unions adapted to salted `hash_pin_secure` | natives 84/84 (clamp 12, parse 31, safety 27, status 14); cluster 63 passed |

> ⚠️ **RE-VERIFY `protocols.py` FROM SCRATCH BEFORE COMMITTING (2026-07-02, session 1b).** A follow-up session re-applied the head-method pause guards (`run_pressure_sequence`, `set_to_pressure`, `set_to_c_distance`, `apply_continuous_pulse`) by hand on top of a partially-reverted working tree. The tail methods (`protocol_4`, `_pulse_or_hold_phase`) already had them. The file **parses OK** and has no duplicate method defs (`def pause`=1, `_start_pulse`=6 refs, `is_paused`=`_wait_while_paused`=14), but the "56/57" figure below is from the ORIGINAL attempt and is **NOT re-confirmed** — the merge could have doubled or dropped a guard. **First action next session:** run `test_protocol_pause.py` + `test_protocol_pressure.py` + full WSL suite, AND `git diff feat/gui-modernization:main/helpers/protocols.py -- <working tree>` to confirm the pause/pulse-rate semantics match the GUI source, before trusting anything or committing replay(3/n).

**Uncommitted working tree (B4 in flight, protocols union applied — pending re-verification per the warning above):**

- `main/helpers/protocols.py` — GUI pause/resume/`_start_pulse`/`pulse_rate` grafted onto improvement-plan's restructured version (pause-hold guards in every wait loop; 3× `send("J")` → `_start_pulse()`). Original attempt reported 56/57 unit (pause 10, pressure 24/25, logic 22) + 8/8 pty integration — **re-run to confirm.**
- The 1 failure: `tests/unit/test_protocol_pressure.py::TestStop::test_disables_high_frequency_before_emergency_stop` — GUI-line test pinning the OLD stop() ordering (HF0 before X). The base's `stop()` deliberately sends **X first** (jumps the queue), then P0, then HF0, keeping telemetry alive during release — that ordering is the safety-correct contract. **Fix the TEST to pin the base ordering (X → P0 → HF0), do not touch stop().**
- `tests/unit/test_protocol_pause.py` (A), `test_protocol_pressure.py` (A), `tests/integration/test_protocols.py` (M — GUI teardown hardening + timeout marker) — staged.
- `.gitignore` — union applied (native-build + .pio under Testing).
- `main/config/kneespa.cfg`, `main/data/user_pins.csv` — **runtime state, NEVER commit** (backups in scratchpad `runtime-backup/`; Phase D moves them out of git).

## Next steps, in order

1. **Finish B4** (~30 min): fix that one stop-ordering test expectation → run full WSL suite (expect ~334: 291 + 10 + 25 + 8 new) → `AGENTS.md` union (in-tree base version: KEEP its Testing + protocol-v2 sections — they are accurate; graft the GUI tip's kneespa.py bullet + "UI Components (code-built)" section; both sides' versions are stale about the other's domain) → commit replay(3/n).
2. **ci.yml union**: tip-vs-tip +38 −21. Phase A's workflow (GUI tip) ≈ improvement-plan's structure already; union = GUI tip's version (python job w/ Qt libs + libfontconfig1 + xvfb, gating firmware-native + firmware-avr jobs, de-duped triggers). Compare for anything improvement-plan-only (e.g. its own workflow name/paths) before overwriting.
3. **B2+B3 — the big one.** Design analysis done last session:
   - Controllers (`main/controllers/*`) take `window` in ctor and call `window.<attr>` directly (bind via local `window = self.window`). Full attribute contract extracted: `arduino, worker, ui(×19! legacy .ui object), config, treatment_panel, login_line_edit, start_button, timer_dialog, pressure_dialog, loading_spinner, time_edit, max_left/right/pressure_edit, protocol_number_field, increase/decrease_time, initial_setup_complete, protocol_state/running/start_time/duration, reset_in_progress, mid_protocol_warning_shown, current_user/users/login_pin, threadpool, thread, I2Cstatus(_event), _prev_*` + methods `_show_timed_error, _show_safety_alert, _warn_uncalibrated, set_protocol_state, stop_actuators, reset_arduino, setup_gpio, disable/enable_actuator_controls, reset_setup_readings, reset_extra_button_clicked, update_ui_after_login, ensure_arduino_connection, set_to_c_distance, read_position, status_emit, handle_*`.
   - **Approach:** new `kneespa.py` = improvement-plan's KneeSpa (controllers + frozen math + GPIO/reset paths byte-preserved) with the view layer swapped: legacy `.ui`/dialog/page methods (~lines 280–1143) → AppShell construction + `_connect_shell()` + `_on_*` handlers from the GUI tip's kneespa.py (scratchpad copy: `gui_kneespa.py`; also `git show feat/gui-modernization:main/kneespa.py`). GUI handlers delegate INTO the controllers instead of reimplementing. Controller UI touchpoints (`window.ui.start_button` etc.): keep controllers' logic identical; satisfy their contract via explicit window attrs/properties mapped to modern widgets (e.g. `start_button` → treatment screen's start/stop button; `time_edit`-like adapter over the duration slider exposing `.value()`); no-op only where the modern UI dropped the feature (show_timer/show_pressure buttons, forward/backward protocol-image buttons, timer_dialog/pressure_dialog) — with explicit comments. `treatment_panel` (SafetyMonitor's fault/pressure banner: `update_pressure/set_fault/set_idle/set_running/set_phase/set_stopping/update_remaining`): improvement-plan ships `main/ui/widgets/treatment_status_panel.py` — either mount it in AppShell chrome or map to the treatment screen's inline live-status; fault visibility is safety-relevant, decide with eyes open.
   - AuthController seam: modern login modal emits whole-PIN `login_attempt(pin)`; controller reads `window.login_pin` buffer — adapter: set `window.login_pin = pin` then `auth.handle_login()`; `window.login_dialog.accept()` → modal close. **Improvement-plan already has salted verify + 5-try/60s lockout (part of H3!).**
   - **B3:** on e-stop path also assert `EMERGENCYSTOP` GPIO (configured but never driven) + short-timeout no-reconnect X send. GUI tip's `_on_estop`/`emergency_stop_clicked`/`_emergency_stop_phase2` vs ProtocolController.emergency_stop_clicked — unify on the controller's, add GPIO assert.
   - Then replay the 12 deletions (7 `.ui`, 4 `main/ui/dialogs/*`, `tests/integration/test_pressure_dialog.py`) + retire legacy constants (PAGES, MAIN_UI/LOGIN_UI/... from UI_PATHS, 2 ERROR_MESSAGES) — grep first that nothing else references them (improvement-plan's `main/ui/widgets/press_feedback.py` + its tests may — check; retire or keep deliberately).
   - Re-enable deferred tests: `test_controller_wiring.py` (checkout from GUI tip; adapt to the new seam), and union `test_arduino_send.py` (36 tests) + `test_reset_worker_logic.py` (24) against improvement-plan's arduino.py/reset_worker.py (both were rewritten there; keep tests that still apply, adapt the rest — improvement-plan has its own `test_arduino_parse.py` 31 tests as reference). Both-sides files to union: `tests/unit/test_actuator_controls.py`, `test_conversions.py`, `tests/integration/test_arduino_comm.py`, `test_reset_worker.py`, `test_secure_auth.py` (take base version + GUI-only additions).
4. **B6**: verify `KNEESPA_PROTOCOL_V2` default-off + H4/H5 resolution (improvement-plan's arduino.py single reader / flush discipline) — likely just verification + note.
5. **AVR build retry**: `pio run -e mega` blocked all session — registry.platformio.org unreachable (HTTPClientError; DNS fine, github fine). Libs missing from `main/motor/.pio/libdeps/mega/`. Retry; if still down at checkpoint, report honestly (CI has its own cache when a push is approved).
6. **🛑 Checkpoint B**: full union WSL + Windows suites + natives (+ AVR if unblocked) green → report resolved-vs-open findings (expect resolved: C1–C5, H2, H4, H5, H8, plus C6+H6 discovered already-done on base; open: H1-UI-lock?, H3-rest, H7 → C/D).

## Verification recipes

- WSL: `wsl.exe bash <script>` via PowerShell tool; scripts in scratchpad (Git-Bash↔wsl pipes stall; PowerShell mangles quotes). venv: `~/.venvs/drx312` (CPython 3.12.13). Full suite: `QT_QPA_PLATFORM=offscreen ~/.venvs/drx312/bin/python -m pytest -q -p no:cacheprovider` (~60 s). Natives: `bash main/motor/run_native_tests.sh`.
- Windows quick checks fine for unit tests; pty tests skip here.
- Baseline flake to watch: `test_fake_arduino.py::TestFakeArduinoProtocolV2::test_corrupt_frame_rejected_not_executed` under full-suite load; de-flake if it recurs (tip commit `ec0e18a` was itself a de-flake — known theme).

## Standing constraints (from the implementation prompt — unchanged)

Safety first (hazard/acceptance/verification for any stop-path/clamp/protocol change; fail safe = stop + release). Software only. Frozen conventions stay frozen (command math, A-zero-offset, AFULLINCH vs AXIAL_MAX, B-axis direction — Phase E measures first). No blind merges. Verify "already fixed" claims. Flag-gate firmware-dependent behavior (`KNEESPA_PULSE_RATE_FIRMWARE`, `KNEESPA_PROTOCOL_V2`). **No push / no PRs without explicit owner approval; no history rewrites without 🛑 approval. Never commit `main/config/kneespa.cfg` or `main/data/user_pins.csv`.** Report honestly.
