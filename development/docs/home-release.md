# Verified final home release

The app and firmware must be installed as a compatible pair. Treatment start
requires `DRX-HX711-NB2` and the `HOME_RELEASE_V1` capability. The firmware version
is `2026-10-28-DRX2-release-margin`. Older three-field identities remain readable,
but cannot authorize treatment. Disconnection, reset initiation, `Reset|`, and
`Ready to Go` invalidate the identity and pressure authorization.

After the timed phase, protocols 1–4 stop pulsing and protocols 2–4 try to
centre the lateral actuator. That centre is best effort: if it is not
confirmed, the miss is logged and the release and zero still run, then the
centre is tried once more unloaded. A second miss sends `X` and is only logged;
the next treatment start re-centres anyway. An operator stop or controller
fault during centering still cancels the release. The app invalidates its
baseline authorization, sends `X`,
then `R|<12 lowercase hex characters>`. Final cleanup does not send `P0`.
Pre-treatment zeroing remains `L1|BASELINE`; treatment pressure adjustments keep
their existing `P` semantics.

Firmware uses the existing configured `AZERO`, with an inclusive ±25-count
band. It only retracts from above that band, and stops 10 counts inside it
(home + 15) rather than on the edge, so rebound or feedback noise after the
stop stays in band. If a reading after the stop is above the band, it retracts
again. A reading below the band stops the motor and is held, never corrected
outward; the release is rejected only if that reading persists for 500 ms. One
low reading mid-travel is treated as a feedback dropout, not a verdict. A
release that starts inside the band verifies the stop without travel.
Fresh calibrated pressure, fresh controller-12
position, acknowledged stop writes, no unresolved stops, and zero accepted
motor outputs are required. Position must remain within two counts for at
least 250 ms after the axial stop. Pressure freshness, pressure limits, I2C,
motor writes, and the physical stop remain authoritative. Release times out
after 60 seconds; the host waits up to 62 seconds.

Every controller position read, including those during release and the
final tare, repeats a failed I2C exchange up to three times before it counts
as a failure. Each miss is reported as
`DIAG|I2C|POSITION_FAILED|<device>|<attempt>|<attempts>` and logged by the
app as a warning. A miss with no following `FAULT|` was recovered.

The release reply is evidence of a stopped home position, not zero pressure:

```text
HOME_RELEASE|token|configured_home|actual_position|pre_zero_pressure_lb|old_offset|factor
```

The host checks the token, home calibration, actual position and factor before
sending `L1|HOME|token`. A generic motion completion or `DONE` cannot authorize
this operation. The final tare requires at least ten samples spanning 900 ms,
with a range no greater than 0.5 lb. Every candidate sample, including the
committing sample, requires another valid stationary home read. Failure keeps
the old offset. Stop, fault, movement and configuration changes invalidate the
home proof. The firmware allows 30 seconds; the host allows 32 seconds and
retries once after a two-second stationary settle only for explicit `UNSTABLE`.

The host requires `TARE|STARTED`, a matching-factor `TARE|OK`, and completion.
For protocol v2 the completion must carry the current command sequence. Faults
and cancellation remain latched even if success replies have arrived.

## Outcomes and audit evidence

`completed` means the timed treatment and final zero both succeeded. A failed
cleanup after the timed phase is `completed_cleanup_failed`, with
`treatment_completed: true`. The UI reports:

```text
Treatment completed, but cleanup needs attention: <reason>
```

The session preserves active treatment duration independently of cleanup time
and uploads one immutable record through the existing durable outbox. Records
include `treatment_completed`, `cleanup_warning`, and `underlying_error` alongside
the existing outcome. The cloud receiver must accept the new outcome and fields;
a receiver rejection retains the exact record in the outbox for correction.
This change does not update or deploy the cloud receiver.

Application audit entries retain the release token, configured home, actual
home position, pre-zero pressure, old offset, factor and accepted new offset.
The release evidence is logged before tare begins, so it survives a tare
failure. Existing raw serial and HX711 diagnostics remain enabled.

Cleanup faults invalidate pressure authorization, keep recovery explicit and
display the warning even if a stop handler already changed the UI state.
There is no automatic reset, reboot, homing or retry after these faults.

## Validation

- `python -m pytest`: host parsing, cancellation, all four protocols in pulse
  and hold, UI/session outcomes and durable upload behavior.
- `development/tests/unit/test_home_release.py`: release correlation, tare
  sequencing, bounded retries, capability gating and final pulse-stop failure.
- `development/tests/unit/test_simulator_transport.py`: production Arduino
  transport/parser and protocol worker through the simulator's fragmented TCP
  byte stream, in both v1 and v2 modes.
- `bash development/tests/firmware/run_native_tests.sh`: actual sketch against
  fake I/O. `home_release_cases.h` adds 30 release/tare interlock cases, including
  home 100 / actual 83 / residual 36.61 lb, failed stop writes, short/timed-out/
  out-of-range position replies and failure on the committing tare sample.
- Compile `runtime/arduino/motor` for `arduino:avr:mega` before installation.

Generated local validation logs and build products belong under
`.cache/home-release/`. No device is flashed by these tests.

Local validation on September 23, 2026: 1,817 host tests passed, 110 skipped;
192 native sketch tests passed with zero failures. The native suites were built
on Windows with Zig 0.16.0 C/C++ and the vendored Unity sources. The Mega build
used 36,958 bytes flash (14%) and 2,930 bytes global RAM (35%). After the final
audit-log formatting change, the 79 affected host regression tests also passed.
The generated `validation.json` records hashes of the changed source files.

Before deployment, bench-test the matching pair with a suitable fixture.
Confirm the machine's actual home calibration, retraction direction, stopping
distance, the 250 ms / two-count stationary test, residual resting-load zeroing
and fault/cancel handling. Save pre/post-zero logs. Stop evidence is accepted
controller output plus stationary position feedback, not independently measured
motor velocity. A new resting baseline does not explain the previous baseline
shift or establish that there is no physical load. This change does not resolve
the separate pulse-recovery timeout or axial I2C incidents.
