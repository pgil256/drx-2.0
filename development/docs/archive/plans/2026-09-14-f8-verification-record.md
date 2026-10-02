# F8 compatibility API retirement

Implemented: 2026-09-14
Scope: F8 and Phase 5's compatibility-consumer/worktree inventory in
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting HEAD: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with the existing
F1–F7 working-tree implementation preserved.

## Result and consumer decision

Removed eight helpers with no current-checkout callers after completing the
consumer inventory below. The production change deletes 188 lines across three
files; no replacement API or dependency is introduced. The active treatment
loops, timing, pulse commands, configuration persistence, and logging helpers
with callers retain their implementations. No tests were deleted or rewritten.

The owner initially indicated that some old code might still be used. After
clarification distinguishing active run/deploy/development checkouts from backup
copies, the owner explicitly requested retirement of both old worktrees
("Yeah id say nix them") and answered "None" to the question about external
maintenance/calibration/service scripts using KneeSpa's Python code. This is the
external-consumer evidence for API retirement, not a claim that remote devices
were inspected.

Both worktrees were archived and verified before retirement. All 19 uncommitted
entries from the dirty worktree also have a verified named Git stash. Both
checkouts were then removed using ordinary `git worktree remove`, without force.
The old branch and existing stash entries remain available.

## Deletion manifest

| File / symbol | Current-checkout evidence before deletion | Historical / external evidence | Disposition |
| --- | --- | --- | --- |
| `main/helpers/protocols.py`: `Protocols.apply_continuous_pulse` | Definition and two diagnostic strings only; no caller, import, test, discovery hook, or configured route. Current protocols 1–3 use `_pulse_or_hold_phase`; protocol 4 has its own active loop. | One direct caller in each older checkout, recorded below. Both checkouts retired by the owner; no external scripts reported. | Removed the complete 69-line method. Active pulse/hold and oscillation implementations retained. |
| `main/config/config.py`: `Configuration.get_list` | Definition only in executable code; historical audit recommendations are documentation references. Configuration reads use `ConfigParser` and explicit parsing, not this helper. | Definition but no caller in either older checkout; no external scripts reported. | Removed the three-line definition/separator. All configuration loading/writing behavior retained. |
| `main/helpers/logging.py`: `debug_serial`, `debug_protocol`, `debug_thread`, `debug_gpio`, `debug_signal`, `debug_lock` | Six definitions only; no callers or imports in source, tests, scripts, or operational files. | The same definitions, without callers, occur in both older checkouts; no external scripts reported. | Removed all six wrappers and their separators: 116 lines. |
| `main/helpers/reset_worker.py`: polling branch in `_wait_for_done` | Explicit current tests cover success and timeout without an Event. The real window initializes `I2Cstatus_event`; normal v1 reset completion uses that Event. | No external scripts reported. This remains a valid, tested completion contract for callers without the Event. | Retained deliberately, including its tests. This is not classified as an unsupported branch. |

`setup_logger`, `debug`, `debug_safety`, `debug_state_change`, `debug_timing`, and
`debug_error` remain. `Any` is still used by `debug_state_change`. The Arduino
transport, reset Event handling, command handles, public worker signals, and
working v1/v2 completion paths are unchanged.

This resolves all F8 candidates as either deleted or deliberately retained.
F9's backport and asset candidates are outside this manifest and remain deferred
pending their own supported-Pi and packaged/deployed-consumer evidence.

## Reproducible search and indirect consumers

The search covered tracked, untracked, and ignored text in the current checkout,
including hidden files, CI/configuration, tests, styles, scripts, operational
tools, and documentation. Dependency/generated directories and older worktrees
were excluded from current-code counts, with the old worktrees searched
separately before removal. Binary assets/archives were not treated as Python
callers. No extra blanket exclusion of logs, configuration formats, or scripts
was applied.

The directory-level exclusions below implement the plan's scope on Windows.
The plan's original trailing-`/**` form still attempted to traverse the
inaccessible root `.pytest_cache`; rerunning with directory exclusions completed
without search errors.

```powershell
$f8Globs = @(
    '-g', '!**/.git', '-g', '!**/.venv', '-g', '!**/venv',
    '-g', '!**/kneespa_env', '-g', '!**/__pycache__',
    '-g', '!**/.pytest_cache', '-g', '!**/.pio',
    '-g', '!**/.native-build', '-g', '!.claude/worktrees'
)
rg -n --hidden --no-ignore @f8Globs 'apply_continuous_pulse|get_list|debug_serial|debug_protocol|debug_thread|debug_gpio|debug_signal|debug_lock' .
```

Before deletion this found only the eight definitions, the two self-referencing
pulse diagnostic strings, and historical documentation in the current checkout.
After deletion it found only documentation references. The old audit documents
remain as historical records rather than being edited to erase those references.

Additional inspection covered:

- **Imports and exports:** `main/kneespa.py`, the controllers, helper modules,
  tests, tools, and package `__init__.py` files. `helpers` and `config` have no
  `__init__.py` re-export lists. Existing UI package exports name UI components.
  No wildcard import, dynamic import, module scanner, or plugin/entry-point
  registration selects any of the eight helpers.
- **Dynamic attributes and discovery:** configuration persistence's `getattr`
  iterates a fixed list of five data attributes; protocol signal disconnection
  iterates `done_emit`/`error_emit`; logging resolves levels on logger objects.
  None selects the candidates. Video/font loading scans media directories;
  theme exports, startup path validation, and those directories are unchanged.
- **Launchers and packaging:** `rpi/desktop_executable.sh`,
  `rpi/startup_version.txt`, `rpi/dev-path.txt`, `rpi/sync_pis.sh`,
  `tools/run_local.py`, requirements files, and `.github/workflows/ci.yml`.
  The desktop and example systemd launchers invoke `kneespa.py`; the development
  launcher imports the actual window and substitutes hardware boundaries.
  The sync script copies `main/`; it does not discover these functions.
- **Operational/support tools:** all `tools/`, `scripts/`, `rpi/`, and
  `docs/archive/tools/` sources were included, including calibration and probe
  tools. Comparing the script-file inventory with `git check-ignore` identified
  `.calibration-preview.tmp/render.py` as an ignored Python script. It was read
  explicitly: it imports `Configuration` and `CalibrationDraft`, renders the
  shell/calibration dialog, and does not use the candidates.
- **External services:** the owner's explicit statement above establishes that
  no separate external maintenance/calibration/service scripts need these APIs.
  Example launcher files were inspected locally; no deployed service settings
  or remote source directories were queried, and stale IP defaults were not
  used for device operations.

## Older worktrees and preservation

Both worktrees started at `b517d108e96d61b8350d9bb360bbc5cde3fdb19d`.

| Worktree under `.claude/worktrees/` | Original state | Historical pulse caller | Preserved files |
| --- | --- | --- | --- |
| `sad-ritchie-346623` | Detached HEAD, clean. | `main/helpers/protocols.py:623`, inside `_pulse_or_hold_phase`; method definition at line 497. | 229 files plus Git-link metadata. |
| `setup-protocols-vlc-fixes-847050` | Branch `claude/setup-protocols-vlc-fixes-847050`; 18 modified tracked files and one untracked plan. | `main/helpers/protocols.py:687`, inside `_pulse_or_hold_phase`; method definition at line 552. The dirty version also updates pulse-rate handling there. | 323 files plus Git-link metadata, including all 19 uncommitted entries. |

The dirty checkout's changes were preserved as their original work, not assumed
equivalent to current code or silently merged into this refactor. They are:

```text
AGENTS.md
main/config/constants.py
main/controllers/protocol_controller.py
main/controllers/safety_monitor.py
main/helpers/conversions.py
main/helpers/protocols.py
main/helpers/reset_worker.py
main/kneespa.py
main/ui/modals/video_modal.py
tests/integration/test_reset_worker.py
tests/unit/test_actuator_controls.py
tests/unit/test_conversions.py
tests/unit/test_protocol_controller.py
tests/unit/test_protocol_pause.py
tests/unit/test_protocol_pressure.py
tests/unit/test_reset_worker_logic.py
tests/unit/test_safety_monitor.py
tools/run_local.py
docs/plans/2026-07-09-setup-protocols-vlc-fixes.md  (untracked)
```

The local archive is `.f8-worktrees-backup.zip` at the repository root:

- Size: **79,288,936 bytes**.
- SHA-256: `7195d477f338ebca37222c7ef326dcd4e8562afd052d1ddb4b4241a518508257`.
- Each worktree has its own directory in the archive. `metadata/manifest.json`
  records the original HEAD, status, and SHA-256 of every included file;
  `metadata/*.patch` preserves the tracked binary-capable diff, and
  `metadata/*.gitfile` records the original Git linkage.
- All 552 archived files were read back and verified against both their stored
  hashes and the still-existing source files before retirement; ZIP integrity
  also passed. `.pytest_cache` is the only omitted directory, deliberately
  excluded as generated cache. Ignored runtime files, including the dirty
  checkout's local PIN table and logs, are preserved. The archive stays local
  and ignored by Git's existing `*.zip` rule.

The dirty worktree was made clean with:

```powershell
git -C .claude/worktrees/setup-protocols-vlc-fixes-847050 stash push --include-untracked -m 'F8: preserve retired setup-protocols-vlc-fixes-847050 worktree'
```

Preservation stash: **`41910d45355485927a1b9c259541d980016bcbe4`**.
Its tracked diff matches the archived patch exactly. All 19 entries were also
verified against the stash's tracked/untracked blob IDs, using Git's path-aware
normalization for line endings. The earlier stash was not dropped or modified.

After verifying both worktrees were clean and checking the removal paths within
this repository's `.claude/worktrees`, ordinary `git worktree remove` removed
both checkouts. Final `git worktree list --porcelain` lists only the main
checkout. `git worktree prune --dry-run --verbose` reports no stale metadata,
so no additional pruning is needed.

To recover the dirty source in a new checkout, use the retained branch and
apply the preservation stash without dropping it:

```powershell
git worktree add .claude/worktrees/recovered-f8 claude/setup-protocols-vlc-fixes-847050
git -C .claude/worktrees/recovered-f8 stash apply 41910d45355485927a1b9c259541d980016bcbe4
```

The archive additionally restores ignored files if needed; the preserved
`.gitfile` is historical metadata, not a valid link for a newly created checkout.
The clean source can be recreated from the recorded `b517d108...` commit.

## Verification

| Check | Result |
| --- | --- |
| Focused protocol/config/logging/reset/launcher selection before deletion | 204 passed in 5.95 s. |
| Same selection after deletion | 204 passed in 6.17 s. |
| Full Windows suite | 946 passed, 39 expected POSIX skips, no warnings, in 40.87 s. |
| Full WSL/Linux suite | 985 passed, no skips or warnings, in 68.28 s. |
| Behavioral verification runner with writable temporary/cache paths | All 11 limit checks and 81 behavioral cases passed; pytest took 3.03 s. |
| Deletion/source review | The eight complete definitions were removed; all surviving Python AST nodes matched the pre-edit working tree. `git diff --check` passes after removing the newly trailing logging separator. |
| Reset/transport preservation | `git diff --exit-code -- main/helpers/reset_worker.py main/helpers/arduino.py` passes. |
| Worktree/backup verification | All 552 archived files and 19 stash entries verified; only the main checkout remains registered; no stale worktree metadata. |

Commands from the repository root:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_protocol_logic.py tests/unit/test_protocol_pause.py tests/unit/test_protocol_pressure.py tests/unit/test_protocol_live_settings.py tests/unit/test_config.py tests/unit/test_config_defaults.py tests/unit/test_logging.py tests/unit/test_reset_worker_logic.py tests/unit/test_run_local.py tests/unit/test_kneespa_cli.py --basetemp=.f8-after-tmp -o cache_dir=.f8-pytest-cache --tb=short
.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f8-full-windows-tmp -o cache_dir=.f8-pytest-cache --tb=short
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f8-full-linux -o cache_dir=/tmp/drx-f8-linux-cache --tb=short
$env:PYTEST_ADDOPTS = '--basetemp=.f8-runner-tmp -o cache_dir=.f8-runner-cache'
.venv/Scripts/python.exe scripts/validate_fixes.py
git diff --check
```

The first runner invocation used pytest's default temporary/cache directories,
which are inaccessible in this Windows sandbox: 72 passed, 9 setup errors, and
2 cache warnings. Rerunning with the invocation-scoped writable paths above
passed without changing the runner or tests. Git worktree/stash writes and WSL
execution used the required sandbox permission; no action was rejected by
automatic approval review.

The existing coverage exercises live pulse-rate changes, pulse-off holding,
pause/resume, pressure and command failure, configuration persistence, retained
logging, reset Event/polling success and timeout, stale Event rejection, and v2
command-specific DONE handles. The full suites include the real window/screen
startup checks; the Linux suite also covers POSIX serial and reset integration.

F8's source changes are limited to `main/helpers/protocols.py`,
`main/config/config.py`, and `main/helpers/logging.py`, plus this record and the
plan update. Existing F2/F7 edits in the first two files are preserved. No
application commits, deployments, firmware flashes/builds, or physical-Pi startup
checks were performed. Supported-Pi startup/resource checks, B2 deployment
preservation, and the committed release baseline remain separate release gates;
this record establishes completion in the working tree.
