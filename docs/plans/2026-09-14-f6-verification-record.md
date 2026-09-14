# F6 SMTP consolidation

Implemented: 2026-09-14
Scope: F6 and Phase 4's SMTP task in
[the incremental refactoring plan](2026-09-12-incremental-refactoring-plan.md)
Starting HEAD: `7aa99974ff9321d738dfdcf4645a9c830450808a`, with the existing
F1–F5 working-tree implementation preserved.

## Result

`KneeSpa.email_admin` and `KneeSpa.submit_ticket` retain their own recipients,
subjects, bodies, identity handling, and user feedback. The new private window
method `_send_support_email` owns the shared credential reads, MIME headers,
SMTP-over-SSL context, login/send, diagnostics, and daemon-thread dispatch.
There is no new service layer or dependency.

The helper captures credentials and constructs the message before dispatch,
then performs credential validation and SMTP work inside the worker. The
15-second connection timeout, success messages, failure prefixes, and logger
calls are unchanged. Ticket submission still immediately displays
`Support ticket is being sent.` after starting the worker; completion/failure
does not produce a new UI acknowledgement. Assistance retains its body print
and existing console/log feedback.

## Offline contract coverage

`tests/unit/test_support_email.py` adds 24 cases using an explicit window facade,
fake credentials and `.test` addresses, mocked SMTP, and a deferred thread
target. It runs the actual public methods and shared helper without a hardware
window, real network connection, or background thread.

The cases verify:

- Separate envelope recipients, From/To/Subject headers, plain-text MIME bodies,
  Unicode/newlines, and exact success diagnostics for both workflows.
- One started daemon worker, no SMTP before its target runs, SSL host/port and
  15-second timeout, login before sendmail, and context-manager cleanup.
- Queued messages retaining their original content, destination, and credentials
  after operator/configuration changes.
- Missing sender, password, or workflow-specific recipient failing inside the
  worker without opening a connection, with the existing error log and print.
- Connection, context-entry, authentication, sending, and context-exit failures
  being caught and logged with each workflow's existing diagnostic.
- Immediate ticket acknowledgement before worker execution, unchanged by SMTP
  success/failure, and no added assistance UI acknowledgement.
- Device-id failure falling back to `unknown`, and absent/partial current-user
  records retaining the existing ticket identity defaults.

The old controller-wiring case started an actual daemon thread and assumed the
operator's environment had no SMTP credentials. Its missing-credential coverage
now lives in the offline contract suite. Three deterministic wiring cases cover
selected issue text and the general-support fallback instead.

## Verification

| Check | Result |
| --- | --- |
| New SMTP contracts and controller wiring before extraction | 103 passed in 1.67 s. |
| Same combined selection after extraction | 103 passed in 1.66 s. |
| SMTP contracts alone | 24 passed in 0.23 s. |
| Controller wiring alone | 79 passed in 1.82 s. |
| Full Windows suite | 924 passed, 39 expected POSIX skips, no warnings, in 36.13 s. |
| Full WSL/Linux suite | 963 passed, no skips or warnings, in 66.88 s. |
| Source/diff review | Changed Python parses; no added Python lines over 100 characters; `git diff --check` passes. |

The pre-extraction tests exercised the duplicated implementation. Extraction
required only binding the new real helper on the explicit test facade; the
contract assertions were unchanged. The final production diff was reviewed
against a copy of the working file taken at the start of F6, preserving prior
refactoring changes. Only the support-email block in `main/kneespa.py` changed.
The other F6 paths are the new SMTP tests, the controller-wiring test changes,
this record, and the plan's F6 status update.

Commands from the repository root:

```powershell
# Before extraction: use .f6-before-tmp; after extraction:
.venv/Scripts/python.exe -m pytest -q tests/unit/test_support_email.py tests/unit/test_controller_wiring.py --basetemp=.f6-after-tmp -o cache_dir=.f6-pytest-cache --tb=short

.venv/Scripts/python.exe -m pytest -q tests/unit/test_support_email.py --basetemp=.f6-smtp-alone-tmp -o cache_dir=.f6-pytest-cache --tb=short
.venv/Scripts/python.exe -m pytest -q tests/unit/test_controller_wiring.py --basetemp=.f6-wiring-alone-tmp -o cache_dir=.f6-pytest-cache --tb=short

.venv/Scripts/python.exe -m pytest -q -ra --basetemp=.f6-full-windows-tmp -o cache_dir=.f6-pytest-cache --tb=short
wsl --exec python3 -m pytest -q -ra --basetemp=/tmp/drx-f6-full-linux -o cache_dir=/tmp/drx-f6-linux-cache --tb=short

git diff --check
```

The initial WSL launch could not access the WSL service from the Windows
sandbox. The same command passed with the required execution permission.

F6 is complete in the working tree. No real emails, commits, deployments,
firmware flashes, or physical-device checks were performed. Phase 0 and B2
remain separate prerequisites for landing/deployment work; calibration
persistence remains F7.
