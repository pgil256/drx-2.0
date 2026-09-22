# GUI implementation evidence

Tracks the full scope of [the UX/UI plan](2026-09-19-gui-ux-ui-improvement-plan.md).
The implementation is complete under the user's 2026-09-21 instruction to use the simulated
app and hardware for acceptance sessions. Eight sessions passed, with 250 checkpoints and
deterministic replay. Physical-device/human studies are deferred follow-up work, not claimed
as completed. See the [simulator acceptance report](2026-09-21-gui-simulator-validation.md).

**Action contract, inspected 2026-09-19**

| Action | Existing path and consequence | Presentation requirement |
|---|---|---|
| Setup/Treatment emergency action | `_on_estop` → `stop_from_view` → `emergency_stop_clicked`: asserts GPIO, cancels worker, sends Stop, then timed release/recovery unless recovery is inhibited. | Immediate activation; label Stop & reset, explain automatic recovery movement. |
| Banner emergency action | `panel_stop_requested` → same emergency chain, records fault outcome. | Preserve immediate routing and outcome. |
| Setup row Stop | `_on_setup_stop` → firmware X for axial/horizontal/lateral/pressure; firmware stops all axes. Leg length stops its GPIO movement separately. | Label scope accurately; keep outside movement lock group. |
| Pressure-notice Stop | `stop_without_recovery`, cancels reset and motion, enters fault state. | Do not imply automatic reset; keep direct Stop. |
| Physical emergency stop | GPIO event handling, inhibits automatic recovery. | Do not add an automatic resume/reset path. |
| Pause/resume | Worker pause/resume and session/countdown bookkeeping. | Keep measured values and Stop accessible; do not claim load is released. |
| Reset | Connection manager launches ResetWorker, moves/homes axes and restores readiness on success. | Describe movement and progress; never infer success from elapsed time. |

**Delivery and evidence checklist**

- [x] Inspect current source, baseline gallery, and action/state paths.
- [x] Record simulator environment and both display resolutions; physical conditions deferred.
- [x] Shared contrast, touch geometry, numeric entry, focus and read-only states.
- [x] Separate target/command/measurement data; validity and stale presentation.
- [x] Treatment preparation/active layouts and protocol-specific settings.
- [x] Readiness and independent device, lifecycle, measurement, upload state.
- [x] Themed start confirmation preserving preflight and cancellation checks.
- [x] Outcome summary and explicit next-patient flow.
- [x] Setup direction legend, service placement, accurate reset/default actions.
- [x] Home actions, login destination, guarded navigation and overlays.
- [x] Help/Support copy, selected issue, send progress/results, long content.
- [x] Coherent gallery states at 1366 × 768 and 1360 × 768, including alerts/modals.
- [x] Focused Qt and controller regression tests, applicable Linux integrations.
- [x] Simulated app/hardware control sessions, substituted by user instruction on 2026-09-21.
- [x] Eight scripted operator/service scenarios; human recruitment and metrics deferred.
- [x] Requirement-by-requirement software audit with evidence and remaining gates below.

Physical observation and human usability remain separate from simulator acceptance. The
original physical/human worksheet stays pending for that later work.

**Implemented behavior and evidence**

| Requirement | Implementation and check |
|---|---|
| Readable shared controls | Darker action colors, explicit focus/pressed states, readable locked values, 48/56/72 px control sizing. Cards use flat divider edges: nested Qt shadow effects caused missing chrome in repeated renders. Contrast assertions cover primary actions/control edges. |
| Effective slider hit areas | The full 48 px slider row accepts touch. Plus/minus controls permit exact steps. A drag with tracking disabled emits its edit on release, verified for motor speeds. |
| Independent targets and feedback | Setup commands use `set_position`; sensor data uses `set_measured_position`. Tests exercise real `KneeSpa.status_emit` against a real shell and ensure pending targets survive telemetry. Leg position remains explicitly estimated/open loop. |
| Validity and calibration | Display-only interpolation rejects invalid/nonmonotonic/out-of-range tables. Missing/invalid/stale pressure is a neutral dash. The existing 2.5 s diagnostic freshness duration also ages cached status readings, even when diagnostic packets continue. No stop threshold changed. |
| Treatment preparation and monitoring | Compact patient/record strip, relevant angle fields with saved inactive values retained, larger measured pressure/time/selected limit, collapsed protocol choices during a run, explicit permitted-edit entry. |
| Device and lifecycle state | A read-only presentation adapter combines existing connection, initialization, calibration, reset, physical stop and protocol state. Offline status takes precedence over an unverified recovery claim; record upload remains separate. |
| Review before motion | Themed review names the protocol, patient/link state and applicable parameters. Explicit Start/Back replaces Yes/No. Existing preflight, nested-event cancellation and post-dialog rechecks retain regression coverage. |
| Outcome and next treatment | Session outcome/active time persists independently of readiness and upload result. The next-treatment action disables immediately during busy/recovery state and opens a fresh patient choice when ready. |
| Setup | Five full-width rows separate jog, selected target, command, measurement and Stop. Pressure arrows edit only. Row stops state their all-axis scope; leg Go is omitted with an explanation. Existing service PIN and motion/recovery paths remain in place. Physical direction wording still requires bench confirmation. |
| Navigation and identity | Treatment navigation label, useful Home actions, remembered login destination, entry guards for nonessential overlays, and closing already-open overlays when active treatment takes control. |
| Help and Support | Scrolling reference/troubleshooting, runtime-derived limits, accurate stop/pause/measurement copy, visible selected issue, persistent sending/sent/failed feedback and duplicate-send guard. SMTP tests use mocks; no support request was sent during this work. |
| Pressure advisory | Plain operator explanation and expandable raw details; Dismiss and immediate Stop retain their existing distinct effects. |

**Verification completed on 2026-09-19**

- Windows full suite: **1,363 passed, 110 skipped**. Platform/PTY cases skip on Windows.
  JUnit evidence: `.cache/ux-ui-implementation/windows-results.xml`.
- WSL Ubuntu integration suite: **231 passed, 1,242 deselected**. This includes simulated
  serial/PTY communication. JUnit: `.cache/ux-ui-implementation/linux-results.xml`.
- After the final flat-card/read-only rendering changes: **79 GUI/screen checks passed**.
  Defaults-feedback follow-up: **79 controller-wiring checks passed**.
  Compact unavailable-reading labels: **31 UX checks passed**, including ancestor clipping
  checks at both resolutions and full-height slider touch/release behavior.
- Follow-up acceptance audit: **102 checks passed** across UX, screen, component and token
  suites. Coverage now includes long patient/record text and stable Stop position/activation
  through ready, starting, running, paused, stopping, resetting, fault and completed states
  at both resolutions. Help/Support register touch gestures and accept simulated drag input
  without sending a request. Badge/action/hover/pressed/disabled text contrast is checked.
  This audit corrected low-contrast disabled text and small control indicators, added swipe
  scrolling, and replaced keypad opacity with a readable disabled style.
- The expanded UX suite also passed under WSL Ubuntu: **45 passed**. Evidence:
  `.cache/ux-ui-implementation/linux-ux-audit.xml`. Both resolution galleries were regenerated
  and the pending-patient screen was visually checked after the disabled-keypad change.
- `git diff --check` passed for the changed implementation/tests. Existing unrelated
  workspace changes were preserved. No production device was synced or moved.
- Final gallery: 24 states at each resolution, including login, patient lookup, start review,
  ready/running/starting/paused/stopping/recovery/fault, completion/upload failure,
  missing/stale readings, pressure notice, technician PIN/service and expanded Support.
  Open `.cache/ux-ui-implementation/index.html` or its `1366/` and `1360/` image folders.
  Gallery logs and images stay under `.cache/`.

Reproduction commands from the repository root:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.cache/gui-verification
.\.venv\Scripts\python.exe development/tools/screen_gallery.py --outdir .cache/gui-1366 --width 1366
.\.venv\Scripts\python.exe development/tools/screen_gallery.py --outdir .cache/gui-1360 --width 1360
```

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q -m integration --basetemp=.cache/gui-linux
```

**Simulator acceptance completed on 2026-09-21**

Eight real-GUI/local-hardware sessions passed, including all four full-duration protocols,
patient/review/outbox/support/service flows, live edits, distinct stop routes and faults/restart.
All 27,896 recorded model snapshots replayed deterministically. Final Windows suite:
**1,432 passed, 110 skipped**; focused regressions: **271 passed**. Corrected stale recovery
badges, premature Running state before worker preparation, and preparation progress labeling.
The report above records source fingerprints, scope, failures corrected, and reproduction.

**Deferred physical and human follow-up**

Use the [device and operator worksheet](2026-09-19-gui-device-validation.md) to record actual
display/scaling/touch conditions, jog directions, physical stop/recovery behavior, technician
ergonomics and 5–8 representative-operator sessions. Check secondary text at working distance
and with real gloves/lighting. Software pixel dimensions do not establish physical hit size.
No physical bench results, operator task times or usability success rates have been inferred
from the automated tests. On 2026-09-21, the user confirmed that neither a Pi on an unloaded
bench with someone present nor completed bench/operator results is currently available.
The user subsequently directed simulation for the current acceptance. Physical-device
validation and representative-operator sessions remain pending as separate follow-up work.
