# Hardware Tests & Calibration

The Device page provides separate Hardware Tests and Calibration workflows.
Hardware Tests covers the three position-feedback actuators, leg-length
actuator, HX711 load cell, communication, and stop inputs without changing
calibration. Password-protected Calibration stages actuator and load-cell
configuration changes for review. Both keep an evidence report and share the
same movement and stop safeguards. They do not certify the device or replace the
responsible technician's approved physical bench procedure.

Use an unloaded device with no patient present. Have suitable travel and angle
references available, and a known force or reference force gauge with an
appropriate fixture for load-cell work. The exact installed hardware and
available reference tools have not been independently confirmed. Record extra
sensors, switches or accessories in the inspection notes, and mark unavailable
checks skipped rather than assuming they passed.

## Access and firmware

1. Log in normally. Finish treatment, manual movement and reset operations.
2. Open **Device** (the wrench), then its third tab, **Service**. Choose
   **Hardware Tests** for supervised checks, or **Calibration** to adjust settings.
   Tests cannot record calibration marks, calculate factors, or save
   calibration, including through the controller action dispatcher.
3. Service requires the separate six-digit technician PIN. On first use, a logged-in
   administrator creates it and enters it again to confirm. A non-administrator
   cannot perform this initial enrollment.

There is no default service PIN and no fallback to a treatment-login PIN.
Every new Service visit requires technician authentication; leaving locks the tab.
Calibration focuses on measured marks and load-cell factors, while tests contain
pass/fail observations, leg-length checks and bench inspections. The salted PBKDF2 hash and
attempt-limit state are stored in
`devices/local/raspberry-pi/service-pin.json` by default. The selected
`KNEESPA_DEVICE_DIR` changes the device root; `KNEESPA_SERVICE_PIN_PATH` can
override the credential-file location. Never put this file in `runtime/` or
commit a device's credential state.

Provisioned installations may supply a compatible PBKDF2 record through
`KNEESPA_SERVICE_PIN_HASH`; its value is a hash, not a plaintext PIN. It takes
precedence over the file's hash. Writable device storage is still required to
persist attempt limits. Five consecutive failed attempts cause a 60-second
lockout, which survives closing the dialog or restarting the application.
Unreadable credential state blocks access rather than enabling re-enrollment.
See [service_auth.py](../../runtime/raspberry-pi/main/helpers/service_auth.py).

If initial setup failed, the wizard can open for diagnostics and load-cell
calibration while movement stays locked. Fresh raw load-cell capture does not
depend on a working position sensor. Save a measured repair, remove the reference
load, close, and reset explicitly; a fault never grants permission to move.

Deploy the matching Pi application and Arduino firmware. This feature's firmware
identity is **`2026-09-18-DRX2-NB2-SERVICE`** and its load-cell driver identity is
`DRX-HX711-NB2`. Copying a sketch to the Pi does not flash the Arduino; follow
the project's separate firmware deployment process.

The wizard requires the new read-only **`D` hardware-diagnostics command**,
which probes the three position controllers and reports their response health,
the physical stop input, and whether a leg output is commanded. It neither
starts a motor nor clears a fault. The existing `T` response supplies firmware
identity and HX711 diagnostics. Missing or stale hardware diagnostics keep
service motion unavailable; a successful keepalive alone is insufficient.
The `D` response is:

```text
DIAG|HARDWARE|<axial_ok>|<horizontal_ok>|<lateral_ok>|<stop_pressed>|<fit_active>
```

Fields are `0` or `1`. Controller response health does not establish position
accuracy, and the leg-output flag is not position feedback. See
[motor.ino](../../runtime/arduino/motor/motor.ino) and
[deployment.md](deployment.md).

## Guided workflow

**Preparation.** Confirm no patient, clear travel paths, accessible physical
emergency stop, operator presence, and visual inspection. Confirm that measuring
tools are available or that unsupported checks will be skipped. Opening the
wizard and selecting a step do not request movement.

**Connection and sensors.** Read the connection and diagnostics, inspect the
stationary position and load readings, and watch for instability or implausible
values. Later movement should produce corresponding position changes. Record
the operator's observation; diagnostics do not substitute for inspecting sensor
behavior and wiring.

**Axial, horizontal and lateral.** Begin with a small bounded jog, observe
direction and smooth travel, then reverse. Each jog and move to a recorded point
requires confirmation that the device is unloaded, the path is clear and the
physical stop is accessible. The controller requires fresh, stable feedback and
enforces the supported position envelope. Wait for the move to complete and
settle before recording another point.

Measure the physical position, enter it, and choose **Record current reading**.
Entering a measurement alone does not move the actuator. Existing table entries
are labeled **Existing / unverified**; captured entries are labeled **Recorded
this session**. Record intermediate points and the required endpoints:

| Axis | Physical measurement | Configuration table | Required endpoint measurements |
| --- | --- | --- | --- |
| Axial | Distance in inches | `AMarks` | 0.0 and 4.0 inches |
| Horizontal | Platform angle in degrees | `BMarks` | −25° and +5° |
| Lateral | Platform angle in degrees | `CMarks` | −20° and +20° |

Use **Move to selected point** to revisit a point and compare it with the
physical reference. Check repeatability when approaching from both directions.
Do not drive into a mechanical end stop to discover travel limits. If a required
point cannot be reached safely, stop and document the unresolved condition;
do not substitute a guessed measurement. Edited tables require endpoint
coverage, supported feedback counts and consistent position ordering.

**Optional travel factors.** Capture a stationary start, jog to a stationary
end, and measure actual actuator stroke between them in inches. Choose
**Calculate proposed factor**. For horizontal and lateral actuators, this means
actuator stroke, not platform angle. The proposed value is:

```text
factor = abs(end_counts - start_counts) / measured_inches * 6
```

`a_factor`, `b_factor` and `c_factor` use the legacy counts-per-six-inches
distance-readout convention. They are not travel limits and do not by themselves
recalibrate the firmware's legacy inch command. Angle motion uses measured marks.
Initially, axial position calibration is opt-in: saving a session that records
both measured 0.0- and 4.0-inch endpoints enables
`Options.axial_service_calibrated`. Supported calibrated axial distance moves
then interpolate `AMarks` and use raw position commands. Existing installations
retain their legacy behavior until that measured table is enabled. See
[hardware_service.py](../../runtime/raspberry-pi/main/helpers/hardware_service.py)
and [kneespa.py](../../runtime/raspberry-pi/main/kneespa.py).

**Leg-length actuator.** Run brief retract and extend checks and observe actual
direction, smooth motion and stopping. The wizard coordinates the existing Pi
and Arduino drive paths. There is no position feedback for this actuator in
the current interface: elapsed drive time cannot prove travel distance or
calibrate position. Record that limitation along with the physical observations.
After any leg service movement, reset Arduino and then use the leg-length row's
**Reset** control to restore its position estimate before normal leg jogs.

**Load cell.** With the device stationary and unloaded, capture the raw unloaded
sample. Apply a known reference force with suitable bench equipment, let it
settle, and capture the known-force sample. Enter the independently known force
in pounds and calculate the proposed load-cell factor:

```text
counts_per_pound = (loaded_raw - unloaded_raw) / reference_pounds
```

The controller requires fresh, stable raw samples. Capturing a new unloaded
point invalidates the earlier loaded point. Captures do not move or tare the
device. The proposed factor changes `Options.calibration`; the unloaded sample
is evidence, not a permanently stored tare offset. After saving and resetting
unloaded, independently verify zero, several reference forces, repeatability
and drift. This page never starts a pressure-building or pulse sequence.

## Stops and additional bench checks

Perform the **stationary UI stop first**, then the **physical stop input** check:

1. With no motion active, choose **Check stationary UI stop**. This requests the
   software stop and ends the session's ability to move.
2. Choose **Check physical stop input** and follow the displayed instructions to
   press the physical emergency stop. Observe and record its input response.
3. Record the actual observation. The controller requires both the transmitted
   software stop and observed physical input before accepting an observed pass
   for this combined step.

The stationary checks remain available after the first stop. If the physical
stop happens first, the software check remains incomplete: close, perform the
normal reset/recovery process, and use a new session to do the software check
first. The wizard does not issue an extra software stop to override the physical
stop's existing firmware recovery behavior.

These checks do not prove stopping distance, pressure release, or safe restart
under load. The following individually recorded bench observations start as
**Not tested**:

| Record | Evidence required from the physical bench procedure |
| --- | --- |
| Pressure regulation & pulse | Actual pressure-control and pulse behavior with a suitable test fixture |
| Independent load reference / repeatability | Comparison against an independent force reference after calibration |
| Loaded motion stop & safe release | Dynamic stop and release behavior under the approved test conditions |
| Heartbeat / communication-loss watchdog | Response and recovery under controlled link-loss conditions |
| Power-loss & restart safety | Controlled power interruption and restart behavior |
| Installed limits & interlocks | Behavior of the switches/interlocks actually fitted to this device |
| Cabling, mountings & mechanical condition | Inspection of connections, strain relief, fasteners, binding and abnormal behavior |

Use the responsible technician's existing approved bench protocol, a suitable
test rig, and no patient. The wizard only records these observations; it does
not automatically inject faults, remove power, run loaded stop tests, or drive
into mechanical or pressure limits. Enter the procedure/reference, conditions
and measured outcome for each observed pass or failure. Mark missing equipment,
unavailable procedures or untested hardware as skipped or leave it not tested.
Use the device's approved acceptance criteria; this manual introduces no new
force, accuracy or stopping-distance acceptance thresholds.

## Review, persistence and recovery

**Review & save** lists the individual observed passes, failures, skipped and
incomplete checks separately from the proposed configuration changes. Saving is
independent of whether all checks passed. It is not approval for patient use.

Only **Save reviewed calibration** writes the draft. The model validates edited
settings, makes a timestamped `.bak` beside the active configuration file
(including a custom `--config` path), and writes the new configuration atomically.
Unrelated settings are retained. The application updates its saved configuration
in memory, then blocks further movement so it cannot mix new settings with the
Arduino's previous settings.

Remove external reference loads, close the wizard, and explicitly choose
**Setup → Reset Arduino**. Follow the existing stop/reset prompts and wait for
initialization to finish. This reset applies the firmware settings and performs
the unloaded initialization/zeroing sequence. Verify the changed calibration
physically afterward before releasing the device for use. Saving does not
automatically reset, home, tare or resume movement.

**STOP** stays visible during service actions. Motion timeout, rejected commands,
lost communication, invalid feedback or stop activation end active movement and
require reset before more motion. Closing during movement stops it before any
discard question. Unsaved configuration changes can be discarded; recorded
observations and report export remain available after an aborted session.
Even successfully completed service movement requires a deliberate reset on
exit, including when no settings were edited, because normal position estimates
must be re-established before the next jog.

**Export service report** writes JSON under
`devices/local/raspberry-pi/service-reports/hardware-<session>.json` by default,
or under the selected device state's `service-reports/` directory. Saving and
closing also export the session. Reports include technician username, firmware,
configuration path, diagnostic snapshots, raw captures, events and individual
results. Missing results use `not_tested`; skipped and failed observations use
`skip` and `fail`. There is no inferred overall pass or certification. PINs are
not included. Export failures are reported in the GUI and logs; confirm the file
exists when retaining service evidence. Keep reports with their device state,
outside routine `runtime/` software sync.

## Verification before deployment

Software simulation cannot establish physical safety or measurement accuracy.
Complete both software verification and the applicable physical bench acceptance
before deploying these changes to a treatment device.

For developers, run from the repository root:

```bash
python -m pytest development/tests/unit/test_service_auth.py development/tests/unit/test_hardware_service_model.py development/tests/unit/test_hardware_service_controller.py development/tests/unit/test_hardware_service_dialog.py development/tests/unit/test_firmware_protocol.py
python -m pytest
bash development/tests/firmware/run_native_tests.sh
```

The native firmware command requires a C/C++ compiler and Bash. POSIX serial
integration tests require WSL/Linux and skip on Windows. Use the project's
firmware build process to compile the production target as well. These tests
cover credential handling, draft persistence and validation, guarded service
commands, UI confirmation/stop behavior, diagnostic parsing and native firmware
logic; they do not stand in for real hardware tests.

The deployment bench checklist is:

- Verify the physical device/profile match, back up its active configuration,
  and confirm the matching firmware identity and live `D` diagnostics.
- Check first-admin enrollment, separate service login, non-admin enrollment
  refusal, and attempt limiting without exposing the credential.
- Verify movement ownership, confirmation before every requested move, fresh
  feedback gating, accessible STOP, cancellation, and reset requirements using
  the approved bench procedure.
- Measure direction, usable travel, reference-point accuracy and repeatability
  for all three feedback actuators; inspect both leg-drive directions and stops.
- Save a controlled measured change, inspect its backup and report, explicitly
  reset unloaded, and compare the resulting motion/readings to independent
  references. Confirm unchanged settings and device identity remain intact.
- Complete the stationary software-then-physical stop sequence. Separately
  perform and document the applicable pressure/pulse, loaded stop/release,
  watchdog, power/restart and installed-interlock acceptance checks with the
  approved fixture and procedure.
- Reconcile every installed hardware item with the report. Keep failures,
  missing evidence and skipped checks visible, and resolve them according to
  the device's release process before patient use.

Controller behavior and report schema are implemented in
[hardware_service_controller.py](../../runtime/raspberry-pi/main/controllers/hardware_service_controller.py).
