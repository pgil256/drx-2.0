# KneeSpa / drx-2.0

PyQt5 control application for a motorized knee-traction therapy device:
a Raspberry Pi touch-screen kiosk drives an Arduino Mega over serial
(`/dev/serial0`), which commands three actuators (axial, horizontal,
lateral) via Pololu SMC motor controllers on I2C and reads an HX711
load cell (treatment pressure, up to 80 lbs).

## Layout

| Path | What it is |
|---|---|
| `main/kneespa.py` | Application entry point + UI controller |
| `main/helpers/` | Serial transport (`arduino.py`), protocol engine (`protocols.py`), reset sequence, auth, conversions |
| `main/config/` | Constants, runtime calibration config (`kneespa.cfg`) |
| `main/motor/` | Arduino Mega firmware (`motor.ino`) + native unit tests |
| `main/ui/` | Qt Designer `.ui` files, dialogs, widgets (incl. the treatment status banner) |
| `tools/calibrate.py` | CLI calibration tool (jog, marks, load-cell tare + known-weight factor) |
| `tests/` | pytest suite: unit + pty-based integration against a firmware-faithful FakeArduino |
| `rpi/` | Deployment notes, systemd unit example, `sync_pis.sh` deploy script |
| `docs/audits/`, `docs/plans/` | The 2026-06-11 full audit, improvement plan (with status), and the Flash Batch-1 hardware checklist |

## Running

```bash
python main/kneespa.py                  # on the Pi (requires RPi.GPIO, PyQt5)
python main/kneespa.py --debug --print-logs
```

## User provisioning & runtime secrets

`main/config/kneespa.cfg` (per-device calibration) and
`main/data/user_pins.csv` (login credentials) are runtime state and are
**not tracked in git** — the repo ships `*.example` templates. On first
run the app generates a default (uncalibrated) config and seeds an empty
users file; with zero users provisioned nobody can log in.

Provision users one of two ways:

- **Environment / `.env`** (preferred): set `ADMIN_PIN_HASH` /
  `USER_PIN_HASH` (values from `SecureAuthHelper.hash_pin_secure`), plus
  optional `ADMIN_USERNAME` / `ADMIN_EMAIL` etc. Plaintext `ADMIN_PIN` /
  `USER_PIN` also work but keep the PIN readable in the environment.
- **CSV**: add `pin_hash,username,email,status` rows to the runtime
  `user_pins.csv`. Point `KNEESPA_USER_PINS_PATH` at a file outside the
  checkout to keep credentials away from the repo entirely
  (`KNEESPA_CONFIG_PATH` does the same for the config file).

Generate a hash:

```bash
python -c "import sys; sys.path.insert(0, 'main'); \
from helpers.secure_auth import SecureAuthHelper; \
print(SecureAuthHelper.hash_pin_secure(input('PIN: ')))"
```

## Testing

```bash
python -m pytest                        # unit tests anywhere; integration tests need POSIX pty
bash tools/wsl_run_tests.sh             # full suite + firmware tests (WSL/Linux)
bash main/motor/run_native_tests.sh     # firmware suites (g++ + vendored Unity)
cd main/motor && pio test -e native     # same, via PlatformIO where available
```

CI (`.github/workflows/ci.yml`) runs the full Python suite, the firmware
native tests, and an AVR compile check of `motor.ino` for the Mega 2560.

### Physical touchscreen E2E

`tools/e2e_touchscreen.py` launches the real GUI and uses operating-system
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
python tools/e2e_touchscreen.py --setup --yes-move-hardware
python tools/e2e_touchscreen.py --actuators axial lateral --yes-move-hardware
python tools/e2e_touchscreen.py --protocols 1 2 3 --yes-move-hardware
python tools/e2e_touchscreen.py --video
python tools/e2e_touchscreen.py --all --yes-move-hardware
```

Actuator/protocol runs require `--yes-move-hardware`: remove the patient,
clear the mechanism, and keep an operator at the physical STOP throughout.
Each run writes a timestamped folder under `logs/e2e/` with `e2e.log`, raw
serial `TX`/`RX` in `serial.log` when the port connects, step screenshots when
available, and `summary.json`. Protocols are observed for 20 seconds by
default and then stopped through the permanent on-screen STOP; change this
with `--protocol-observe-seconds`.

## Deploying

```bash
./rpi/sync_pis.sh    # stops the service, syncs main/ (excluding device-local
                     # calibration/PINs/logs), restarts the service
```

### Display diagnostics

Install two double-clickable Pi desktop launchers:

```bash
bash rpi/install_display_diagnostics.sh
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

Protocol v2 (per-command sequence numbers + XOR checksums on commands
and status frames) is built into the firmware and the Pi transport but
disabled by default; enable with `KNEESPA_PROTOCOL_V2=1` after the
hardware checkout. Legacy unframed traffic keeps working either way.

Numeric pulse cadence (`J<ms>`) is enabled by default for the current
firmware, including live Treatment-slider changes. Set
`KNEESPA_PULSE_RATE_FIRMWARE=0` and restart for an immediate compatibility
rollback when operating a device with older bare-`J` firmware.

**Before flashing firmware to a device**, run the checkout list in
[docs/plans/2026-06-11-batch1-hardware-checklist.md](docs/plans/2026-06-11-batch1-hardware-checklist.md)
— including the watchdog/bootloader recovery check (A2) and the
position-convention measurements (E1–E3) that later math corrections
are gated on.

Known residual risk: there is no hardware E-stop that cuts motor power
independently of the MCU; see the audit §8 for the recommended future
hardware change.
