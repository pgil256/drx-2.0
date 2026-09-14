# F7 calibration persistence

Implemented: 2026-09-14
Scope: F7 and Phase 4's calibration persistence task in
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting HEAD: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with the existing
F1–F6 working-tree implementation preserved.

## Result

`Configuration._atomic_write` accepts an optional candidate `ConfigParser`.
Omitting the argument or passing `None` writes the current parser, preserving
existing callers. The writer never assigns the candidate to live configuration.
It retains the same temporary file location, UTF-8 serialization, flush/fsync,
atomic replacement, cleanup, and exception propagation.

`CalibrationDraft.save` copies the live parser, applies only edited tables and
factors, and backs up the existing file with the same timestamped `copy2` call.
It passes the candidate directly to the writer, publishing the parser and
changed calibration attributes only after the write returns successfully.
Temporary parser replacement and failure rollback are removed. Validation,
calibration-confidence handling, and resetting the draft's saved values remain
at their existing points.

Caller-specific error contracts are unchanged: calibration and initial-default
writes propagate failures; `update_config` prints and catches write failures.
`save_protocol_defaults` continues to update memory and return normally after
such failures. That behavior is B1 and is deliberately characterized, not fixed.

## Contract coverage

The existing calibration/configuration suites were extended with 22 cases:
9 in `tests/unit/test_calibration.py` and 13 in `tests/unit/test_config.py`.
All use temporary configuration files; no device configuration is edited.

- Observe the original live parser, marks, factors, and unsaved draft immediately
  before and after the actual atomic replacement. Exercise both success and an
  injected replacement failure, and inspect the pending file's edited values.
- Confirm backup bytes match the prior file and exist before replacement, failed
  backups prevent writes, unchanged drafts do nothing, and saving without an
  existing file succeeds without creating a backup.
- Preserve unknown sections/options, valueless keys, device metadata, axial
  marks, load-cell calibration, untouched `0` versus `0.0` keys, and missing,
  unmarked, marked, and malformed protocol defaults across calibration saves.
  Existing edited-mark tests still check canonical key replacement.
- Write the current parser, an explicit candidate (including UTF-8 text and
  parser defaults), and an empty candidate without publishing any candidate.
- Inject partial serialization, fsync, and replacement failures for both current
  and candidate parsers. Verify the previous file survives, live parser identity
  and contents remain unchanged, and temporary files are removed.
- Exercise initial-default, ordinary update, and protocol-default callers with
  a failing real writer, preserving their distinct error/return contracts.

Existing disk-full calibration/controller tests, invalid-table rejection,
fallback calibration-confidence tests, missing/corrupt configuration loading,
and protocol-default round trips remain in the focused gate.

## Verification

| Check | Result |
| --- | --- |
| Existing calibration/config/defaults selection before edits | 67 passed in 0.98 s. |
| Extended selection before production refactor | 81 passed, 8 expected failures in 1.34 s: 2 premature-publication failures and 6 unsupported candidate/explicit-None calls. |
| Same selection after refactor | 89 passed in 1.22 s. |
| Calibration suite alone | 42 passed in 0.95 s. |
| Configuration suite alone | 39 passed in 0.31 s. |
| Full Windows suite | 946 passed, 39 expected POSIX skips, no warnings, in 43.64 s. |
| Full WSL/Linux suite | 985 passed, no skips or warnings, in 72.64 s. |
| Source/diff review | All four changed Python files parse and have no lines over 100 characters; `git diff --check` passes. |

Commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_calibration.py tests/unit/test_config.py tests/unit/test_config_defaults.py --basetemp=.f7-after-tmp -o cache_dir=.f7-pytest-cache --tb=short
.venv/Scripts/python.exe -m pytest -q tests/unit/test_calibration.py --basetemp=.f7-calibration-alone-tmp -o cache_dir=.f7-calibration-cache --tb=short
.venv/Scripts/python.exe -m pytest -q tests/unit/test_config.py --basetemp=.f7-config-alone-tmp -o cache_dir=.f7-config-cache --tb=short
.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f7-full-windows-tmp -o cache_dir=.f7-pytest-cache --tb=short
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f7-full-linux -o cache_dir=/tmp/drx-f7-linux-cache --tb=short
git diff --check
```

The first WSL launch was denied access to the WSL service by the Windows
sandbox. The same command passed with the required execution permission.

## Separate observation and scope

An initial compatibility test used non-ASCII text in an unknown section and
exposed a pre-existing Windows encoding mismatch: the writer explicitly uses
UTF-8, while `get_config` calls `ConfigParser.read` without an encoding. On this
Windows environment, repeated save/load cycles altered that text. This happened
before production changes. The final compatibility cases use ASCII values to
characterize the existing reload contract; a direct writer test verifies UTF-8
output using an explicit UTF-8 read. Changing reload encoding is separate work.
The initial extended run had 77 passes and 12 failures, including these four
encoding failures; after adjusting those cases, only the eight intended F7
failures remained before the refactor.

The F7 production diff is limited to `main/config/config.py` and
`main/helpers/calibration.py`. Its other paths are additions to the two existing
test files, this record, and the plan's F7 status update. Pre-existing changes in
`tests/unit/test_config.py` and the plan are retained.

F7 is complete in the working tree. No commits, deployments, firmware flashes,
or physical-device checks were performed. Phase 0 and B2 remain separate
prerequisites for landing/deployment work.
