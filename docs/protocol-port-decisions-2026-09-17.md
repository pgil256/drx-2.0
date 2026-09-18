**Protocol port — confirmed decisions and implementation record**

User decisions, September 17, 2026:

- Sensor loss over 500 ms, pressure above the relative/absolute limits, and pulse recovery failure at 5 seconds stop treatment and latch a fault until explicit operator recovery.
- Retain the existing early pressure-build advisory; add a firmware stop/fault at 90 seconds and a 95-second app response deadline.
- Preserve adjustable pulse timing and motor output controls. Recovery to the target must precede the next release; actual cycles may take longer than the requested timing. Do not impose the source's fixed 500 ms phase duration.
- On an increasing pressure command, stop at the first fresh sample at/above the target. Use the handoff's reduction/release completion rules.
- Use the source's inclusive 100-count K tolerance, exact crossing for ordinary raw positioning, and inclusive 25-count axial-home tolerance.
- Preserve machine calibration, calibrated horizontal reset at -10 degrees, all four protocols, live settings, pause/resume, inline UI, and existing patient/cloud changes.

The controller query is SMC Get Variable 12 (AN1 unlimited raw value). The [Pololu SMC G2 variable reference](https://www.pololu.com/docs/0J77/all) specifies 12-bit feedback, 0–4095, with 65535 indicating disconnection. Feedback validation uses that range independently of legacy nominal travel maxima. Machine calibration and nominal travel configuration were not rewritten; commands outside valid feedback range are rejected.

Implementation scope: matching firmware/Python wire contract, bounded sampling and automatic resting baseline, ordered cancellable reset/preparation/completion, pulse recovery and faults, measurement validity/progress notice, and Restart App with complete cleanup and mode preservation. No hardware upload is authorized or planned in this task.

Implemented in the current working tree, on top of the existing patient/cloud/UI work:

| Area | Result |
| --- | --- |
| Sensor acquisition | Repository-owned HX711 reader performs at most 25 clocks per attempt, without readiness waits or blocking tare. Invalid samples and gaps cannot refresh the pressure safety timer. AVR clock-high sections are atomic. |
| Resting baseline | `L0` changes only the factor and invalidates baseline permission. `L1\|BASELINE` requires idle outputs, at least 10 stable samples over 900 ms, and a range no greater than 0.5 lb within a fixed eight-second deadline. Cancellation or failure never commits a new offset. |
| Reset | Cancellable worker requires boot/identity, confirmed zero marks, lateral neutral, calibrated horizontal −10°, axial home, factor acceptance, and baseline. Only a timeout outside baseline permits one complete replay. An explicit reset waits for a cancelled treatment producer to detach. |
| Treatment lifecycle | All four protocols require confirmed centering and baseline before their clocks start. Success requires confirmed P0 release, axial home, and final baseline. Failures cannot enter that success path. Cloud timing starts at the same prepared boundary. |
| Motion replies | Strict typed validation plus the trailing acknowledgement replaces generic-DONE/telemetry-only completion. V2 additionally requires the matching command handle. Stop invalidates queued work and legacy retry eligibility. |
| Pressure and pulse | Increasing commands reach the target, P0 completes within 0–2 lb, duplicate commands cannot restart deadlines, and pulse recovery must reach target before the next release. Adjustable cadence/output percentages remain available. The 80-second advisory precedes the 90-second firmware fault; the app waits at most 95 seconds. |
| Faults | Armed sensor loss over 500 ms, relative/absolute overpressure, invalid sensor/position evidence, and five-second pulse recovery failure stop outputs and latch faults. Further motion requires explicit operator reset. No automatic home or tare is scheduled from these faults. |
| Readouts and advisory | Inline pressure shows tenths with waiting/zero-required/unavailable/stale/live/fault captions. Duration previews the selection until preparation completes. The progress notice offers Dismiss and Stop; Stop cancels without recovery movement. Manual axial home no longer fabricates zero pressure. |
| Restart | Profile has Restart App. Shutdown cancels producers, drains stop writes, waits for serial/thread-pool/cloud completion, and releases video/GPIO before relaunching the same interpreter, arguments, working directory, environment, and entry mode. Ordinary Exit stays an exit. |

The relative pressure guard uses the selected treatment target plus 10 lb. During a commanded reduction it initially permits the current pressure plus 10 lb, then returns to the selected-target guard at completion; the absolute 100 lb guard remains active. This preserves the source reduction contract. The existing physical emergency-stop release behavior remains distinct from the new stop-and-latch faults.

The firmware identifies as `2026-09-17-DRX2-NB2` with driver `DRX-HX711-NB2`. This is a coordinated app/firmware change: the app refuses baseline preparation on an older or unknown driver. The matching firmware has been compiled, not uploaded.

Verification performed on Windows:

- Final full Python suite: **1,192 passed, 48 skipped in 44.44 seconds**, including the reset cancellation and delayed-failure regressions.
- Native firmware: 152 passed across seven suites, including the actual bounded sampler, baseline timing/cancellation, faults and fixed deadlines, exact pressure crossing, arrival bands, and a three-minute synthetic adjustable-pulse run. Built using the existing Zig C/C++ toolchain and vendored Unity.
- Arduino Mega 2560 target build: passed using Arduino CLI and AVR core 1.8.8; 33,724 bytes flash (13%) and 2,628 bytes static RAM (32%). A staging directory containing only the sketch and sampler header avoided Arduino CLI traversing Windows pytest temporary folders.
- Actual Qt window tests exercise advisory Dismiss/Stop, Restart, cancellation and cleanup. The rendered pressure readout was inspected: `40.2 lbs`, with the `Pressure live` caption.
- `git diff --check`: passed. Existing unrelated working-tree changes were retained.

Python command used: `.venv/Scripts/python.exe -X utf8 -m pytest -q -p no:cacheprovider --basetemp=main/motor/.native-build/pytest-verified-final`. Native results and target-build logs are in ignored `main/motor/.native-build/`.

The 48 skipped tests require POSIX serial pseudo-terminals or deployment fixtures. Linux/Pi launcher and real serial integration still need execution on a POSIX host. No real actuator, load-cell, pressure-load, emergency-stop, or device-restart bench test was performed, and no firmware was flashed. The local development launcher preserves its existing no-hardware mode; it is not a complete NB2 device simulator. Software test results do not establish physical-device readiness.
