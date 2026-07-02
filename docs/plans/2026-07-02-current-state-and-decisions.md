# drx-2.0 — Current State & Decisions Ahead (2026-07-02)

*Companion to the audit (`2026-07-01-audit-and-improvement-plan.md`), the execution prompt (`2026-07-01-implementation-prompt.md`), and the reconciliation ADR (`../adr/2026-07-02-branch-reconciliation.md`). This doc is the "where are we, what's decided, what still needs a human" layer.*

---

## 1. Where things stand

### Branches & PRs

| Ref | State |
|---|---|
| `main` | Tip `d33f100` = June-17 test batch (PRs #3–#14). Pre-failsafe firmware, monolith controller, legacy `.ui` GUI. |
| `feat/gui-modernization` (**PR #15**, open) | Modern GUI (Phases 0–4 + duration control) + **Phase A CI remediation (`7142cae`)**. **CI green & gating as of 2026-07-02**: Python tests ✅ 2m21s · firmware native (g++ + Unity) ✅ 27s · AVR build ✅ 38s · GitGuardian ✅. Firmware still `2025-11-05-STOP-PIN-FIX` (pre-failsafe). |
| `improvement-plan` (never merged) | The completed safety overhaul: firmware `2026-06-11-FAILSAFE-2`, decomposed controllers (`SafetyMonitor` / `AuthController` / `ProtocolController` / `ConnectionManager`), protocol-v2 framing (gated), UI-thread unblocking, safety docs + Batch-1 hardware checklist. Branched *before* the test batch — contains neither PRs #3–#14 nor any GUI work. |
| PRs #1, #2 | Ancient (Nov 2025), superseded; still open. |
| `worktree-agent-*` ×12 | Stale local agent branches. |

### Phase A outcomes (done, verified on real CI)

- **Firmware native tests exist *and run* for the first time on this line: 42/42** via both the hermetic runner (`main/motor/run_native_tests.sh`, vendored Unity, no registry) and `pio test -e native`. `motor.ino`'s hardware includes are guarded behind `UNIT_TEST` (build-only change — firmware behavior and VERSION untouched).
- **Exit-137 root cause found, reproduced, neutralized.** Not OOM: `Arduino.release_busy_port()` runs `fuser -k <port>`; in tests the port is a pty held by the pytest process itself, so any stray reconnect SIGKILLed the whole run (repro exits 137 exactly). Patched in `tests/conftest.py` only — production code untouched; `improvement-plan`'s `arduino.py` removes the fuser path entirely, so Phase B supersedes the patch.
- **Qt test hygiene:** the QApplication is now pinned for the session (PyQt5 was GC-ing it between tests, silently dropping registered fonts — the stylesheet survives in a Qt static, which masked the loss) and an autouse janitor deletes all top-level widgets after every integration test.
- **CI workflow:** firmware jobs gate (no `continue-on-error`), triggers de-duped, jobs mirror `improvement-plan`'s proven structure.
- Suite counts: Ubuntu 411 passed / 0 skipped (~100 s); Windows dev 387 passed / 24 skipped (the pty tests — they run on Linux only).

### Finding status after Phase A

| Finding | Status |
|---|---|
| CI red / non-gating; firmware build broken | ✅ **Resolved** (Phase A) |
| C1 host-death watchdog · C2 STOP in all phases · C3 release-on-fault · C4 e-stop 1 s re-command · C5 e-stop serial-only/GUI-blocking · H2 pulse truncation · H4 buffer flush · H5 double reader · H8 `noStatus` latch | ⏳ **Open here; already fixed on `improvement-plan`** → land via Phase B reconciliation |
| C6 atomic config write · H1 mid-run pressure no-op · H6 config validation · csv/BOM row handling · reset_worker event · timer/thread races · SMTP · keepalive · CMarks dedup · watchdog message · kiosk flags · VLC poll · QSS warn | ⏳ Open → Phase C (net-new fixes) |
| H3 PIN security · secrets in git · H7 limits drift · safety-gate tests | ⏳ Open → Phase D (needs owner input, see §3) |
| Hardware verification, flag flips, deferred measurements | ⏳ Open → Phase E (needs device session) |
| Hygiene (clutter, stale branches/PRs, `demo/`/`rpi/`) | ⏳ Open → Phase F (anytime) |

---

## 2. Decided (2026-07-02)

**Reconciliation base — ADR `docs/adr/2026-07-02-branch-reconciliation.md`:** build a new integration branch **`feat/gui-on-failsafe` from `improvement-plan`**, replay the `9b23e11..feat/gui-modernization` work onto it (test batch → GUI phases → Phase A), file-by-file over the 9-file conflict surface, no history rewrites anywhere. When it reaches parity with PR #15 and the **union** of both test suites is green, a new PR supersedes #15. Rationale in the ADR (short form: the safety backend must stay byte-identical to its tested state; the GUI must be rewired onto the decomposed controllers anyway; a new branch avoids force-pushing an open PR).

Owner delegations recorded: Phase A pushed to PR #15 (approved 2026-07-02); base-branch choice delegated ("do whichever makes sense") and resolved per the ADR.

---

## 3. Decisions / inputs still needed from the owner

Ordered roughly by when they block work.

1. **(Blocks nothing yet, decide by end of Phase B) PR #15 disposition.** When the `feat/gui-on-failsafe` PR opens with parity + green union CI: close #15 unmerged (recommended; its branch stays for reference), or keep it open longer for side-by-side review.
2. **(Phase D, H3 — needs real-world input) PIN security package:**
   - **New PINs for every user** — `1234` / `456` / `123` are burned (reversible from committed hashes and from git history). Someone with authority over the clinic users must choose/distribute them; I can generate and install, but not invent, real credentials.
   - **Where the real user store lives out-of-repo** (e.g. `/home/pi/kneespa/user_pins.csv` + env var path). Repo ships only an empty `.example`.
   - **🛑 History purge approval** (`git-filter-repo`/BFG on `user_pins.csv` + `kneespa.cfg`): rewrites all shared history and requires every clone to re-clone; also invalidates open PR diffs — best sequenced *after* the reconciliation PR lands. Needs your explicit go, and a moment when no one else has work in flight.
3. **(Phase E — needs scheduling) Hardware session** on the physical device: Batch-1 checklist first (especially WDT-bootloader-recovery — old Mega bootloaders boot-loop on WDT reset; `ENABLE_WDT 0` is the fallback), then flash FAILSAFE, run natives, flip `KNEESPA_PULSE_RATE_FIRMWARE=1`, and `KNEESPA_PROTOCOL_V2=1` only after its checklist item (D5a). Also the deferred measurements that unfreeze the frozen conventions: A-command zero-offset, `AFULLINCH` vs `AXIAL_MAX`, B-axis direction — measure first, change second.
4. **(Phase F, cheap but outward-facing) Repo housekeeping approvals:** close superseded PRs #1/#2; delete the 12 local `worktree-agent-*` branches; keep-or-move `demo/` and `rpi/` (recommendation: `docs/reference/` if anything in them is still load-bearing, else delete — they're inert on both branches).
5. **(Anytime) Design-reference clutter** (`_ds/`, `app/`, `assets/`, `screenshots/`, two `*.html` mockups, `tweaks-panel.jsx`, `.thumbnail`): default per plan is `.gitignore` them (they stay on disk, out of git). Say if you'd rather relocate them out of the repo entirely.

**Standing constraint (not a decision):** the missing independent hardware E-stop power interlock remains a documented residual risk that software cannot close — every protection still assumes the SMC drivers obey a stop command.

---

## 4. Execution roadmap from here

1. **Phase B (next, ~1–2 weeks):** create `feat/gui-on-failsafe` from `improvement-plan`; replay per ADR; reconcile the 9 files per B1–B6 (FAILSAFE `motor.ino` wholesale + `J<ms>` re-applied behind `PULSE_RATE_FIRMWARE_SUPPORT`; AppShell onto decomposed controllers — resolves C4; assert `EMERGENCYSTOP` GPIO on the e-stop path — C5 completion; merge GUI additions into `protocols.py`/`config.py`/`constants.py`/`csv.py`; bring safety docs across; verify protocol-v2 closes H4/H5). 🛑 Checkpoint B: union suite green; report resolved-vs-open findings.
2. **Phase C (~2–3 days):** net-new fixes (C6 atomic write, H1 slider lock, H6 validation, csv robustness, the timer/thread/SMTP/keepalive/VLC/QSS/kiosk items).
3. **Phase D (~3–4 days):** PIN KDF + lockout + rotation + secrets-out-of-git (needs §3.2), H7 limits single-source, safety-gate unit tests, `validate_fixes.py` → CI.
4. **Phase E:** the scheduled hardware session (§3.3).
5. **Phase F:** hygiene, parallel anytime.

## 5. Local verification recipe (working today)

- WSL Ubuntu; uv-managed venv `~/.venvs/drx312` (CPython 3.12.13 + `requirements-test.txt` + `platformio`).
- Full suite: `QT_QPA_PLATFORM=offscreen ~/.venvs/drx312/bin/python -m pytest -q` from the repo (pty tests active on Linux).
- Firmware: `bash main/motor/run_native_tests.sh` (hermetic) or `~/.venvs/drx312/bin/pio test -e native`; AVR: `pio run -e mega`.
- Windows dev box runs the same pytest minus the 24 pty tests (auto-skip).
- Gotchas: drive `wsl.exe` via PowerShell or a script file (Git-Bash pipes stall on long runs; PowerShell mangles nested quotes); teardown prints benign "Errno 5" / "wrapped C/C++ object deleted" noise from the legacy `arduino.py` reader — disappears with Phase B.
