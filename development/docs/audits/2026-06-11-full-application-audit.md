# KneeSpa / drx-2.0 — Full Application Audit

**Date:** 2026-06-11
**Scope:** Pi application (`main/`), firmware (`main/motor/motor.ino`), calibration tools (`main/calibrate/`, `tools/`, `main/arduino/`), tests, deployment (`rpi/`), prior-audit reconciliation (`docs/archive/audits/`).
**Method:** Six parallel deep-read audits (serial comms/latency, safety, calibration/accuracy, UX/UI, architecture/threading/tests, prior-audit reconciliation), with the highest-impact claims independently verified against source. Test suite run: **81 passed, 24 skipped** (all integration tests skip on non-POSIX; no CI exists, so they effectively never run).

Findings marked ✅ were independently verified line-by-line during this audit; the rest carry the auditing agent's stated confidence.

---

## 1. Critical findings (patient safety)

### S1. Firmware never fails safe without the Pi ✅
`main/motor/motor.ino` includes `<avr/wdt.h>` (line 20) but never calls `wdt_enable`/`wdt_reset`, and has **no heartbeat timeout**: if the Pi app crashes or the UART drops mid-treatment, the pulse loop (motor.ino:827-851) keeps yanking the leg at speed 1600 indefinitely, and held traction stays applied indefinitely. The only exits are serial commands.

### S2. Physical STOP pin ignored during pressure and pulse phases ✅
`STOP = digitalRead(STOP_PIN)` runs every loop (motor.ino:796) but is only consumed inside `if (bRunning)` (motor.ino:865-868). During `measurePressure` (922-966) and `jerking` (827-851) — i.e. exactly when up to 80 lbs is being applied or pulsed — pressing the physical stop button does nothing.

### S3. Pressure monitoring is blind during pulse phase ✅
`J` sets `noStatus = true` (motor.ino:668) which suppresses all status frames (motor.ino:217), and the only >80 lb cutoff lives inside `if (measurePressure)` (motor.ino:922-931), which is false while jerking. Neither firmware nor Pi sees pressure for the bulk of a treatment. The Pi-side backstop (kneespa.py:2075-2118) is additionally disabled whenever `initial_setup_complete` is false.

### S4. The "EMERGENCYSTOP" GPIO is vestigial; E-stop is software-only, five hops deep ✅
GPIO16 is configured as an **output**, driven HIGH once at startup, never read (kneespa.py:2321, 2327). The on-screen E-stop exists **only on the Setup page** (kneespa.ui `emergency_stop_setup_label`); the treatment page has only the Start/Stop toggle. Every stop path reduces to `arduino.send("X")`: Qt touch event → Python → UART → firmware parser → I2C to motor controllers. If the link is down, `send()` enters a ~minutes-long reconnect loop and the X may never arrive. No hardware interlock cuts motor power.

### S5. Blocking HX711 reads freeze the firmware loop ~500 ms at a time ✅
`scale.get_units(5)` (10 SPS HX711 → ~500 ms) runs inside `sendStatus()` (motor.ino:237) and the pressure loop (925, 961). While blocked, STOP-pin polling, position-target checks, and the pressure cutoff all stall while motors keep moving. If the load cell disconnects (DOUT floats), the stock HX711 `read()` busy-waits **forever** — firmware hangs with the motor still driven, and with no watchdog only power removal stops it.

### S6. No stop path releases applied traction
`emergencyStop()` (motor.ino:270-289) zeroes motor speeds; screw actuators hold position, so the patient remains under whatever force was applied. No Python stop path sends a pressure-release; the reset sequence that would home the actuators aborts if `worker.is_running` (reset_worker.py:135-141) — typically true right after a fault.

### S7. Firmware's 'X' can be silently lost; commands merge under the rate limiter
If a completed command waits out the 200 ms `MIN_COMMAND_INTERVAL`, the serial loop keeps appending new bytes to the same buffer (motor.ino:969-996): `"Q"`+`"X"` → `processCommand("QX")` → handled as Q; the emergency stop vanishes. No ack is required or verified for X. Busy firmware also silently drops P/I/K/A commands with no NACK (387-390, 449, 493-496, 535).

### S8. Pressure dose depends on three contradictory calibration factors
HX711 scale factor: firmware boot default `-4360.14` (motor.ino:68), device config `-28369.0` (kneespa.cfg), Python fallback default `1.0` (config.py:18). From boot until reset step 6 sends `L0`, pressure reads ~6.5× off; with a missing/corrupt cfg, the silent default makes `get_units()` return raw counts. `setup()` also never tares (motor.ino:752-755), so boot-time readings include full bridge offset — and the 80 lb safety check consumes those readings. `abs()` on every read (motor.ino:237, 925) masks reversed wiring/negative drift; a single saturated HX711 sample averaged over 5 yields ~1924 lbs — exactly the documented "jumping to 1923.3" field symptom (scale.ino:6).

### S9. Silent fallback to fabricated geometry on config corruption
Any exception reading `kneespa.cfg` silently substitutes generated defaults (config.py:50-58): linear CMarks (~4-5° lateral error vs the device's strongly non-linear measured table), calibration=1.0. No UI alarm; the device will treat patients on fabricated geometry. Config writes are non-atomic (`open(..., "w")`, config.py:156, 179) on a power-cut-prone Pi.

### S10. Position command path systematically wrong ✅
- `A` command ignores the calibrated zero offset except at exactly 0: `localDesiredPosition = AFULLINCH * inches` (motor.ino:544-559) → every non-zero axial target offset by AZERO (~0.37"), discontinuity near zero.
- `L5` zero-mark parse is fixed-width: `substring(2,5)`/`substring(5,9)` (motor.ino:616-618) vs Python's `"L5{:3} {:3}"` — any 4-digit a_zero corrupts both fields; the default b_zero=1900 parses as **190** (10× error), silently.
- Negative/corrupt values: `uint16_t = AFULLINCH * inches` with negative inches wraps → clamped to **max travel**; a commanded retraction becomes full extension. `toInt()` garbage → 0 → lateral drives to minimum. No checksum anywhere on the link; a flipped digit ("P10"→"P70") passes every check.

### S11. Disconnect detection can never fire; "emergency flush" destroys valid data
- The 120 s silence watchdog writes a test "T" then unconditionally `continue`s, extending the deadline forever; on `/dev/serial0` writes succeed with the cable cut, so `connection_lost` never fires (arduino.py:303-342).
- `monitor_buffer` compares the host kernel RX buffer against the 64-byte *Arduino* constant and flushes input whenever two status lines queue (arduino.py:284-286) — destroying in-flight DONE/status frames and causing 30 s reset timeouts.
- Firmware safety errors (`ERROR: Pressure limit exceeded`) have **no parser branch** in `handle_com` (arduino.py:417-446) — a firmware e-stop is logged as "Unrecognized data format" and never reaches the operator; the protocol keeps ramping.
- Every UI call site ignores `send()`'s return, including all stop paths (kneespa.py:1529, 1539, 1546).

### S12. Treatment can run with no visible pressure or time
Live pressure and countdown are opt-in floating dialogs (`checkbox_show_pressure/timer`), default off and force-unchecked on completion (kneespa.py:778-802, 2006-2007). Safety events use `_show_timed_error` — a non-modal box that auto-closes in 5 s (kneespa.py:2120-2136). An operator can run traction blind, and miss an automatic emergency stop entirely.

---

## 2. High-severity findings

### Hardware communication & reliability
- No sequence numbers/acks/checksums; any `DONE` from any source satisfies the single shared `I2Cstatus_event` — reset steps can advance on stale DONEs (arduino.py:420-421, reset_worker.py:42).
- Reader thread can trigger `reconnect()` from inside its own loop → two concurrent reader threads on one port (arduino.py:329-332, 214-218). `send()` can run the full blocking reconnect (~40-60 s/attempt) on the **UI thread** (arduino.py:457-466).
- `reset_dtr()` toggles DTR on `/dev/serial0` (Pi GPIO UART, no modem lines wired) — every "DTR reset" recovery path is a placebo costing 5-8 s (arduino.py:91-115; used 4× in reset_worker.py).
- Truncated status frames (no `STATUS_END`) are still parsed and emitted — corrupt values feed the safety-limit checks (arduino.py:382-394).
- `verify_connection()` flushes the input buffer while other commands are in flight; the post-stop keepalive thread does this every 3 s for 60 s after *every* protocol stop, stacking one thread per stop (arduino.py:163; protocols.py:822, 831-890).
- `Y` reset's `DONE` ack is printed after `resetFunc()` — unreachable; host compensates with a blind 5 s sleep (motor.ino:423-424; reset_worker.py:161-162). `resetFunc()` doesn't stop motors first; `setup()` zeroes them only after ~1.2 s, and `exitSafeStart()` defeats Pololu safe-start before pin init (motor.ino:737-789).
- Reader-loop exception handler resets the watchdog timestamp and spins with no sleep (arduino.py:365-368).
- Test fixture (`fake_arduino.py`) diverges from firmware in load-bearing ways: no DONE on completion, no Q/rate-limit modeling, 100 ms vs 1000 ms status, 'Y' replies DONE instead of resetting.

### Latency
- UI-thread blocking: `send()` sleeps 0.3 s holding the lock per command (arduino.py:478); `time.sleep(5)` in axial reset (kneespa.py:1441); `ensure_arduino_connection` sleeps 2+5+1 s (1792-1807); startup spin-waits up to 30 s with `processEvents()` (2186-2196); blocking SMTP on UI thread (928-952).
- Every status triggers a host 'Q' ack that consumes a 200 ms firmware command slot → user commands queue behind acks; worst-case button-to-motor ≈ 1 s healthy-link (motor.ino:59, 991; arduino.py:400-409).
- Status rate is 1 Hz in HF mode, 0.2 Hz idle, zero during moves (non-HF) and zero during pulsing — on a 115200 link that could carry 10-20 Hz (motor.ino:90, 819). 9600-baud debug prints inside the motion loop throttle position checks to ~12-15 Hz (motor.ino:874-878).

### Calibration & accuracy
- `main/calibrate/calibrate_gui.py` is protocol-incompatible with the production firmware: sends `A{actuator}{int}` malformed (device 0, sub-inch truncated to 0), `HA` (unknown), parses a status format the firmware never emits → **all recorded marks are 0**; its two-click full-inch measurement completes in one click with delta always 0; "Update Arduino Values" would write `AFULLINCH 1` into motor.ino.
- `tools/calibrate.py` jogs A/B via `F+/F-` which drive the **FIT/leg-length motor**, not actuators 12/13 → a_factor/b_factor can never be computed; load-cell flow conflates tare offset with scale factor and `fallback="0"` → `set_scale(0)` → division by zero.
- Three contradictory factor conventions across tools/guide/firmware (×8 vs ×6 vs counts-per-unit); four coexisting counts-per-inch scales for actuator A (430 / 455 / 606.7 / 475) — display math diverges ~25-40% from motion math.
- Stall counter never resets on resumed movement — accumulates across the session, stops motors mid-move after 6 lifetime hits, then still reports DONE (motor.ino:898-909). ✅ (code read confirms `stallCount` only zeroed when tripped)
- `readPosition()` returns 0 on I2C error — indistinguishable from real position 0; in a backward move, instant false "target reached" (motor.ino:178-195, 881-888).
- One-sided 25-count deadband: forward moves <25 counts no-op (≈1° on the compressed side of CMarks); no symmetric tolerance or re-approach (motor.ino:464-468 etc.).
- No monotonicity/completeness validation on saved marks anywhere; partial one-point calibrations can be saved.
- Horizontal (B) motion uses a hardcoded, possibly direction-inverted formula, never the calibrated BMarks (kneespa.py:1295, 1458).
- After every axial reset, `send_calibration()` re-tares under whatever load is present → all session readings under-report by that amount (motor.ino:599-607; kneespa.py:1442).

### UX/UI & state
- No confirmation before starting treatment; Start immediately commands pressure (kneespa.py:818-852).
- Start/Stop button text is the de-facto state machine and desyncs from `protocol_running` (set in different places); navigation isn't blocked during treatment; setup-page actuator controls stay live (kneespa.py:836-846, 1009-1067, 2019-2029).
- Displayed positions/pressure are commanded values, not feedback; `read_position` computes real values and discards them (kneespa.py:1521-1523, 1731-1767). After reset, labels show hardcoded defaults.
- On disconnect mid-treatment: 5 s auto-closing toast + spinner; Start button still says "Stop"; worker keeps sending into the void.
- `worker.signals.progress`, `error`, `result`, `stopped`, and **`reset_needed`** (safety recovery, emitted on pulse failure in protocols 2/3) are never connected (protocols.py:32-37, 539, 601).
- Mid-protocol pressure changes update `worker.max_pressure` but the ramp captured the value at start — UI implies an effect that doesn't happen (kneespa.py:706-708; protocols.py:461). First mid-protocol change + Cancel raises TypeError on `None` rollback (kneespa.py:217-219, 700-729).
- Axial "reset" button sends `R12` — a command the firmware doesn't implement; UI then displays 0 in / 0 lb while nothing moved (kneespa.py:1431-1440).
- PINs: unsalted SHA-256 of short numeric PINs (secure_auth.py:82-94); committed hashes decode to "1234" etc.; no lockout/throttle (kneespa.py:954-968).

### Architecture, tests, deployment
- `KneeSpa` god class: 2417 lines, 0% tested, contains the entire safety monitor and protocol lifecycle. `protocol_1..4` are ~90% copy-paste with behavioral drift (`reset_needed` only in 2/3). `set_to_c_distance` duplicated in kneespa.py and protocols.py — **the protocols.py copy lacks the div-by-zero guard the other has (regression vs documented fix)**.
- ~150 `print()` error handlers vs ~0 `logger.exception` — field failures on a kiosk are invisible; the rotating-log infrastructure captures almost nothing.
- No CI; integration tests skip on Windows (the dev machine); firmware tests don't compile (`pio test -e native` fails: unguarded hardware includes, mocks named wrong, no String/F/elapsedMillis shim). `validate_fixes.py` is regex-grep pseudo-testing.
- Prior-audit regression: the documented lateral double-click lockup fix (`actuator_command_in_progress` + single `controls_enable_timer`) **does not exist in this tree** — the bug it fixed (controls permanently disabled, restart required) is live again.
- Deployment: rsync to three hardcoded Tailscale IPs with `StrictHostKeyChecking=no`, no atomic switch, `Restart=always` systemd unit can restart mid-sync; systemd uses system python while the desktop launcher uses a venv; `os._exit()` + `Restart=always` means "Exit app" relaunches it.

---

## 3. Medium/low (condensed)

- `connection_failed` emitted per retry → stacked dialogs (arduino.py:193-194).
- Any single write exception triggers full multi-minute reset (arduino.py:481-486).
- Status-rate aliasing vs verification windows (1 Hz status + 500 ms stalls vs 5 s verify windows) → false "not verified" aborts.
- Leg-length fast button moves 3.0" where comments/intent say 1.0" (kneespa.py:1622, 1640); dual control path (Pi GPIO pins latch HIGH with no Pi-side timeout + serial F commands).
- Lateral stop button wired to actuator A (kneespa.py:1180-1182) — masked by X stopping everything.
- Fixed 1366×768 geometry; QLabel-as-button navigation with no pressed feedback; double-masked PIN field with no backspace; unit-label inconsistencies; stale "Protocol Started" status text.
- AXIAL_MAX=4600 counts ≈ 10.7" at AFULLINCH=430 vs UI limit 4" — firmware clamp provides no real redundancy or AFULLINCH is wrong ~2.7×; unverified.
- Dead code: shadow CMarks table, unused QTimers, dead `I2CStatus` twin flag, dead E/P parser branches, `COMMAND_DELAY` constant referenced nowhere, `smcDeviceNumber == 12 && false` residue.
- `fuser -k` / `systemctl stop` run as routine connect side effects (arduino.py:49-65).
- python-dotenv from 2021; PyQt5 version floats with OS image; no Python version constraint.

---

## 4. What's already good (preserve)

- Hard clamps at the command layer on both sides for pressure and primary positions (kneespa.py:1498-1504, 1685-1691; motor.ino:291-302, 926) — 13 of 15 documented prior safety/boundary fixes verified present.
- The `_state_lock` + property pattern in protocols.py, the `I2Cstatus_event` threading.Event work, the RLock'd `send()` TOCTOU fix — all verified in place.
- The integration-test architecture (real pty, real threads, qtbot) is genuinely concurrent and worth building on; FakeArduino just needs fidelity fixes.
- Start button sizing/color-coding is a good touch baseline; spinner-overlay and ResetWorker's event-gated completion are good patterns.
- STOP pin pull-up fix, firmware buffer overflow handling, I2C timeout handling, stall clamp, speed clamping — all prior firmware fixes verified present.

## 5. Verified regressions from the prior audit cycle

1. Lateral double-click control-lockup fix — documented as applied + verified, absent from this tree.
2. `protocols.py` `set_to_c_distance` div-by-zero guard — documented as applied, absent (the kneespa.py copy has it).

These two suggest this repo was re-snapshotted from a tree that predates some fixes; worth a history sweep before trusting any other "fixed" status.
