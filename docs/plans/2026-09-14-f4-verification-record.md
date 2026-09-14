# F4 treatment presentation and timer ownership

Implemented: 2026-09-14
Scope: F4 / Phase 1D, Gate W, and Phase 3 of
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting commit: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with existing
uncommitted F1/F2/F3 changes

## Result

Removed the obsolete `_prev_pressure`, `_prev_left`, and `_prev_right`
initializers, assignments, rollback comment, and test assertions. The real
`_prev_settings` rollback path and the worker-input assertions remain.

Removed `_StartButtonAdapter`, `_PhaseLabelAdapter`, `_ValueProxy`, and their
`_LegacyUi` namespace. ProtocolController now drives the treatment view through
its existing setters. The window's public lifecycle entry points remain as
delegating methods. Reset completion uses the existing lifecycle transition
instead of also writing the Start adapter; reset startup asks the protocol
controller to make the treatment controls busy.

Moved pause/resume and screen-stop handling into the existing protocol controller.
Worker operations, timer changes, pause anchors, stop/release commands, staged
recovery callbacks, and their order remain unchanged. The screen STOP and banner
emergency-stop paths retain their distinct presentation/timer behavior.

Phase mapping now lives in `ProtocolController._set_phase_from_text`. It preserves
the precedence `pulsing`, `oscillat`, `moving to`, `complete`, `stopped`, then
`started`/`pressure`; case-insensitive matching; and leaving an unknown phase
unchanged. Progress still strips only leading `>` characters and passes the
full uppercase text to the banner. View setter failures are still swallowed at
the former adapter boundaries, so a failed badge update does not prevent a
banner update. Completion and startup retain their existing banner behavior.
The post-start ramping phase write stays after the toggle returns, now inside
the controller, including the existing early-return behavior.

Settings reads replace each former proxy invocation at the same point, with
the same conversions and defaults. Confirmation, post-connection worker setup,
and treatment upload still read independently. Inputs are not captured earlier
as a single immutable snapshot. Pulse seeding and `_prev_settings` are unchanged.

Removed only the superseded parentless protocol timer from the constructor.
`setup_timers` still constructs `QTimer(self)`, configures 1000 ms, and connects
the same countdown callback at its existing startup point. Startup still starts
the timer after worker/signal/banner setup and immediately before dispatch.

## Gate W and review boundaries

`tests/integration/test_window_wiring.py` constructs the actual KneeSpa window,
AppShell, controllers, `_connect_shell`, and `setup_timers`. Configuration and
CSV/auth storage use temporary files. GPIO/VLC use the suite's existing mocks;
serial startup, worker scheduling, cloud, and SMTP are controlled offline.
Protocol and reset workers use real Qt signals. Test teardown stops child
timers, executes window cleanup, deletes the window, and drains deferred deletes.

Before presentation edits, **30 window cases passed** against the F3 working
tree. The constructor test characterized both original timer instances: the
parentless instance was inactive with no timeout receivers; the owned instance
was the active protocol timer with a 1000 ms interval and one receiver.
All 30 cases passed again after presentation migration, before timer deletion.
The constructor assertion was then tightened to exactly one constructed timer.

The final **32 window cases** cover:

- Actual START, PAUSE, and RESUME clicks reaching the real controller and
  changing visible text, enabled controls, settings gating, and phase badges.
- Confirmation acceptance/cancellation and settings/protocol edits during
  confirmation and connection verification. These event deliveries execute
  inside real nested Qt event loops without native confirmation dialogs.
- Fault, reset, and stop arriving during confirmation or connection verification,
  preventing worker dispatch and timer startup.
- Immediate worker progress/completion, including unsuccessful completion,
  without a later promotion back to running.
- Pause/resume clock adjustment, live setting acceptance, and Cancel restoring
  the prior slider value through `_prev_settings`.
- Screen stop racing successful/unsuccessful completion, reset success/failure/
  error signals, physical fault persistence, a late reset after physical stop,
  and completion/recovery callbacks after close.
- Live upload settings with a frozen patient association, countdown rendering,
  phase precedence/unknown text/full banner text, and a failing phase setter.
- Timer construction, ownership, interval, receiver count, startup ordering,
  shutdown stop/release commands, and cleanup.

Existing unit coverage was migrated to the actual treatment setters. The
treatment state-machine harness now uses a real TreatmentScreen instead of a
legacy QPushButton. The connection-manager stub includes a real
ProtocolController, and the protocol fixture explicitly lacks the retired
attributes. The existing controller timer-order and Cancel regressions remain.

Reviewable groups are the obsolete-field deletion, constructor/transition
coverage, lifecycle presentation migration, proxy/phase migration, and the
single constructor-timer deletion. No unrelated work was staged or committed.
The F4 production diff is confined to `main/kneespa.py`,
`main/controllers/protocol_controller.py`, and
`main/controllers/connection_manager.py`. Test edits are confined to the new
window suite and `test_protocol_controller.py`, `test_controller_wiring.py`,
`test_connection_manager.py`, `test_treatment_ui.py`, and the one migrated
busy-state assertion in `test_additional_regressions.py`.

## Consumer inventory

The removed adapters were private classes instantiated only by KneeSpa.
ProtocolController was the consumer of proxy reads and phase writes;
ProtocolController and ConnectionManager consumed the start-button adapter.
No executable consumer remains. The explicit absent-attribute fixture is
retained, and an archived audit's old `self.start_button` example is historical.

Search covered current source, tests, scripts, operational tools, hidden CI,
and non-plan documentation. Ignored operational Python/shell/PowerShell and CI
files in `scripts/`, `rpi/`, and `.github/` were also searched with `rg -uuu`.
Git internals, virtual environments, generated test/cache directories, historical
plans, and older `.claude/worktrees` were excluded. No public worker signal,
window lifecycle method, serial protocol, or persistence format was removed.

## Verification

| Check | Result |
| --- | --- |
| Gate W before production edits | 30 passed in 10.03 s. |
| Gate W after presentation migration, before timer deletion | 30 passed in 8.04 s. |
| Final window suite with nested Qt event loops | 32 passed in 8.68 s. |
| Full Windows pytest, final state | 896 passed, 39 expected POSIX skips, no warnings, in 40.32 s. |
| Full WSL/Linux pytest, final state | 935 passed, no skips or warnings, in 65.25 s. |
| Local behavioral runner | 11 limits checks passed; 81 cases passed in 3.14 s. |
| Diff and consumer review | No remaining production adapter consumers; whitespace check passed. |

The initial window-fixture attempt hit a Windows native Qt access violation
while opening a safety QMessageBox during a simulated fault. The fixture now
records safety-alert requests without opening native dialogs. Production alert
handling was not changed. The first focused unit run also identified one
remaining assertion against the removed button adapter (225 passed, 1 failed);
that assertion now checks the modern view's busy state.

Final commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_window_wiring.py --basetemp=.f4-final-window-tmp -o cache_dir=.f4-pytest-cache
.venv/Scripts/python.exe -m pytest -q --basetemp=.f4-final-windows-tmp -o cache_dir=.f4-pytest-cache
wsl --exec python3 -m pytest -q --basetemp=/tmp/drx-f4-final-linux -o cache_dir=/tmp/drx-f4-linux-cache
$env:PYTEST_ADDOPTS = '--basetemp=.f4-runner-tmp -o cache_dir=.f4-runner-cache'
.venv/Scripts/python.exe scripts/validate_fixes.py
git diff --check
```

This is a tested working-tree implementation, not a committed phase tip.
Existing F1/F2/F3 changes were preserved. Phase 0 and B2 are not claimed complete;
no commits, deployments, firmware changes, or flashes were performed. The
simulated event races establish host/controller/view behavior only. Physical
device timing, pressure release, serial/GPIO hardware behavior, native dialogs,
VLC/audio, and on-device validation remain outside this offline gate.
