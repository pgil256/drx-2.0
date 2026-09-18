# KneeSpa desktop launcher

## Install by clicking

1. In the Pi's File Manager, open `/home/pi/drx/devices`.
2. Double-click **Install KneeSpa.desktop** (it may display as **Install KneeSpa**).
3. An installer window opens, creates the shortcuts, and shows the result.
4. Close that window. Your desktop now has **KneeSpa** and **Flash KneeSpa Firmware**.

No commands need to be typed. If the first installer icon opens as text or is
blocked, use its **Properties → Permissions** to allow executing it, then open it
again and choose **Execute / Allow Launching** if prompted. This is the desktop's
trust step for a newly copied launcher. Do this while signed in as `pi`.

If using [`kneespa-pi-desktop-setup.tar.gz`](../../../../kneespa-pi-desktop-setup.tar.gz),
extract its contents
into `/home/pi/drx` using File Manager first. The archive contains the `devices/`
paths and preserves executable permissions for the installer icon and scripts.

[`install_kneespa_desktop.sh`](../../../install_kneespa_desktop.sh) is a small
wrapper around this folder's `install.sh`. You can copy the wrapper anywhere on
the Pi; it always runs the installer in `/home/pi/drx`.

The fixed defaults are `/home/pi/drx` for the repository and `/home/pi/Desktop`
for the desktop. The installer creates `/home/pi/Desktop/KneeSpa.desktop` and
application-menu entries, including the bundled KneeSpa icon. It sets the shortcuts and
launcher scripts executable (`0755`) and asks `gio` to mark the shortcuts trusted
when available. Double-click **KneeSpa** to start the app. Some desktop environments
may still ask you to allow launching/execution the first time.

Rerunning the installer updates these entries; no manual `chmod` step is needed.

Keep this folder and the three entry files (`devices/Install KneeSpa.desktop`,
`devices/install_kneespa_desktop.sh`, `devices/flash_firmware.sh`) in the repository
on the Pi. Routine software sync only copies `runtime/`, so copy these files
separately on first installation and when updating the launchers. Rerun the
installer by clicking its icon after an update.

**Flash KneeSpa Firmware** opens a progress window, installs missing build tools,
builds the current checkout, backs up the old board firmware, and uploads over USB.
It may ask for your `pi` password for tool installation or stopping the app service.
See [firmware flashing](../firmware.md) for the USB and app-close requirements.

## Launch behavior

- Starts `runtime/raspberry-pi/main/kneespa.py` in the existing desktop session.
- Looks for Python in the repository's `kneespa_env`, then `.venv`, then
  `$HOME/kneespa_env`. Falls back to `python3` from `PATH`, matching a system-Python
  installation. The selected interpreter must have the app's dependencies installed.
- Forwards command-line arguments and preserves the display/session environment.
- Uses `flock` to prevent a second app opened through this launcher. The lock
  releases when the app exits and survives its in-app restart.
- Refuses to launch while the standard system `kneespa.service` is active.
  It does not stop services or detect every app started by other commands or
  custom service names; choose one way to start the app.
- Saves stdout/stderr, including early startup errors, to
  `devices/local/raspberry-pi/logs/desktop-launch.log`, retaining one previous
  session in `desktop-launch.log.previous`. A configured `KNEESPA_DEVICE_DIR`
  changes the state root in the same way as it does for the app.
- Reports launcher setup errors through `zenity`, `xmessage`, or `notify-send`
  when available, as well as stderr. If the app exits after launch, inspect the
  startup log. Install `zenity` if you need error dialogs on a desktop without
  any of these utilities.

For troubleshooting from a terminal:

```bash
bash /home/pi/drx/devices/maintenance/raspberry-pi/desktop/launch_kneespa.sh --debug --print-logs
```

Optional environment overrides are `KNEESPA_APP_DIR` (repository root) and
`KNEESPA_PYTHON` (full path to a Python executable). The installer records
`KNEESPA_APP_DIR` in the shortcut. Interpreter and device-directory overrides
must be present in the launching session or added to the shortcut's `Exec` line.
For testing or another installation, `KNEESPA_DESKTOP_DIR` overrides the installer's
desktop destination; neither path override is needed on the Pi.

The installer uses the [Desktop Entry specification's argument escaping](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)
so paths containing spaces and shell metacharacters stay literal.

To uninstall, remove `KneeSpa.desktop` and `Flash KneeSpa Firmware.desktop` from
`/home/pi/Desktop`, and `kneespa.desktop` and `kneespa-firmware.desktop` from
`${XDG_DATA_HOME:-$HOME/.local/share}/applications`.
