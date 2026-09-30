# F9 dependency and asset inventory

Inspected: 2026-09-14
Scope: F9 and Phase 5's dependency/asset checks in
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting HEAD: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with the existing
F1–F8 working-tree implementation preserved.

## Status

**Local inventory and proposed-package smoke checks are complete. F9 deletion
is deferred at the owner's request.** No runtime dependency or shipped asset
was deleted. No device was contacted, deployed to, restarted, or flashed.

The plan requires the supported Pi interpreter's actual import source before
removing the backport, and packaged/deployed-consumer evidence before removing
assets. Neither is established by the repository or the local developer
interpreters. The owner subsequently set aside the current Pi host/account and
deployed/packaged-consumer follow-up; there is no outstanding request for access.
F8's owner statement about external
Python service scripts is not treated as evidence about these separate subjects.

The initial local deployment dry run reproduced **B2**: that version of the
deploy script would delete device-local authentication state and pending uploads.
Commit `f0d813c` subsequently fixes both exclusions, requires explicit device
hosts, and passes seven local rsync regression cases. The dry-run observations
below describe the earlier script, not the fixed deployment behavior.

## Dependency disposition

| Candidate | Evidence | Disposition |
| --- | --- | --- |
| `main/requirements.txt`: `configparser==5.0.2` | Windows Python 3.12.14 loads `configparser.py` from the bundled interpreter's standard library. WSL Python 3.14.4 loads `/usr/lib/python3.14/configparser.py`. Neither environment has the `configparser` distribution installed, according to `importlib.metadata`. | Retained pending the supported Pi OS/Python version, deployed dependency set, and actual import source for each supported launcher environment. |

The exact Windows import was
`C:\Users\patri\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\configparser.py`.
These observations establish local behavior only. The import/distribution probe
was read-only; nothing was installed or uninstalled.

Current consumers use ordinary `import configparser`: `main/config/config.py`,
`tools/calibrate.py`, `docs/archive/tools/calibrate_gui.py`, and configuration/
calibration tests. No explicit backport import or package-metadata lookup was
found in those consumers. Their existence does not establish the Pi's import
resolution or support policy.

`rpi/desktop_executable.sh` optionally activates
`$KNEESPA_APP_DIR/kneespa_env/bin/activate` and then invokes `python3`.
`rpi/startup_version.txt` instead illustrates
`/home/pi/kneespa_env/bin/python`. These examples may refer to different virtual
environments; neither proves the deployed service's effective interpreter.
The direct entry point and `rpi/dev-path.txt` also use `python3`. CI configures
Python 3.12 but does not establish the supported Pi version.

## Asset disposition manifest

All candidates below are under `main/ui/media/images/buttons/`. All remain in
the working tree pending deployed/packaged-consumer evidence. Together they
occupy **12,074 bytes**. No current application, tool, style, CI, or launcher
reference to these files was found, and the application does not discover PNG
buttons by enumerating this directory.

| Candidate | Bytes | Current-checkout reference outside the application | Disposition |
| --- | ---: | --- | --- |
| `arrow-back.png` | 770 | Ignored design reference README names the old icon. | Deferred |
| `arrow-forward.png` | 650 | Ignored design reference README names the old icon. | Deferred |
| `down_1.png` | 886 | Ignored design reference README names the old icon. | Deferred |
| `down_2.png` | 997 | Refactoring-plan inventory only. | Deferred |
| `pause-black.png` | 555 | Ignored design reference README names the old icon. | Deferred |
| `play-button.png` | 3,076 | Ignored design bundle renders a separate copy; historical modernization plan proposes this asset. | Deferred |
| `play.png` | 1,186 | Ignored design reference README names the old icon. | Deferred |
| `restart.png` | 2,196 | Ignored design reference README names the old icon. | Deferred |
| `up_1.png` | 801 | Ignored design reference README names the old icon. | Deferred |
| `up_2.png` | 957 | Refactoring-plan inventory only. | Deferred |

The ignored `_ds/kneespa-drx-design-system-3c820074-bcbc-43cb-80b9-2e6778732e44/_ds_bundle.js`
uses `../../assets/icons/play-button.png`. This resolves to the separate
root-level `assets/icons/play-button.png`, not the candidate in `main/`.
Both copies have SHA-256
`0b12a0062abf748046b3de09f1ee1b6ca1718e7a21093099d40d52b1c49cb866`.
The reference README describes icons copied into `assets/`; `.gitignore`
identifies `_ds/`, `app/`, and `assets/` as design-source scratch outside the app
build. These reference files and their assets were left intact.

The old worktrees were already preserved and retired in F8. `git worktree list
--porcelain` now lists only the main checkout. Their archive is historical
evidence, not an operational consumer; F9 performed no worktree housekeeping.

## Resource and packaging contracts

- `rpi/sync_pis.sh` distributes `main/` recursively with rsync `--delete`.
  There is no separate asset manifest or PNG discovery in this launcher.
  Removing a source PNG would therefore remove its deployed counterpart.
- `ui.widgets.ds._common.image_path()` resolves named images relative to the
  actual UI module. The avatar (`user-profile.png`), knee image, full logo,
  and loading GIF have current callers and remain required.
- `ui.theme.icons` draws play/pause/navigation icons with Qt. Setup controls
  use glyphs; the old button PNGs are not their fallback path.
- `config.constants.validate_paths()` requires both `UI_PATHS` directories:
  `ui/media/images/graphics` and `ui/media/videos`. All four protocol graphics
  remain, including their directories, regardless of direct drawing usage.
- `_VlcEngine._discover_playlist()` scans the configured video directory for
  every `.mp4`, case-insensitively, in sorted order. It also supports the legacy
  single-file configuration shape through a directory fallback. All three
  shipped clips remain.
- `ui.theme.qss.load_fonts()` scans every `.ttf`/`.otf` file in the bundled
  font directory. All seven IBM Plex fonts, their license, and README remain.
- `tools/run_local.py` and `tools/screen_gallery.py` construct the current UI;
  the calibration tools use configuration/serial interfaces rather than the
  candidate buttons. The spinner has its own explicit GIF path.

## Search scope

Searched tracked, untracked, ignored, and hidden text, including production
source, tests, QSS, CI/configuration, `rpi/`, operational/calibration tools,
documentation, and the ignored design-source directories. This follows F8's
directory exclusions, which avoid inaccessible/generated dependency caches:

```powershell
$f9Globs = @(
    '-g', '!**/.git', '-g', '!**/.venv', '-g', '!**/venv',
    '-g', '!**/kneespa_env', '-g', '!**/__pycache__',
    '-g', '!**/.pytest_cache', '-g', '!**/.pio',
    '-g', '!**/.native-build', '-g', '!.claude/worktrees',
    '-g', '!.f9-audit.tmp', '-g', '!.f9-before.tmp', '-g', '!.f9-cache.tmp'
)
rg -n --hidden --no-ignore @f9Globs 'arrow-back|arrow-forward|down_1|down_2|pause-black|play-button|play\.png|restart\.png|up_1|up_2|configparser|PROTOCOL_IMAGES' .
rg -n 'image_path|QPixmap|QIcon|listdir|glob\(' main tools rpi .github -g '*.py' -g '*.qss' -g '*.sh' -g '*.yml'
git ls-files rpi main/ui main/requirements.txt '*setup*' '*manifest*' '*requirements*' '*spec*'
git worktree list --porcelain
```

The initial inventory preceded creation of `.f9-*.tmp`; the exclusions above
prevent the later proposed package and audit output from counting as production
consumers on a rerun. Binary assets and the F8 ZIP backup were not searched as
executable text. Media inventories, actual resource loading, launcher behavior,
and the design bundle's relative path were checked separately. No remote
consumer or package repository was searched, and the documented stale Pi IPs
were not used.

## Verification

| Check | Result and limits |
| --- | --- |
| Focused Windows selection | **181 passed**, no skips or warnings, in **16.11 s**. Real window/wiring, six-screen controls, theme, video behavior with mocked VLC, design-system widgets, configuration/calibration persistence, and launchers. |
| Same focused WSL/Linux selection | **181 passed**, no skips or warnings, in **19.74 s**. Uses Python 3.14.4; this is local Linux coverage, not a supported-Pi check. |
| Windows / WSL dependency probe | Both use standard-library `configparser`; neither has the backport distribution installed. These are developer environments, not Pi evidence. |
| Proposed-package fresh startup | Passed on Windows/offscreen with path validation explicitly enabled. The isolated package omits the ten PNGs and backport requirement. The real `KneeSpa` constructor creates a fresh temporary config, shell, controllers, and timer. GPIO, deferred hardware startup, cloud, SMTP, and VLC are controlled. No serial/network operations execute. |
| Proposed-package resource loading | All seven remaining PNGs decode, the spinner GIF is valid, all seven font files register, both IBM Plex families load, and `1.mp4`, `2.mp4`, `3.mp4` are discovered in order. |
| Proposed-package screen inspection | All six pages plus Login and Video rendered at 1366×768. All eight captures were visually inspected; control icons, avatars, logos, and text render. Native VLC/audio playback and physical Pi display behavior were not exercised. |
| Deployment dry run | The actual script runs with an inert SSH stub and a local shim forwarding its effective options to real rsync with `--dry-run --itemize-changes`. It schedules all ten candidate PNG deletions **and the two B2 state-file deletions**. Calibration, PINs, and logs are excluded. Destination file hashes are unchanged. Process success is not a passed state-preservation gate. |
| Production preservation | `git diff --exit-code -- main/requirements.txt main/ui/media rpi/sync_pis.sh` passes. `git diff --check` passes. Earlier F1–F8 edits are preserved. |

The focused test command was:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/integration/test_window_wiring.py tests/integration/test_screens.py tests/integration/test_theme_apply.py tests/integration/test_ds_components.py tests/unit/test_config.py tests/unit/test_config_defaults.py tests/unit/test_calibration.py tests/unit/test_run_local.py tests/unit/test_kneespa_cli.py --basetemp=.f9-before.tmp -o cache_dir=.f9-cache.tmp --tb=short
wsl --exec python3 -m pytest -q tests/integration/test_window_wiring.py tests/integration/test_screens.py tests/integration/test_theme_apply.py tests/integration/test_ds_components.py tests/unit/test_config.py tests/unit/test_config_defaults.py tests/unit/test_calibration.py tests/unit/test_run_local.py tests/unit/test_kneespa_cli.py --basetemp=/tmp/drx-f9-before -o cache_dir=/tmp/drx-f9-cache --tb=short
```

Local, ignored evidence remains in `.f9-audit.tmp/`: `prepare.py`, `smoke.py`,
`deploy_dry_run.py`, per-candidate SHA-256 `manifest.json`, `smoke-result.json`,
eight `screens/*.png`, `rsync-args.json`, and `deploy-dry-run.txt`. The proposed
package copied only Git-listed `main/` files from their current working-tree
contents; it did not copy operator config, PINs, lockout state, or upload queues.
The smoke uses separate temporary runtime state. These are disposable local
verification artifacts, not new application modules or a deployment package.

The deployment fixture uses `fixture@offline.invalid`, and both service commands
are intercepted by the no-op SSH executable. It never runs a remote command.
The script's real effective exclusions are `config/kneespa.cfg`,
`data/user_pins.csv`, `logs/`, and `__pycache__/`; the absent exclusions for
`data/auth_state.json` and `data/pending_uploads.json` reproduce B2.

## Remaining acceptance evidence

1. Obtain the supported Pi OS/Python version and read-only import/distribution
   results using the interpreter actually selected by each deployed launcher.
   Remove the backport only after its deployment role is disproved.
2. Inspect or obtain an owner inventory of separate deployed/packaged UI
   consumers. If none use these PNGs, apply the ten-file deletion separately
   from dependency removal, then rerun the affected checks on the actual tree.
3. B2's separate file-preservation repair and fixture gate are now complete.
   Record fresh Pi startup/screens/font/video checks for any eventual deployed
   package that removes the F9 candidates.

F9 has not been marked complete on the strength of desktop-only evidence or a
dry run that still loses device state. Deferred candidates stay available while
these specific prerequisites are resolved.
