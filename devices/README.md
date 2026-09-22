# Device state and provisioning

Start with the [setup and maintenance command reference](../development/docs/rpi/setup-and-maintenance.md)
for all Pi setup scripts, bundles, update steps and report locations.

- `local/raspberry-pi/`: active device state on a Pi.
- `profiles/<device-name>/raspberry-pi/`: separate PC copies for individual devices.
- `development/raspberry-pi/`: isolated state for the desktop simulator.
- `templates/`: tracked examples and historical calibration presets.
- `maintenance/`: optional Pi diagnostics and Arduino calibration/scale sketches.
- `archive/`: ignored originals retained after local state migration and cleanup.

On the Pi, double-click **Install KneeSpa.desktop** in `/home/pi/drx/devices` to
install the **KneeSpa** and **Flash KneeSpa Firmware** desktop icons. See the
[desktop launcher setup](maintenance/raspberry-pi/desktop/README.md).

The [Pi setup bundle](../kneespa-pi-desktop-setup.tar.gz) is kept at the project root.
Extract it into `/home/pi/drx` using File Manager to preserve executable permissions,
then double-click **Install KneeSpa** in the `devices` folder.

[`flash_firmware.sh`](flash_firmware.sh) builds and flashes the current Mega firmware
over USB. See [firmware flashing](maintenance/raspberry-pi/firmware.md) for the flow.

Run `bash devices/collect_pi_info.sh` from the project root on the Pi to collect
OS, hardware, Python package, and firmware-tool versions for update planning.
The script prints its report without installing packages, changing services, reading
credentials, or opening serial ports. Run it as the normal desktop user, without sudo.
See the [reported Pi baseline and proposed OS migration](maintenance/raspberry-pi/system-baseline.md)
for the September 2026 installation and the candidate replacement environment.

For the selected Buster maintenance path, run
`bash devices/update_buster.sh --use-legacy-repository` to preview, then add
`--apply` while KneeSpa is closed. This backs up and repairs retired Buster mirror
URLs, updates system packages/Python and installs the runtime requirements.
Read [Buster maintenance](maintenance/raspberry-pi/buster-updates.md) for preparation,
interpreter selection, logs, and recovery limits.

Live state, profiles, and simulator state are ignored by Git. Shared software
updates never sync this directory. Do not copy one device's identity or calibration
to another. See [deployment and migration](../development/docs/deployment.md)
for targeted transfers and first-time upgrades.
