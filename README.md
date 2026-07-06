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

## Deploying

```bash
./rpi/sync_pis.sh    # stops the service, syncs main/ (excluding device-local
                     # calibration/PINs/logs), restarts the service
```

## Safety architecture (since firmware `2026-06-11-FAILSAFE-2`)

The firmware fails safe on its own: AVR watchdog, a 3 s host-heartbeat
timeout, the physical STOP pin and the 80 lb pressure ceiling enforced
in every state, non-blocking validated load-cell reads, and an
autonomous bounded traction release on every fault path. The Pi layer is
defense-in-depth on top: a single-owner serial transport with real
disconnect detection, firmware `ERROR:` lines surfaced as persistent
operator alarms, an always-visible treatment banner with a permanent
STOP, and calibration-state gating (an uncalibrated or corrupt config
blocks treatment loudly instead of running on generated defaults).

Protocol v2 (per-command sequence numbers + XOR checksums on commands
and status frames) is built into the firmware and the Pi transport but
disabled by default; enable with `KNEESPA_PROTOCOL_V2=1` after the
hardware checkout. Legacy unframed traffic keeps working either way.

**Before flashing firmware to a device**, run the checkout list in
[docs/plans/2026-06-11-batch1-hardware-checklist.md](docs/plans/2026-06-11-batch1-hardware-checklist.md)
— including the watchdog/bootloader recovery check (A2) and the
position-convention measurements (E1–E3) that later math corrections
are gated on.

Known residual risk: there is no hardware E-stop that cuts motor power
independently of the MCU; see the audit §8 for the recommended future
hardware change.
