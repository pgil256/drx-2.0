# Maintain the existing Buster Pi

This is the selected maintenance path for the reported Pi 4 at `/home/pi/drx`.
It keeps Raspbian 10 Buster and the distribution's Python 3.7. System Python is
updated by APT to whatever signed Buster revision the configured repositories
provide. Its visible version may remain `3.7.3` despite a package revision change.
It does not install Python 3.13, switch distributions, or restore upstream support.

## Run on the Pi

Copy the updated `devices/` tools and
`runtime/raspberry-pi/main/requirements.txt` to `/home/pi/drx`. Routine runtime
sync does not copy `devices/`. Run as the normal `pi` desktop user, not with sudo:

```bash
cd /home/pi/drx
bash devices/update_buster.sh --use-legacy-repository
```

Without `--apply`, this is a read-only preflight and plan; it does not refresh APT
or contact package indexes. `--use-legacy-repository` includes the Buster mirror
repair described below. Before applying, keep an SD-card backup and perform maintenance
with the device unoccupied. Close KneeSpa and the firmware updater. If KneeSpa
runs as a service, stop it while the device is idle:

```bash
sudo systemctl stop kneespa.service
```

An absent service is fine; do not run that stop command if you use only the
desktop launcher and no unit is installed. Then apply:

```bash
bash devices/update_buster.sh --apply --use-legacy-repository
```

The script requests sudo for package-manager operations and source-file repair. Keep the SSH
session connected until it finishes. It does not restart the app or reboot.
After a successful update, reboot during the maintenance window and check
startup, login/calibration, stop behavior, serial connection, video and audio
before treatment use. Dependency import checks do not validate motor behavior.

## Fix the Buster repository 404

The Pi's first update attempt stopped at `apt-get update` with:

```text
http://raspbian.raspberrypi.org/raspbian buster Release
404 Not Found
The repository ... no longer has a Release file.
```

That attempt refreshed some package indexes but installed or upgraded no packages.
Buster moved to the [official Raspbian legacy archive](https://legacy.raspbian.org/raspbian/dists/buster/).
The [Raspbian maintainer's announcement](https://forums.raspberrypi.com/viewtopic.php?t=237469)
confirms that move. Use the updated wrapper/helper and the commands above to retry.

With `--use-legacy-repository`, the updater backs up each affected source file
inside the maintenance record's `apt-sources/before/` directory, then replaces
recognized Buster entries using `raspbian.raspberrypi.org`, `archive.raspbian.org`
or `mirrordirector.raspbian.org` with `https://legacy.raspbian.org/raspbian`.
It supports `.list` files and Buster-only `.sources` stanzas. Existing components,
source options, comments and disabled entries are preserved. It leaves
`archive.raspberrypi.org/debian` and Tailscale's repository alone.

APT still verifies signatures with the installed keys; the repair adds no trust,
signature, TLS or date-check bypass. It supplies archived Buster packages, not
renewed security support. Without the option, recognized retired mirrors produce
an actionable error before package operations. Once repaired, repeating the
command makes no further source changes.

If APT subsequently fails, the original source backup and proposed replacement
remain in the record, and the repaired URL stays installed. Other repository,
key or expiry errors require separate diagnosis; do not change `buster` to a
newer suite to resolve them.

## What changes

- Refreshes the existing Buster APT repositories, simulates `dist-upgrade`, and
  applies available upgrades with `--no-remove`. Installs Python 3.7, development
  headers, pip/venv support, system PyQt5, GPIO, VLC, audio and build tools.
  Existing edited package configuration files are retained with `--force-confold`.
- Installs Python 3.7-compatible packaging tools: pip 24.0, setuptools 67.8.0,
  wheel 0.42.0. No `sudo pip` or replacement of `/usr/bin/python3` is used.
- Installs the checked-out runtime `requirements.txt`: RPi.GPIO 0.7.1, pyserial
  3.5, python-dotenv 0.21.1, configparser 5.3.0, python-vlc 3.0.21203.
  The configparser distribution is retained for legacy installs; the app's
  `import configparser` uses Python's standard library.
- Selects Python like the desktop launcher: `KNEESPA_PYTHON`, project
  `kneespa_env`, project `.venv`, `~/kneespa_env`, then `/usr/bin/python3`.
  Installs into an existing selected virtualenv, or into the desktop user's
  Python user-site directory when using system Python. It never uninstalls
  APT-owned Python packages. If a service uses a different interpreter, select
  that interpreter explicitly using `KNEESPA_PYTHON=/absolute/path/to/python`.
- Installs/maintains PlatformIO 6.1.19 and compatible dependencies in
  `~/.local/share/kneespa/platformio`, matching the device's reported Core version.
  Use `--skip-firmware-tools` to omit this step. It does not update installed AVR
  platforms/libraries, compile firmware, or open/flash the Arduino.
- Runs `pip check` and imports the native Qt/GPIO/VLC dependencies without
  launching KneeSpa, setting GPIO pins, or opening the serial port.

Do not use a different user to apply these updates: a user-site installation is
visible to that user only. The script refuses a root invocation and disabled
Python user-site packages. PyQt5 remains supplied by APT, not a pip Qt wheel.

## Failures and records

The script rejects enabled APT suites outside the Buster family, including
moving aliases such as `stable`. The explicit legacy-repository option repairs
only the known retired Buster mirror URLs above. It does not import new keys,
disable signature/TLS/date checks, remove held packages, autoremove packages,
or use `rpi-update`. Other unavailable repositories stop the update. Send the
repository error for diagnosis instead of changing the distro name in the sources.

Package updates require at least 1 GiB free before starting; APT can require more
for a particular transaction. An active app, service, or firmware launcher blocks
the update. The shared desktop/firmware lock is held throughout maintenance.

Private logs, requirement copies, and before/after inventories are saved under
`devices/local/raspberry-pi/maintenance/buster-<timestamp>-<id>/`, or the selected
`KNEESPA_DEVICE_DIR` state root. These records are not complete backups or an
automatic rollback mechanism. An interrupted or failed run returns nonzero;
completed APT/pip changes remain. Calibration, credentials and treatment records
are not read, copied, or rewritten by the maintenance script.

System-wide upgrades can affect SSH, display drivers and audio. Retain physical
access and the original SD backup for recovery. Review the result before
reopening the app; do not infer hardware readiness from `SUCCESS` alone.

## Version references

- [pip 24.0 / Python >=3.7](https://pypi.org/project/pip/24.0/)
- [setuptools 67.8.0 / Python >=3.7](https://pypi.org/project/setuptools/67.8.0/)
- [wheel 0.42.0 / Python >=3.7](https://pypi.org/project/wheel/0.42.0/)
- [python-dotenv 0.21.1](https://pypi.org/project/python-dotenv/0.21.1/)
- [configparser 5.3.0](https://pypi.org/project/configparser/5.3.0/)
- [python-vlc 3.0.21203](https://pypi.org/project/python-vlc/3.0.21203/)
- [PlatformIO 6.1.19](https://pypi.org/project/platformio/6.1.19/)
