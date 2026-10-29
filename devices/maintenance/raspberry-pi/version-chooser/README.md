# Choose the legacy or new KneeSpa at startup

After the desktop logs in, a full-screen touch menu offers **Legacy KneeSpa** or
**KneeSpa 2.0**. The two apps need different Mega firmware. Choosing a version:

1. builds that version's firmware from its source folder (the last build is
   reused while the source is unchanged),
2. writes it to the Mega over USB, unless the board already verifies identical,
3. verifies it with avrdude, and only then
4. starts the app.

If anything fails, neither app starts; the screen shows the error with **Back**
and **Try again**. The last-used version starts by itself after a countdown
(15 s by default); touching the screen stops the countdown.

## Requirements

- The Mega's USB cable stays connected to the Pi. The apps talk over
  `/dev/serial0`; checking and writing firmware use USB (`/dev/ttyACM0`).
- avrdude, which **Flash KneeSpa Firmware** installs on its first run under
  `~/.platformio/packages/tool-avrdude`. Otherwise run `sudo apt-get install avrdude`.
- Build tools for each firmware: PlatformIO for a source folder with a
  `platformio.ini` (KneeSpa 2.0; installed by **Flash KneeSpa Firmware**), and
  `arduino-cli` or an Arduino IDE under `/opt` for a plain sketch folder (legacy).

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
3. Edit `versions.cfg`. In `[legacy]`, set `command` and `directory` to the way
   the legacy app starts, and `source` to its motor firmware folder (the one
   with `motor.ino`). Check the `[new]` paths if the project is not at
   `/home/pi/drx`. To flash a fixed `.hex` file instead of building, set
   `image` and leave `source` blank. On a Pi without internet access, set
   `builder = arduino` for KneeSpa 2.0 as well: PlatformIO stalls for minutes
   trying to download its library, while the Arduino toolchain is local. The
   image then differs from CI's by compiler only, not by source.
4. Build both firmwares once, without flashing, to confirm the toolchains work:

   ```bash
   cd /home/pi/drx/devices/maintenance/raspberry-pi/version-chooser
   python3 version_chooser.py build legacy
   python3 version_chooser.py build new
   ```

5. Stop anything else from starting an app at boot:

   ```bash
   sudo systemctl disable --now kneespa.service
   ```

   Also remove the legacy app's own autostart entry, if it has one.
6. Run `python3 version_chooser.py status` until it prints `OK`, then reboot.

## Behavior

- **Build:** sources (`.ino`, `.h`, `.c`, `.cpp`, `.ini`) are hashed; a build
  is reused while they are unchanged, so a normal start takes seconds. Editing
  the firmware source means the next start of that version builds and flashes
  the edited source, exactly as the version's own flash tools would.
- **Flash:** avrdude `flash:v` compares the image with the board. Opening the
  USB port resets the Mega, so every start includes a reset before the app
  connects. When the board differs, the whole flash is read into a backup
  before the write; the write is verified, then verified again.
- **Unfinished KneeSpa 2.0 firmware update:** if
  `devices/local/raspberry-pi/updates/firmware-recovery.json` exists, the
  chooser does not touch the Mega. It starts KneeSpa 2.0, which finishes its own
  recovery, and refuses to start the legacy app until then.
- **Refusals:** it refuses while `kneespa.service` is active, while another
  program holds `/dev/serial0` or the Mega's USB port, and while the KneeSpa
  launcher or firmware flasher holds `devices/local/raspberry-pi/logs/desktop-launch.lock`.
  It holds that lock itself until it hands over to the app.
- **Records:** `devices/local/raspberry-pi/logs/version-chooser.log` (plus one
  `.previous`). Builds live under `version-chooser/build/<version>/` with their
  `build.log`. Starts that built or wrote firmware keep their logs, the backup
  (`previous.hex`) and the written image (`current.hex`) in
  `devices/local/raspberry-pi/firmware/<time>-choose-<version>-*/`.
- **Other settings:** `timeout = 0` always waits for a touch. `port`, `avrdude`,
  `avrdude_config`, `pio` and `arduino` override auto-detection; `builder`
  per version picks `platformio` or `arduino`.
- **Not changed:** the chooser writes flash only. It never changes fuses, the
  bootloader or EEPROM. The KneeSpa 2.0 firmware does not use EEPROM. Whether
  the legacy firmware does has not been checked.

Keep the other shortcuts for maintenance only. **KneeSpa** starts the new app
without checking the firmware. Do the existing firmware boot and hardware
checkout the first time each version runs after a switch.

To remove the autostart entry and shortcut, run `install.sh --uninstall`.
Settings and builds in `devices/local` are kept.
