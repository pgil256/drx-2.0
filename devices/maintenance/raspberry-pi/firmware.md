# Flash the current firmware from the Pi desktop

Use the [clickable installer](desktop/README.md) to create **Flash KneeSpa Firmware**
on `/home/pi/Desktop`. It runs `devices/flash_firmware.sh` against the source in
`/home/pi/drx/runtime/arduino/motor`, including local changes. It does not fetch Git
updates or reuse a previously compiled HEX file.

1. Close the KneeSpa app and any serial-monitor window. Perform firmware maintenance
   with the device unoccupied, as in the project's
   [on-device playbook](../../../development/docs/plans/2026-07-06-phase-e-on-device-plan.md).
2. Connect the Arduino Mega 2560's USB port to the Pi. The Pi's `/dev/serial0`
   control wiring is not the USB programming connection.
3. Double-click **Flash KneeSpa Firmware**. Read progress in the window that opens.
   A single recognized Mega is selected automatically; otherwise choose the Mega's
   USB port in the graphical list. Canceling the list does not flash anything.
4. On first use, an internet connection may be needed for build tools. If prompted,
   enter the `pi` password. No shell commands need to be typed.
5. Wait for **SUCCESS: firmware written and verified**. Close the progress window.
   Complete the existing firmware boot/hardware checkout before reopening **KneeSpa**.

The script builds the PlatformIO `mega` environment, then explicitly installs
its optional `avrdude` upload dependency if needed. A successful build alone does
not install that tool. The updater uses PlatformIO's own Python environment to
resolve the selected tool version and package location, including custom storage.
It uses `avrdude` with the Mega 2560's `wiring` protocol at 115200 baud. It reads the old
flash into `previous.hex` before writing `current.hex`; a failed read cancels the
write. Normal avrdude readback verification remains enabled. Flashing does not
burn a bootloader, change fuses, or upload an EEPROM image.

The script shares the desktop launcher's lock, stops `kneespa.service` if needed,
and checks the upload port and `/dev/serial0` for other processes before touching
the board. It never kills an app or serial monitor to free a port. It leaves the
service stopped after success or a subsequent failure; reopening the app is an
explicit desktop action after the firmware checkout.

Each run saves the log, previous/new HEX files when available, and new-build
checksums under `devices/local/raspberry-pi/firmware/<timestamp>-<id>/`. This is
device-owned, ignored state. Build output goes under `.cache/firmware-platformio/`.
A successful upload verifies the flash contents, not motor behavior or calibration.

Missing `zenity`, `psmisc`, or Python virtual-environment support is installed with
the Pi's package manager. If PlatformIO is absent, it is installed in a private
`~/.local/share/kneespa/platformio` environment; the app's environment is unchanged.
The `pi` user needs read/write permission on the USB port (normally through its
serial-device group); permission problems are reported before the board is touched.

For scripted use, the entry point also accepts `--port /dev/ttyACM0`.
Environment overrides: `KNEESPA_APP_DIR`, `KNEESPA_DEVICE_DIR`, `KNEESPA_SERVICE`,
`KNEESPA_PIO` (full executable path), and `PLATFORMIO_CORE_DIR`. Use absolute paths.

If an older launcher reports **Cannot find PlatformIO's avrdude package** after
a successful build, update `devices/flash_firmware.sh` from the current
[Pi setup bundle](../../../kneespa-pi-desktop-setup.tar.gz) and retry the desktop
shortcut. Extract the bundle into `/home/pi/drx`, replacing its launcher files.
Routine runtime sync does not update this script. That lookup failure happens
before stopping the service or reading/writing the board; the new launcher prepares
the missing tool before those steps. An internet connection is needed to download
an upload tool that is not already installed.

Build/upload settings follow the repository's `platformio.ini` and PlatformIO's
[Mega board definition](https://github.com/platformio/platform-atmelavr/blob/master/boards/megaatmega2560.json)
and [AVR uploader](https://github.com/platformio/platform-atmelavr/blob/master/builder/main.py).
