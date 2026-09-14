# F2 pressure-local cleanup

Implemented: 2026-09-14
Scope: F2 / Phase 1B of [the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting commit: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with existing uncommitted F1 changes

## Result and boundaries

Removed only the unused `final_attempt_start` and `max_final_wait_time` assignments
from `Protocols.run_pressure_sequence` in `main/helpers/protocols.py`. Repository
search confirmed neither name had a read. Actual timeout values, retries, pressure
verification, pause/cancellation handling, and serial command flow are unchanged.

Existing F1 changes, including their behavioral tests and simulated protocol clock,
were preserved. No new tests were added solely to assert unused-variable removal.
The eight firmware locals remain deferred to the next verified firmware/reflash
batch, as the plan requires; firmware was not edited, built, or flashed.

This records a tested working-tree change, not a committed phase tip. B2 and the
remaining Phase 1 tasks and full phase gate remain separate; this result does not
claim those prerequisites or acceptance criteria are complete.

## Verification

| Check | Result |
| --- | --- |
| Pressure, protocol logic, and pause unit tests | 73 passed in 2.21 s. |
| Host/firmware limits synchronization | 11 checks passed. |
| Production diff review and `git diff --check` | Exactly two assignment deletions; no whitespace errors. |

Commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_pressure.py tests/unit/test_protocol_logic.py tests/unit/test_protocol_pause.py --basetemp=.f2-focused-tmp -o cache_dir=.f2-pytest-cache
.venv/Scripts/python.exe scripts/check_limits_sync.py
git diff --check -- main/helpers/protocols.py
git diff -- main/helpers/protocols.py
```

These are the plan's focused checks for 1B. Full Windows/Linux suites and the local
runner remain the phase-completion gate; no device verification was performed.
