# Phase E — On-Device Playbook

*The one document to work through with the device in front of you. Every
software phase (A–D, C, F) is merged to `main`; this is the only remaining
phase and it needs the physical Raspberry Pi + Arduino Mega + the KneeSpa
mechanism. Print this or open it on a second screen and check the boxes as
you go.*

Companion doc: `docs/plans/2026-06-11-batch1-hardware-checklist.md` — the
detailed A–F item list. This playbook wraps it in the correct order and
adds the items that landed after it was written (the e-stop GPIO polarity
confirmation and the 500 ms pulse-cadence default).

---

## 0. Golden rules (read before touching anything)

1. **No patient. Ever, for any item here.** Every test can drive the
   actuators. Keep the mechanism free to move through full travel with
   nothing and no one attached.
2. **Fail safe = stop + release.** If anything is ambiguous or misbehaves,
   hit the physical STOP, power down, and stop. Do not "try one more thing"
   on a machine applying force.
3. **One change at a time.** Flash, then verify. Enable one flag, then
   verify. Never stack unverified changes.
4. **Measure before you change frozen math.** The A-zero-offset, AFULLINCH,
   and B-axis conventions are deliberately unchanged pending *your*
   measurements in §7. Bring numbers back; do not adjust them from a guess.
5. **Keep a rollback.** Save the currently-flashed firmware `.hex` before
   you overwrite it (§2), and the device keeps its own `kneespa.cfg` /
   `user_pins.csv` (the deploy script never touches them).

**Bring to the bench:** USB-B cable (Mega flashing), a multimeter (e-stop
polarity, §4), a ruler/calipers (axial travel, §7), a known test weight and
a way to load the cell (pressure, §5/§7), and a serial console on the Pi
(`screen`/`minicom` or the app's debug log).

**Login PINs must be exactly 4 digits** — the GUI keypad auto-submits on
the 4th digit (`LoginModal`/`DSKeypad` are fixed at `length=4`), so the
6-digit PINs originally rotated in Phase D cannot be entered. Provision
your own 4-digit admin + user PINs on the device with the README "User
provisioning" one-liner (the old 1234/456/123 hashes no longer exist).

---

## 1. Prep the Pi and the bench

- [ ] **1.1 Deploy the current code to the Pi.** From your dev machine on
  the same network as the devices:
  ```bash
  ./rpi/sync_pis.sh          # stops kneespa.service, rsyncs main/, restarts
  ```
  It excludes `config/kneespa.cfg`, `data/user_pins.csv`, and `logs/`, so a
  deploy can never clobber the device's calibration or credentials. Override
  `PI_HOSTS="<ip>"` to target a single bench unit.
- [ ] **1.2 Stop the app for bench work.** `sudo systemctl stop
  kneespa.service` on the bench Pi so it isn't fighting you for the serial
  port while you use a console. Restart it when you reach the GUI items (§9).
- [ ] **1.3 Open a serial console** to the Mega (115200 or the project's
  configured baud) so you can see `VERSION:`, `Ready to Go`, `ERROR:` lines
  and send raw commands.
- [ ] **1.4 Back up the device config** (calibration you don't want to lose):
  `cp /home/pi/drx-2.0/main/config/kneespa.cfg ~/kneespa.cfg.bak`.

---

## 2. Flash the FAILSAFE firmware

The AVR build is already CI-verified (`pio run -e mega` green on every PR),
so this compiles; the risk is entirely the bootloader (§3), not the code.

- [ ] **2.1 Save the current firmware** as a rollback (via `avrdude -U
  flash:r:old.hex:i` on the port), so you can restore the known-good build
  if the new one boot-loops and can't be recovered in place.
- [ ] **2.2 Flash** from `main/motor/`:
  ```bash
  cd main/motor && pio run -e mega -t upload   # or your usual avrdude flow
  ```
- [ ] **2.3 Confirm the version.** On the serial console after reset you
  must see `VERSION: 2026-07-08-FAILSAFE-3`. If you see an older version
  string, the upload didn't take — stop and fix before proceeding.

> This firmware carries the reconciliation changes: the `J<ms>` pulse-rate
> parse (dormant until you enable the flag in §6) and the **500 ms** boot
> pulse cadence (was 200 ms). Both are verified in §6.

---

## 3. Boot & watchdog — the bootloader gate (do this FIRST)

Batch-1 checklist §A. **This is the make-or-break step:** old Mega
`stk500v2` bootloaders boot-loop on a watchdog reset, which would turn the
safety watchdog into a brick. Settle this before trusting anything else.

- [ ] **3.1 (A1) Normal boot.** Power-cycle. Serial shows `All actuators
  stopped` → load-cell init → `VERSION: 2026-07-08-FAILSAFE-3` → `Ready to
  Go`, with **no motor twitch** during boot.
- [ ] **3.2 (A2) Watchdog recovery — CRITICAL, motors disconnected from any
  load.** Force a hang (e.g. unplug the load-cell DOUT mid-`L1` tare to wedge
  a blocking read). The board must **reset itself within ~2 s** and return to
  `Ready to Go`.
  - **Bootloader half already verified 2026-07-08 via WDT test sketch:** 2 s
    watchdog armed and not fed; board hardware-reset and re-booted cleanly
    8+ consecutive cycles. Found while chasing the `Y`-command wedge: the
    old jump-to-0 `resetFunc()` froze the MCU until power cycle on every
    GUI-triggered reset; `Y` now does a real WDT reset (`resetBoard()`,
    FAILSAFE-3). Remaining: confirm the recovery on the FAILSAFE firmware
    itself via the forced-hang test above.
  - **If it boot-loops:** you've hit the bootloader bug. Either reflash a
    modern bootloader (Optiboot/known-good stk500v2), **or** set
    `ENABLE_WDT 0` in `motor.ino`, re-flash, and **record that the watchdog
    is unavailable on this unit** (a documented residual risk — the host
    heartbeat and physical STOP still work, but the AVR self-recovery does
    not).
- [ ] **3.3 (A3) WDT reset is safe.** Trigger 3.2 while an actuator is
  mid-move: motion must **stop at reset and NOT resume** after boot.
- [x] **3.4 (E4) Record the bootloader verdict:** WDT-safe? **YES**
  (2026-07-08, WDT test sketch, 8+ clean reset cycles at WDTO_2S).

---

## 4. Stop paths — includes the NEW e-stop GPIO polarity confirmation

Batch-1 checklist §B, **plus the reconciliation's e-stop GPIO assert**,
which is the single most important unverified item on the device.

Test each stop in all three states: (1) position move (`I14...`),
(2) pressure ramp (`P30`), (3) pulsing (`J` after `P30`).

- [ ] **4.1 (B1) Physical STOP button** halts motion in states 1, 2, and 3
  (2 and 3 used to ignore it). After the stop, the axial actuator backs off
  until the load cell reads < 5 lbs (`RELEASED` on the Pi log).
- [ ] **4.2 (B2) UI Stop / `X`** halts each state. Send `X` within 200 ms of
  another command — it must still act instantly (rate-limiter bypass).
- [ ] **4.3 (B3) Host heartbeat.** Start a pressure ramp, then pull the Pi's
  serial cable (or `sudo systemctl stop kneespa.service`). Within ~3 s the
  firmware emits `WARNING: Host heartbeat lost` without interrupting motion.
  Use the physical E-stop to halt, then reconnect.
- [ ] **4.4 (B4) Load-cell fault.** Start a ramp, unplug the load-cell
  connector: within ~0.5 s → `WARNING: Load cell not responding`; operation
  continues until the physical/software E-stop is used.

### 4.5 🔴 CONFIRM THE E-STOP GPIO POLARITY (new, ship-blocking)

The UI/software e-stop now drives the hardware `EMERGENCYSTOP` line
(**BCM pin 16**) in addition to sending `X`. The polarity is **inferred, not
measured**: the boot default parks the pin **HIGH = run-permitted**, so the
code drives it **LOW = asserted/stop**. Code:
`main/controllers/protocol_controller.py:406` (`emergency_stop_clicked` →
`GPIO.output(EMERGENCYSTOP, GPIO.LOW)`), released again at
`_emergency_stop_phase3:435` (`GPIO.HIGH`) before the recovery reset.

Procedure (multimeter on BCM pin 16 vs ground):

- [ ] **4.5a Boot state.** With the app running and idle, pin 16 reads
  **HIGH** (≈3.3 V). If it boots LOW, the machine is being told "stop" at
  rest, or the default is wrong — stop and investigate.
- [ ] **4.5b Assert.** Trigger the UI/physical e-stop. Pin 16 must drop to
  **LOW** (≈0 V) immediately, **and the machine
  must actually halt.** Watch the mechanism, not just the meter.
- [ ] **4.5c The decisive check — does LOW mean STOP to the wiring?** Confirm
  the downstream interlock/relay/driver-enable treats **LOW as stop**. If the
  hardware is active-high (LOW = run-enabled), the polarity is **inverted**
  and asserting the e-stop would *release* the interlock — the exact opposite
  of safe. In that case: **do not ship.** Flip the two `GPIO.output` calls
  (LOW↔HIGH) at `protocol_controller.py:418` and `:441`, redeploy, and
  re-test from 4.5a.
- [ ] **4.5d Release + recover.** After the e-stop's phase-3 (~2 s), pin 16
  returns **HIGH** and the reset/home sequence runs on the now-powered
  machine. Confirm the machine homes and returns to idle.
- [ ] **4.5e Record the verdict:** polarity **confirmed as-is / inverted &
  fixed**. This is a sign-off gate — the device does not ship until this box
  is checked.

---

## 5. Pressure integrity

Batch-1 checklist §C. Use a safe test-load arrangement; never your hand.

- [ ] **5.1 (C1) Pressure warning.** Treatment commands remain capped at
  80 lbs. A measured value above 100 lbs emits `WARNING: Pressure warning
  threshold exceeded` without interrupting operation; only E-stop halts it.
- [ ] **5.2 (C2) Telemetry during pulse.** During `J`, the Pi keeps receiving
  `STATUS_START|...` frames (~1 Hz); status is no longer silent through the
  pulse phase.
- [ ] **5.3 (C3) No saturation spikes.** Tap/flex the load-cell cable —
  reported pressure must NOT jump to ~1923 lbs (saturated samples are
  rejected + median-filtered).
- [ ] **5.4 (C4) Stall/progress bound.** `P50` with the cell unable to rise:
  the disabled progress heuristic does not interrupt the move. At 30 s,
  `WARNING: Pressure move timeout` appears and operation continues.
- [ ] **5.5 (C5) Tare discipline.** `L0<factor>` / `L1` tare; unloaded reads
  0 ± 0.5 lbs and tracks a known weight. **Record: ______ lbs measured at
  ______ lbs reference.**

---

## 6. Position integrity + pulse cadence

Batch-1 checklist §D, plus the **500 ms cadence** verification (new default).

- [ ] **6.1 (D1) Zero marks round-trip.** Trigger an app reset; serial shows
  `AZERO: 160 BZERO: 1900` (or your config values) — BZERO 1900 used to
  truncate to 190. Pi log shows `ZEROS|160|1900`.
- [ ] **6.2 (D2) Reject corrupt commands.** From a console send `A12-1.0`,
  `Kabc`, `I991000`: each must answer `ERROR: ...` and **nothing moves**
  (`A12-1.0` used to command FULL EXTENSION).
- [ ] **6.3 (D3) Stall timer.** Run ≥10 normal moves in a row — none may warn
  early. Then carefully block an actuator: only after about 20 seconds without
  meaningful encoder progress, it emits `WARNING: Motor stalled` and continues
  until E-stop is used.
- [ ] **6.4 (D4) Small-move behavior.** Command a move ≤25 counts: immediate
  `DONE`, no motion, UI does not hang.
- [ ] **6.5 (D5) BUSY visibility.** Send a second move while one runs: host
  receives `BUSY` (used to be a silent drop → 30 s UI timeout).
- [ ] **6.6 Pulse cadence default (new).** Start pulsing with the pulse-rate
  firmware flag still OFF (bare `J`). Time the pulse period: it should be
  **~500 ms (2 pulses/sec)**, matching the UI's stated default — not the old
  200 ms. (This is the H7 drift fix: `DEFAULT_JERK_INTERVAL_MS = 500` in
  `config/constants.py` paired with the `jerkInterval` initializer in `motor.ino`.)
- [ ] **6.7 Validate host-settable cadence.** Numeric cadence is enabled by
  default for current firmware. Change the Treatment pulse-rate slider and
  confirm the physical cadence tracks it (the app sends `J<ms>`;
  out-of-range values are clamped to 100–5000 ms in firmware). If anything
  misbehaves, set `KNEESPA_PULSE_RATE_FIRMWARE=0`, restart for the bare-`J`
  fallback, and report.

---

## 7. Measurements to bring back (unblocks the frozen-convention code)

Batch-1 checklist §E. **These are the deliverables of the session** — the
frozen math in `kneespa.py`/`protocols.py` stays frozen until you supply
these numbers. Record everything, even if it looks obvious.

- [ ] **7.1 (E1) AFULLINCH ground truth.** Command `A12` moves of 1.0, 2.0,
  3.0 in from home; measure actual travel with a ruler.
  **Record: 1.0→____ in, 2.0→____ in, 3.0→____ in. Implied counts/inch:
  ______.** (Firmware assumes 430; `AXIAL_MAX 4600` implies ~10.7 in of
  travel vs the UI's 4 in limit — this measurement reconciles them.)
- [ ] **7.2 (E2) A-command zero-offset.** With AZERO set (6.1), check whether
  `A12<x>` targets land offset by AZERO counts from the intended physical
  position (the audit found the math drops the zero offset for non-zero
  targets). **Decide + record:** add `ZERO +` to the conversion in the
  follow-up code change, **or** recalibrate the marks around current behavior.
- [ ] **7.3 (E3) Horizontal (B) direction.** Verify which way increasing
  counts moves the horizontal actuator, and what counts correspond to `-25°`
  and `-5°`. The Pi-side formula and the `constants.py` comments currently
  disagree. **Record the true convention.**
- [ ] **7.4 (E4) Bootloader verdict** — carried from §3.4.

> After the session, these four feed a small "Batch 2" code change (adjust
> the conversion constants/offsets to match measured reality) — a software
> task I can do once you bring the numbers back.

---

## 8. Protocol v2 (optional, checksummed link)

Batch-1 checklist §D5a. Only after §4–§6 are clean.

- [ ] **8.1** Set `KNEESPA_PROTOCOL_V2=1` in the app environment and restart.
  Commands flow normally; acks show `DONE|<seq>` in the debug log; status
  frames end in `*XX`.
- [ ] **8.2** Send a deliberately corrupted framed command from a console
  (`#1:P70*FF`): it must be rejected with `ERR|1|Checksum mismatch` and
  **nothing moves.**
- [ ] **8.3** If anything misbehaves, set the flag back to `0` and report —
  the bare-framing link is the safe default.

---

## 9. GUI / touch verification (eyes on the device)

Batch-1 checklist §F. Restart the app (`sudo systemctl start
kneespa.service`) so it's running fullscreen on the touchscreen.

- [ ] **9.1 (F1) Treatment banner** overlays the top of every screen during a
  protocol, is readable at arm's length, the STOP button is comfortably
  tappable, and a fault turns it red and keeps it up.
- [ ] **9.2 (F2) PIN pad** keys are finger-sized, the in-field backspace is
  discoverable/tappable, digits mask correctly (single mask). Log in with the
  4-digit admin PIN you provisioned (§0).
- [ ] **9.3 (F3) Press feedback** — label-based controls (profile, home,
  assistance, time +/-, setup-page e-stop) visibly dim while pressed.
- [ ] **9.4 Fullscreen sanity (Phase C fix).** Confirm the app comes up
  genuinely fullscreen and frameless with no title bar and nothing clipped —
  the window flags are now set before `showFullScreen()`.
- [ ] **9.5 (F4) Fixed-geometry assessment.** At native resolution, note any
  clipped/overlapping widgets for a follow-up. **Record what needs moving:**
  ________________________________________________.

---

## 10. Supervised end-to-end treatment (dry run, no patient)

- [ ] **10.1** With the mechanism free and unloaded (or a test fixture), run
  **one complete protocol start-to-finish** from the GUI: login → select
  protocol → confirm the start dialog → watch the ramp, positioning, and
  pulse phases → let it complete (or stop it mid-run). Confirm the banner
  countdown, live pressure/angle readouts, and phase labels all track, and
  that completion releases traction and returns to idle.
- [ ] **10.2** Repeat with a **mid-run STOP** and with the **e-stop**, and a
  **mid-run settings change** (confirm the safety confirmation dialog appears
  and the change takes effect on accept / rolls back on cancel).

---

## 11. Sign-off & what to send back

**Ship-blocking gates (all must be checked):**
- [ ] §3 watchdog resolved (WDT-safe, or `ENABLE_WDT 0` recorded)
- [ ] §4.5 **e-stop GPIO polarity confirmed** (as-is, or inverted-and-fixed)
- [ ] §4.1–4.4 all stop paths halt + release in all three states
- [ ] §5 pressure ceiling + fault handling verified

**Bring back to unblock the final software change:**
- E1 counts/inch, E2 zero-offset decision, E3 B-axis convention, E4
  bootloader verdict (§7), plus the C5 load-cell calibration reading and any
  F4 layout notes.

**If you hit a wall:** stop, power down, and capture the serial log + what
you saw. Most items map to a specific code location — the e-stop polarity to
`protocol_controller.py:406/418/435/441`, the flags to `config/constants.py:147`
and `helpers/arduino.py:76`, the cadence to `config/constants.py`/`motor.ino` — so a
finding turns directly into a fix.

Sign-off: __________________  Date: __________
