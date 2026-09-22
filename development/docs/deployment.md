# Repository layout and device sync

`runtime/` is the shared release, `devices/` is state and optional provisioning,
and `development/` stays on the PC. Within each deployable area, the hardware
target is explicit: `raspberry-pi/` or `arduino/`.

For installation and maintenance entry points, use the
[Pi setup script reference](rpi/setup-and-maintenance.md). Its examples target
the reported `/home/pi/drx` installation; the sync defaults below remain `/home/pi/drx-2.0`.

```text
runtime/
  raspberry-pi/
    launch.sh
    main/                 # app, Python constants, UI, assets, requirements.txt
  arduino/motor/          # production sketch, HX711 helper, PlatformIO config
devices/
  local/raspberry-pi/     # active state on each Pi; ignored by Git
    config/kneespa.cfg    # calibration, support UUID, display device number
    data/user_pins.csv
    data/auth_state.json
    data/pending_uploads.json
    .env                 # operator/support/runtime settings
    cloud.env            # cloud device ID and token
    logs/                # app + serial logs and rotation segments
  profiles/<name>/raspberry-pi/   # PC copies, separately named for each device
  development/raspberry-pi/       # desktop simulator's independent state
  templates/raspberry-pi/        # tracked examples, not live device settings
  maintenance/                  # optional Pi diagnostics / Arduino sketches
development/
  docs/
  tests/                 # Python tests and firmware/ native tests
  scripts/               # audit/limit validation and cloud provisioning
  tools/                 # development previews, galleries, diagnostics
  sync/                  # PC-side deployment scripts
```

The application needs only `runtime/raspberry-pi/` plus writable device state.
Keep the directory nesting when copying. A Pi can also hold
`runtime/arduino/motor/` as firmware staging, but the `.ino` runs on its Arduino
after a separate build/flash. The source and AVR build remain usable without
copying `development/`; native tests require the full checkout on the PC/CI.
Python modules under `main/config/` are software, while `config/kneespa.cfg`
inside a device profile is mutable calibration. Hardware-specific Arduino
calibration/scale sketches are maintenance tools, not production firmware.

## Routine software and firmware sync

Run these from the PC in WSL/Linux with `bash`, `ssh`, and `rsync` installed:

```bash
PI_HOSTS="device-1-host device-2-host" bash development/sync/sync_pis.sh
PI_HOSTS="device-1-host device-2-host" bash development/sync/sync_pis.sh --apply
```

No flag means a dry run: it reports changes without stopping the service or
writing remote files. Apply checks the service points at the new entry point,
stops it, mirrors `runtime/`, and starts it only after successful transfer.
Stop, copy, and restart failures return a nonzero exit code. A failed copy
leaves the service stopped. Deletion is confined to the remote `runtime/`
directory; sibling device state and development files are outside the transfer.
Build outputs, caches, documentation, and accidentally misplaced state are filtered.
Do not manually mirror the repository root with `--delete`.

Defaults: SSH user `pi`, root `/home/pi/drx-2.0`, service `kneespa.service`.
Override with `PI_USER`, `DEST_ROOT`, `SERVICE`, and optionally `SSH_OPTS`.
`SOURCE_DIR` may select another release's **runtime directory**, not its root.
The retired `DEST_DIR` variable is rejected to prevent old deployment commands
from targeting the wrong tree. Root paths use shell-safe characters without spaces.

## Transfer selected state for one device

Profile names are PC folder labels; use one stable name per physical device.
They do not change the config's support UUID, display number, or cloud device ID.
Verify the host corresponds to that profile before applying a transfer.

```bash
# Preview, then download this device's calibration and IDs to its PC profile.
bash development/sync/sync_device_state.sh pull device-2 device-2-host config
bash development/sync/sync_device_state.sh pull device-2 device-2-host config --apply

# Send an intentionally edited config back to the same device.
bash development/sync/sync_device_state.sh push device-2 device-2-host config --apply

# Collect logs separately; they are never part of a software update.
bash development/sync/sync_device_state.sh pull device-2 device-2-host logs --apply
```

Categories are `config`, `credentials` (user PIN CSV), `environment` (both `.env`
and `cloud.env`), `logs`, and `uploads` (outbox snapshot). Logs and uploads are
download-only. Missing files are reported rather than silently skipped. For
environment provisioning, create both env files from the examples, leaving
unused entries blank. Neither script reads or prints secret file contents.

State transfers never delete files, and changed destination files receive
timestamped backup copies. Apply stops the service to keep mutable files
consistent and restarts it after success; failure leaves it stopped. Login
lockout state is device-owned and is not a push category. A download of pending
uploads is a backup, not permission to replay treatment records on another device.
State scripts target the default `devices/local/` on the Pi. For a custom service
state directory, transfer explicitly to that directory instead of using this helper.

## Upgrade an existing device

Do this once per device, with the application stopped. Preserve the old `main/`,
`config/`, `logs/`, `.env`, and `cloud.env` until migration is verified.

1. Stop `kneespa.service` and copy the new `runtime/` directory alongside the old
   files. For the first copy, use `rsync -avz runtime/ pi@HOST:/home/pi/drx-2.0/runtime/`
   from a clean checkout, or copy that directory manually. Routine sync rejects
   the old service entry point until step 3 is complete.
2. On the Pi run, from `/home/pi/drx-2.0`:

   ```bash
   python3 runtime/raspberry-pi/main/config/migrate_state.py
   ```

   This copies config (preferring root `config/kneespa.cfg` over the older
   `main/config/kneespa.cfg`), credentials, lockouts, pending uploads, env files,
   and logs into `devices/local/raspberry-pi/`. Existing destination files win.
   The source files remain intact. A completion marker prevents future launches
   from restoring revoked/deleted state. Failed copies raise an error, remove
   incomplete output, and can be retried. Allow disk space for the copied logs.
3. Update the systemd unit's `ExecStart` to
   `/home/pi/kneespa_env/bin/python /home/pi/drx-2.0/runtime/raspberry-pi/main/kneespa.py`.
   Adapt the user, virtualenv, and working directory to the actual installation.
   Use [the unit example](../../devices/templates/raspberry-pi/kneespa.service.example)
   as a reference. Run `sudo systemctl daemon-reload` and then
   `sudo systemctl start kneespa.service`. Update desktop shortcuts to
   `runtime/raspberry-pi/launch.sh`.
4. Verify the existing device identity, calibration, login, and logs before
   retiring the old folders. Use routine sync for subsequent updates.

A direct application launch performs the same migration before loading settings.
Explicit `KNEESPA_DEVICE_DIR` profiles are never auto-migrated from local state;
the migration CLI's `--device-dir` and `--project-root` are available for an
intentional import. Existing `--config` and individual `KNEESPA_*_PATH` overrides
remain supported and keep their explicit external paths.

New devices start with an uncalibrated config and an empty operator table.
Provision each device's own calibration, IDs and credentials; archived presets
are reference material and must be checked against the physical device.

## Local development

```bash
python -m pip install -r development/requirements-test.txt
python development/tools/run_local.py
python -m pytest
bash development/tests/firmware/run_native_tests.sh
python development/scripts/check_limits_sync.py
```

The desktop preview selects `devices/development/` unless `KNEESPA_DEVICE_DIR`
is explicitly set. For example, a disposable profile can be selected with
`KNEESPA_DEVICE_DIR=/tmp/drx-preview python development/tools/run_local.py`.
The repository's historical plans/audits retain references to their original
layout; use this document and the root README for current commands.
