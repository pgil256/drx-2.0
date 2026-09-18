# F5 test-support consolidation

Implemented: 2026-09-14
Scope: F5, including Phase 4's test-support task, of
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting HEAD: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with the existing
F1–F4 working-tree implementation preserved.

## Result

Shared test builders now live under `tests/fixtures/`. No test imports a builder
from another collected test module, including function-local imports in the
regression suites. The migrated controller windows use explicit namespaces or
classes, concrete gate values, and bounded mock interfaces for views, workers,
timers, thread pools, logging, and serial transport. Unknown window attributes
raise `AttributeError`; retired dialogs are present only where a test explicitly
installs the historical placeholder.

| Support module | Responsibility and consumers |
| --- | --- |
| `controllers.py` | Protocol and window-wiring facades, worker double, shared view collaborators, and connection/reset facade. Used by controller, wiring, connection-manager, additional-regression, and reported-regression tests. |
| `protocols.py` | One real Protocols builder with concrete default calibration marks, bounded Arduino mock, accepted-send boolean, and opt-in DONE acknowledgement. Used by pressure, logic, pause, live-settings, and both regression suites. |
| `reset.py` | ResetWorker configuration/window/worker builders; real Event and explicitly absent-Event polling alternatives. Used by reset-worker and both regression suites. |
| `actuators.py` | Existing real-QPushButton control-gating harness. Used by actuator-control and reported-regression tests. |

`tests/conftest.py` no longer replaces `os.path.exists`, `os.makedirs`, or
`logging.handlers.RotatingFileHandler` process-wide. Shipped paths undergo real
validation. Before collection, a session hook imports application logging with
only its base directory redirected to temporary storage. The constants module's
base directory is restored immediately; application log handlers and Qt log
filters are cleaned up before the temporary directory is removed. Real rotating
handlers remain available to every test.

Two path-validation cases now require missing flat/nested resource entries to
fail until their directories exist. The existing logger/root-handler regression
now verifies all three real rotating handlers write records to temporary files.
Filesystem failures are no longer hidden by the old Pi-path exemption.

The initial focused run exposed two reset-sequence tests relying on a fabricated
truthy boot event. Their serial callback now explicitly sets the real boot event
after `Y`. The production reset sequence and its waits were not changed.

## Preserved coverage and boundaries

F1 already supplied the opt-in `protocol_clock` and bounded pressure waits.
Those fixtures and timeout/retry/cancellation assertions are unchanged. The
shared protocol builder does not replace time, emit DONE by default, or change
threading. Pressure ramp cases explicitly opt into acknowledgement; missing-DONE
and delayed-DONE cases keep their original real-thread behavior. Event/polling
reset tests and the POSIX FakeArduino suites remain in place.

F4 already supplied Gate W's actual constructor, shell signal, timer, and
transition coverage. The complete window suite passes in both full gates; no
new constructor abstraction or dependency-injection layer was introduced.

This is a bounded migration of shared support, not replacement of every local
mock in the suite. Hardware/VLC import doubles, test-specific local collaborators,
and the separate real-thread integration builders remain. SMTP and calibration
persistence refactoring belong to F6/F7.

No production, firmware, CI, or verification-runner code changed during F5.
The existing F1–F4 edits were compared with a snapshot taken at the start of this
task and preserved. The changed test files are `tests/conftest.py` and these unit
modules:

```text
test_actuator_controls.py
test_additional_regressions.py
test_connection_manager.py
test_constants.py
test_controller_wiring.py
test_logging.py
test_protocol_controller.py
test_protocol_live_settings.py
test_protocol_logic.py
test_protocol_pause.py
test_protocol_pressure.py
test_reported_regressions.py
test_reset_worker_logic.py
```

## Verification

| Check | Result |
| --- | --- |
| Each of the 13 affected unit modules in a separate pytest process | All passed; 415 total cases. |
| All 13 affected modules together | 415 passed in 11.11 s. |
| Full Windows suite | 898 passed, 39 expected POSIX skips, no warnings, in 36.29 s. |
| Full WSL/Linux suite | 937 passed, no skips or warnings, in 65.89 s. |
| Local behavioral runner | 11 limits checks passed; 81 cases passed in 3.12 s. |
| Source/diff review | Changed Python files parse; no new lines over 100 characters; no remaining test-module builder imports or global filesystem/rotating-handler replacements. |

The first focused run reported 411 passed and the two boot-event failures
described above; the corrected focused run passed. The first WSL launch was
denied access to the WSL service by the Windows sandbox. The same command ran
successfully with the required execution permission.

Commands from the repository root (fresh temporary/cache paths avoid the
checkout's older pytest-directory permission problems):

```powershell
# Run each affected module separately, then pass the same 13 paths together.
.venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_controller.py --basetemp=.f5-alone-test_protocol_controller -o cache_dir=.f5-pytest-cache

.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f5-full-windows-tmp -o cache_dir=.f5-pytest-cache --tb=short
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f5-full-linux -o cache_dir=/tmp/drx-f5-linux-cache --tb=short

$env:PYTEST_ADDOPTS = '--basetemp=.f5-runner-tmp -o cache_dir=.f5-runner-cache'
.venv/Scripts/python.exe scripts/validate_fixes.py
git diff --check
```

This completes F5 in the working tree, not a committed phase tip. No commits,
deployments, firmware flashes, or physical-device checks were performed. Phase 0
and B2 remain separate prerequisites for landing/deployment work.
