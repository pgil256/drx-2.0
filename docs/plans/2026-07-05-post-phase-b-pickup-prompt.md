# Post–Phase B — Pickup Prompt (Checkpoint B cleared)

> **STATUS (2026-07-05): fork resolved — owner chose (B) Phase D before any push. PHASE D CODE ITEMS COMPLETE** on `feat/gui-on-failsafe` (8 new commits, `4461b23..19bd8b7`):
> secrets untracked + gitignored + `.example` templates + first-run seeding + `KNEESPA_USER_PINS_PATH`/`KNEESPA_AUTH_STATE_PATH` overrides · unused `unlock=123` retired from config.py + 7 presets · H3: PINs rotated to salted PBKDF2 (runtime file only; new PINs delivered to owner in-session), persistent lockout w/ exponential backoff + audit logging · H7: `scripts/check_limits_sync.py` (CI + pytest) + firmware `jerkInterval` boot default 200→500 ms to match the host's 2/sec · logging `.handlers` guard · `validate_fixes.py` → `scripts/` (patterns refreshed, 12/12, in CI) · safety-gate tests (protocol controller 28, ensure-connection 5, no-worker settings, DS style contracts).
> Verified 2026-07-05: WSL **565/0**, Windows **526 pass/39 pty-skip**, firmware natives green, AVR `pio run -e mega` SUCCESS.
> **Still pending (owner):** 🛑 history purge of `main/data/user_pins.csv` (plaintext `123`/`456` at `3a982b6`/`ad4d725`; reversible hashes at `1293dc3+`) + `kneespa.cfg` (`unlock=123`) — present on ALL branches incl. origin/main; needs git-filter-repo + force-push everywhere. Rotation makes the leaked values dead credentials, so urgency is reduced but purge is still recommended before the repo is shared. Push/PR approval still outstanding. Phase C/E/F untouched.
> The body below is retained as written on 2026-07-05 before Phase D ran.

*Hand this to a fresh Claude Code session in `C:\Users\patri\Documents\Projects\drx-2.0`. Phase B (branch reconciliation) is **complete and verified**; this session is the post-checkpoint fork. Read these first, in order:*

1. `docs/plans/2026-07-01-implementation-prompt.md` — ground rules (all still in force) + Phase C/D/E/F definitions.
2. `docs/plans/2026-07-02-phase-b-session2-prompt.md` — the STATUS header at the top is the Phase B completion record; the body below it is retained history.
3. `docs/adr/2026-07-02-branch-reconciliation.md` — the replay strategy that produced this branch.
4. This file — exact state and the decision fork.

## Where things stand (end of Phase B, 2026-07-02; prompt written 2026-07-05)

**Branch `feat/gui-on-failsafe`** — 8 commits on `improvement-plan` tip (`ec0e18a`), **LOCAL ONLY, nothing pushed, no PR opened**:

| Commit | Content |
|---|---|
| `75a0d6d` | replay(1): GUI view layer (`main/ui/**`), DS library, docs, angles.py, `.gitattributes`, constants union |
| `39642fc` | replay(2): B1 firmware `J<ms>` union (FAILSAFE-2 kept) + config.py/csv.py helper unions |
| `63a8654` | replay(3): protocols.py pause/pulse-rate union + pause/pressure tests + AGENTS.md union |
| `fb83316` | replay(4): ci.yml union (Phase A gating workflow + base pip-cache/triggers) |
| `c1d4d68` | replay(5): **B2** AppShell view swap on the controller base + **B3** e-stop GPIO assert |
| `06fb641` | replay(6): retire the 12 legacy Qt-Designer view files + legacy constants |
| `75825ae` | replay(7): re-enable the deferred GUI-line tests, adapted to FAILSAFE contracts |
| `7e8bf21` | Plan status header: Phase B complete |

**Verified green at the tip (2026-07-02):**
- WSL full suite: **513 passed / 0 failed** (`QT_QPA_PLATFORM=offscreen ~/.venvs/drx312/bin/python -m pytest -q -p no:cacheprovider`, ~74 s)
- Windows pytest: **474 passed / 39 skipped** (the 39 are pty-gated integration tests, skip on Windows by design)
- Firmware natives: all suites pass (`bash main/motor/run_native_tests.sh`)
- **AVR build: `pio run -e mega` SUCCESS** (registry.platformio.org reachable again; RAM 25.9%, Flash 10.6%) — the multi-session blocker is cleared.

**Uncommitted, intentionally (do NOT commit):** `main/config/kneespa.cfg`, `main/data/user_pins.csv` — runtime state with burned secrets, Phase D moves them out of git. Backups in scratchpad `runtime-backup/`. Also untracked and NOT part of this work: `.thumbnail`, the two `KneeSpa DRx - Modern GUI*.html` mockups, `_ds/`, `app/`, `assets/`, `screenshots/`, `tools/run_local.py`, `tweaks-panel.jsx` — design-source scratch, leave alone unless the owner asks.

## 🔱 The decision fork — this needs the owner FIRST

**Do not push or open a PR without explicit owner approval.** Before doing anything else this session, confirm which path the owner wants. The likely options:

- **(A) Push `feat/gui-on-failsafe` + open a PR** into `improvement-plan` (or `main` — ask which). If approved: push, open the PR with a body that summarizes the 8 replay commits and the resolved-vs-open findings ledger (below), and let real CI run the AVR + gating jobs. Then watch CI to green.
- **(B) Proceed to Phase D (secret hygiene)** before any push, so the burned PIN/config secrets never enter a shared branch's history. This is the safer ordering and probably what the owner wants — **flag it.**
- **(C) Phase C** (whatever the implementation-prompt scopes it as — re-read §Phase C; it was not touched this run).

If the owner is not available, **stop and report** — this is a genuine fork, not a reversible default.

## Owner decisions still outstanding (blocking, from Phase A/B)

1. **Push/PR approval** + target branch (see fork above).
2. **Phase D — PIN re-provision + secret purge.** `kneespa.cfg` + `user_pins.csv` hold burned secrets; move them out of git (gitignore + `.example` templates + env/`.env` provisioning), rotate the PINs, and scrub history if they were ever committed on any branch. H3 is only *part*-resolved: salted `hash_pin_secure` + 5-try/60 s lockout are live in code, but the credentials themselves are still exposed.
3. **Phase E — hardware measurements.** Frozen conventions (command math, A-zero-offset, AFULLINCH vs AXIAL_MAX, B-axis direction) await physical measurement before any change. **NEW this run:** the **e-stop EMERGENCYSTOP GPIO polarity** is inferred from the boot default (HIGH = run-permitted, so LOW = asserted/stop) — this MUST be confirmed on real hardware before the device ships. See `main/controllers/protocol_controller.py::emergency_stop_clicked` / `_emergency_stop_phase3` and the comment there.

## Findings ledger (report this state; re-verify before claiming to the owner)

- **Resolved on `feat/gui-on-failsafe`:** C1–C5, H2, H4 (single I/O thread owns the port), H5 (flush-per-write + RX-silence watchdog that actually fires), H8, H1 (nav-lock via `AppShell.set_nav_guard` + Treatment `set_busy` states), plus C6 + H6 found already-fixed on the base.
- **Part-resolved:** H3 (hash+lockout live; PIN purge/re-provision = Phase D).
- **Open → later phases:** H3-rest + H7 → Phase D; frozen-convention + e-stop-polarity confirmation → Phase E.
- **B6 confirmed:** `KNEESPA_PROTOCOL_V2` and `KNEESPA_PULSE_RATE_FIRMWARE` both default OFF; the flag-gated `J<ms>` / v2-framing paths are dormant until a flashed device sets them.

## What B2/B3 actually did (so you can answer questions without re-deriving)

- `main/kneespa.py` is now the improvement-plan `KneeSpa` (controllers + frozen math + GPIO/reset paths preserved) with the view swapped to `ui.app_shell.AppShell`. The controllers were **not** rewritten — they still address the window through the legacy contract (`window.ui.start_button`, `window.time_edit`, `window.timer_dialog`, …), which is satisfied by explicit adapters at the top of `kneespa.py`:
  - `_StartButtonAdapter` (setText "Stop"/"Start" → `treatment.set_run_state`; setEnabled → `set_busy`),
  - `_PhaseLabelAdapter` (status text → phase stepper),
  - `_ValueProxy` (protocol/settings/duration live reads off the modern sliders),
  - `_NullWidget` (documented no-ops for the dropped floating dialogs, protocol-image pager, show-timer/pressure checkboxes, legacy login field).
- `TreatmentStatusPanel` is deliberately still mounted over the shell — the SafetyMonitor fault/pressure banner must be visible on every screen (not just Treatment). Decision made with eyes open.
- Auth seam: modern `LoginModal` emits the whole PIN → `window.login_pin = pin` → `AuthController.handle_login()` (salted verify + lockout intact). Success → `shell.login_succeeded(...)`.
- One **deliberate** controller delta: `ProtocolController.start_protocol` now reads `window.current_pulse_rate` and passes `pulse_rate=` into `Protocols(...)` (flag-gated `J<ms>`, bare-`J` fallback otherwise). Documented in the replay(5) commit body.
- B3 e-stop chain (in `ProtocolController`): assert `EMERGENCYSTOP` LOW → `stop_actuators()` (queued `X`, jumps the tx queue, alarms if link down) → phase2 `worker.stop()` → phase3 release `EMERGENCYSTOP` HIGH → `reset_arduino()`. Release happens before reset because homing needs a powered machine. Pinned by `tests/unit/test_estop_gpio.py` (5 tests).

## Verification recipes (unchanged)

- WSL: `wsl.exe bash <script>` via the PowerShell tool; put scripts in scratchpad (Git-Bash↔wsl pipes stall; PowerShell mangles quotes). venv `~/.venvs/drx312` (CPython 3.12.13). Reusable scripts already in the current scratchpad: `run_full_suite.sh`, `run_pause_pressure.sh`.
- Natives: `bash main/motor/run_native_tests.sh`. AVR: `cd main/motor && ~/.venvs/drx312/bin/pio run -e mega`.
- Windows pytest is fine for unit tests (pty integration tests skip).
- Baseline flake to watch: `test_fake_arduino.py::…::test_corrupt_frame_rejected_not_executed` under full-suite load — did NOT recur across 4 full runs this session, but de-flake if it comes back (tip `ec0e18a` was itself a de-flake of this theme).

## Standing constraints (from the implementation prompt — unchanged)

Safety first (hazard/acceptance/verification for any stop-path/clamp/protocol change; fail safe = stop + release). Software only. Frozen conventions stay frozen (Phase E measures first). No blind merges; verify "already fixed" claims. Flag-gate firmware-dependent behavior. **No push / no PRs without explicit owner approval; no history rewrites without 🛑 approval. Never commit `main/config/kneespa.cfg` or `main/data/user_pins.csv`.** Report honestly.
