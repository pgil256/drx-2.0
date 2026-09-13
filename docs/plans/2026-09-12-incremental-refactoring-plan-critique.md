# Critique of the incremental refactoring plan

Reviewed: `docs/plans/2026-09-12-incremental-refactoring-plan.md`
Date: 2026-09-12
Working tree at review: branch `docs/phase-e-on-device-plan` at `fd7ddc2`, 31 modified files (+1794 / -469), 10 untracked files

## Verdict

The findings are accurate, but the sequencing is wrong. Findings F1 through F4 and F8 were checked against the working tree, and every symbol, line reference, and "unused" claim held up:

- `scripts/validate_fixes.py:79` still requires the literal `_send_command(f"P{current_command}")` pattern; `protocols.py` now routes through `_send_pressure_command`.
- `final_attempt_start` (`protocols.py:655`) and `max_final_wait_time` (`protocols.py:663`) are assigned and never read.
- The eight firmware locals are declared at `motor.ino:706–714`.
- `_NullWidget` consumers are exactly the treatment-side calls in `protocol_controller.py` (lines 272–290, 329–360, 477–482, 573–574) and the auth-side calls in `auth_controller.py` (lines 92–111, 152).
- `_prev_pressure`, `_prev_left`, `_prev_right` are written at `protocol_controller.py:298–300`, initialised at `kneespa.py:381–383`, and never read in `main/`. Production rollback uses `_prev_settings` (`kneespa.py:743–775`). The only reader is `tests/unit/test_protocol_controller.py:222–224`.
- `apply_continuous_pulse` has no caller in the working tree. Its only callers are in two stale worktrees under `.claude/worktrees`.

The problems are in what the plan gates on, what it ships first, and what it leaves buried.

## Where the plan is weak

### 1. The baseline is not a baseline

The plan proposes "independently reviewable and revertible" refactoring commits on top of 31 modified files, roughly 1,800 added lines, and 10 untracked files, on a branch named for docs. Phase 0 task 1 says to record the baseline "against the working-tree snapshot", which is not something reviewers can diff against.

The calibration panel, the regression test files, and the firmware changes need to land as their own commits before any refactoring commit is meaningful. Given the earlier PIN-backup leak (`69b6cb1`), that landing must be by explicit path, never with a blanket `git add -A`.

### 2. The recommended first batch is the lowest-value change, and it touches firmware

Deleting eight unused locals in the sketch changes nothing at runtime, but it widens the gap between committed and flashed firmware while a reflash for FAILSAFE-6 and continuous pulsing is already owed. Either fold the deletion into that reflash or drop it from the first batch.

A Python-only first batch would be:

- the F1 script repair,
- the two `protocols.py` locals,
- the dead pressure subscriptions from F3 (see next item).

### 3. F3 is over-cautious about the subscriptions and under-cautious about the timer

Both pressure connections in `start_protocol` terminate in `_NullWidget.update_pressure`, which is a no-op. The worker `pressure_emit` connection, the Arduino `status_emit` lambda, and the `_arduino_pressure_slot` bookkeeping are dead wiring, as safe to delete as F2. They can move into Phase 1.

The opposite hazard is the timer. The `timer_dialog.isVisible()` guard at `protocol_controller.py:272` is always false, so the `protocol_timer.start(1000)` inside it never runs. The real start is at `protocol_controller.py:378`. Anyone removing the guard without removing its body introduces an earlier timer start, before the worker exists. The plan should name that trap explicitly in the Phase 2 tasks.

### 4. Phase 0 is the critical path and has no size

A real-window fixture that constructs `KneeSpa` with hardware, auth, timers, cloud, and VLC replaced but real Qt widgets retained is probably the largest single task in the plan. It gates Phases 2 through 5. There is no estimate, no fallback, and no statement of what `tests/unit/test_controller_wiring.py` already covers and why it is insufficient.

Risk: Phase 0 never finishes and nothing ships. Recommendation: let Phase 2's treatment cleanup proceed on the existing controller tests, and reserve the real-window fixture as the gate for Phase 3 only.

### 5. B2 is buried under "tracked separately"

`rpi/sync_pis.sh` deleting `data/auth_state.json` and `data/pending_uploads.json` on every sync is an operational hazard that bites the next time anyone runs it. It should be pulled ahead of Phase 1, as its own commit, not left behind cosmetic cleanup. (Note also that the script's default IPs are stale per earlier bench work.)

### 6. F4 needs to delete the comment, not just the fields

The comment at `protocol_controller.py:294–297` claims the mid-protocol Cancel path restores `_prev_*`. It does not; rollback goes through `_prev_settings`. Leaving the comment while deleting the fields would mislead the next reader into thinking the deletion broke something. Delete the comment, the three assignments, the three initialisers, and the three test assertions together.

## Smaller gaps

- **Per-commit gate cost is unstated.** Two full Python suites take over five minutes each, plus native firmware tests and the Mega build. That is roughly fifteen minutes per "small commit". Define a fast gate (affected tests) per commit and the full gate per phase.
- **Search scope for "repository-unused" is unstated.** Two stale worktrees under `.claude/worktrees` at `b517d10` still call `apply_continuous_pulse`. The Phase 5 inventory should list its exclusions (`.venv`, `.claude/worktrees`, `__pycache__`), and those worktrees should be pruned first.
- **F1 fixes one stale pattern in a script built entirely from source patterns.** "Inspect the remaining checks individually" will keep producing this class of failure. Decide whether `validate_fixes.py` survives at all or becomes a thin wrapper over `check_limits_sync.py` plus real tests.
- **Phase 3 defers the phase-text contract "initially" and never schedules it.** Either give it a phase or state that string-matching the status label in `_PhaseLabelAdapter` is the accepted long-term design.
- **`protocol_timer` is constructed twice** (`kneespa.py:346` and `kneespa.py:1783`). Not a refactoring target in the plan, but worth a line in F3 or F4 since Phase 2 touches the timer paths.

## What to keep

The "Leave alone for now" section is the strongest part of the plan and should not change. The dead-code classification (confirmed local / obsolete internal / repository-unused / asset candidate) is the right taxonomy and should be kept as the standard for any future deletion.

## Suggested reordering

1. Land the current working tree as reviewable commits (calibration, regression tests, firmware, UI fixes) by explicit path.
2. Fix B2 (deployment sync preserving runtime state) as its own commit.
3. Phase 1 (Python only): F1 script repair, two `protocols.py` locals, dead pressure subscriptions, `_prev_*` fields plus their comment and test assertions.
4. Firmware unused locals: bundle with the owed FAILSAFE-6 / continuous-pulse reflash.
5. Phase 2 treatment placeholder cleanup, gated on existing controller tests, with the timer-guard trap called out.
6. Phase 0 real-window fixture and transition matrix, as the gate for Phase 3.
7. Phases 3, 4, 5 as written.
