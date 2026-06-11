# Flash Batch 1 — Hardware Checkout Checklist

**Firmware:** `main/motor/motor.ino` VERSION `2026-06-11-FAILSAFE-2`
**Pi software:** same branch (the delimited `L5|a|b` zero-mark command requires the new firmware; everything else is backward compatible).
**Precondition:** no patient attached for ANY item below. Keep actuators free to move through full travel.

Flash the Mega, deploy the Pi software, then run these in order. Each item maps to a Phase-1 change; check the box only on observed behavior.

## A. Boot and watchdog

- [ ] **A1. Normal boot.** Power-cycle. Debug serial shows `All actuators stopped` before the load-cell init, then `VERSION: 2026-06-11-FAILSAFE-2` and `Ready to Go`. No motor twitch during boot.
- [ ] **A2. Watchdog recovery (CRITICAL — do first, motors disconnected from load).** Temporarily unplug the load cell DOUT wire mid `L1` tare (forces a blocking read) or otherwise wedge the loop. The board must reset itself within ~2 s and come back to `Ready to Go`. **If it boot-loops** (old stk500v2 bootloader bug): reflash the bootloader, or set `ENABLE_WDT 0` and re-flash, and record that the watchdog is unavailable.
- [ ] **A3. WDT reset is safe.** Trigger A2 while an actuator is mid-move: motion must stop at reset and NOT resume after boot.

## B. Stop paths (each in every state)

States: (1) position move (`I14...`), (2) pressure ramp (`P30`), (3) pulsing (`J` after `P30`).

- [ ] **B1. Physical STOP button** halts motion in state 1, 2, AND 3 (2 and 3 previously ignored it). After the stop, the axial actuator should back off until the load cell reads < 5 lbs (`RELEASED` on the Pi serial log).
- [ ] **B2. UI Stop / `X`** halts each state. Send `X` immediately after another command (within 200 ms): it must still act instantly (rate-limiter bypass).
- [ ] **B3. Heartbeat.** Start a pressure ramp, then pull the Pi's serial cable (or `sudo systemctl stop` the app). Within ~3 s the firmware must stop and begin the autonomous release. Reconnect; verify `ERROR: Host heartbeat lost` was emitted.
- [ ] **B4. Load-cell fault.** Start a pressure ramp, unplug the load-cell connector. Within ~0.5 s: stop + release attempt + `ERROR: Load cell not responding`. (Release will end on travel/timeout bounds since the sensor is dead — verify it stops at the axial floor or after 15 s, not indefinitely.)

## C. Pressure integrity

- [ ] **C1. Ceiling everywhere.** With a test load arrangement, exceed 80 lbs during pulsing (state 3): firmware must stop + release + `ERROR: Pressure limit exceeded`. Previously the ceiling was OFF during pulsing.
- [ ] **C2. Telemetry during pulse.** During `J`, the Pi keeps receiving `STATUS_START|...` frames (~1 Hz). Previously status was silent for the whole pulse phase.
- [ ] **C3. No saturation spikes.** Tap/flex the load-cell cable; the reported pressure must NOT jump to ~1923 lbs (saturated samples are now rejected, median-filtered).
- [ ] **C4. Stall/progress bound.** Command `P50` with the load cell unloaded mechanically (no possible pressure rise): within ~5 s, `ERROR: No pressure progress` + stop + release. Also verify the 30 s overall bound (`ERROR: Pressure move timeout`).
- [ ] **C5. Tare discipline.** `L0<factor>` and `L1` still tare; verify pressure reads 0 ± 0.5 lbs unloaded and tracks a known weight (record value: ______ lbs at ______ lbs reference).

## D. Position integrity

- [ ] **D1. Zero marks round-trip.** Trigger an app reset sequence; on the debug serial verify `AZERO: 160 BZERO: 1900` (or current config values) — previously BZERO 1900 was silently truncated to 190. The Pi log shows `ZEROS|160|1900`.
- [ ] **D2. Reject corrupt commands.** From a serial console send `A12-1.0`, `Kabc`, `I991000`: each must answer `ERROR: ...` and nothing may move. (Previously `A12-1.0` commanded FULL EXTENSION.)
- [ ] **D3. Stall counter.** Run ≥ 10 normal moves in a row; none may stop early with `Motor stalled` (the counter used to accumulate across moves). Then physically block an actuator (carefully): it must stop with `ERROR: Motor stalled` rather than grind.
- [ ] **D4. Small-move behavior.** Command a move ≤ 25 counts from current position: immediate `DONE`, no motion, UI does not hang.
- [ ] **D5a. Protocol v2 smoke test (optional, enables checksummed link).** With `KNEESPA_PROTOCOL_V2=1` in the app environment: commands flow normally, acks show `DONE|<seq>` in the debug log, status frames end in `*XX`, and a deliberately corrupted command (send `#1:P70*FF` from a console) is rejected with `ERR|1|Checksum mismatch` and nothing moves. Leave the env var OFF if anything misbehaves.
- [ ] **D5. BUSY visibility.** Send a second move while one runs: host receives `BUSY` (previously silent drop → 30 s UI timeout).

## E. Measurements to bring back (blocking items for later phases)

- [ ] **E1. AFULLINCH ground truth.** Command `A12` moves of 1.0, 2.0, 3.0 in from home; measure actual travel with a ruler. Record: 1.0→____ in, 2.0→____ in, 3.0→____ in. (Implied counts/inch: ______. Firmware assumes 430; `AXIAL_MAX 4600` implies 10.7 in of travel vs the UI's 4 in limit — reconcile.)
- [ ] **E2. A-command zero-offset convention.** With AZERO correctly set (D1), check whether `A12<x>` targets are offset by AZERO counts from intended physical positions (the audit found the math drops the zero offset for non-zero targets). Record the decision: add `ZERO +` to the conversion in Batch 2, or recalibrate marks around current behavior.
- [ ] **E3. Horizontal (B) convention.** Verify which direction increasing counts moves the horizontal actuator and what count `-25°`/`-5°` correspond to. The Pi-side formula and the constants file comments disagree.
- [ ] **E4. Bootloader version** (from A2): WDT-safe? yes / no — if no, schedule a bootloader reflash.

Sign-off: __________ Date: __________
