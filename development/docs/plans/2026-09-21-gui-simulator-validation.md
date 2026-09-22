# GUI simulator acceptance results

Date: 2026-09-21. Result: **passed for the user-authorized simulator scope**.

The user directed use of the simulated app and hardware in place of the unavailable
physical-device/operator sessions. Eight scripted sessions used the real PyQt GUI,
authentication, controllers, treatment workers, serial queue/parser, local outbox, and
the workspace's Python controller emulator and synthetic mechanism. They produced
**250 passed checkpoints, 89 screenshots, and 27,896 deterministically replayed snapshots**.
These are automated scenarios, not eight people or a human usability study.

The full Windows test suite passed: **1,432 passed, 110 skipped**. The focused GUI,
controller, session and simulator regression suite passed **271 tests**. The skips are
the suite's platform/hardware cases, not successful physical-device checks. Earlier WSL
integration results remain documented in the implementation evidence.

## Recorded sessions

Artifacts are under `.cache/simulator/<session>/`. Each directory contains its actual
`verification.json`, command/state recording, screenshots, and isolated synthetic device
profile. Session manifests contain a local token and should remain local. The sanitized
summary and screenshot index are in `.cache/gui-simulator-validation/summary.json` and
`.cache/gui-simulator-validation/index.html`.

| Scenario | Session | Checkpoints | Observed result |
|---|---|---:|---|
| Axial protocol | `20260921-143503-8124` | 18 | Five-minute worker run reaches load/pulse, completes, releases and rezeros. |
| Left protocol | `20260921-143503-4008` | 18 | Negative lateral pose under load, complete five-minute run and recovery. |
| Right protocol | `20260921-143503-612` | 18 | Positive lateral pose under load, complete five-minute run and recovery. |
| Oscillating protocol | `20260921-143504-30400` | 20 | Both lateral directions observed, complete five-minute run and recovery. |
| Operator and service workflow | `20260921-143923-8216` | 58 | Patient/error/change/cancel, four review dialogs, stopped outcome, upload failure/retry, next patient, Help/Support and service access. |
| Distinct Stop routes | `20260921-143840-32580` | 33 | Stop during preparation/reset, advisory Dismiss/Stop, banner Stop and leg Stop. |
| Live adjustments | `20260921-143840-20860` | 23 | Pause/resume, applied pressure/angle changes, pulse-off and screen Stop/recovery. |
| Faults and restart | `20260921-143840-19440` | 62 | Identity/tare failures, jam/frozen feedback, pressure faults, simulated physical stop, disconnect and explicit restart. |

All eight processes exited successfully, and the replay checker compared every recorded
core snapshot against the original seeded command/GPIO/fault inputs. The durations and
worker algorithms were not shortened or replaced. Support requests and treatment uploads
were captured by the local adapter; no external delivery was used.

## Findings corrected during the sessions

1. **Recovery badge persisted after readiness.** The top bar could say Ready while the
   treatment badge still said Stopping / recovering. Ready now restores Not started or the
   completed/stopped outcome, without erasing the session summary.
2. **Dispatch was presented as preparation completion.** The start handler immediately
   promoted a dispatched worker to Running. It now waits for the existing `prepared` signal;
   preparation controls remain locked and the treatment clock still starts from that signal.
3. **Preparation text was classified as pressure ramping.** The progress message containing
   "zeroing resting pressure" matched the generic pressure rule. Preparation now has explicit
   precedence, so the badge and readiness explanation agree while centering/zeroing.

Unit/Qt regressions cover these transitions. The final UX and Stop sessions show their
actual runtime behavior. No firmware, pressure threshold, motion algorithm, or recovery
sequence was changed in this acceptance pass.

Source fingerprints are preserved per session. The four full-duration runs used application
hash `849f8b50ce64ea2f34abf461104ae29cf8e413db311cd702cb606117e7e7519c`, which includes the
first two fixes. The final preparation-word classification was then checked by the other
four sessions and the final full suite at application hash
`0da996aed3cdd641ef23fbaefa9d2f58848748ce0ccf1c15a415eb12a74ce539`. The last change only maps
the displayed progress label; it does not alter worker duration, commands or completion.

Exploratory failed runs are retained locally. They identified the state issues above and
test-driver issues (checking a deleted Qt dialog, tapping before controls reenabled, and
using an idle pressure bias below the warning threshold). Those attempts are not counted
among the eight accepted sessions.

## Acceptance coverage and limits

| Planned area | Evidence and disposition |
|---|---|
| Login/destination and identities | Demo operator returns to Setup. Unknown patient is rejected; link/change/cancel/relink and explicit next-patient choice run through actual PIN controls and local lookup. |
| Targets versus measurements | Editing pressure does not move the model or replace measured pressure while telemetry continues. Separate regression cases cover pending targets surviving real status bindings. |
| Preparation and protocol-specific fields | Both settings tabs, all protocols, applicable angles and explicit Back/Start are exercised. Cancelling each review leaves the controller idle. |
| Readiness and lifecycle | Preparation, running, paused, stopping, reset, fault, completion and next-treatment availability have runtime and regression evidence. Outcome survives failed upload. |
| Critical control access | Both 1360 × 768 and 1366 × 768 captures; control bounds and hit sizes checked. Stop is reachable through the window's hit-test during preparation, run, pause and reset, including its click-through spinner. |
| Stop distinctions | Screen/banner stops recover; advisory Stop halts without automatic homing; advisory Dismiss preserves the loaded hold; leg Stop clears GPIO direction outputs. Simulated physical stop releases and requires explicit reset. |
| Fault/measurement handling | Jam differs from frozen feedback in model versus sensor state. Stale/biased pressure and offline controller produce real fault/advisory paths. Reconnection uses the application's explicit Restart action. |
| Upload and Support | Real outbox retains the failed record and respects retry backoff. Support shows selected issue and failed/sent feedback through the local capture boundary. Reading troubleshooting remains a separate action. |
| Service | Routine operator cannot provision service access. Administrator enrolls the separate PIN; all nine service pages retain Stop and Close. No calibration values or bench inspection outcomes are fabricated. |
| Contrast, touch geometry and long content | Existing pixel/contrast and clipping tests, the final 271-test regression run, and actual-window screenshots support software acceptance. Physical hit size and glove use are deferred. |
| Human performance targets | Three-second glance identification, 90% unassisted completion and 20% preparation-time improvement are unmeasured. No synthetic user scores or human timings are reported. |
| Physical device properties | Force accuracy, wiring/polarity, mechanical clearances, real stop latency, Pi rendering and working-distance legibility remain deferred to the physical worksheet. |

The pressure-progress advisory is an explicit serial **wire fixture**: its fixed travel/rise
values are not derived from the synthetic mechanism. It exercises the real parser, advisory
dialog and stop path. The synthetic model itself is not a measured device or native AVR
firmware execution.

The local recorder observed 4.9–18.5 ms from scripted Stop activation to receipt of serial
`X` for the five instrumented Stop actions. GPIO observations arrived through a separate
asynchronous bridge (26.0–103.3 ms). These are desktop simulator observations, not physical
response limits or proof of GPIO/serial ordering on a device.

## Reproduce

Use the native Windows Qt platform; the simulator documentation notes dialog problems
with the offscreen plugin. Every run creates a separate local session/profile.

```powershell
$env:QT_QPA_PLATFORM='windows'
.\.venv\Scripts\python.exe development/tools/run_simulator.py --no-browser --verify ux
.\.venv\Scripts\python.exe development/tools/run_simulator.py --no-browser --verify ux-stops
.\.venv\Scripts\python.exe development/tools/run_simulator.py --no-browser --verify live
.\.venv\Scripts\python.exe development/tools/run_simulator.py --no-browser --verify faults
.\.venv\Scripts\python.exe development/tools/run_simulator.py --no-browser --verify protocols
```

`--verify protocol-1` through `protocol-4` select individual full-duration runs; isolated
sessions can run concurrently. Use `development/tools/check_simulator_replay.py` with each
session's `session.jsonl`. JUnit evidence for this pass is `.cache/gui-simulator-full.xml`
and `.cache/gui-simulator-final-regression.xml`.

The [physical/operator worksheet](2026-09-19-gui-device-validation.md) remains available
for later real-device and human validation. It is explicitly outside the substituted
simulator acceptance requested for this implementation.
