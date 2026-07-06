# ADR: Branch reconciliation — GUI rebuild replays onto `improvement-plan`

- **Status:** Accepted (decision delegated by owner 2026-07-02: "do whichever makes sense"; recorded here per the 🛑 Phase-B checkpoint in `docs/plans/2026-07-01-implementation-prompt.md`)
- **Date:** 2026-07-02
- **Context docs:** `docs/plans/2026-07-01-audit-and-improvement-plan.md` (the audit), `docs/plans/2026-07-02-current-state-and-decisions.md` (state of affairs)

## Context

Two long-lived branches contain disjoint, both-essential work:

| | `improvement-plan` (30 commits over `9b23e11`, never merged) | `feat/gui-modernization` (PR #15; 21 commits over `9b23e11`, includes current `main`) |
|---|---|---|
| Firmware | `2026-06-11-FAILSAFE-2`: host-death heartbeat watchdog + `wdt_enable`, STOP honored in all phases, autonomous pressure release on fault | `2025-11-05-STOP-PIN-FIX` (pre-failsafe) + `J<ms>` pulse-rate parse |
| Controller | `KneeSpa` decomposed into `main/controllers/{safety_monitor,auth_controller,protocol_controller,connection_manager}.py`; UI-thread unblocking; protocol-v2 framing (gated `KNEESPA_PROTOCOL_V2`) | 1600-line monolith, rewired onto the new `AppShell` |
| UI | legacy `.ui` files | full modern touchscreen GUI (`main/ui/**`: DS widgets, 5 screens, modals, theme) |
| Tests | its own suite incl. controller unit tests; green CI (its own workflow) | main's June-17 test batch (PRs #3–#14) + GUI/DS/screen tests + Phase A fixes (CI green as of `7142cae`) |

Git topology (verified 2026-07-02): merge-base of the two branches is `9b23e11`, which **predates current `main`** — `improvement-plan` does *not* contain the June-17 test batch. So the reconciliation is a three-way union: FAILSAFE backend ∪ test batch ∪ GUI rebuild.

Known both-sides conflict surface (from the audit, §1): `main/kneespa.py`, `main/motor/motor.ino` (the two hard ones), `main/helpers/protocols.py`, `main/config/config.py`, `main/config/constants.py`, `main/helpers/csv.py`, `main/motor/test/test_command_parse/test_command_parse.cpp`, `tests/unit/test_csv_helper.py`, `AGENTS.md`.

## Decision

**Create a new integration branch `feat/gui-on-failsafe` based on `improvement-plan`, and replay the `9b23e11..feat/gui-modernization` work onto it, file-by-file over the conflict surface. When it reaches feature parity with PR #15 and CI is green, open a new PR that supersedes PR #15.**

Concretely:

1. Branch `feat/gui-on-failsafe` from `improvement-plan` tip (`ec0e18a`).
2. Replay in order, adapting rather than blind-merging:
   - the test batch + GUI commits whose files don't exist on `improvement-plan` (all of `main/ui/**`, DS/screen/theme tests, GUI assets) — these apply nearly clean;
   - the 9-file conflict surface per the plan's B1–B6 (FAILSAFE `motor.ino` wholesale + re-applied `J<ms>` parse behind `PULSE_RATE_FIRMWARE_SUPPORT`; `AppShell` seam rewired onto the decomposed controllers; GUI additions merged into `improvement-plan`'s `protocols.py`/`config.py`/`constants.py`/`csv.py`);
   - the Phase A CI work (`7142cae`) — largely convergent already, since Phase A deliberately adopted `improvement-plan`'s harness and workflow structure; the GUI branch's `test_clamp` suite, `J<ms>` tests, mock-clock `delay()` fix, and pytest fixture hardening carry across.
3. Preserve PR #15's branch and history untouched (review archaeology); no force-pushes to any shared branch.
4. The frozen, unit-tested conventions stay frozen (ground rule 3): e-stop/conversion command math, A-command zero-offset, `AFULLINCH` vs `AXIAL_MAX`, B-axis degree/direction — pending hardware measurement in Phase E.

## Rationale

- **Asymmetric risk.** The safety backend (FAILSAFE firmware, `SafetyMonitor`, connection rework) is the code that must not be re-derived by hand through merge conflicts — a wrong conflict resolution there is a patient-safety defect that tests may not catch. The GUI, by contrast, must be rewired onto the decomposed controllers *anyway* (plan item B2): the adaptation cost lands on the GUI side regardless of which base we pick. Choosing `improvement-plan` as base keeps the safety code byte-identical to its tested state.
- **Commit shapes favor replaying the GUI.** The GUI work is a handful of well-scoped phase commits dominated by new files that don't exist on `improvement-plan`; the safety work is 30 interleaved commits that repeatedly touch `kneespa.py` (the decomposition was iterative). Cherry-picking the former is mostly clean application; cherry-picking the latter is conflict archaeology.
- **A new branch avoids history rewrites.** Rebasing/force-pushing PR #15 was the other way to express "GUI onto improvement-plan"; a fresh integration branch achieves the same tree with zero rewriting of pushed history (and the 🛑 rule constrains history rewrites).

## Alternatives considered

- **Cherry-pick FAILSAFE firmware + controllers + protocol-v2 onto `feat/gui-modernization`** (preserves PR #15 as *the* PR). Rejected: it drags the 30 intertwined backend commits through conflicts against the rewired monolith — precisely the "re-derive safety code by hand" failure mode. The plan lists it only as the fallback.
- **Plain `git merge` in either direction.** Rejected outright by the audit ("do NOT blind-merge"): 9 files conflict, including the two files where a silent mis-merge is most dangerous (`kneespa.py`, `motor.ino`).
- **Rebase `feat/gui-modernization` onto `improvement-plan` + force-push.** Same resulting tree as the decision, but rewrites a pushed, open-PR branch. No benefit over a new branch.

## Consequences

- PR #15 remains open but frozen; a new PR from `feat/gui-on-failsafe` supersedes it (owner closes #15 at that point — see open decisions in the state doc).
- CI on the integration branch must pass the **union** of both suites (improvement-plan's controller tests + the test batch + GUI tests + firmware natives) before Checkpoint B is met.
- `main/controllers/` stops being an empty stub package on the GUI line (the audit's "empty controllers package" hygiene item resolves itself).
- The Phase-B checkpoint report must state which CRITICAL/HIGH findings the merge resolves (expected: C1–C5, H2, H4, H5, H8) vs. which remain for Phase C/D (C6, H1, H3, H6, H7).
