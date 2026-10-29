# Choose the legacy or new KneeSpa at startup

After the desktop logs in, a full-screen touch menu offers **Legacy KneeSpa** or
**KneeSpa 2.0**. The two apps need different Mega firmware. Before starting
the chosen app, the chooser uses avrdude over the Mega's USB port to check that
the board holds that version's firmware. If it does not, the chooser asks
before writing the matching image, then verifies it again. Neither app starts
if the firmware cannot be confirmed.

If the last-used version is already on the Mega, it starts by itself after a
countdown (15 s by default). Touching the screen stops the countdown. Writing
firmware always waits for a touch on **Write … firmware**.

## Requirements

- The Mega's USB cable stays connected to the Pi. The apps talk over
  `/dev/serial0`; checking and writing firmware use USB (`/dev/ttyACM0`).
- avrdude, which **Flash KneeSpa Firmware** installs on its first run under
  `~/.platformio/packages/tool-avrdude`. Otherwise run `sudo apt-get install avrdude`.
- One firmware image (`.hex`) for each version, registered as below.

## Set up

1. Copy this folder and `devices/templates/raspberry-pi/version-chooser.cfg.example`
   into `/home/pi/drx` (both are in the
   [Pi setup bundle](../../../../development/docs/rpi/setup-and-maintenance.md#copying-the-tools-and-bundles)).
2. Run the installer as `pi`:

   ```bash
   bash /home/pi/drx/devices/maintenance/raspberry-pi/version-chooser/install.sh
   ```

   It creates `devices/local/raspberry-pi/version-chooser/versions.cfg` (never
   overwritten), an autostart entry and a **Choose KneeSpa Version** desktop
   shortcut, then prints a setup check.
3. Edit `versions.cfg`. In `[legacy]`, set `command` to the legacy app's start
   command and `directory` to the directory it starts in, as its old shortcut or
   service did. Check the `[new]` paths if the project is not at `/home/pi/drx`.
4. Register both firmware images:

   ```bash
   cd /home/pi/drx/devices/maintenance/raspberry-pi/version-chooser
   python3 version_chooser.py register legacy /path/to/legacy.hex
   python3 version_chooser.py register new /path/to/new.hex
   ```

   - **New:** CI's firmware job uploads the Mega image and its sha256 as an artifact.
     Each **Flash KneeSpa Firmware** run also saves the image it built as
     `devices/local/raspberry-pi/firmware/<run>/current.hex`.
   - **Legacy:** if the Mega had the legacy firmware when **Flash KneeSpa Firmware**
     first ran, that firmware was saved as `previous.hex` in that run's folder.
     Registering a full-flash backup like this removes its bootloader region
     and blank space, because the bootloader cannot rewrite itself.
   - Registration validates the Intel HEX file, copies it into
     `version-chooser/images/` and records its sha256. A changed image is refused
     at startup.
5. Stop anything else from starting an app at boot:

   ```bash
   sudo systemctl disable --now kneespa.service
   ```

   Also remove the legacy app's own autostart entry, if it has one.
6. Run `python3 version_chooser.py status` until it prints `OK`, then reboot.

## Behavior

- **Firmware check:** avrdude `flash:v` compares the chosen image with the
  board. Opening the USB port resets the Mega, so every start includes a reset
  before the app connects.
- **Switching:** if the board holds the other registered image, the chooser
  writes the chosen one after confirmation. If it holds neither (for example
  after a KneeSpa 2.0 release update or **Flash KneeSpa Firmware**), it first
  backs up the whole flash. That backup also confirms the board is answering.
  Re-register the new image after updating the firmware from either of those
  tools, or the chooser will offer to replace the newer firmware.
- **Unfinished KneeSpa 2.0 firmware update:** if
  `devices/local/raspberry-pi/updates/firmware-recovery.json` exists, the
  chooser does not touch the Mega. It starts KneeSpa 2.0, which finishes its own
  recovery, and refuses to start the legacy app until then.
- **Refusals:** it refuses while `kneespa.service` is active, while another
  program holds `/dev/serial0` or the Mega's USB port, and while the KneeSpa
  launcher or firmware flasher holds `devices/local/raspberry-pi/logs/desktop-launch.lock`.
  It holds that lock itself until it hands over to the app.
- **Records:** `devices/local/raspberry-pi/logs/version-chooser.log` (plus one
  `.previous`). Starts that needed a switch keep their avrdude log, and any
  backup, in `devices/local/raspberry-pi/firmware/<time>-choose-<version>-*/`.
- **Other settings:** `timeout = 0` always waits for a touch. `port`, `avrdude`
  and `avrdude_config` override auto-detection.
- **Not changed:** the chooser writes flash only. It never changes fuses, the
  bootloader or EEPROM. The KneeSpa 2.0 firmware does not use EEPROM. Whether
  the legacy firmware does has not been checked.

Keep the other shortcuts for maintenance only. **KneeSpa** starts the new app
without checking the firmware. Do the existing firmware boot and hardware
checkout the first time each version runs after a switch.

To remove the autostart entry and shortcut, run `install.sh --uninstall`.
Settings and images in `devices/local` are kept.
