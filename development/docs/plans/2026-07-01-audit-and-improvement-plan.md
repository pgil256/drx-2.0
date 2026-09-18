# KneeSpa DRx (drx-2.0) — Audit & Improvement Plan

**Date:** 2026-07-01
**Auditor:** multi-agent audit (10 dimensions) + direct verification of every critical/high finding against the current code on branch `feat/gui-modernization`.
**Scope:** correctness, safety, concurrency, security, UI layer, tests/CI, firmware, config, repo hygiene.

---

## 0. Executive summary

The current branch `feat/gui-modernization` (open as **PR #15 → main**) is a well-built modern touchscreen GUI. The problem is **what it is built on top of**, and a set of GUI-introduced regressions.

Three headline conclusions:

1. **The safety overhaul this device needs already exists — on a branch that was never merged.** The `improvement-plan` branch (30 commits, pushed, CI-green, **never merged to main**) contains a completed 7-phase safety/architecture program: fail-safe firmware `2026-06-11-FAILSAFE-2` (hardware watchdog + host-heartbeat + autonomous pressure release + stop-in-all-states), protocol-v2 serial framing (sequence numbers + XOR checksums), UI-thread unblocking, and the decomposition of the `KneeSpa` god-object into `SafetyMonitor / AuthController / ProtocolController / ConnectionManager`. **PR #15 branched from the old pre-FAILSAFE `main`**, so its firmware is still `2025-11-05-STOP-PIN-FIX` and its controller is still the 1600-line monolith. If PR #15 merges as-is, the device **loses** the safety work that was already written and tested.

2. **Several verified CRITICAL safety defects are live on this branch** — and most are *already fixed* on `improvement-plan`. The device can hold or keep pulling traction on a patient's knee when the host app dies, when a protocol fails mid-ramp, when the physical STOP button is pressed during the pressure/pulse phases, and for ~1 second after an emergency stop.

3. **PR #15's CI is red and non-gating.** The Python test job is SIGKILLed (exit 137, OOM/hang under headless Qt) and the firmware native build fails to compile; the firmware job is `continue-on-error: true` so it is silently ignored.

**The single highest-leverage action is not to write new safety code — it is to reconcile the two branches** so the modern GUI ships *on top of* the fail-safe backend, then fix the GUI-specific regressions on top.

---

## 1. The strategic problem: two diverged branches

| Capability | `main` / `feat/gui-modernization` (PR #15) | `improvement-plan` (unmerged) |
|---|---|---|
| Firmware version | `2025-11-05-STOP-PIN-FIX` | `2026-06-11-FAILSAFE-2` |
| Host-death watchdog (motor stops if Pi dies) | ❌ none | ✅ heartbeat 3 s → stop+release; `wdt_enable(WDTO_2S)` |
| Autonomous pressure release after fault | ❌ motor just stops, screw holds force | ✅ `emergencyStopAndRelease()` backs axial off to ~5 lb |
| Physical STOP honored in all phases | ❌ only during position moves | ✅ restructured |
| Serial framing / command correlation | ❌ bare strings, `send()` returns "bytes written" | ✅ protocol-v2 seq + XOR checksum (gated `KNEESPA_PROTOCOL_V2=1`) |
| Controller structure | ❌ 1600-line `KneeSpa` god-object | ✅ decomposed into `main/controllers/*` + `SafetyMonitor` |
| E-stop unblocks UI thread | ❌ blocking serial on GUI thread | ✅ UI-thread unblocking (Phase 3) |
| Modern touchscreen GUI | ✅ full rebuild (this branch) | ❌ still legacy `.ui` |
| Hardware safety docs/checklist | ❌ not on this branch | ✅ `docs/audits/2026-06-11-…`, `docs/plans/2026-06-11-…`, Batch-1 checklist |

**Conflict surface** — files changed by *both* branches relative to `main` (i.e. real merge conflicts):
`main/kneespa.py`, `main/motor/motor.ino` (the two hard ones), `main/helpers/protocols.py`, `main/config/config.py`, `main/config/constants.py`, `main/helpers/csv.py`, `main/motor/test/test_command_parse/test_command_parse.cpp`, `tests/unit/test_csv_helper.py`, `AGENTS.md`.

Neither branch is a superset of the other. This must be resolved deliberately, not by a blind merge.

---

## 2. Verified findings

Every finding below was confirmed by reading the cited code on `feat/gui-modernization`. The **"already on improvement-plan?"** column tells you whether reconciliation (Part 3, Phase B) fixes it for free or whether it is a net-new GUI regression that needs its own fix.

### 2.1 CRITICAL — safety (device can apply/hold traction on a patient unexpectedly)

| # | Finding | Location | Fixed on improvement-plan? |
|---|---|---|---|
| C1 | **No firmware host-death watchdog.** `loop()` never checks time-since-last-host-command for safety (`lastCommandTime` only rate-limits); `#include <avr/wdt.h>` is unused. If the Pi app crashes/hangs mid-treatment, the Arduino keeps holding traction and pulsing **forever**. | `main/motor/motor.ino` (loop ~836; no `wdt_*`) | ✅ Yes (FAILSAFE-2 heartbeat + WDT) |
| C2 | **Physical STOP button dead during pressure ramp, pulsing, and hold.** `STOP` is read every loop but the only consumer is inside `if (bRunning)`; the `measurePressure` and `jerking` blocks never check it. The button only works during brief position moves. | `main/motor/motor.ino:874-877` (vs blocks 836-860, 931-975) | ✅ Yes (STOP restructure) |
| C3 | **Protocol failure leaves traction applied while UI shows "stopped."** On any mid-run failure the worker does `finished.emit(False); return` **without** `set_to_pressure(0)`; only the success path releases. `protocol_completed` sends `X`, and firmware `emergencyStop()` only zeroes motor speed — the lead-screw holds the built-up force. Reachable in normal operation (a pressure step that doesn't stabilize in 5 s fails the protocol). | `main/helpers/protocols.py:573/578` vs `:612`; `main/motor/motor.ino:272-291` | ✅ Effectively (autonomous release on fault) |
| C4 | **E-stop re-commands the motor for ~1 s.** `emergency_stop_clicked` sends `X`, then schedules `worker.stop()` **1 second later** via `QTimer.singleShot(1000, …)`. `worker.stop()` is the only thing that clears `is_running`, so the protocol thread keeps sending `P{…}`/`K{…}` in the gap — the device visibly restarts pulling right after an e-stop. | `main/kneespa.py:620-627` | ✅ Yes (`SafetyMonitor` flips `is_running=False` immediately: `controllers/safety_monitor.py:89,134`) |
| C5 | **Software e-stop depends entirely on the serial link and can freeze the UI for tens of seconds.** `stop_actuators()`'s only kill path is `arduino.send("X")`; on a dead link `send()` runs up to 3 blocking reconnect attempts (sleeps + `verify_connection` up to ~30 s) **on the GUI thread**. Meanwhile the wired `EMERGENCYSTOP` GPIO is configured but **never asserted** on any stop path. | `main/kneespa.py:884-899, 1482/1488`; `main/helpers/arduino.py:457-464` | ✅ Yes (UI-thread unblocking) |
| C6 | **Config write is not atomic → power-loss corrupts `kneespa.cfg`.** `update_config()`/`_write_default_config()` do `open(cfg, "w")` then stream `config.write()` — no temp-file + `os.replace()`. A hard power-off (routine on this Pi) mid-write truncates the file; on next boot calibration/marks/device-id are gone and the loader silently falls back to `calibration = 1.0` — a silently-miscalibrated load cell. | `main/config/config.py:239-240, 272-273` | ❌ Net-new to fix (shared code) |

### 2.2 HIGH — incorrect behavior users/patients will hit

| # | Finding | Location | On improvement-plan? |
|---|---|---|---|
| H1 | **Lowering "Max Pressure" mid-run does nothing.** `_on_setting_changed` sets `worker.max_pressure`, but the worker reads it **once**, at ramp start (`run_pressure_sequence(initial, self.max_pressure)`); the hold/pulse phase never re-reads it. The clinician drags pressure 80→40, clicks through the safety confirmation, sees "worker max_pressure updated to 40", and the device holds 80 for the rest of the treatment. | `main/kneespa.py:522-523`; `main/helpers/protocols.py:577/638/701/768` | ❌ Net-new (GUI mid-run feature) |
| H2 | **Turning pulse off mid-treatment silently ends the protocol early and reports success.** In protocols 1-3 the final-phase loop unconditionally sets `main_phase_loop_active = False` after `apply_continuous_pulse()`. Because `apply_continuous_pulse` returns as soon as `use_pulse` flips False (which the pulse-rate slider→0 does live), the phase exits, pressure is released, and `finished.emit(True)` fires — a 12-min treatment truncated to 3 min, logged as completed. | `main/helpers/protocols.py:585-597`; `main/kneespa.py:528-530` | ✅ Restructured (no such variable there) |
| H3 | **PINs are unsalted SHA-256 over a 4-digit space = effectively plaintext.** The committed `user_pins.csv` hashes reverse instantly: admin `03ac67…` = **`1234`**, user `b3a8e0…` = **`456`** (verified). Anyone who reads the repo, git history, or the Pi filesystem recovers every PIN in milliseconds and logs in as admin. No salt, no KDF, no attempt lockout. | `main/helpers/secure_auth.py:94`; `main/data/user_pins.csv` | ⚠️ Partly (improvement-plan hardened PIN handling; keyspace problem remains) |
| H4 | **`monitor_buffer` flushes unread serial frames.** It divides the **host** OS receive-buffer byte count by the **64-byte Arduino** constant and calls `reset_input_buffer()` whenever >57 bytes are pending — destroying complete unread STATUS/DONE frames during any HF1 or reset burst, causing reset timeouts and spurious reconnects. | `main/helpers/arduino.py:270-271, 284-285` | ✅ Likely (protocol-v2 rework) |
| H5 | **Reconnect can leave two reader threads on one serial port.** After a reconnect triggered from inside the reader thread, `connect_to_arduino` spawns a *new* reader (guard passes because `disconnect()` set `_running=False`), then sets `_running=True`; the old reader's loop condition is true again and it keeps running. Two threads then `readline()` the same handle — frames split, DONEs missed. Each further reconnect adds another. | `main/helpers/arduino.py:214-218, 298, 329` | ✅ Likely (ConnectionManager rework) |
| H6 | **No schema/range validation on `kneespa.cfg`.** Every loader catches parse errors and silently substitutes a hard-coded default with only a `print()`. A one-character typo in the calibration factor (`-28369.O`) → silent `calibration = 1.0`; an insane-but-parseable `max_pressure = 500` is accepted verbatim. | `main/config/config.py:82-106, 133-142, 157-162` | ❌ Net-new to fix |
| H7 | **Safety-limit constants duplicated between `constants.py` and `motor.ino`, already drifting.** Two sources of truth for `PRESSURE_MAX`/`AXIAL_MAX`/lateral/horizontal limits and jerk interval; the jerk-interval *default* already differs (host vs `motor.ino:111 jerkInterval=200`). Raise a limit in one place, forget the other → UI and firmware disagree on the safety envelope. | `main/config/constants.py` vs `main/motor/motor.ino` | ➖ Independent |
| H8 | **`emergencyStop()` doesn't clear `noStatus`, and the pressure limit is blind during pulsing.** `J` sets `noStatus=true` (no STATUS frames the whole pulse phase → Pi-side watchdog blind), the firmware's own `pressure>MAX` check lives only inside `measurePressure` (inactive while jerking), and `emergencyStop()` never resets `noStatus`, so an `X` during pulsing latches status off for the rest of the session. | `main/motor/motor.ino:687, 272-291, 931-940` | ✅ Yes (FAILSAFE-2) |

### 2.3 MEDIUM — latent bugs, maintainability traps, real UX/perf cost

- **CI red & non-gating (blocks the PR).** Python job SIGKILLed (exit 137); firmware native build fails `HX711.h: No such file or directory`; firmware job is `continue-on-error: true`. See §3 Phase A. — `.github/workflows/ci.yml:44`
- **Firmware native tests can't compile.** `motor.ino:17-20` includes `HX711.h`/`elapsedMillis.h`/`Wire.h`/`avr/wdt.h` unconditionally; the tests `#include "../../motor.ino"`. A `mock_hx711.h` exists but `motor.ino` never includes that *name*, and `elapsedMillis`/`wdt`/`Wire` have no mocks. — `main/motor/motor.ino:17-20`, `main/motor/test/*`
- **Exit-137 root cause (leading hypothesis):** the FakeArduino **pty integration tests skip on the Windows dev machine but RUN on Ubuntu CI**, where they spawn real threads + 30–60 s `waitSignal` waits with no guaranteed fixture teardown; module-scoped `QApplication` fixtures never delete widgets. Under the runner's memory cap this compounds to OOM/SIGKILL. Fix = per-function `QApplication` with teardown, guaranteed thread/serial cleanup in `conftest.py`, and per-test timeouts. *(Needs a CI repro to confirm; the fixes are safe regardless.)* — `tests/conftest.py`, `tests/integration/*`, `pytest.ini:7`
- **Secrets & runtime state tracked in git.** `user_pins.csv` (real admin email + reversible PINs) and `kneespa.cfg` (`unlock=123`, per-site calibration, device id) are committed and show Modified on every run. No `.example` templates. — `main/data/user_pins.csv`, `main/config/kneespa.cfg`
- **csv.py: one bad row silently locks out every later user.** An empty `pin_hash` mid-file raises inside the row loop, aborting iteration; the handler reports the misleading "Missing 'pin_hash' column" and returns a partial dict. — `main/helpers/csv.py:83`
- **csv.py: BOM/encoding lockout.** Opened `encoding="utf-8"` (not `utf-8-sig`); Excel's "CSV UTF-8" BOM hides the `pin_hash` header → zero users load → total login lockout with a misleading error. `UnicodeDecodeError`/`PermissionError` are uncaught. — `main/helpers/csv.py:74`
- **reset_worker retry doesn't clear the DONE event** → a late DONE from the timed-out attempt instantly satisfies the retry, advancing the reset while an actuator is still moving. — `main/helpers/reset_worker.py:117`
- **Stale QTimer/thread races in the controller:** `enable_actuator_controls` schedules 200 ms `singleShot`s never cancelled by `disable_actuator_controls` (re-enable controls mid-command); `enable_actuator_controls` ignores `reset_in_progress` (re-enables jog/Go during the 6-step reset); the Arduino `QThread` is never `quit()/wait()`ed and `finished` is never emitted (leaks a thread + stale signal wiring per reconnect). — `main/kneespa.py:347-351, 1317`
- **SMTP runs on the GUI thread with no timeout** (assistance + ticket) → touchscreen freezes 60–120 s on a dead network, including the e-stop button. — `main/kneespa.py:663, 703`
- **Blocking `Arduino.send` holds the lock 0.3 s per command** → visible touchscreen stutter/missed taps; contends with the reader thread's Q-ack. — `main/helpers/arduino.py:478`
- **Post-stop keepalive thread flushes the input buffer & can reconnect for 60 s**, racing any newly-started protocol (eats its STATUS/DONE frames). — `main/helpers/protocols.py:1003`
- **CMarks degree→position interpolation duplicated 3×** (controller, worker, `move_actuator`) → calibration changes fixed in one copy only diverge silently. — `main/kneespa.py:124`, `main/helpers/protocols.py:424`
- **Watchdog status message misattributes pressure trips as "Axial limit exceeded."** — `main/kneespa.py:1234`
- **Kiosk fullscreen fragile:** `setWindowFlags(FramelessWindowHint)` called *after* `showFullScreen()` (hides the window; relies on a later `show()`), and drops the `Qt.Window` type bit → device may come up windowed, exposing the desktop. — `main/kneespa.py:247`
- **VLC poll timer keeps firing after a playback crash** (`position()` returns `None`, handler returns early, black surface stays, no failure surfaced). — `main/ui/modals/video_modal.py` `_on_poll`
- **QSS `var(--token)` resolver silently unstyles on a typo** — unknown token returns the literal `var(...)` text into the stylesheet; Qt drops the property with no warning, so a misspelled token renders an unstyled control. — `main/ui/theme/qss.py:43-46`
- **Empty `main/controllers/` package with orphaned `.pyc`** (sources live only on `improvement-plan`) can be imported and mask real modules; `main/ui/main.py` is an empty stale file. — `main/controllers/`, `main/ui/main.py`

### 2.4 LOW — cleanup

- Zero unit tests for controller safety gates (`_on_treatment_start`, `ensure_arduino_connection`, `start_protocol`) and the whole `main/ui/` slot layer (integration-only).
- `validate_fixes.py` is a stray audit-snapshot script at repo root → move to `scripts/`, wire into CI.
- Vacuous DS-component tests assert widget *counts*, not styling contracts.
- `requirements.txt` vs `requirements-test.txt` drift (`pyserial`/`python-dotenv` pinned vs floating; PyQt5 apt-vs-pip disagreement).
- `.gitignore` gaps: design refs (`_ds/`, `assets/`, `screenshots/`, `app/`, `*.html` mockups, `tweaks-panel.jsx`, `.thumbnail`) and `main/motor/.native-build/` show as untracked clutter; `tools/run_local.py` should be **committed**.
- Stale `demo/` and `rpi/` reference dirs; 12 local `worktree-agent-*` branches; 2 ancient open PRs (#1, #2) superseded by #15.
- `logging.py` uses `hasHandlers()` (walks to root) → a stray `basicConfig()` disables all file logs.
- Duplicate/typo'd `self.I2CStatus` (capital S) never resets the real `I2Cstatus` flag; `exit_app()` dead code double-cleans GPIO and `os._exit(1)`.

---

## 3. Phased implementation plan

Sequenced so that **safety lands first**, the PR becomes mergeable, and risk is retired before polish.

### Phase A — Unblock the PR (get CI green & gating) · ~1 day · effort S–M
The PR can't be trusted or merged while CI is red and non-gating.
1. **Fix firmware native build.** Guard the hardware includes in `motor.ino` behind `#ifdef UNIT_TEST` (real libs in the `#else`), and add the missing mocks (`elapsedMillis`, `avr/wdt` no-op macros, `Wire`) so `#include "../../motor.ino"` compiles on `env:native`. *(Cross-check against `improvement-plan`'s test harness, whose firmware CI was green — reuse its approach.)*
2. **Fix the exit-137 Python hang.** Convert module-scoped `QApplication` fixtures to per-function with a teardown that `deleteLater()`s top-level widgets and drains events; make `conftest.py`'s FakeArduino/protocol fixtures guarantee thread `join()` + serial `close()`; set sane per-test timeouts (raise global to ~120 s, mark the long pty tests). Reproduce on an Ubuntu runner to confirm the culprit is the pty integration tests that never run on Windows dev.
3. **Make firmware CI gate.** Remove `continue-on-error: true` once (1) passes; split the always-buildable `pio run -e mega` (blocking) from native tests if needed.
4. **De-dupe CI triggers** (currently runs on both `push` and `pull_request` for every commit).

### Phase B — Reconcile the two branches (THE core work) · ~1–2 weeks · effort L
Goal: the modern GUI running on the fail-safe backend. Do **not** blind-merge; go file-by-file over the 9-file conflict surface.
1. **Decide the base.** Recommended: rebase/replay the GUI rebuild *onto* `improvement-plan` (or cherry-pick the FAILSAFE-2 firmware + `SafetyMonitor`/controllers + protocol-v2 + UI-thread-unblocking onto `feat/gui-modernization`). Capture the decision in a short ADR.
2. **Firmware:** take `motor.ino` `2026-06-11-FAILSAFE-2` wholesale (resolves C1, C2, C3, C5, H8). Preserve the GUI branch's `J<ms>` pulse-rate parse addition on top; keep it behind the existing `PULSE_RATE_FIRMWARE_SUPPORT` flag.
3. **Controller:** rebuild the GUI's `AppShell` wiring against the **decomposed** controllers (`SafetyMonitor`/`AuthController`/`ProtocolController`/`ConnectionManager`) instead of the monolith — this resolves C4 (immediate `is_running=False`), the blocking-e-stop, and the god-object debt in one move. The Phase-3 screen-signal seam is a clean interface to graft onto.
4. **`protocols.py`, `config.py`, `constants.py`, `csv.py`:** merge the GUI additions (duration control, `[ProtocolDefaults]`, `pos_c_to_angle`) into the `improvement-plan` versions; H2 (pulse truncation) disappears because that branch restructured the loop.
5. **Bring the safety docs across:** `docs/audits/2026-06-11-full-application-audit.md`, the improvement plan, and the **Batch-1 hardware checklist** (needed for the eventual reflash).
6. **Re-run the full suite + firmware native tests; expect the union of both branches' tests to pass.**

### Phase C — Net-new fixes not covered by reconciliation · ~2–3 days · effort S–M
These are GUI-branch regressions or shared bugs that survive the merge:
- **C6** atomic config write (temp-file + `fsync` + `os.replace`) — apply to `update_config` and `_write_default_config`.
- **H1** lock `max_pressure`/`max_left`/`max_right` sliders during a run (mirror the duration lock) *or* make the worker re-read them — the lock is the safe quick fix.
- **H6** post-load schema/range validation on `kneespa.cfg` (validate against `PRESSURE_MAX`, lateral/axial ranges, non-zero calibration; surface a blocking error, route prints through the logger).
- **csv.py:** open `utf-8-sig`, skip-and-log malformed rows instead of aborting, catch `OSError`/`UnicodeDecodeError`.
- **VLC poll-on-crash**, **QSS unknown-token warning**, **SMTP `timeout=10` + move off GUI thread**, **kiosk `setWindowFlags` ordering**, **stale-timer/thread-leak cleanup** in the controller.

### Phase D — Security & robustness hardening · ~3–4 days · effort M
- **H3 PIN security (do all three):** (1) migrate to a salted slow KDF (argon2id/bcrypt) with per-user salt; (2) add persistent attempt lockout + exponential backoff + failed-attempt logging (no PIN in logs); (3) **rotate all PINs** (1234/456/123 are burned), ship an empty `user_pins.csv.example`, load real users from an out-of-repo/env path, and **purge the plaintext history** (git-filter-repo/BFG). Remove `unlock=123` if unused.
- **Secrets out of git:** `git rm --cached user_pins.csv kneespa.cfg`, gitignore them, add `.example` templates, seed on first run.
- **H7 single source of truth for safety limits:** generate `motor_limits.h` from `constants.py` (or a CI equality check) so host and firmware can't drift.
- **Tests for the safety gates:** unit tests for `_on_treatment_start` / `ensure_arduino_connection` / `start_protocol` / `_on_setting_changed` (stub-window pattern); add the `validate_fixes.py`-style snapshot check to CI.

### Phase E — On-device verification (needs the physical device) · scheduled hardware session
- Run the **Batch-1 hardware checklist** from `improvement-plan` before flashing FAILSAFE firmware (esp. the WDT-bootloader-recovery check — old Mega bootloaders boot-loop on WDT reset; `ENABLE_WDT 0` fallback).
- GUI Phase 5 items: fullscreen/touch ≥44 px, real-encoder telemetry into the Setup Live Position card, full treatment on device.
- Flash firmware, run `pio test -e native`, then flip `KNEESPA_PULSE_RATE_FIRMWARE=1` and (once D5a passes) `KNEESPA_PROTOCOL_V2=1`.
- Resolve the deferred hardware-measurement items (A-command zero-offset, AFULLINCH vs AXIAL_MAX, B-axis direction).

### Phase F — Hygiene (anytime, parallelizable) · effort S
Delete empty `main/controllers/` + orphaned `.pyc`; delete empty `main/ui/main.py`; `.gitignore` the design refs + `.native-build/`; commit `tools/run_local.py`; move `validate_fixes.py` → `scripts/`; pin test deps; delete 12 `worktree-agent-*` branches; close PRs #1/#2; evaluate `demo/` + `rpi/`.

---

## 4. Quick-win punch list (high value / low effort — can start today, independent of Phase B)

| Item | File | Effort |
|---|---|---|
| Atomic config write (temp + `os.replace`) | `config.py:239/272` | S |
| Lock pressure/lateral sliders during a run (H1) | `kneespa.py:522`, `treatment.py` | S |
| `utf-8-sig` + skip-malformed-row in PIN loader | `csv.py:74/83` | S |
| SMTP `timeout=10` + move off GUI thread | `kneespa.py:663/703` | S |
| Firmware native build guard + mocks (unblocks CI) | `motor.ino:17-20`, `test/*` | M |
| Per-function QApplication fixture + teardown (unblocks CI) | `tests/conftest.py`, `tests/integration/*` | S |
| Remove firmware `continue-on-error` after build fix | `ci.yml:44` | S |
| `git rm --cached` secrets + `.example` templates | `user_pins.csv`, `kneespa.cfg` | M |
| Delete empty `controllers/` + orphaned `.pyc`, empty `ui/main.py` | — | S |

---

## 5. Notes & caveats

- Findings were verified against code; **the exact exit-137 cause needs a CI repro** to confirm (the teardown/timeout fixes are safe and correct regardless).
- The **"already on improvement-plan?"** column is based on reading that branch's `motor.ino`, `controllers/safety_monitor.py`, `protocols.py`, and `arduino.py`; confirm each during the Phase-B file-by-file reconciliation rather than assuming.
- Owner constraints (from prior effort): **software/firmware only, no new hardware**; real patients → maximum safety rigor; hardware access is scheduled → firmware ships in batches behind flash-gating flags with a hardware checkout checklist. Phase B/E respect this.
- The one **residual hardware risk** the software cannot fix (documented on `improvement-plan` §8): there is no independent hardware E-stop power interlock — every software/firmware protection still assumes the SMC drivers obey a stop command.
