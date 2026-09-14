# Incremental refactoring closeout

Date: 2026-09-14

Status: local implementation and verification complete; F9 deletion and device
release verification deferred.

## Scope and committed state

F1–F8 are committed, including the real-window Gate W and F2's eight unused
firmware locals. B1, B2, B3, and the Windows configuration-encoding issue have
separate fix commits. F9's `configparser` backport and ten PNG candidates remain
in place: the owner set aside the Pi/deployed-consumer investigation needed to
justify their deletion. No deployment, firmware flash, Pi inspection, or push
was performed.

The final application, tests, deployment script, and CI configuration were tested
from a clean detached checkout of:

```text
d8deeefc7853388e0c069b6d7b3f8c8010a3e48b
```

The checkout had an empty `git status --porcelain` before and after validation.
The subsequent closeout commit changes only documentation. Earlier finding
records retain their historical measurements; this record supersedes their
outstanding-commit and follow-up status.

Starting commit: `7aa99974ff9321d738dfdcf4645a9c830450808a`.

| Commit | Reviewed unit |
| --- | --- |
| `f0d813c` | B2: preserve deployment state, require explicit hosts, add local rsync regressions and CI dependency. |
| `799ddff` | F7: persist calibration candidates before publishing live state, with transaction tests. |
| `f2d9474` | F6: consolidate support email transport with offline contracts. |
| `d10967b` | F1–F5 and F8: controller cleanup, lifecycle and presentation coverage, Gate W, behavioral runner, and compatibility inventory. |
| `4dbb594` | Read configuration as UTF-8 across save/reload cycles. |
| `9cf222b` | B1: publish default saves only after persistence succeeds; report failures. |
| `1b398ec` | B3: correlate lateral completion with its command in protocol v2. |
| `5375534` | F2: remove eight unused firmware command locals. |
| `d8deeef` | Record implemented findings and owner-deferred F9 candidate deletion. |

The controller changes share adapters, timer construction, fixtures, and the
behavioral runner, so they form one coherent commit. Calibration, SMTP,
deployment, firmware, and bug fixes were separated for independent review.
Individual staged snapshots were tested before committing; the final gates below
cover the combined committed result. Runtime configuration, PINs, authentication
state, pending uploads, credentials, and generated validation artifacts were
excluded from the commits.

## Bug regression evidence

**B2 — deployment state.** `rpi/sync_pis.sh` now excludes
`data/auth_state.json` and `data/pending_uploads.json` from both overwrites and
`--delete`, alongside the existing calibration, PIN, log, and cache exclusions.
Unset, empty, or whitespace-only `PI_HOSTS` fails before any external action;
the README now requires explicit verified hosts. The seven regression cases in
`tests/integration/test_deploy_sync.py` run the actual script with no-op SSH and
a wrapper that forwards its rsync arguments to real local rsync. They verify
destination-only and conflicting source state, code replacement and obsolete
code deletion, failed-sync behavior, unreachable hosts, and host validation.
Before the fix: **5 failed, 2 passed**. After: **7 passed**. The Linux CI setup
installs rsync. No remote host is required by these tests.

**B1 — default saves.** Inputs are converted before mutation; a copied parser is
populated and atomically written before the live parser and defaults are
published. Persistence failures propagate to the UI, which logs and displays
the error without applying the new settings or reporting success. Regression
tests cover marked/unmarked defaults, write failure, invalid input, unknown-key
preservation, publication order, and the UI failure path. The existing error
contract for other `update_config()` callers is retained. The focused
configuration, calibration, and controller gate passed **173 tests**.

**Windows encoding.** Configuration reads explicitly use UTF-8 to match writes.
A regression simulates the Windows cp1252 default on either OS and repeats
Unicode default/calibration save/reload cycles, including preservation of
unrelated configuration values.

**B3 — acknowledgement interleaving.** Tests using the real Arduino parser,
signals, and command handles reproduced a delayed pressure `DONE` completing a
lateral move prematurely in both protocol versions. An unrelated `DONE` could
also override a v2 rejection. The initial reproduction had **5 failed, 3 passed**.
Lateral v2 moves now retain their own tracked handle, accept their own `DONE`,
and reject terminal errors; parse retries preserve the handle while ignoring
the old sequence. Legacy v1 has no acknowledgement identity, so lateral arrival
requires position telemetry. The existing 25-count tolerance and 45-second
lateral deadline remain in place. Telemetry can still prove arrival in either
version. Cancellation and enqueue-failure paths are covered. The final 11 new
interleaving cases and the broader **137-test** transport/protocol gate passed.
The shared pressure-settling event remains advisory; the public transport and
signal interfaces were not redesigned.

## Final validation on the clean commit

| Gate | Result |
| --- | --- |
| Full Windows pytest suite | **962 passed, 46 skipped**, 39.82 s. All skips are POSIX-only tests, including seven local deployment tests. No warnings reported. |
| Full WSL/Linux pytest suite | **1,008 passed**, 68.40 s. No skips or warnings reported. |
| `scripts/validate_fixes.py` on Windows | **81 behavioral cases passed**, 3.27 s, plus **11 limit checks passed**. |
| Native firmware suites in WSL | **119 passed**: clamp 12, parsing 32, safety 57, status 18. |
| Mega firmware build in WSL | **Passed**; RAM 2,317/8,192 bytes (28.3%), flash 29,086/253,952 bytes (11.5%). |
| Deployment shell syntax | `bash -n rpi/sync_pis.sh` passed. |
| Patch hygiene | `git diff --check 7aa9997..d8deeef` passed. |

Windows: Python 3.12.14, pytest 9.1.1, PyQt 5.15.11, Qt 5.15.2.
WSL/Linux: Python 3.14.4, pytest 9.0.3, PyQt 5.15.11, Qt 5.15.14.
These are local verification results, not a claim that hosted CI or device
release tests ran.

The verification checkout was created at `.closeout.tmp/final-checkout` using
`git worktree add --detach` with the full tested SHA above. Commands were run
from that checkout; the Windows interpreter came from the repository's existing
`.venv`. Temporary and pytest cache paths were kept outside the checkout:

```powershell
C:/Users/patri/Documents/Projects/drx-2.0/.venv/Scripts/python.exe -m pytest -q -ra --basetemp=C:/Users/patri/Documents/Projects/drx-2.0/.closeout.tmp/final-win -o cache_dir=C:/Users/patri/Documents/Projects/drx-2.0/.closeout.tmp/final-cache --tb=short

$env:PYTEST_ADDOPTS = '--basetemp=C:/Users/patri/Documents/Projects/drx-2.0/.closeout.tmp/final-runner -o cache_dir=C:/Users/patri/Documents/Projects/drx-2.0/.closeout.tmp/runner-cache'
C:/Users/patri/Documents/Projects/drx-2.0/.venv/Scripts/python.exe scripts/validate_fixes.py
```

The behavioral-runner environment override was scoped to its shell process.
Inside WSL, from the same checkout:

```bash
python3 -m pytest -q -ra --basetemp=/tmp/drx-closeout-final -o cache_dir=/tmp/drx-closeout-final-cache --tb=short
bash -n rpi/sync_pis.sh
bash main/motor/run_native_tests.sh
pio run --project-dir main/motor -e mega
sha256sum main/motor/.pio/build/mega/firmware.hex
```

## Verified firmware cleanup

Only these eight unused declarations in `processCommand()` were removed:
`speedFactor`, `weight`, `calibration`, `limit`, `movement`, `positionA`,
`positionB`, and `positionC`. Identically named variables used elsewhere remain.

Native tests and Mega builds passed before deletion, after deletion, and from
the final clean commit. All three flash images have the identical SHA-256:

```text
80e96b14f7ac2d051f05cff0761142b8d44a132a2d4e3749dbbd5083cc034c6a
```

The build used Atmel AVR 5.3.0, Arduino AVR framework 5.4.0, AVR GCC 7.3.0,
HX711 0.7.5, and elapsedMillis 1.0.6. The fresh checkout's registry dependency
resolution stalled; the successful build reused the exact already-installed
HX711 and elapsedMillis dependencies from the verified baseline, then compiled
the checkout's sources. No dependency declaration or version changed.

The eight unused-local warnings disappeared. The pre-existing signed/unsigned
comparison warning remains at `main/motor/motor.ino:1519`. No firmware version
bump was needed for an identical flash image, and no device was flashed.

## Remaining boundary

Local closeout is complete. F9 candidate deletion remains deferred pending
external-consumer evidence if the owner chooses to revisit it. Device deployment,
hardware workflows, and firmware flashing were outside this local batch and are
not established by these test results.
