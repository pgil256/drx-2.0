# F3 obsolete widget cleanup

Implemented: 2026-09-14
Scope: F3 / Phase 1C and the Phase 2 placeholder cleanup in
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting commit: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with existing
uncommitted F1/F2 changes

## Result and boundaries

Removed the worker-pressure and Arduino-status subscriptions targeting the
inert pressure dialog, including their disconnect attempts, lambda, diagnostics,
and `_arduino_pressure_slot` bookkeeping. Removed the entire unreachable
timer-dialog startup branch, obsolete treatment-control calls, hidden-dialog
completion cleanup, and invisible-dialog countdown updates.

Removed the authentication controller's calls to the inert PIN field and login
dialog. Its public PIN-buffer methods, clearing on successful/failed/locked-out
login, hashing, lockout persistence, and modern modal flow remain. All consumers
of the placeholder fields were removed before deleting `_NullWidget` and those
fields from the window and `_LegacyUi`.

The active `protocol_timer.start()` stays after worker construction and
signal/UI setup, immediately before thread-pool dispatch. `setup_timers` retains
its 1000 ms interval and timeout connection. Both existing timer constructions
remain for F4/Gate W. Public worker signals, the active ConnectionManager status
connection, SafetyMonitor, serial commands, completion/stop recovery, and
`_prev_settings` rollback behavior are unchanged.

This is a tested working-tree change, not a committed phase tip. Existing
F1/F2 changes were preserved; F4's obsolete rollback fields and presentation
adapters were left in place. Phase 0 and B2 are not claimed complete. No commits,
deployment, firmware changes, or hardware verification were performed.
Treatment subscription/placeholder cleanup and authentication cleanup remain
distinct review boundaries in the diff; no unrelated work was staged.

## Consumer inventory

| Removed surface | Accounted-for consumers and retained behavior |
| --- | --- |
| `pressure_dialog`, `_arduino_pressure_slot` | Protocol start attached two no-op receivers; completion hid the inert dialog. Actual telemetry still travels from ConnectionManager through `KneeSpa.status_emit` to the treatment view and SafetyMonitor. |
| `timer_dialog` | Start's false visibility branch, completion's hide, and countdown's false visibility branch. Banner countdown and late timer start remain. |
| `forward_button_protocol_image`, `backward_button_protocol_image` | Start/completion enabled or disabled the inert legacy pager. Modern protocol controls and navigation gating remain. |
| `show_timer_button`, `show_pressure_button`, `use_pulse_button` | Completion changed inert checkboxes; the commented pulse checkbox write was also removed. Modern pulse settings remain. |
| `reset_arduino_main_button`, `increase_time`, `decrease_time` | Start/completion toggled inert controls. Existing modern busy/navigation/reset and settings behavior remains. |
| `login_line_edit`, `login_dialog` | Auth PIN editing/clearing and successful-login acceptance targeted no-ops. The actual modal owns keypad display; `update_ui_after_login` still drives `shell.login_succeeded`. |
| `_NullWidget` | Only supplied the fields above. No remaining production caller or instantiation. |

Search covered current-checkout source, tests, hidden CI/configuration files,
styles, scripts, and operational tools. Ignored operational Python/shell/PowerShell
scripts and CI YAML in `scripts/`, `rpi/`, and `.github/` were also searched with
`rg -uuu`. Git internals, virtual environments, generated test/cache directories,
and older `.claude/worktrees` checkouts were excluded. Historical plan documents
are retained as records, not active consumers. The only remaining executable
references are the explicit absent-field/inert-dialog regression fixtures in
`tests/unit/test_protocol_controller.py`.

## Regression coverage

- `tests/unit/test_protocol_controller.py`: explicit UI collaborators, absent
  retired fields, and a genuinely false-visibility/no-op dialog where needed.
  Added seven cases for worker-construction failure, timer ordering with/without
  the inert dialog, three complete treatment starts using real Qt signals,
  preserved external pressure subscribers, live telemetry through real
  SafetyMonitor and TreatmentStatusPanel, and countdown/expiry/clamping.
  Strengthened existing rejected-start timer assertions. Existing F1 edits and
  F4's worker-input/rollback-seed assertions remain.
- `tests/unit/test_controller_wiring.py`: three real AppShell/AuthController
  keypad flows cover success, incorrect PIN, and lockout, including PIN clearing,
  modal state, and gated navigation. One timer case checks parent ownership,
  1000 ms interval, inactive setup, and the countdown callback. Existing telemetry,
  pause/resume, logout, and Cancel rollback cases remain.
- `tests/unit/test_secure_auth.py`: removed fake login widgets from the explicit
  window stub, retained backspace cases, added append/clear buffer coverage, and
  asserted PIN clearing after success, rejection, and lockout.

These tests do not construct the hardware-connected KneeSpa window and do not
claim Gate W. GPIO and VLC remain mocked under the existing suite fixtures.

## Verification

| Check | Result |
| --- | --- |
| Focused treatment/controller/wiring/regression selection | 202 passed in 2.30 s. |
| Focused authentication/wiring/real-shell selection | 156 passed in 12.35 s. |
| Full Windows pytest | 863 passed, 39 POSIX skips, no warnings, in 30.65 s. |
| Full WSL/Linux pytest | 902 passed, no skips or warnings, in 56.46 s. |
| Local behavioral runner | 11 limits checks passed; 81 cases passed in 3.25 s. |
| Diff and usage review | No remaining production placeholder consumers; whitespace check passed. |

The focused treatment run preceded the final worker-construction-failure test
and login/timer wiring additions; the full gates include all final tests. The
first ordered-test run exposed an implicit MagicMock truthiness call in its
centering stub (2 failed, 200 passed). Setting the successful centering return
value explicitly to `True` repaired the test collaborator; production behavior
was not changed to satisfy the assertion.

Windows: Python 3.12.14, pytest 9.1.1, PyQt5 5.15.11, Qt 5.15.2.
WSL/Linux: Python 3.14.4, pytest 9.0.3, PyQt5 5.15.11, Qt 5.15.14.

Commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_controller.py tests/unit/test_controller_wiring.py tests/unit/test_treatment_ui.py tests/unit/test_additional_regressions.py tests/unit/test_reported_regressions.py --basetemp=.f3-treatment-rerun-tmp -o cache_dir=.f3-pytest-cache
.venv/Scripts/python.exe -m pytest -q tests/unit/test_secure_auth.py tests/unit/test_controller_wiring.py tests/integration/test_screens.py --basetemp=.f3-auth-tmp -o cache_dir=.f3-pytest-cache
.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f3-windows-full-tmp -o cache_dir=.f3-pytest-cache
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f3-linux-full -o cache_dir=/tmp/drx-f3-linux-cache
$env:PYTEST_ADDOPTS = '--basetemp=.f3-runner-tmp -o cache_dir=.f3-runner-cache'
.venv/Scripts/python.exe scripts/validate_fixes.py
git diff --check
```
