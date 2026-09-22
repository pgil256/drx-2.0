# KneeSpa GUI UX/UI improvement plan

Date: 2026-09-19. Status: implemented and accepted within the updated simulator scope.

**Validation scope update, 2026-09-21**

The user directed: "Use the simulated app + hardware for those sessions."
For this implementation, run the real GUI/controllers against the local hardware simulator
and use recorded, scripted operator workflows as the acceptance sessions. Physical-device
checks and recruitment of 5–8 human participants are deferred follow-up work, rather than
blockers for this simulator acceptance. Preserve the original physical/human targets below
as future validation requirements; do not report simulated sessions as human observations
or infer physical touch, force, stop latency, or usability success rates from them.
The [simulator acceptance report](2026-09-21-gui-simulator-validation.md) records the
eight passed sessions, corrections, regression results and deferred physical/human checks.

Improve the existing PyQt5 interface around three operator questions: **What is the device doing?
What settings will it use? What can I do next?** Keep the established brand, bundled fonts,
reusable widgets, and controller architecture. Prioritize accurate state and readable controls,
then simplify treatment preparation and monitoring.

**Basis and scope**

This plan follows a source review of the current screens, shell, theme, protocol controller,
connection manager, safety presentation, and relevant tests. Nine view-only screenshots were
generated with `development/tools/screen_gallery.py` at 1366 × 768; Treatment, active Treatment,
Setup, and Support were visually inspected. Temporary review images are in
`.cache/ux-ui-review-20260919/`.

The gallery uses synthetic state and does not run the hardware controllers. Its sample countdown,
pressure captions, and default connection indicator are not evidence of live device behavior.
Controller findings below come from code inspection. No physical usability study or on-Pi
verification has been performed for this plan.

Assume the primary user is a clinician operating the landscape device touchscreen. Validate the
actual display size, resolution, scaling, viewing distance, gloves, and lighting in the first
phase. Check both 1366 × 768 and 1360 × 768 because the main window code documents the latter
as a device mode. Smaller screen support requires an explicit product decision.

This is an improvement to the current code-built GUI, which already implements much of the
[June modernization plan](2026-06-25-pyqt5-gui-modernization.md). It is not a second framework
migration. Treatment algorithms, calibration mathematics, motion limits, firmware, and automatic
recovery policy are outside the proposed UI changes. Any behavior change discovered necessary
during design becomes a separately specified engineering change.

**1. Findings that should drive the design**

| Priority | Current evidence | UX improvement |
|---|---|---|
| P0 | Setup's `Live Position` shares storage/display updates with slider edits and commanded positions. Pressure and lateral telemetry also update those controls. | Separate target, commanded, and measured values; clearly label unavailable or estimated measurements. |
| P0 | Treatment says `STOP/RESET`, Setup says `Emergency Stop`, and both use `_on_estop`. The screen stop chain performs emergency-stop handling followed by release/recovery. Pressure-notice Stop uses a different path without automatic homing. | Establish precise action labels and visible stopping/recovery states from the actual controller behavior. |
| P0 | Pressure colors use local 50/70 lb thresholds; countdown colors turn amber/red near ordinary completion. Missing pressure initially uses a success-colored readout. | Make neutral, selected, advisory, fault, and completion meanings consistent. Use authoritative state for alarm styling. |
| P0 | Rendered Setup Go is 55 × 41 px; jog is 46 × 46 px; the slider widget is 167 × 24 px. White text on the current green is 2.27:1. | Increase effective hit areas and improve text/control contrast before expanding the layout. |
| P1 | Treatment assigns a full-height column to patient linking and upload retry, including during a run. | Compact patient identity and record status; give measured pressure, phase, and time greater prominence. |
| P1 | All treatment settings remain visually present; duration and motor speeds lock during a run while pressure, angles, and pulse can change. | Explain pre-run versus live settings, show only protocol-relevant inputs, and preserve access to permitted adjustments. |
| P1 | Start already has a parameter confirmation, but uses a native Yes/No dialog and numeric protocol label. | Restyle the existing confirmation with the protocol name, patient, applicable settings, and explicit actions. |
| P1 | Navigation is guarded during active treatment, but Video opens through a separate launcher. Login routes to Treatment even when the operator originally selected Setup. | Apply consistent navigation/overlay rules and remember the intended destination through login. |
| P2 | Home is mostly a logo and a text instruction. Support separates troubleshooting and contact, but the selected issue context is invisible. | Give Home useful next actions and Support an explicit issue summary with actionable delivery feedback. |

P0 means foundational clarity and interaction work; it does not classify every item as a
confirmed device defect. P1 improves routine workflow. P2 improves secondary tasks.

**2. Proposed treatment workflow**

Use one Treatment page with stable locations for status and controls. The page changes emphasis
between preparation and an active run; it should not send the user through an extra wizard.

Preparation sequence: clinician login → link a patient or explicitly continue unlinked → select
protocol → review applicable settings → existing start confirmation → treatment.

Rename the navigation label `Protocols` to `Treatment` while retaining the internal page key.
Keep the recognizable numbered protocol choices with descriptive names. Make patient identity a
compact, persistent strip. Use `Patient linked` or `No patient linked`; when unlinked, state that
this treatment will not upload, matching the current start confirmation. Keep record upload
status separate from device connectivity and treatment readiness.

Candidate preparation layout:

```text
Brand       Device: Ready / Connecting / Recovery needed        Clinician
Navigation | Patient identity · Change patient       Record status
           | Protocol: [1 Axial] [2 Left] [3 Right] [4 Oscillate]
           | Settings                           | Device measurements
           | Duration · pressure · pulse        | Pressure + validity
           | Relevant angle controls            | Lateral angle
           | Motor speed settings               | Readiness / next step
           | [Review & start]       [Pause]      [Stop / recovery action]
```

The stop label in this sketch is provisional until the action map below is complete. Retain its
existing direct activation behavior throughout implementation.

While running, prioritize the phase, measured pressure, applicable target/limit, time remaining,
and lateral angle. Compress the protocol picker to a readable selected-protocol summary, and
retain a dedicated settings area with an explicit `Adjust treatment` entry. Do not put permitted
live adjustments behind a full-screen modal or allow them to cover Stop. Explain when a change
is requested, pending, or applied if the controller exposes those distinctions; do not report
an applied value merely because the user tapped a control.

Keep patient and protocol information readable when editing is disabled. Do not fade an entire
read-only summary to low opacity. For protocol-specific fields, verify actual worker usage
before omitting a field; preserve saved values and never silently zero an inactive angle.

Candidate active layout:

```text
Brand       Device status                                      Clinician
Navigation | Patient identity · Selected protocol              Record status
           | Treatment phase                    | Treatment settings
           | MEASURED PRESSURE   TARGET / LIMIT | Applicable values
           | TIME REMAINING      LATERAL ANGLE  | Adjust treatment
           | Progress / recovery explanation    | Read-only duration/speeds
           | Persistent actionable notice, only when needed
           | [Start / Resume]       [Pause]     [Stop / recovery action]
```

For both layouts, keep the bottom controls in the same locations. Show a concise reason near
an unavailable action: `Looking up patient`, `Preparing device`, or `Recovery required`.
Derive readiness from the controller; an idle phase alone must not imply readiness.

Replace the existing start dialog with a themed confirmation containing protocol name,
patient/link status, duration, applicable angles, pressure limit, pulse rate, and motor speeds.
Use `Back to settings` and `Start treatment`; preserve the current preflight checks, cancellation
behavior, and rechecks after the dialog closes. Avoid adding a second confirmation.

Completion should distinguish completed, operator-stopped, and fault outcomes. Show a compact
summary and record upload status. Offer `Prepare next treatment` only when the controller is
ready; ensure the next patient is an explicit choice. Never equate timer zero with recovery
complete or label a patient ready for removal from a timer alone.

**3. Stop, state, and measurement contract**

Before changing labels, map each action from touch → controller → commands/GPIO → recovery →
visible result. Include screen Stop, per-axis Stop, banner emergency stop, pressure-notice Stop,
physical emergency stop, pause/resume, and reset. These paths currently have different behavior.

Do not turn `STOP/RESET` into separate Stop and Reset actions by changing only the widgets.
That would change the meaning of the existing recovery sequence. For the first implementation,
retain the sequence and explain its stages. Any split requires a separate behavior specification.
All urgent stop actions remain immediate, with no confirmation or press-and-hold requirement.

| Presentation state | Required information and interaction |
|---|---|
| Connecting / preparing | Name the current activity; explain why Start is unavailable. |
| Ready | Show selected treatment and a valid readiness result; allow review/start. |
| Starting | Show preparation progress from real events; prevent duplicate starts. |
| Running | Show phase, measured pressure, time, and applicable target/limit; allow supported controls. |
| Paused | State that the protocol is paused; keep measurements and Stop available. Describe pressure/motion behavior only as verified in the worker and on device. |
| Stopping / releasing / resetting | Show the stage actually reached; retain Stop; do not display Ready prematurely. |
| Advisory | State what happened and the operator action. Dismissal must retain its existing effect and must not imply the cause is resolved. |
| Fault / connection loss | Name the condition and permitted next action. Do not claim a software stop reached disconnected hardware. |
| Completed / stopped | Preserve the outcome independently of readiness and record upload status. |

Treat connection, protocol lifecycle, measurement validity, and record upload as independent
dimensions. A record upload failure must not look like a hardware fault. Use a small presentation
adapter fed by existing controller signals rather than another independent device state machine.

For Setup, implement separate setters/models for selected targets and telemetry. Editing a
target must not alter a measured readout; incoming telemetry must not overwrite an unsubmitted
target. Show `Target`, `Measured`, and, where needed, `Estimated` explicitly. Leg length currently
uses open-loop movement: do not invent a measured position. Keep unit and precision conventions
consistent, and preserve the calibrated degree-to-position mapping.

For stale, invalid, disconnected, or missing measurements, use `—` and a visible reason, or a
clearly marked last reading. Determine freshness thresholds from actual telemetry cadence and
existing diagnostics; this plan does not create a new automatic-stop threshold.

The existing treatment banner is intentionally suppressed during an active protocol; warnings
already use safety dialogs. Consolidate presentation without restoring an always-on competing
banner. Keep notices inside reserved page space where practical. Retain acknowledgment behavior
and ensure any blocking alert provides the appropriate Stop route. Put raw encoder counts and
diagnostic codes in expandable details; operator copy should describe the observed condition.

**4. Setup and supporting screens**

Keep all five Setup rows visible at the device resolution initially. Each row should clearly
separate axis name, direction/jog controls, selected target, measured/estimated position, Go,
and Stop. Use space recovered from the duplicated Live Position card for larger controls.
Put limits near the relevant input, using runtime constants/configuration as the source.

Add persistent direction labels or a compact legend, with exact meanings confirmed on the
hardware. Hover-only tooltips cannot carry essential touch instructions. Explicitly show that
leg length supports jog/reset rather than leaving an unexplained disabled Go button. Distinguish
pressure target editing from physical jog actions. Do not change motion press/release or speed
semantics as a styling shortcut.

Move technician-only hardware tests and calibration into a clearly labeled service entry,
preserving the service PIN requirement. Keep routine recovery accessible where operators need
it. Replace `Mark As Default` with wording that states exactly which settings are saved, and
show a brief confirmation with those values. Describe reset movement accurately rather than
presenting it as a harmless connection refresh.

Home should offer `Prepare treatment`, `Position device`, and device status when logged in,
with login as the primary action when logged out. Preserve the destination after authentication.
Keep Help and Support available outside active-treatment restrictions. Apply the same guard to
Video and all other overlays so a nonessential overlay cannot hide active controls.

Support should allow reading troubleshooting without sending a request, show the selected
issue before submission, and distinguish sending, sent, and failed states. Keep the current
explicit send action. Update Help copy to match implemented pause, stop, reset, and advisory
behavior; remove generic restart advice where controller state does not permit it. Retain
offline reference content and verify long expanded answers fit or scroll.

**5. Visual and interaction specifications**

Keep IBM Plex Sans for labels and IBM Plex Mono for live values. Use a restrained page wash,
white panels, dark text, consistent alignment, and fewer heavy shadows. Retain cyan as a brand
accent. Use filled color chiefly for primary actions and selected controls; reserve warning and
fault styling for those states. Ordinary treatment completion should not turn the timer red.

| Element | Proposed design target |
|---|---|
| Primary run controls | At least 72 px high; stable placement; distinct labels and press feedback. |
| Frequent touch controls | Aim for 56 × 56 px hit areas; minimum 48 × 48 px for other actionable controls. Validate physical size on the device. |
| Neighboring controls | At least 8 px separation where practical, with more separation around destructive actions. |
| Sliders | At least 48 px effective vertical interaction area and an exact-value alternative; distinguish hit area from handle artwork. |
| Text | Start with 18–20 px operator labels, 16 px secondary text, and 40–56 px primary readouts; verify at working distance. |
| States | Label, shape/icon, and color together; visible focus and pressed states; readable disabled explanations. |
| Chrome | Trial a 72 px top bar instead of 96 px; retain labeled navigation. Adopt only if identity/status fit at both target resolutions. |

Use WCAG contrast values as measurable design benchmarks for this native interface: 4.5:1 for
normal text, 3:1 for large text, and 3:1 for required control/state graphics. These benchmarks
do not establish medical-device usability or a native-app compliance claim.
[W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/#contrast-minimum)
[Non-text contrast](https://www.w3.org/TR/WCAG22/#non-text-contrast)

Current token calculations against white: green `#00c800` = 2.27:1, blue `#3498db` = 3.15:1,
cyan `#29abe2` = 2.62:1, red `#c80000` = 6.08:1. Candidate action colors `#15803d` and
`#176b9a` provide 5.02:1 and 5.82:1 respectively. Test all hover, pressed, selected, disabled,
and badge combinations before adopting final tokens. Fix shared tokens and widgets first.

**6. Delivery order and implementation map**

Effort ranges are preliminary hands-on design/development estimates for one engineer with
design input. They exclude user recruitment, hardware availability, and separate behavior work.

| Phase | Deliverable | Main code areas | Exit criterion | Estimate |
|---|---|---|---|---|
| 1. Baseline and contracts | Observe routine use; document action/state/measurement map; capture representative states. | `kneespa.py`, controllers, existing tests/gallery | Every action has an accurate meaning and source; display/user assumptions confirmed. | 1–2 days |
| 2. Shared clarity fixes | Contrast, hit areas, labels, read-only states, measured-versus-target separation. | `ui/theme/`, `ui/widgets/ds/`, `ui/screens/setup.py`, telemetry bindings | Touch geometry and state-dependent readouts verified; no target/measurement crossover. | 3–5 days |
| 3. Treatment redesign | Compact identity, readiness, preparation/run layouts, themed confirmation, outcome summary. | `ui/screens/treatment.py`, `ui/modals/`, protocol presentation bindings | Complete simulated treatment flow with all stop/recovery controls accessible. | 4–6 days |
| 4. Setup and navigation | Clear movement controls, service placement, login return path, overlay guards, Home actions. | `setup.py`, `app_shell.py`, chrome, auth/navigation bindings | Routine positioning/login paths work without ambiguity or hidden controls. | 3–5 days |
| 5. Secondary screens and validation | Help/support copy, delivery feedback, representative-user sessions, on-Pi verification. | Help/Support/Profile, test suite, galleries | Acceptance checks pass and observed critical interaction problems are resolved. | 3–5 days |

Expected scope is approximately 14–23 working days, refined after Phase 1. The first release
should prioritize Phases 1–3; ship state clarity and the core treatment workflow before secondary
visual work. Use small, reviewable changes with simulator evidence for each phase.

**7. Validation and acceptance**

Compare baseline and proposed designs using the same tasks: log in to Setup; link/change/cancel
patient selection; prepare each protocol; identify pressure and target; adjust permitted live
settings; pause/resume; stop during movement and recovery; handle missing telemetry; interpret
connection loss; complete a session; retry a failed record upload; find service tools.

Run an initial formative study with 5–8 representative operators, including both experienced
and less familiar users, plus technician review of service tasks. This is an iteration sample,
not a claim of formal validation. Match lighting, viewing distance, touch equipment, interruptions,
and glove use to actual practice. This follows the focus on users, use environments, and interfaces
in [FDA human factors guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/applying-human-factors-and-usability-engineering-medical-devices).

Proposed release targets, to refine against the baseline:

- Operators can identify phase, measured pressure, and applicable target/limit within 3 seconds
  in a glance task; this is a usability target, not a hardware-response requirement.
- No observed confusion between target and measured values or between stop and reset consequences.
  Investigate every critical task error; do not average it away in a satisfaction score.
- At least 90% unassisted completion for routine preparation tasks; reduce median preparation
  time by approximately 20% without dropping required checks or increasing errors.
- Stop remains visible and actionable during starting, running, paused, stopping, and recovery
  states, and through alert/overlay interactions. Verify correct routing and responsiveness.
- No clipping, overlapping controls, or scrolling required to reach critical treatment actions
  at both 1366 × 768 and 1360 × 768. Check longest labels and expanded notices on the actual Pi.
- Text, control contrast, and hit-area targets pass measurement in all interactive states.
- Controller guards, patient identity handling, live-setting rules, session outcomes, and existing
  stop/recovery behavior retain their regression coverage.

Extend the existing screen gallery with coherent fixtures for ready, starting, running, paused,
stopping, recovery, fault, missing/stale telemetry, patient lookup, long patient names, and upload
failure. Include representative alerts and service/PIN dialogs. Avoid synthetic combinations
that display an unrelated countdown or measurement caption.

Use the existing Qt/screen tests and the focused unit suites for treatment UI, protocol
controller, pause/live settings, safety monitor, connection manager, actuator controls, and
treatment sessions. Run serial/PTY integrations under Linux/WSL as needed; check on-device
rendering and physical touch separately. Offscreen screenshots cannot establish hardware stop
behavior, touch accuracy, or display legibility. Keep generated output under `.cache/`.

**Source map**

- [Treatment screen](../../../runtime/raspberry-pi/main/ui/screens/treatment.py): layout, settings,
  button states, color rules, patient and record status.
- [Setup screen](../../../runtime/raspberry-pi/main/ui/screens/setup.py): target/readout coupling,
  jog controls, recovery/service actions, open-loop leg length.
- [Main window](../../../runtime/raspberry-pi/main/kneespa.py): live telemetry, patient flow,
  safety dialogs, support wiring, and view/controller integration.
- [Protocol controller](../../../runtime/raspberry-pi/main/controllers/protocol_controller.py):
  current start confirmation, lifecycle, navigation, stop, pause, and recovery paths.
- [App shell](../../../runtime/raspberry-pi/main/ui/app_shell.py): login/navigation and overlays.
- [Treatment banner](../../../runtime/raspberry-pi/main/ui/widgets/treatment_status_panel.py):
  intentional active-run suppression and warning/fault presentation.
- [Theme](../../../runtime/raspberry-pi/main/ui/theme/tokens.py),
  [QSS](../../../runtime/raspberry-pi/main/ui/theme/app.qss), and
  [slider](../../../runtime/raspberry-pi/main/ui/widgets/ds/slider.py): contrast, sizing, and states.
- [Screen gallery](../../tools/screen_gallery.py),
  [screen tests](../../tests/integration/test_screens.py), and
  [treatment UI tests](../../tests/unit/test_treatment_ui.py): existing verification foundations.
