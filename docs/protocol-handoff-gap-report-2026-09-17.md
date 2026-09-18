**Protocol handoff gap report — September 17, 2026**

Historical snapshot taken before implementation. The subsequent confirmed decisions, changes, and verification are recorded in [the implementation record](protocol-port-decisions-2026-09-17.md).

The current app does not implement the handoff's complete pressure-baseline and pulse-recovery contract. Most of that work remains relevant, but several prerequisites already exist and several behaviors conflict with deliberate choices in this version. This should be an adapted, coordinated app/firmware change, not a replacement with the older application's files.

This is a review only. No application, firmware, configuration, or test code was changed. The comparison uses the current working tree, including existing uncommitted patient/cloud/UI changes, on top of commit `3a824d9`. The reference is [the supplied handoff](C:/Users/patri/Documents/Projects/drx-demo/PROTOCOL_FIXES_HANDOFF_2026-09-16.md); its implementation/deployment instructions were treated as proposed requirements, not authorization to deploy or change hardware.

| Area | Current status | Recommended treatment |
| --- | --- | --- |
| Reset completion and cancellation | Partly implemented | Keep the worker architecture and calibrated targets; replace shared completion state with validated per-operation replies. |
| Automatic resting-leg baseline | Missing | Add coordinated firmware collection, app authorization, and startup/before/after-treatment integration. |
| Bounded sensor acquisition and validity | Incomplete | Replace blocking acquisition paths and expose measurement validity. |
| Pressure waypoint completion | Incomplete; behavior differs | Require typed completion and reconcile target/timeout semantics. |
| Pulse recovery | Missing | Add feedback-controlled release/recovery while retaining speed controls; resolve cadence and fault-policy differences. |
| Pressure-progress advisory | Missing specific feature | Add its typed notice and a Stop path that does not start homing. |
| Pressure/time presentation | Existing inline replacement | Improve the current readouts and timing rather than reintroduce the old floating windows. |
| Restart App | Missing | Add the Profile action and complete asynchronous cleanup/relaunch support. |

**1. Reset: useful foundations exist, but completion is still too permissive.**

The app already runs reset in a `QRunnable`, distinguishes the startup banner from ordinary `DONE`, sends delimited zero marks, and uses the destination's calibrated horizontal reset position. However, [ResetWorker](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/reset_worker.py:132) continues after waiting 15 seconds without receiving the startup banner. It does not require NB2 firmware identity. In default legacy mode it waits on the window's shared `I2Cstatus_event`; opt-in v2 correlates sequence acknowledgements but still does not verify motion kind, effective target, and actual position. Reset uses `I14` for lateral centering and ends at `L0`, with no separate baseline.

The worker retries the individual command on timeout. It has shutdown/physical-stop checks at selected points, but no dedicated cancellation API or lock shared with sends. [ConnectionManager](C:/Users/patri/Documents/Projects/drx-2.0/main/controllers/connection_manager.py:242) does not retain the reset worker for cancellation, and its error callback clears reset state before the worker's final completion callback. Existing actuator-control guards prevent many generic acknowledgements from unlocking controls during reset; those guards should remain, with cleanup becoming the sole authority for ending reset.

The reconnect path also needs attention: [ensure_arduino_connection](C:/Users/patri/Documents/Projects/drx-2.0/main/controllers/connection_manager.py:121) sends zero marks and calibration after reconnect without the full confirmed positioning/baseline sequence.

Already present in [firmware position handling](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:909): axial target clamping before direction selection, direction chosen from the sign of position error, and an inclusive 25-count arrival band. The reported 103-versus-100 home condition therefore already receives immediate completion in the normal idle case. The immediate-completion branch does not explicitly issue a motor-stop write before replying; that guarantee still deserves a regression check. This firmware applies the 25-count band to ordinary raw moves and lateral moves too, unlike the handoff's exact-crossing raw moves and 100-count lateral band. Do not widen those tolerances incidentally.

**2. Automatic baseline: the main lifecycle is absent.**

[Firmware L0/L1](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:1141) still performs implicit/blocking tare. There is no explicit resting-baseline state machine, eight-second settling window, motion/tare interlock, or baseline-valid permission gate. The handoff's numerical-offset-versus-permission distinction is also absent.

Before treatment, [ProtocolController](C:/Users/patri/Documents/Projects/drx-2.0/main/controllers/protocol_controller.py:295) queues lateral centering but does not wait for its confirmed completion before dispatching the worker and starting the UI clock. The worker starts its own clock before pressure preparation. At successful completion, [Protocols._release](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/protocols.py:988) releases with `P0` and reports success, without confirmed `I120` retraction or final baseline. The controller subsequently calls `worker.stop()`, which sends more stop/release commands; that cleanup must be adapted so it does not issue motion after a newly established final baseline.

The [standalone axial-home button](C:/Users/patri/Documents/Projects/drx-2.0/main/kneespa.py:1321) still schedules `L0` after a fixed five seconds. Under the current firmware that silently tares without verified home completion. Remove that delayed calibration/tare when automatic workflows own zeroing.

Required integration points are reset, reconnect, all four protocol starts, successful completion, and failure/cancellation handling. Fresh tare must follow confirmed idle positioning; failed/cancelled runs must not fall into the successful retract-and-zero path. Keep the resting leg supported as specified in the handoff, without adding manual-zero dialogs.

**3. Serial and sensor validation: retain the newer transport, extend its contract.**

The current [Arduino transport](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/arduino.py:543) already validates complete status layouts, numeric syntax/finiteness, and checksums. It also has a single I/O owner, tracked v2 commands, priority Stop, queued-command cancellation, and limited parse-rejection retries. Those are valuable destination features.

Missing are the NB2 identity cache/live calibration gate and typed parsing/signals for `MOTION_DONE`, `CALIBRATION`, `DIAG`, `NOTICE`, and `COMMAND_REJECTED`. Status positions are not bounded to the handoff's 0–4095 feedback range; the simpler pressure/position reply branches have weaker validation. Reply parsing should reject extra fields while retaining this version's valid `DONE|sequence` acknowledgements. Cancellation must also invalidate legacy retry eligibility so a delayed parse rejection cannot requeue stopped work.

[updatePressure](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:629) checks readiness before calling the HX711 library, but still relies on its blocking read API. `L0`, `L1`, `L4`, and `L6` retain blocking tare/averaging calls. `lastScaleReady` advances before saturation/factor validation. The repository-owned bounded sampler, candidate-window tare collection, sample/service-gap diagnostics, and validity state are missing.

[Position acquisition](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:297) checks the returned byte count but does not perform all the handoff's device/write/byte/timeout/range checks. It accepts values up to 65000 and can publish cached positions through status after failed queries.

Raw evidence logging is already present: [serial tracing](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/arduino.py:157) records traffic before parsing, and the existing trace-report parser retains raw rows. Extend those facilities rather than replace the logging subsystem.

**4. Pressure completion and pulse recovery: substantial firmware work remains.**

[Pressure waits](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/protocols.py:509) use telemetry plus a generic completion event. The final wait explicitly continues after 15 seconds without `DONE`; pressure requests are repeated during the ramp/final retries. [Lateral waits](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/protocols.py:812) can still succeed from telemetry alone, including in v2 mode. The handoff requires typed evidence that the corresponding motor operation stopped, with its trailing acknowledgement consumed before proceeding.

Current [pressure control](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:808) accepts a positive target within ±2 lb without moving. Its loop can reverse direction after overshooting the band. This differs from reaching the first fresh sample at/above an increasing target, and from the source's reduction/P0 completion rules. Identical requests can restart the current deadline; completed-command deduplication is absent. Firmware's 80-second timeout is advisory, while the host uses 90-second waits and retries; this is not the source's 90-second bounded move and 95-second final-reply wait.

The [pulse loop](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:1568) alternates direction at the selected interval without comparing pressure to the target. It has no measured release floor, recover-before-next-release rule, dwell correction, or fixed recovery timeout. Repeated `J` restarts pulse timing. Add the source behavior as a state machine, preserving the destination's axial/lateral/pulse output percentages and live settings.

**5. Differences requiring a decision before implementation.**

| Difference | Why it matters |
| --- | --- |
| Advisory conditions versus latched faults | [Current firmware](C:/Users/patri/Documents/Projects/drx-2.0/main/motor/motor.ino:1469) deliberately continues on pressure, sensor-loss, heartbeat, and forward-travel warnings; [SafetyMonitor](C:/Users/patri/Documents/Projects/drx-2.0/main/controllers/safety_monitor.py:216) treats most device faults as advisories. The handoff assumes enforced pressure/sensor/feedback guards and a latched pulse-recovery fault. Copying only its pulse loop would omit prerequisites; copying the complete fault policy would change intentional destination behavior. |
| Adjustable cadence versus fixed phase minima | The destination sends [J with a selected interval](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/protocols.py:451) and supports 100–5000 ms. The source specifies 500 ms release/recovery minima. Define how the rate control behaves when pressure recovery requires a longer cycle; do not silently ignore the slider. |
| Pressure completion rules | Current ±2 lb correction/reversal and exact-zero P0 handling differ from source crossing rules and 0–2 lb P0 completion. Setpoint caps remain 80 lb here. Agree on the intended control behavior before changing tests to match it. |
| Feedback range and geometry | The source requires 0–4095 feedback, while destination nominal axial/horizontal limits are 4600/4500. Reconcile feedback validity with target/configuration limits; do not rewrite machine calibration from the source's examples. Preserve calibrated BMarks reset to −10 degrees and review any tolerance change separately. |

These are implementation decisions, not reasons to discard the fixes. Existing tests explicitly encode several destination choices, so a green existing suite alone cannot establish handoff compliance.

**6. UI and Restart App: adapt to the current application.**

This app has inline pressure/time readouts rather than the source's floating dialogs. It already receives controller status independently of protocol workers, and the protocol clock is independent of readout visibility. Keep that architecture. The [treatment pressure display](C:/Users/patri/Documents/Projects/drx-2.0/main/ui/screens/treatment.py:402) rounds to whole pounds and initializes to zero. It needs tenths, an unknown initial state, and waiting/zero-required/unavailable/stale/live/fault presentation. The inline timer starts with a fixed placeholder; selected-duration preview and preparation-aware clock start are still needed. Preserve pause behavior and align the new start boundary with [TreatmentSession](C:/Users/patri/Documents/Projects/drx-2.0/main/helpers/treatment_session.py:20) so cloud durations have a deliberate definition.

The specific 2150-count/<2-lb pressure-progress notice is absent. Existing nonmodal warnings have an OK button, and ordinary Stop proceeds to release/reset. The new notice needs Dismiss and a dedicated cancel/Stop path that preserves telemetry without scheduling reset, home, or tare. It should not be wired to the ordinary recovery chain.

[Profile](C:/Users/patri/Documents/Projects/drx-2.0/main/ui/screens/profile.py:94) has Exit App but no Restart App. [Cleanup](C:/Users/patri/Documents/Projects/drx-2.0/main/kneespa.py:1076) already cancels treatment work, drains stop/release writes, and releases video/GPIO/cloud resources. It does not await all reset/thread-pool work through a responsive close lifecycle; `closeEvent` accepts immediately and the main entry point ultimately uses `os._exit(0)`.

Add restart only after robust cleanup, preserving interpreter, arguments, working directory, environment, and launch mode. The existing [Linux launcher](C:/Users/patri/Documents/Projects/drx-2.0/rpi/desktop_executable.sh:16) already uses `exec python3 kneespa.py`, making the handoff's POSIX process-replacement approach relevant. This repository's development entry point is [tools/run_local.py](C:/Users/patri/Documents/Projects/drx-2.0/tools/run_local.py:1), not `main/simulate.py`; it must remain in development mode after restart. Test fixtures/development fakes need the new replies where they exercise real preparation; the current local launcher bypasses reset and is not a firmware simulator.

**Suggested implementation order:** resolve the four behavior differences; implement firmware sampling/baseline/typed replies with Python parsing and ordered reset; integrate protocol preparation/completion and pulse recovery; then finish readout/notice behavior and restart. Keep each app/firmware contract compatible within the same change. Preserve the existing uncommitted patient/cloud work, speed controls, live treatment settings, pause/resume, calibration service UI, and v2 transport.

**Verification performed:** six focused existing Python test modules passed: `test_reset_worker_logic`, `test_protocol_ack_correlation`, `test_protocol_pressure`, `test_arduino_parse`, `test_arduino_send`, and `test_safety_monitor`. Result: **224 passed in 3.02 seconds**, with one pytest cache-permission warning. No tests were added or altered. This was not the full suite, a new-contract acceptance run, or a physical device test. Firmware was neither built nor uploaded.

Acceptance work for the port should cover delayed/wrong replies, cancellation and late retries, settling near the eight-second deadline, all four baseline lifecycles, sensor/service gaps, three-minute synthetic pulse loads and fixed fault deadlines, notice Stop without homing, preparation-aware clocks, and restart cleanup/mode preservation. Run native firmware tests, a target Mega build, and POSIX integration/launcher tests; the documented source results are not verification of this destination. Hardware validation remains separate from those software checks.
