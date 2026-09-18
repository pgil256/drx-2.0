# KneeSpa / drx-2.0

PyQt5 control application for a motorized knee-traction therapy device:
a Raspberry Pi touch-screen kiosk drives an Arduino Mega over serial
(`/dev/serial0`), which commands three actuators (axial, horizontal,
lateral) via Pololu SMC motor controllers on I2C and reads an HX711
load cell (treatment pressure, up to 80 lbs).

## Layout

| Directory | Contents | Sync policy |
|---|---|---|
| `runtime/raspberry-pi/` | Python application, UI assets, dependencies, launcher | Shared software updates to every Pi |
| `runtime/arduino/motor/` | Production Arduino Mega firmware and build definition | Shared firmware updates; flash to the Arduino separately |
| `devices/local/raspberry-pi/` | This device's calibration, IDs, credentials, outbox, logs | Preserve during software updates |
| `devices/profiles/<device-name>/raspberry-pi/` | PC copies of a specific device's state | Explicit transfer for that device only; ignored by Git |
| `devices/templates/` | Provisioning examples and historical calibration presets | Copy selected files during setup |
| `devices/maintenance/` | Pi diagnostics and Arduino calibration/scale sketches | Optional maintenance only |
| `development/` | Documentation, Python and firmware tests, PC tools, sync scripts | Kept on the PC; excluded from routine deployment |

Git/CI metadata, `pytest.ini`, and this README remain at the repository root.
See [deployment and migration](development/docs/deployment.md) for the exact
device layout, upgrade steps, and sync commands. Firmware tests live under
`development/tests/firmware/`, separate from the shipped sketch.

## Running

```bash
python runtime/raspberry-pi/main/kneespa.py                  # on the Pi (requires RPi.GPIO, PyQt5)
python runtime/raspberry-pi/main/kneespa.py --debug --print-logs
python development/tools/run_local.py   # desktop preview with simulated hardware
```

## User provisioning & runtime secrets

`devices/local/raspberry-pi/config/kneespa.cfg` (calibration and identity) and
`devices/local/raspberry-pi/data/user_pins.csv` (login credentials) are device
state and are **not tracked in git** — the repo ships `*.example` templates. On first
run the app generates a default (uncalibrated) config and seeds an empty
users file; with zero users provisioned nobody can log in.

Replacing `runtime/` preserves all of `devices/`. The first normal application
launch copies legacy config, credentials, auth state, pending uploads, env files,
and logs into `devices/local/raspberry-pi/`, without overwriting existing files.
The original files remain for rollback. Migrate before removing any legacy folders.
Set `KNEESPA_DEVICE_DIR` to a device profile directory to select a different device;
explicit profiles do not import another device's legacy state. The desktop preview
uses its own `devices/development/` state. `--config PATH` and the existing
`KNEESPA_*_PATH` overrides still work.

Set the device number in `devices/local/raspberry-pi/config/kneespa.cfg`:

```ini
[Device]
number = 1
```

Valid numbers are **1, 2, and 3**, with **1** used when missing or invalid.
Keep the existing `id` entry; it is the separate unique id used for support.

Every application process creates a matching pair of logs in the selected
device's `raspberry-pi/logs/` directory:
`python_YYYYMMDD-HHMMSS-microseconds_PID.log` and
`arduino_YYYYMMDD-HHMMSS-microseconds_PID.log`. The Python log includes debug,
error, printed output, and Python stderr. The serial log timestamps sent (`TX`)
and received (`RX`) lines, including firmware diagnostics, using the app's
existing connection. Both files are created even if the Arduino cannot connect.
Each file rotates at 20 MiB into ascending numbered segments (`.log.1`, `.log.2`,
and so on); `.log` always contains the newest output. Individual log records stay
intact, so a single oversized record can exceed that target. A shared 1 GiB budget
covers both kinds of run logs and their segments across launches. Cleanup removes
the oldest closed files at startup, on rotation, and at most once per minute while
logging. Active base files are protected, including those owned by other running
processes; the budget can temporarily be exceeded between checks or if files
cannot be removed. Unrelated files and subdirectories are left alone.
`--print-logs` prints the last 200 lines of each current-run log, including preceding
segments when needed, without loading entire files into memory. `--sync-logs DIR`
copies logs and numbered segments from this folder after exit.
`KNEESPA_SERIAL_TRACE_FILE` can still request an additional serial copy for E2E runs.

Provision users one of two ways:

- **Environment / device-local `.env`** (preferred): set `ADMIN_PIN_HASH` /
  `USER_PIN_HASH` (values from `SecureAuthHelper.hash_pin_secure`), plus
  optional `ADMIN_USERNAME` / `ADMIN_EMAIL` etc. Plaintext `ADMIN_PIN` /
  `USER_PIN` also work but keep the PIN readable in the environment.
- **CSV**: add `pin_hash,username,email,status` rows to the runtime
  `user_pins.csv`. Point `KNEESPA_USER_PINS_PATH` at a file outside the
  checkout to keep credentials away from the repo entirely
  (`KNEESPA_CONFIG_PATH` does the same for the config file).

Generate a hash:

```bash
python -c "import sys; sys.path.insert(0, 'runtime/raspberry-pi/main'); \
from helpers.secure_auth import SecureAuthHelper; \
print(SecureAuthHelper.hash_pin_secure(input('PIN: ')))"
```

## Cloud patient settings and treatment records

DRx connects to the KneeSpa cloud Device API for patient PIN lookup, treatment
settings, and session history. Operator PIN login remains local. See
[Cloud integration](development/docs/cloud-integration.md) for provisioning, supported
settings, upload status, offline behavior, and verification instructions.

## Testing

```bash
python -m pytest                        # unit tests anywhere; integration tests need POSIX pty
bash development/tools/wsl_run_tests.sh             # full suite + firmware tests (WSL/Linux)
bash development/tests/firmware/run_native_tests.sh     # firmware suites (g++ + vendored Unity)
cd runtime/arduino/motor && pio test -e native  # same, via PlatformIO where available
```

CI (`.github/workflows/ci.yml`) runs the full Python suite, the firmware
native tests, and an AVR compile check of `motor.ino` for the Mega 2560.

### Physical touchscreen E2E

`development/tools/e2e_touchscreen.py` launches the real GUI and uses operating-system
mouse events at the physical 1366x768 screen coordinates. It can test the
automatic reset acknowledgement, PIN login, Setup actuators, protocols 1-3,
and the video player. It does not call Qt slots directly.

On the Raspberry Pi, install the click driver and optional screenshot helper:

```bash
sudo apt-get install xdotool scrot
```

Stop any already-running KneeSpa service first so only the E2E-launched app
owns `/dev/serial0`. Then run one of:

```bash
python development/tools/e2e_touchscreen.py --setup --yes-move-hardware
python development/tools/e2e_touchscreen.py --actuators axial lateral --yes-move-hardware
python development/tools/e2e_touchscreen.py --protocols 1 2 3 --yes-move-hardware
python development/tools/e2e_touchscreen.py --video
python development/tools/e2e_touchscreen.py --all --yes-move-hardware
```

Actuator/protocol runs require `--yes-move-hardware`: remove the patient,
clear the mechanism, and keep an operator at the physical STOP throughout.
Each run writes a timestamped folder under `devices/local/raspberry-pi/logs/e2e/` with `e2e.log`, raw
serial `TX`/`RX` in `serial.log` when the port connects, step screenshots when
available, and `summary.json`. Protocols are observed for 20 seconds by
default and then stopped through the permanent on-screen STOP; change this
with `--protocol-observe-seconds`.

## Deploying

```bash
PI_HOSTS="<verified-device-host>" bash development/sync/sync_pis.sh --dry-run
PI_HOSTS="<verified-device-host>" bash development/sync/sync_pis.sh --apply
```

`PI_HOSTS` is required; verify the current device addresses before deployment.
The script does not fall back to the historical host list. Apply stops the service,
syncs only `runtime/`, and restarts after a successful copy. Firmware is staged on
the Pi, not flashed automatically. Existing installations need the one-time
[service-path update](development/docs/deployment.md#upgrade-an-existing-device).
Use `development/sync/sync_device_state.sh` for explicit per-device transfers.

### Display diagnostics

Install two double-clickable Pi desktop launchers:

```bash
bash devices/maintenance/raspberry-pi/install_display_diagnostics.sh
```

Use **KneeSpa - Collect Display Baseline** once while the display and touch are
working. If the monitor fails again, use **KneeSpa - Capture Display Failure**
before unplugging cables when possible. Both launchers are read-only and save
timestamped reports under `~/KneeSpa-display-diagnostics/`.

## Safety and warning behavior

The physical STOP input, on-screen EMERGENCY STOP, and explicit firmware
`X` command are the motion-interrupting paths. Other device conditions
(heartbeat, sensor, travel, pressure timeout, and motor stall) emit advisory
`WARNING:` notices without stopping or resetting operation. Treatment pressure
commands remain capped at 80 lbs; measured pressure warns above 100 lbs.
The firmware still uses its watchdog and performs bounded traction release
after an E-stop. The Pi surfaces warnings in the always-visible treatment
banner without changing protocol state.

Firmware diagnostics (everything the sketch prints on its USB debug
serial, such as I2C position-read failures and per-frame actuator
positions) are also sent to the Pi as `LOG|<line>` frames and logged at
INFO as `Firmware: ...`, so device and host output interleave in one
console/log. `LOG|` lines are informational only; nothing acts on them.

A firmware parse rejection (`ERROR: Invalid I value`, `Checksum mismatch`,
`Malformed frame`, ...) means the command never executed, so the Pi
transport resends that command once before reporting a command fault. A
corrupted byte on the UART therefore costs one retry instead of an
emergency stop. Enabling protocol v2 (`KNEESPA_PROTOCOL_V2=1`) adds a
checksum to every command so a corrupted digit that still parses is also
caught and resent rather than executed.

Protocol v2 (per-command sequence numbers + XOR checksums on commands
and status frames) is built into the firmware and the Pi transport but
disabled by default; enable with `KNEESPA_PROTOCOL_V2=1` after the
hardware checkout. Legacy unframed commands keep working either way.

Firmware `2026-09-10-FAILSAFE-7` always checksums position/pressure reports,
even with protocol v2 disabled. `L6` now returns the same checksummed
`STATUS_START|S|...|STATUS_END*XX` format as periodic status. The Pi rejects
damaged reports before updating positions or evaluating limits; after the
first valid checksummed report it also rejects missing checksum trailers
and unchecked legacy `S|...` / `A|...` reports. Valid readings beyond the
travel limits still produce the normal warnings.

This addresses the September 10 log where firmware reported lateral **1940**
but the Pi received **3940**, amid other garbled UART traffic. Deploy both
the Pi parser update and FAILSAFE-7 firmware for protection with default
settings. A Pi-only update with older firmware and v2 disabled still accepts
legacy unchecked reports and cannot detect a digit changing into another
valid digit. FAILSAFE-2 through FAILSAFE-6 already checksum periodic status
when launched with `KNEESPA_PROTOCOL_V2=1` after hardware checkout; for example,
from the project root: `KNEESPA_PROTOCOL_V2=1 python3 runtime/raspberry-pi/main/kneespa.py --debug --print-logs`.
Checksums detect transmission damage; the underlying UART corruption and
the separately logged stall near 1940 counts still need device diagnosis.

Numeric pulse cadence (`J<ms>`) is enabled by default for the current
firmware, including live Treatment-slider changes. Set
`KNEESPA_PULSE_RATE_FIRMWARE=0` and restart for an immediate compatibility
rollback when operating a device with older bare-`J` firmware.

**Before flashing firmware to a device**, run the checkout list in
[hardware checklist](development/docs/plans/2026-06-11-batch1-hardware-checklist.md)
— including the watchdog/bootloader recovery check (A2) and the
position-convention measurements (E1–E3) that later math corrections
are gated on.

Known residual risk: there is no hardware E-stop that cuts motor power
independently of the MCU; see the audit §8 for the recommended future
hardware change.
