# Device state and provisioning

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

Live state, profiles, and simulator state are ignored by Git. Shared software
updates never sync this directory. Do not copy one device's identity or calibration
to another. See [deployment and migration](../development/docs/deployment.md)
for targeted transfers and first-time upgrades.
