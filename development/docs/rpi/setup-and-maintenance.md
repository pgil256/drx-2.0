# Raspberry Pi setup and maintenance scripts

This is the command reference for the KneeSpa setup and maintenance tools.
The current device is a Raspberry Pi 4 running 32-bit Raspbian Buster, with the
project at `/home/pi/drx` and desktop user `pi`. Staying on Buster is the selected
maintenance path. The [recorded system baseline](../../../devices/maintenance/raspberry-pi/system-baseline.md)
contains the reported versions and the separate future OS migration option.

The script files linked below are the source of truth; their contents are not
duplicated here. All **Pi commands** assume this working directory:

```bash
cd /home/pi/drx
```

Run the Pi entry scripts as the normal desktop user, without putting `sudo` in
front of them. Scripts that need elevated package/service operations request it
themselves. Close KneeSpa before system maintenance or firmware flashing, and
perform those operations with the device unoccupied.

## Script index

| Script or entry point | Run on | Purpose |
|---|---|---|
| [collect_pi_info.sh](../../../devices/collect_pi_info.sh) | Pi / SSH | Print the Pi model, OS, memory, disk, Python packages, PlatformIO version and serial paths. |
| [update_buster.sh](../../../devices/update_buster.sh) | Pi / SSH | Preview or apply Buster package and Python requirement updates. |
| [update_buster.py](../../../devices/maintenance/raspberry-pi/update_buster.py) | Called by the Buster wrapper | Implements preflight checks, updates, dependency verification and private logs. Copy it with the wrapper. |
| [Install KneeSpa.desktop](../../../devices/Install%20KneeSpa.desktop) | Pi desktop | Clickable entry point for shortcut installation. |
| [install_kneespa_desktop.sh](../../../devices/install_kneespa_desktop.sh) | Pi | Wrapper for the desktop installer at the fixed `/home/pi/drx` location. |
| [desktop/install.sh](../../../devices/maintenance/raspberry-pi/desktop/install.sh) | Pi | Creates the KneeSpa and Flash KneeSpa Firmware desktop/menu shortcuts. |
| [desktop/launch_kneespa.sh](../../../devices/maintenance/raspberry-pi/desktop/launch_kneespa.sh) | Pi desktop session | Starts KneeSpa with interpreter selection, duplicate-launch lock and startup logs. |
| [runtime/raspberry-pi/launch.sh](../../../runtime/raspberry-pi/launch.sh) | Pi desktop session | Simpler runtime launcher; does not provide the desktop launcher's lock or startup-log wrapper. |
| [flash_firmware.sh](../../../devices/flash_firmware.sh) | Pi | Builds, backs up, writes and verifies the Arduino Mega firmware over USB. |
| [install_display_diagnostics.sh](../../../devices/maintenance/raspberry-pi/install_display_diagnostics.sh) | Pi desktop | Installs baseline/failure diagnostic shortcuts and a collector in `~/.local/bin`. |
| [collect_display_diagnostics.sh](../../../devices/maintenance/raspberry-pi/collect_display_diagnostics.sh) | Pi | Captures display, touch, USB and power evidence without reconfiguring hardware. |
| [test_sound_output.sh](../../../devices/maintenance/raspberry-pi/test_sound_output.sh) | Pi desktop / terminal | Interactive speaker and VLC tests; unmutes the output and sets volume to 65%. |
| [wallpaper.sh](../../../devices/maintenance/raspberry-pi/wallpaper.sh) | Pi desktop | Sets the PCManFM wallpaper to `/home/pi/kneespa-logo-full.png`. |
| [sync_pis.sh](../../sync/sync_pis.sh) | PC, WSL/Linux | Preview/apply shared runtime transfers to explicitly selected Pi hosts. |
| [sync_device_state.sh](../../sync/sync_device_state.sh) | PC, WSL/Linux | Preview/apply a selected category of state for one device profile. |

## Copying the tools and bundles

Keep the repository directory structure when transferring files. Routine sync
copies **only `runtime/`**; it does not update scripts under `devices/`, install
Python requirements, or flash the Arduino. Copy updated device tools separately.
Preserve the Pi's `devices/local/` state; do not replace it with another device's
calibration, identities or credentials.

Two bundles were prepared:

| Bundle | Contents and use |
|---|---|
| [kneespa-pi-desktop-setup.tar.gz](../../../kneespa-pi-desktop-setup.tar.gz) | Desktop installation and firmware-launcher files; extract into `/home/pi/drx`, then run the desktop installer. |
| `.cache/kneespa-buster-update.tar.gz` on the PC | Generated local bundle containing the inventory script, Buster wrapper/helper, maintenance docs and updated runtime requirements. It is ignored by Git and may not exist in a fresh checkout. |

These bundles supplement the existing application; they are not full device
images or state backups. After copying a bundle into `/home/pi/drx` on the Pi,
extract the applicable one:

```bash
tar -xzf kneespa-pi-desktop-setup.tar.gz
```

Or, for the Buster update bundle:

```bash
tar -xzf kneespa-buster-update.tar.gz
```

Extraction replaces the included setup/requirement files but does not run the
installer or apply system updates. When copying individual files, the Buster
wrapper requires `devices/maintenance/raspberry-pi/update_buster.py`; copying only
the `.sh` file is insufficient.

## Collect the Pi's installed versions

On the Pi, including over SSH:

```bash
bash devices/collect_pi_info.sh
```

It prints to the terminal and does not install packages, read credentials, open
serial ports or query the running Arduino firmware. A `tty` session reported over
SSH does not identify the graphical desktop backend. Missing environments or
packages are reported or omitted. Send the complete output when diagnosing
dependency problems.

## Update Buster and install requirements

Preview first:

```bash
bash devices/update_buster.sh --use-legacy-repository
```

The preview reads local metadata and prints the plan. The legacy-repository option
repairs Buster's retired Raspbian mirror URL when applied, saving the original
source files first. See [the Buster 404 fix](../../../devices/maintenance/raspberry-pi/buster-updates.md#fix-the-buster-repository-404).
Keep an SD-card backup
before applying. Close the app and firmware windows. If KneeSpa runs through the
system service, stop that service while the device is idle:

```bash
sudo systemctl stop kneespa.service
```

Skip that stop command if no service is installed. Apply the update:

```bash
bash devices/update_buster.sh --apply --use-legacy-repository
```

To omit maintenance of the private PlatformIO environment:

```bash
bash devices/update_buster.sh --apply --use-legacy-repository --skip-firmware-tools
```

The updater refreshes signed Buster repositories, simulates and applies available
system updates without package removals, installs system Python/PyQt5/VLC/build
dependencies, and installs the checked-out
[runtime requirements](../../../runtime/raspberry-pi/main/requirements.txt).
System Python remains on the distribution's **3.7 series**; its displayed version
can remain `3.7.3` even after package revision updates. Application pip packages
go into the selected existing virtualenv or the desktop user's package directory.
PyQt5 comes from APT.

Repository failures stop the run. The updater does not change repository suites,
disable verification, flash firmware, restart the app or reboot automatically.
Completed package changes are not automatically rolled back after a later failure.
After success, reboot during maintenance and check the application and hardware
before treatment use. See [Buster maintenance](../../../devices/maintenance/raspberry-pi/buster-updates.md)
for exact versions, environment selection and recovery limits.

## Install desktop shortcuts and launch KneeSpa

On the Pi, double-click **Install KneeSpa.desktop** in `/home/pi/drx/devices`, or run:

```bash
bash devices/install_kneespa_desktop.sh
```

This creates **KneeSpa** and **Flash KneeSpa Firmware** on `/home/pi/Desktop` and
in the application menu. If the desktop asks to trust a copied launcher, select
**Allow Launching / Execute**. Rerun the installer after updating the launcher
files. This installs shortcuts; it does not install application requirements.

Use the **KneeSpa** shortcut in the local desktop session. For startup debugging
from a terminal in that desktop session:

```bash
bash devices/maintenance/raspberry-pi/desktop/launch_kneespa.sh --debug --print-logs
```

The desktop launcher selects project `kneespa_env`, project `.venv`, then
`~/kneespa_env`, falling back to `python3` on `PATH`. `KNEESPA_PYTHON` explicitly
selects another interpreter. It refuses a duplicate launcher instance or the
standard running `kneespa.service`. Choose one app startup method.

An SSH shell does not necessarily have the desktop's display/session variables;
the shortcut installer can be run over SSH, but use the desktop to open the GUI.
See [desktop setup details](../../../devices/maintenance/raspberry-pi/desktop/README.md).

## Build and flash Arduino firmware

Close KneeSpa and serial monitors, connect the Mega's **USB programming port**,
and double-click **Flash KneeSpa Firmware**. `/dev/serial0` is the app's control
wiring and is not the USB upload connection.

From a Pi terminal, use the verified USB port explicitly (the reported device
was `/dev/ttyACM0`; check it again if USB devices have changed):

```bash
bash devices/flash_firmware.sh --port /dev/ttyACM0
```

The explicit-port form avoids the graphical port picker when using SSH. It
builds the current source, prepares PlatformIO's uploader, saves the previous
flash, writes the new HEX and performs readback verification. It leaves the app
service stopped. Finish the firmware hardware checkout before reopening KneeSpa.
Updating Buster or copying firmware source does not perform this flash step.
See [firmware maintenance](../../../devices/maintenance/raspberry-pi/firmware.md).

## Optional display, sound and wallpaper tools

Install the two display diagnostic shortcuts:

```bash
bash devices/maintenance/raspberry-pi/install_display_diagnostics.sh
```

Run the baseline while the display works, and the failure capture before
unplugging cables when possible. The direct commands are:

```bash
bash devices/maintenance/raspberry-pi/collect_display_diagnostics.sh --baseline
bash devices/maintenance/raspberry-pi/collect_display_diagnostics.sh --failure
```

The collector records evidence and writes a report; it does not repair the display.
Rerun its installer after updating the collector, because the desktop shortcuts
use a copied version in `~/.local/bin`.

For the interactive speaker/VLC test, run in the Pi desktop session:

```bash
bash devices/maintenance/raspberry-pi/test_sound_output.sh
```

It plays test audio and asks what you heard. It changes mute/volume to an audible
65%; restore your preferred volume afterward. Reports go under
`~/KneeSpa-sound-tests`. A different sample video can be selected with
`KNEESPA_SOUND_TEST_VIDEO`.

The optional legacy wallpaper helper requires PCManFM and an existing image at
`/home/pi/kneespa-logo-full.png`:

```bash
bash devices/maintenance/raspberry-pi/wallpaper.sh
```

## PC-side software and state sync

Run these from the **PC repository root in WSL/Linux**, with Bash, SSH and rsync.
Replace `PI_HOST` with the verified device hostname or address. Both scripts
default to `/home/pi/drx-2.0`; this device needs `DEST_ROOT=/home/pi/drx`.

Preview shared runtime changes, then apply:

```bash
PI_HOSTS="PI_HOST" DEST_ROOT=/home/pi/drx bash development/sync/sync_pis.sh
PI_HOSTS="PI_HOST" DEST_ROOT=/home/pi/drx bash development/sync/sync_pis.sh --apply
```

Apply requires the expected service entry point. It stops the service, mirrors
`runtime/`, then starts the service only after a successful copy. It does not
install changed requirements. Coordinate dependency maintenance while the app is
stopped when a release needs new packages; do not assume a file sync applied them.

To save this device's calibration/config into a named local profile:

```bash
DEST_ROOT=/home/pi/drx bash development/sync/sync_device_state.sh pull kneespa PI_HOST config
DEST_ROOT=/home/pi/drx bash development/sync/sync_device_state.sh pull kneespa PI_HOST config --apply
```

`kneespa` is the PC profile label, not a new device identity. State apply also
stops/restarts the service and needs a working service setup. The state script
does not constitute a full SD backup. See [deployment and state transfer](../deployment.md)
for categories, overrides, failure handling and first-time service migration.

## Default reports and records

| Tool | Output location on the Pi |
|---|---|
| Pi information collector | Terminal output only. |
| Buster updater | `/home/pi/drx/devices/local/raspberry-pi/maintenance/buster-<timestamp>-<id>/` |
| Desktop app launcher | `/home/pi/drx/devices/local/raspberry-pi/logs/desktop-launch.log` and `.previous` |
| Firmware flasher | `/home/pi/drx/devices/local/raspberry-pi/firmware/<timestamp>-<id>/` |
| Display diagnostics | `~/KneeSpa-display-diagnostics/` |
| Sound test | `~/KneeSpa-sound-tests/` |

`KNEESPA_DEVICE_DIR` changes the state root used by the app, updater and flasher.
The display and sound collectors have separate report-directory overrides.
Keep per-device state and private diagnostic records out of Git.
