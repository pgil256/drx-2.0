# Implementation Prompt — drx-2.0 Audit Remediation

*Hand this to a fresh Claude Code session working in `C:\Users\patri\Documents\Projects\drx-2.0`. It is self-contained but references the full audit at `docs/plans/2026-07-01-audit-and-improvement-plan.md` (read it first). The work spans multiple sessions and one on-device session — do not try to do it all in one run. Stop at the checkpoints marked 🛑.*

---

## Your role and the situation

You are remediating a full audit of KneeSpa DRx, a PyQt5 touchscreen controller for a medical knee-traction device (Raspberry Pi + Arduino motor controller over serial). Read `docs/plans/2026-07-01-audit-and-improvement-plan.md` in full before doing anything — it has every finding with file:line evidence. This prompt tells you how to execute it.

**The crux:** a completed, tested safety overhaul lives on the unmerged `improvement-plan` branch (firmware `2026-06-11-FAILSAFE-2`, protocol-v2 framing, UI-thread unblocking, and the `KneeSpa` god-object decomposed into `main/controllers/{safety_monitor,auth_controller,protocol_controller,connection_manager}.py`). The current branch `feat/gui-modernization` (PR #15) rebuilt the GUI on top of the **old pre-FAILSAFE** `main`, so it lacks all of that. Most CRITICAL findings are already fixed on `improvement-plan`. **The core task is to reconcile the two branches, not to re-write safety code from scratch.**

## Ground rules (do not violate)

1. **Safety first, always.** This device applies mechanical force to a patient's knee. Every change to a stop path, pressure/position clamp, or protocol state machine must have a stated hazard, an acceptance criterion, and a verification method. When unsure, fail safe (stop + release).
2. **Software/firmware only** — no hardware changes are in scope (the missing independent hardware E-stop interlock is a documented residual risk, not your task).
3. **Do NOT blind-merge the branches.** Reconcile file-by-file (§Phase B). Do NOT change the "frozen, unit-tested" conventions blind: the e-stop/conversion command math in `kneespa.py`, the A-command zero-offset (`target = ZERO + FULLINCH×inches`), the `AFULLINCH` vs `AXIAL_MAX` values, and the B-axis degree/direction convention are deliberately unchanged pending hardware measurement. Preserve them.
4. **Verify every "already fixed on improvement-plan" claim** against that branch's code before relying on it — do not assume.
5. **Flash-gate new firmware-dependent behavior** behind env flags (existing pattern: `PULSE_RATE_FIRMWARE_SUPPORT`, `KNEESPA_PROTOCOL_V2`). Firmware changes take effect only after an on-device flash + hardware checklist — never assume the device is flashed.
6. **CI is the definition of done for code phases:** the branch must be green AND gating (no `continue-on-error` hiding failures) before a phase is "done."
7. **Do not push or open/merge PRs without explicit human approval.** Do not rewrite shared/pushed history (PIN purge, rebase) without the 🛑 checkpoint approval. Work on a branch; commit locally.
8. **Report honestly.** If a test fails, show the output. If you skip something, say so.

## References

- Audit + phased plan: `docs/plans/2026-07-01-audit-and-improvement-plan.md`
- Prior safety effort (the source of the fix code): branch `improvement-plan`, docs `docs/audits/2026-06-11-full-application-audit.md`, `docs/plans/2026-06-11-improvement-plan.md`, `docs/plans/2026-06-11-batch1-hardware-checklist.md` (these docs are only on that branch — bring them across).
- GUI rebuild context: memory `gui-modernization-plan`, branch `feat/gui-modernization` (PR #15).

---

## Phase A — Unblock the PR: make CI green and gating (~1 day)

Do this first; nothing else can be trusted while CI is red.

- **A1. Fix the firmware native build.** `main/motor/motor.ino:17-20` includes `HX711.h`, `elapsedMillis.h`, `Wire.h`, `avr/wdt.h` unconditionally; the tests `#include "../../motor.ino"`. Guard the hardware includes behind `#ifdef UNIT_TEST` with the real libs in the `#else`, and add the missing mocks (`elapsedMillis` class, `wdt_enable`/`wdt_reset` no-op macros, `Wire`) alongside the existing `mock_hx711.h`. **Cross-check `improvement-plan`'s `main/motor/test/` harness — its firmware CI was green; reuse its approach rather than inventing one.**
  - *Accept:* `cd main/motor && pio test -e native` compiles and passes locally/CI.
- **A2. Fix the Python exit-137 (SIGKILL/OOM) hang.** Leading cause: FakeArduino pty integration tests skip on Windows dev but RUN on Ubuntu CI with real threads + 30–60 s waits + no teardown, and module-scoped `QApplication` fixtures never free widgets. In `tests/conftest.py` and `tests/integration/*`: make `QApplication` fixtures function-scoped with a finalizer that `deleteLater()`s top-level widgets and drains events; guarantee FakeArduino/protocol fixtures `join()` threads and `close()` serial in exception-safe teardown; raise the global `pytest.ini` timeout to ~120 s and mark the long pty tests. Reproduce on an Ubuntu runner to confirm the culprit.
  - *Accept:* full suite completes on Ubuntu CI without SIGKILL; local `python -m pytest -q` still green.
- **A3. Make firmware CI gate.** Remove `continue-on-error: true` from the `firmware-build` job in `.github/workflows/ci.yml:44` once A1 passes (split always-buildable `pio run -e mega` from native tests if you need an interim gate).
- **A4.** De-duplicate CI triggers (currently fires on both `push` and `pull_request` for every commit).

🛑 **Checkpoint A:** report CI status (green + gating) before proceeding.

---

## Phase B — Reconcile the two branches (the core work, ~1–2 weeks)

🛑 **Before any history rewrite, confirm the base-branch decision with the human and write a short ADR (`docs/adr/2026-07-xx-branch-reconciliation.md`).**
- **Recommended default:** replay the GUI rebuild *onto* `improvement-plan` (the safety backend is the riskier, more foundational code and should not be re-derived).
- **Alternative:** cherry-pick the FAILSAFE firmware + `main/controllers/*` + protocol-v2 + UI-thread-unblocking onto `feat/gui-modernization` (preserves PR #15 history).

Then reconcile **file-by-file** over the 9-file conflict surface (`kneespa.py`, `motor.ino`, `protocols.py`, `config.py`, `constants.py`, `csv.py`, `main/motor/test/test_command_parse/test_command_parse.cpp`, `tests/unit/test_csv_helper.py`, `AGENTS.md`):

- **B1. Firmware.** Take `motor.ino` `2026-06-11-FAILSAFE-2` wholesale — this resolves **C1** (host-death heartbeat watchdog + `wdt_enable`), **C2** (STOP honored in all phases), **C3** (autonomous pressure release on fault), **C5** (UI-thread unblocking side), **H8** (`noStatus`/pulse-phase pressure limit). Re-apply the GUI branch's `J<ms>` pulse-rate parse on top, behind `PULSE_RATE_FIRMWARE_SUPPORT`.
- **B2. Controller.** Rewire the GUI's `AppShell`/screen-signal seam onto the **decomposed** controllers instead of the monolith — this resolves **C4** (`SafetyMonitor` flips `worker.is_running = False` immediately on stop) and the god-object debt. Preserve the frozen command math (rule #3).
- **B3. Assert the hardware e-stop line (part of C5).** On the e-stop path, drive the `EMERGENCYSTOP` GPIO (configured at `kneespa.py:1482/1488` but never asserted) in addition to sending `X`, and ensure `X` goes out on a short-timeout path that does not do multi-retry serial reconnect on the GUI thread.
- **B4. `protocols.py` / `config.py` / `constants.py` / `csv.py`.** Merge the GUI additions (duration control, `[ProtocolDefaults]`, `pos_c_to_angle`, `J<ms>`) into the `improvement-plan` versions. **H2** (pulse-off truncation) should disappear because that branch restructured the final-phase loop — verify it does; if any `main_phase_loop_active = False` unconditional exit survives, delete it.
- **B5.** Bring the safety docs across (`docs/audits/2026-06-11-…`, the improvement plan, and the **Batch-1 hardware checklist** — you'll need it for Phase E).
- **B6.** Adopt protocol-v2 framing (seq + XOR checksum) kept behind `KNEESPA_PROTOCOL_V2=1`; confirm it resolves the command-correlation races (**H4** buffer flush, **H5** double reader thread, and the reset_worker stale-DONE race) or fix any that remain.

🛑 **Checkpoint B:** union of both branches' tests + firmware native tests pass; report which CRITICAL/HIGH findings are now resolved by the merge vs still open.

---

## Phase C — Net-new fixes not covered by reconciliation (~2–3 days)

GUI-branch regressions and shared bugs that survive the merge:

- **C6 — Atomic config write.** `main/config/config.py:239-240, 272-273`: write to `<cfg>.tmp`, `flush()` + `os.fsync()`, then `os.replace()`. Apply to `update_config` and `_write_default_config`.
- **H1 — Mid-run pressure no-op.** Lock the Max Pressure / Max Left / Max Right sliders during an active run (mirror the existing duration-slider lock in `treatment.py`), OR make the worker re-read them each phase iteration. The slider lock is the safe quick fix. (`kneespa.py:522`.)
- **H6 — Config schema validation.** After load, validate critical numerics against their ranges (`PRESSURE_MAX`, lateral/axial limits, non-zero calibration); surface a blocking UI error instead of silently defaulting; route the loaders' `print()`s through the logger. (`config.py:82-106, 133-162`.)
- **csv.py:** open `encoding="utf-8-sig"` (BOM lockout), skip-and-log malformed rows instead of aborting the loop (later users silently locked out), and catch `OSError`/`UnicodeDecodeError`. (`csv.py:74, 83`.)
- **reset_worker retry:** clear `I2Cstatus_event` (not just the flag) in both retry paths so a late DONE can't instantly satisfy the retry. (`reset_worker.py:117`.)
- **Controller timer/thread races:** cancel the pending `enable_actuator_controls` `singleShot`s in `disable_actuator_controls`; gate `enable_actuator_controls` on `reset_in_progress` too; `quit()/wait()` the Arduino `QThread` on reconnect/shutdown and drop or actually emit the dead `finished` wiring. (`kneespa.py:347-351, 1317`.)
- **SMTP:** pass `timeout=10` and move both `email_admin`/`submit_ticket` sends off the GUI thread onto the threadpool. (`kneespa.py:663, 703`.)
- **Blocking serial send:** move `time.sleep(0.3)` outside the `_lock` in `Arduino.send` (or drop it). (`arduino.py:478`.)
- **Post-stop keepalive:** make it cancellable and remove its `reset_input_buffer`/`reconnect` so it can't eat a newly-started protocol's frames. (`protocols.py:1003`.)
- **CMarks interpolation:** extract one `degrees_to_pos_c(degrees, cmarks)` into `helpers/angles.py` and call it from both `set_to_c_distance` copies and `move_actuator`. (`kneespa.py:124`, `protocols.py:424`.)
- **Watchdog message:** split the pressure-vs-axial trip into accurate messages. (`kneespa.py:1234`.)
- **Kiosk fullscreen:** `setWindowFlags(Qt.Window | Qt.FramelessWindowHint)` BEFORE `showFullScreen()`. (`kneespa.py:247`.)
- **VLC poll-on-crash:** detect sustained `None` position (≥3 polls) → `_reset_playback()` + stop the timer + surface failure. (`ui/modals/video_modal.py`.)
- **QSS resolver:** log a warning (and fall back to a safe default) on an unknown `var(--token)` instead of emitting literal `var(...)` text. (`ui/theme/qss.py:43`.)

---

## Phase D — Security & robustness hardening (~3–4 days)

- **H3 — PIN security (do all three, they only work together):**
  1. Migrate to a salted slow KDF (argon2id/bcrypt/scrypt), per-user random salt, with a one-time migration of the CSV.
  2. Add persistent attempt lockout + exponential backoff + failed-attempt logging (never log the PIN).
  3. **Rotate every PIN** (`1234`/`456`/`123` are burned and reversible from the committed hashes), ship an empty `user_pins.csv.example`, load real users from an out-of-repo/env path, and 🛑 **with human approval** purge the plaintext blob from history (git-filter-repo/BFG). Remove `unlock = 123` from configs if unused.
- **Secrets out of git:** `git rm --cached main/data/user_pins.csv main/config/kneespa.cfg`, gitignore both, commit `.example` templates, seed on first run.
- **H7 — Single source of truth for safety limits:** generate `motor_limits.h` from `constants.py` (or add a CI check asserting the paired constants are equal) so host/firmware can't drift; fix the already-drifted jerk-interval default.
- **Tests for the safety gates:** unit tests (stub-window pattern) for `_on_treatment_start`, `ensure_arduino_connection`, `start_protocol`, and `_on_setting_changed` (incl. the no-worker path); add unit-level slot tests for the `main/ui/` screens; strengthen the vacuous DS-component tests to assert style contracts, not widget counts.
- **`logging.py`:** guard on `self.logger.handlers` (not `hasHandlers()`) so a stray `basicConfig` can't disable file logs.
- **`validate_fixes.py`:** move to `scripts/`, document, wire into CI as a fast snapshot check.

---

## Phase E — On-device verification (needs the physical device; scheduled hardware session)

Do NOT flash without running the checklist. Follow `docs/plans/2026-06-11-batch1-hardware-checklist.md`.

- Run the Batch-1 hardware checkout **before** flashing FAILSAFE firmware — especially the WDT-bootloader-recovery check (old Mega bootloaders boot-loop on WDT reset; `ENABLE_WDT 0` is the fallback).
- GUI Phase-5 items: fullscreen + touch targets ≥44 px, real-encoder telemetry into the Setup Live Position card, a full supervised treatment on the device.
- Flash `motor.ino`, run `pio test -e native`, then flip `KNEESPA_PULSE_RATE_FIRMWARE=1`; enable `KNEESPA_PROTOCOL_V2=1` once its hardware checklist item (D5a) passes.
- Resolve the deferred hardware-measurement items (A-command zero-offset, AFULLINCH vs AXIAL_MAX, B-axis direction) — measure first, change second.

---

## Phase F — Hygiene (anytime, parallelizable, effort S)

Delete empty `main/controllers/` + orphaned `.pyc`; delete empty `main/ui/main.py`; fix the `self.I2CStatus` (capital S) typo → `I2Cstatus` and remove dead `exit_app()`; `.gitignore` the design refs (`_ds/`, `assets/`, `screenshots/`, `app/`, `*.html` mockups, `tweaks-panel.jsx`, `.thumbnail`) and `main/motor/.native-build/`; `git add tools/run_local.py`; pin `pyserial`/`python-dotenv` in `requirements-test.txt` and reconcile the PyQt5 apt-vs-pip note; evaluate `demo/` and `rpi/` for deletion or a move to `docs/reference/`; delete the 12 `worktree-agent-*` branches; close superseded PRs #1 and #2.

---

## Definition of done (work the checklist; report status per item)

Critical: ☐C1 ☐C2 ☐C3 ☐C4 ☐C5 ☐C6  ·  High: ☐H1 ☐H2 ☐H3 ☐H4 ☐H5 ☐H6 ☐H7 ☐H8
Medium/Low: ☐CI green+gating ☐firmware native build ☐secrets out of git ☐csv row/BOM ☐reset_worker event ☐controller timer/thread races ☐SMTP timeout/thread ☐blocking send ☐keepalive race ☐CMarks dedup ☐watchdog message ☐kiosk fullscreen ☐VLC poll ☐QSS warn ☐safety-gate tests ☐validate_fixes→CI ☐logging handlers ☐hygiene (controllers/ · ui/main.py · gitignore · run_local · reqs · demo/rpi · branches · PRs)

For each code phase: run `python -m pytest -q` and the firmware native tests; report pass/skip counts and any failures with output. Commit locally per phase with clear messages. **Do not push, open, or merge PRs without explicit approval.** End each session with a status of the checklist above and the next 🛑 checkpoint you're blocked on.
