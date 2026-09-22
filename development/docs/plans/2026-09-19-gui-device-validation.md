# GUI device and operator validation worksheet

Companion to the [UX/UI plan](2026-09-19-gui-ux-ui-improvement-plan.md) and
[implementation evidence](2026-09-19-gui-implementation-status.md).
The physical/human checks below remain a follow-up worksheet. On 2026-09-21 the user
directed use of the simulated app and hardware for the current acceptance sessions.
Simulator observations are recorded separately; desktop screenshots and simulated serial
tests do not establish physical performance or human operator usability.
The [simulator acceptance report](2026-09-21-gui-simulator-validation.md) contains the
completed substituted sessions and their evidence. All Pending entries below refer to
future physical-device or human-participant work.

## Test environment

Record the software revision, firmware revision, device/profile, calibration revision,
Pi/OS/Qt versions, physical display size, resolution, scaling, touch driver, orientation,
glove use, lighting, viewing distance, operator experience, and test date.
Use synthetic patient records for these checks. Store local screenshots, recordings and
completed worksheets under `.cache/gui-device-validation/`; keep participant identities
out of Git.

Start with an unloaded bench device and a technician present. Follow the existing device
procedures for movement, emergency stop and recovery. Do not invent loaded test maneuvers
from this worksheet. No physical verification has been performed by the coding agent.

## Bench checks

| Task | Observe and record | Result |
|---|---|---|
| Render at 1366 × 768 and 1360 × 768 | Top bar, longest clinician/patient names, all four protocols, every dialog; no clipped controls or obscured Stop | Pending |
| Touch positioning controls | Accurate taps at center and edges of each jog, Go, Stop and stepper; adjacent controls do not activate | Pending |
| Touch the full slider height | Tap/drag above and below the visible track; target changes without movement until Go; motor-speed drag commits on release | Pending |
| Confirm direction legend | Verify forward/reverse and fast/normal meanings for axial, lateral, horizontal and leg axes; record physical directions before refining labels | Pending |
| Separate targets and readings | Edit a target while telemetry arrives, then issue a permitted command; observed measurement never jumps solely because of the edit | Pending |
| Pressure validity | Missing, unavailable, zero-required, stale and disconnected states show a dash/reason; fresh valid readings return without changing targets | Pending |
| Setup leg length | Jog and return work as previously specified; estimate remains labeled open loop, with no claimed sensor position | Pending |
| Login destination | Choose Setup while logged out, log in, and arrive in Setup; Treatment login opens explicit patient selection | Pending |
| Start review | Each protocol shows applicable angles, patient/link status, pressure, duration, pulse and motor speeds; Back/close cancels | Pending |
| Active treatment | Protocol identity, measured pressure, selected limit, phase and time remain readable; permitted edits require Adjust treatment | Pending |
| Pause/resume | Verify existing motion/load behavior and countdown handling; UI does not imply pressure release; Stop remains available | Pending |
| Stop routes | Verify screen Stop + Reset, row Stop axes, Stop leg, pressure-notice Stop, banner stop and physical stop against the action contract | Pending |
| Stop timing | Record touch-to-command/GPIO and observed motion response using the device's existing acceptance requirements; do not infer it from a screenshot | Pending |
| Recovery | Stop remains available while releasing/homing; Ready appears only after controller readiness; physical-stop recovery remains inhibited as specified | Pending |
| Connection loss | Follow the existing controlled test procedure; confirm offline/readout presentation and actual stop/watchdog behavior | Pending |
| Completion and next patient | Completed/stopped/fault outcomes remain distinct; upload result is separate; next-treatment entry waits for readiness and clears the prior patient link | Pending |
| Help, Support and service | Scroll long answers, inspect selected issue and delivery result, verify service PIN gate; inspect all technician controls with actual touch equipment | Pending |
| Overlay behavior | Video/login/add-PIN cannot obscure an active treatment; pressure notice retains its direct Stop and dismiss behavior | Pending |

Record a failure with its exact trigger, expected and observed behavior, device state,
reproduction steps and supporting evidence. Correct and retest each critical interaction
problem before accepting the affected task.

## Formative operator sessions

Recruit 5–8 representative operators spanning familiarity levels, plus a technician for
service tasks. Use the same tasks and environment for baseline and revised interfaces;
counterbalance order when feasible. Observe unassisted work first, record any assistance,
then ask what the operator understood. Use simulated or approved unloaded workflows;
clinical treatment is outside this formative comparison.

1. Log in to Setup and explain the device status.
2. Select a target and identify the measured value and units.
3. Link, change and cancel a patient selection; explain an unlinked treatment.
4. Prepare each protocol, identify the applicable angle fields, and cancel/confirm review.
5. Identify phase, pressure and selected limit in a timed glance task.
6. Adjust a permitted setting, pause/resume and locate Stop during each lifecycle stage.
7. Explain a stale reading, offline controller and fault outcome without assuming zero load.
8. Complete a session, interpret a failed upload and prepare the next patient explicitly.
9. Find troubleshooting and service tools, distinguishing reading help from sending a request.

For each task record participant code, experience band, success, elapsed time, assistance,
mis-taps, critical errors, interpretation of status/action consequences, and comments.

| Metric | Proposed target from plan | Observed baseline | Observed revised |
|---|---|---|---|
| Phase/pressure/limit identification | Within 3 seconds | Pending | Pending |
| Routine preparation completion | At least 90% unassisted | Pending | Pending |
| Median preparation time | Approximately 20% lower without dropping checks | Pending | Pending |
| Target/measurement and stop/reset confusion | No observed confusion; investigate each error | Pending | Pending |
| Critical controls | Visible, reachable, correct routing in every tested state | Pending | Pending |

These are formative targets, not a certification or a medical-device validation claim.
The final evidence record must name the reviewer, remaining problems, follow-up changes,
retest results and disposition of each pending check.
