# KneeSpa / drx-2.0 — Improvement Plan

**Date:** 2026-06-11
**Basis:** [Full application audit](../audits/2026-06-11-full-application-audit.md) (same date).
**Constraints (per owner):**
- Software/firmware changes only — no new hardware. (A hardware E-stop power interlock remains the single biggest residual risk and is documented in §8 as a recommended future hardware change.)
- Device is used on real patients → every safety change carries a hazard reference, an acceptance criterion, and a verification method.
- Hardware access is limited/scheduled → all work is developed and verified against simulation/CI first; firmware flashes are grouped into two batches, each with a hardware checkout checklist.

**Core principle:** the firmware must be safe *on its own*. Today every protection assumes the Pi→UART→firmware chain is alive. Phase 1 inverts that: the Arduino becomes autonomously fail-safe, and everything above it becomes defense-in-depth.

---

## Hazard → mitigation traceability

| ID | Hazard | Today | Plan items |
|----|--------|-------|-----------|
| H1 | Pi crash / link loss mid-treatment → unbounded traction/pulsing | No watchdog, no heartbeat; firmware runs forever | 1.1, 1.2, 1.6, 2.6 |
| H2 | Pressure exceeds 80 lbs unobserved | Check only in `measurePressure`; blind during pulse; Pi backstop gated off | 1.3, 1.4, 1.5, 3.1 |
| H3 | Stop request fails or is slow | Software-only 5-hop path; X lost to buffer merge; send failures ignored; STOP pin ignored in 2 of 3 states | 1.2 (STOP pin), 1.7, 2.2, 2.4, 3.2 |
| H4 | Load-cell fault → runaway or firmware hang | Blocking reads, no plausibility checks, `abs()` masks faults | 1.5, 1.4 |
| H5 | Wrong position/pressure from bad calibration or corrupted command | Silent config defaults; 3 scale factors; A-cmd offset bug; L5 parse bug; clamp-corrupt-to-max | 1.8, 1.9, 2.1, 4.1–4.4 |
| H6 | Patient left under load after stop/fault | No stop path releases traction | 1.6, 2.6, 3.2 |
| H7 | Operator runs treatment blind / misses safety event | Opt-in floating dialogs; 5 s auto-closing alerts | 3.1, 3.2, 3.3 |

---

## Phase 0 — Verification infrastructure + verified quick wins (no hardware needed)

Everything later depends on being able to prove changes without the device.

- **0.1 Make firmware tests compile and run.** Guard hardware includes in `motor.ino` behind `#ifndef UNIT_TEST`, add an `arduino_shim.h` (String/F()/elapsedMillis/wdt no-ops), fix mock header names, get `pio test -e native` green. *Accept:* all three existing firmware test suites build and pass natively.
- **0.2 CI on Linux (GitHub Actions).** Jobs: pytest unit + integration (pty available on Linux so the 24 currently-skipped tests actually run), firmware native tests, byte-compile/lint. *Accept:* CI runs the full 105-test suite, not 81.
- **0.3 FakeArduino fidelity.** Emit `DONE` after position/pressure completion; model the 200 ms `MIN_COMMAND_INTERVAL` (drop/merge like real firmware); 1000 ms HF status; `Y` resets (no DONE); `Q`/`statusAcknowledged` flow. Add a parity test asserting fixture behavior against documented firmware behavior. *Accept:* reset-worker tests pass against the real DONE chain (no `auto_ack_i2c` MagicMock shim).
- **0.4 Fix the two verified regressions.** (a) Restore div-by-zero guard in `protocols.py set_to_c_distance` (~line 348); (b) re-implement the lateral double-click lockup fix (`actuator_command_in_progress` guard + single re-enable timer, kneespa.py:557-562, 1265+). Both with regression tests.
- **0.5 pytest marker/doc reconciliation** (pytest.ini vs AGENTS.md) and retire `validate_fixes.py` greps into real pytest cases.

## Phase 1 — Firmware fail-safe core (**Flash Batch 1** — protocol-compatible with current Pi app, independently deployable)

All items in this batch keep the existing serial protocol so the current Pi software keeps working; the batch is verifiable via native tests + FakeArduino sim before the scheduled flash.

- **1.1 Enable the AVR watchdog** (`wdt_enable(WDTO_2S)` in setup, `wdt_reset()` in loop). Any firmware hang (e.g. HX711) now reboots into `setup()`, which must zero motors *first statement* (see 1.7). [H1, H4]
- **1.2 Honor STOP pin and run the pressure ceiling in every state.** Move `if (!STOP) emergencyStop()` and the >MAX_PRESSURE check to the top of `loop()`, unconditional (motor.ino:796/865-868/922-931). [H2, H3]
- **1.3 Keep telemetry alive during pulse.** Remove `noStatus` suppression for jerk mode (or emit status between jerks); the pressure ceiling check from 1.2 covers pulsing. (motor.ino:217, 668) [H2]
- **1.4 Heartbeat timeout.** If any of `bRunning || measurePressure || jerking` and no serial traffic from the Pi for 3 s → `emergencyStop()` + autonomous bounded pressure release (1.6). Pi side already sends periodic traffic; add an explicit 1 Hz `T` heartbeat during protocols (Pi change, also compatible). [H1]
- **1.5 Non-blocking, validated load-cell reads.** Replace `abs(scale.get_units(5))` with `is_ready()`-gated single reads into a median-of-N filter; reject saturated raw samples (±8388607); preserve sign and alarm on sustained negative; `wait_ready_timeout` everywhere — not-ready beyond 500 ms = sensor fault → emergencyStop + release. Bound every pressure move by position envelope and time; flag "commanded but no ΔP" as stall. (motor.ino:237, 925, 961, 922-966) [H2, H4]
- **1.6 Safe state = released.** After `emergencyStop()` from fault/heartbeat/STOP-pin (not normal completion), run a bounded axial back-off until load < 5 lbs or travel limit, then stop. Emit `ERROR:` lines describing the cause. [H6]
- **1.7 Command-path integrity (compatible subset).** Fix the buffer-merge bug (don't append to a completed command, motor.ino:969-996); exempt `X` from `MIN_COMMAND_INTERVAL`; reply `BUSY` instead of silently dropping P/I/K/A while running; `emergencyStop()` before `resetFunc()`; zero motors as the first statements of `setup()`; remove `exitSafeStart()`-before-init ordering. [H3]
- **1.8 Position/zero math fixes.** `target = ZERO + FULLINCH×inches` (signed intermediate, reject negatives instead of wrapping, motor.ino:544-559); delimited `L5` parse with echo-back verification (motor.ino:616-618); stall counter reset on movement (898-909); `readPosition()` I2C-error sentinel distinct from 0 + retry (178-195); symmetric approach deadband. [H5]
- **1.9 Input rejection over clamping.** Out-of-range or non-numeric command parameters are rejected with `ERR` reply, not clamped to an extreme. [H5]
- **1.10 Firmware test coverage for every item above** in `main/motor/test/` (now buildable per 0.1): watchdog config, STOP-in-all-states, pressure-check-in-all-states, heartbeat trip, saturated-sample rejection, buffer-merge, negative-input rejection, L5 round-trip, stall reset.
- **1.11 Hardware checkout checklist for Batch 1** (one scheduled session): STOP button in each state; pull cable mid-pulse → motion stops + release within 3 s; unplug load cell mid-pressure → fault + release; A-command positions measure correctly against ruler; pressure vs reference weight.

## Phase 2 — Pi comms layer rebuild (**Flash Batch 2**: protocol v2 — seq/ack/checksum — firmware + Pi together)

- **2.1 Protocol v2 framing.** Per-command sequence number echoed in `DONE|seq` / `BUSY|seq` / `ERR|seq|reason`; XOR or CRC-8 checksum field on status lines and commands; reject unframed input. Firmware accepts v1 commands until the Pi switches (transition flag), so a half-updated system degrades gracefully. [H3, H5]
- **2.2 Single-owner serial transport.** One thread owns the port: command queue in, completion futures keyed by seq out. Removes: reconnect-from-reader dual-thread race, UI-thread reconnects/sends, lock-held sleeps, keepalive thread stacking, shared `I2Cstatus_event` aliasing (arduino.py:457-466, 329-332, 214-218; protocols.py:822-890; reset_worker.py:42). [H3]
- **2.3 Make disconnect detection real.** Fix the 120 s watchdog `continue` bug (response-based, not write-based); delete the `monitor_buffer` emergency flush; drop `readline` timeout to 1 s; reject status frames without `STATUS_END` (arduino.py:284-286, 303-342, 382-394). During an active protocol, status older than 3 s = stop condition. [H1, H2]
- **2.4 Errors become visible.** Parse `ERROR:`/`ERR|` into an `error_emit` signal wired to the operator alarm UI (3.2); check every `send()` return — a failed stop is an alarm; `connection_failed` emitted once per episode, not per retry. Replace ~150 `print()`s in the comms/protocol path with the existing rotating logger (`logger.exception` in handlers). [H3, H7]
- **2.5 Remove placebo recovery.** Verify-then-delete `reset_dtr()` (no modem lines on /dev/serial0) and the `fuser -k`/systemctl runtime self-surgery; replace the blind 5 s post-`Y` sleep with an explicit "Ready to Go" wait; bounded exponential backoff. (arduino.py:91-115, 49-65; reset_worker.py)
- **2.6 Protocol worker stop semantics.** `threading.Event` for stop; locked setpoint properties (finish the `_state_lock` pattern); stop path commands pressure release before X; `reset_needed`/`progress`/`error` signals connected or deleted; mid-protocol setpoint changes either honored (re-read inside ramp loop, decrease = active back-off) or rejected with UI feedback — never silently ignored. (protocols.py:74, 831-890; kneespa.py:706-750) [H6, H2]
- **2.7 Latency cleanup that falls out:** no 0.3 s sleep-in-lock per send; status rate to 5 Hz (115200 budget allows 20+); drop the Q-ack 200 ms slot consumption; gate firmware debug prints behind a flag.

## Phase 3 — Safety UX (treatment screen)

- **3.1 Always-visible treatment state.** Live measured pressure, time remaining, target pressure/angle, and phase as permanent main-page widgets fed from `status_emit` (not commanded values); remove the opt-in floating-dialog model; labels update from feedback after resets too. (kneespa.py:778-802, 1521-1523, 1731-1767, 2006-2007) [H7]
- **3.2 Stop and alarms.** Large persistent STOP button on the treatment page (and all pages while a protocol runs); safety events use persistent acknowledged-modal alerts, never 5 s auto-close; connection loss mid-treatment → forced worker stop, persistent "CONNECTION LOST — verify patient, pressure unknown" banner, Start button state reset. (kneespa.ui:1128; kneespa.py:2120-2136, 2178) [H3, H6, H7]
- **3.3 Protocol state machine.** One `ProtocolState` (idle/starting/running/stopping/fault) drives button label, nav gating (no page changes or setup-jog commands during treatment), and a pre-start confirmation dialog summarizing protocol #, max pressure, angles, duration. Fix the `None`-rollback TypeError and the `R12` no-op reset button (real home command + status confirmation). (kneespa.py:818-852, 1009-1067, 1431-1440, 217-219) [H7]
- **3.4 Off-UI-thread everything.** Remove all `time.sleep`/`processEvents` loops from slots (kneespa.py:1441, 1792-1807, 1889, 1936, 2186-2196, 2270); SMTP to a worker; QTimer chaining (pattern already exists in `_stop_protocol_phase2`).

## Phase 4 — Calibration integrity

- **4.1 One source of truth for the scale factor.** Stored in `kneespa.cfg`, pushed at connect with echo-back verification; firmware refuses `P` commands until factor+tare confirmed (`uncalibrated` state); reject implausible factors (|f| < 1000); tare only via guarded operator action asserting no load — never automatically after resets. (motor.ino:68, 599-607, 752-755; config.py:18; kneespa.py:1442) [H5, H2]
- **4.2 Config corruption fails loud.** Corrupt/missing `kneespa.cfg` → persistent "UNCALIBRATED — motion disabled" state requiring explicit recalibration, not silent linear defaults; atomic config writes (tempfile+fsync+rename); validation on save: strictly monotonic marks, full −20…+20 coverage, ranges within firmware clamps. (config.py:50-58, 156, 179) [H5]
- **4.3 One calibration tool.** Retire `main/calibrate/calibrate_gui.py` (protocol-incompatible; records zeros). Fix `tools/calibrate.py`: jog A/B via real `A12/A13` commands (not FIT-motor `F` commands); separate tare-offset from scale-factor flows with a known-weight procedure; validate before send (no `set_scale(0)`). [H5]
- **4.4 Unify conversion math.** Single shared degrees/inches↔counts helper used by kneespa.py, protocols.py, and the calibration tool; horizontal (B) driven from BMarks instead of the hardcoded inverted formula; delete the dead shadow tables and factor-÷6/×8 display math; reconcile `AFULLINCH 430` vs `AXIAL_MAX 4600` (≈10.7" implied vs 4" UI limit) — flag as a measurement task for the Batch 1 hardware session. (kneespa.py:112-177, 1295, 1458, 1750-1764) [H5]

## Phase 5 — Architecture, auth, deployment

- **5.1 Decompose `KneeSpa`** (2,417 lines, 0% tested): extract `SafetyMonitor` (status-limit checks), `ProtocolController` (lifecycle), `ConnectionManager` — each unit-testable; the two live UI bugs and the whole E-stop chain currently sit in untested code.
- **5.2 One parameterized protocol engine** replacing the 90%-duplicated `protocol_1..4` (divergence already produced the missing `reset_needed` emit in 1/4).
- **5.3 Auth hardening:** salted slow KDF (bcrypt/argon2) for PINs; remove committed weak hashes (decode to "1234"); attempt throttling/lockout; drop or implement the dead admin/user distinction.
- **5.4 Deployment hygiene:** versioned atomic deploys (sync to staging dir + symlink switch + service restart) instead of raw rsync-over-running-app; one interpreter environment (systemd unit uses the venv); fix `os._exit` + `Restart=always` exit loop; host key checking on; pin PyQt5/Python versions; log level INFO in production with `--debug` opt-in.

## Phase 6 — UX polish (after safety UX)

Touch-target/layout pass (responsive layouts vs fixed 1366×768, QPushButton-based nav with pressed states), PIN-pad usability (backspace, single masking, larger keys), unit-label consistency, status-text lifecycle, leg-length step-size fix (3.0" vs documented 1.0") and single control path, dead-code removal (shadow CMarks, unused QTimers, dead flags/branches).

---

## Sequencing & verification strategy

1. **Phase 0 first** — it is the proof machinery for everything else; without CI the integration suite literally never runs.
2. **Phases 1 and 2 are the payload.** Phase 1 ships as Flash Batch 1 (compatible, independently safe). Phase 2 ships as Flash Batch 2 (protocol v2, firmware+Pi together, graceful transition).
3. **Phases 3-4 are Pi-only** — deployable any time after their tests pass; 3.1/3.2 should land with Batch 1 so the operator sees the new firmware `ERROR:` alarms.
4. Each safety item: native/pytest test in CI → FakeArduino integration sim → hardware checklist item in the next scheduled session.
5. Hardware sessions needed: ~2 (Batch 1 checkout incl. AFULLINCH measurement; Batch 2 checkout).

## §8 Residual risk (requires future hardware work — out of current scope)

- **No hardware E-stop power interlock.** Even after this plan, the fastest stop path is firmware-software (STOP pin → `emergencyStop()`, now honored in all states, watchdog-backed). A stuck motor driver, I2C failure, or MCU fault could still hold/apply force. Recommendation: a physical E-stop in series with actuator power (relay/contactor), and wiring the existing operator stop to it. Document for the next hardware revision.
- **HX711 at 10 SPS** limits pressure-loop bandwidth; the 80 SPS rate-select pin is a jumper change when hardware changes are next possible.
