# KneeSpa Pi baseline and OS migration target

## Reported installation

Collected on the device on 2026-09-18 using `devices/collect_pi_info.sh` and
supplied by its operator. These are observed versions, not desired requirements
for a new installation.

| Component | Observed value |
|---|---|
| Board | Raspberry Pi 4 Model B Rev 1.1 |
| Memory | 3.7 GiB reported (4 GB model) |
| OS | Raspbian GNU/Linux 10, Buster, 32-bit |
| Kernel | 5.10.103-v7l+, armv7l |
| Root filesystem | 12 GB total, 3.1 GB available |
| Project directory | `/home/pi/drx` |
| System Python | `/usr/bin/python3`, Python 3.7.3 |
| System PyQt5 | 5.11.3+dfsg-1+rpi1+b3 |
| System VLC / libvlc5 | 3.0.20-0+deb10u1 |
| System GPIO package | python3-rpi.gpio 0.7.0-0.1~bpo10+4 |
| Python GPIO distribution | RPi.GPIO 0.7.1 |
| pyserial | 3.5 |
| python-dotenv | 0.19.2 |
| python-vlc | 3.0.12118 |
| configparser backport | 5.0.2 |
| pip / setuptools | 18.1 / 40.8.0 |
| PlatformIO Core | 6.1.19, in `~/.local/share/kneespa/platformio` |
| Application serial path | `/dev/serial0` points to `ttyS0` |
| USB programming path | `/dev/ttyACM0`, group `dialout` |

The collector found no app virtualenv in its usual search locations. It does
not establish which interpreter a running app uses. The reported `tty` session
does not establish whether the graphical desktop uses X11 or Wayland. The
installed Arduino firmware version, AVR toolchain/core, and elapsedMillis
version were not captured. PlatformIO's version alone does not identify them.

## Selected maintenance path

The operator chose to remain on Buster for now. Use
[Buster maintenance](buster-updates.md) and `devices/update_buster.sh` for available
distribution updates and the Python 3.7-compatible runtime pins. The following
OS migration remains a future option, not the current update plan.

## Future migration target

Use Raspberry Pi OS with desktop, 64-bit, based on Debian 13 Trixie, with its
distribution Python 3.13 and PyQt5 packages. This is a candidate configuration
requiring KneeSpa hardware validation, not an already qualified device image.
Keep PyQt5 for this migration; a Qt6 conversion is separate work.

Debian 10's regular LTS ended on 2024-06-30 and upstream Python 3.7 support ended
on 2023-06-27. External extended support for some Debian packages does not
establish coverage for this Raspbian installation. Newer Python packages cannot
be assumed compatible with its Python 3.7. A successful import or firmware build
does not validate device behavior.

## Migration sequence

1. Keep the current SD card intact. Back up this device's state, project,
   service/desktop launch configuration, and serial/display settings separately.
   Include legacy state locations if migration into `devices/local/` is incomplete.
   Credentials and patient records belong in private backups, not Git.
2. Install the new OS onto a spare card using Raspberry Pi Imager. Select the
   desktop image for the touchscreen application. Confirm the destination card
   before writing it. Do not attempt an in-place Buster-to-Trixie distribution
   upgrade or replace Buster's system Python.
3. Restore the project and this same device's state. Recreate the app environment
   using the new OS's Python and system PyQt5. Do not copy old virtualenvs,
   compiled Python extensions, or system libraries into the new OS.
4. Configure and verify touchscreen, audio, UART, GPIO permissions, and desktop
   startup. The current video player uses VLC's `set_xwindow()` on Linux; use
   and validate an X11-compatible Qt/VLC setup before changing display backends.
   Recheck `/dev/serial0` and serial-console settings on the new image.
5. Run Python tests, firmware tests/build checks, then the project's on-device
   checkout for stop behavior, pressure limits, actuator directions, serial
   reconnects, calibration, login, and video/audio. Retain the old card until
   the replacement is accepted. Account for any newer device state if rolling back.
6. Treat Arduino flashing as separate maintenance. An OS upgrade does not by
   itself require a different firmware image. Record the installed firmware and
   resolved build dependencies before selecting new firmware pins.

The observed versions above are the pre-maintenance baseline. Updated runtime
requirements retain Python 3.7 compatibility. Routine runtime sync does not install Python packages,
update these device tools, or flash the Arduino.

## Sources

- [Debian 10 LTS end of life](https://www.debian.org/News/2024/20240615)
- [Python version support](https://devguide.python.org/versions/)
- [Raspberry Pi OS downloads](https://www.raspberrypi.com/software/operating-systems/)
- [Trixie release and fresh-image guidance](https://www.raspberrypi.com/news/trixie-the-new-version-of-raspberry-pi-os/)
- [Trixie Python](https://packages.debian.org/trixie/python3)
- [Trixie PyQt5](https://packages.debian.org/trixie/python3-pyqt5)
