# Touchscreen USB watchdog

Brings the monitor's USB touchscreen back without anyone unplugging a cable.

## Why it exists

The KneeSpa monitor (EDID name `CSO-RTK_FHD_HDR`) has a USB hub inside it
(`1a86:8095`) with the touch controller behind that hub (`27c0:0859`,
"wch.cn TouchScreen"). Two things were measured on the units in November 2026:

- The monitor restarts its hub whenever its HDMI input re-syncs, so the
  touchscreen has to reconnect each time.
- The USB link is noisy, and a reconnect sometimes fails with
  `can't set config #1, error -71`. Linux does not retry a device that failed
  to configure. Touch then stays dead until the cable is replugged; on one
  unit it stayed dead for 95 hours.

The watchdog does the replug's job from software. It does not fix the noisy
link or the monitor's hub restarts.

## What it does

Every 2 seconds it checks the touch controller. If the controller has been
stuck for 6 seconds it takes one recovery step, then waits 5 s, 10 s, 20 s and
so on (at most 5 minutes) between further steps:

| State | Meaning | Step |
|---|---|---|
| `healthy` | configured, every interface has a driver | none |
| `unconfigured` | enumerated, but the kernel gave up on it | select its configuration again; if that does not help, re-probe the monitor's hub |
| `missing` | the monitor's hub is there, the controller is not | re-probe the monitor's hub |
| `no-monitor` | neither is on USB (unplugged, or monitor off) | none |

Re-probing detaches and re-attaches the kernel's hub driver on the monitor's
hub only. The watchdog matches devices by USB id and never writes to anything
else, so the Mega's USB connection and the Pi's own ports are left alone.

## Install

On the Pi:

```bash
sudo bash devices/maintenance/raspberry-pi/touch-watchdog/install.sh
```

This copies the script to `/usr/local/sbin/kneespa-touch-watchdog` and starts
`kneespa-touch-watchdog.service`, which also starts at every boot. Run the
installer again after updating `touch_watchdog.py`. To remove it:

```bash
sudo bash devices/maintenance/raspberry-pi/touch-watchdog/install.sh --uninstall
```

## Check it

```bash
/usr/local/sbin/kneespa-touch-watchdog status   # state now; exit code 0 only when healthy
sudo journalctl -u kneespa-touch-watchdog       # every state change and recovery step
```

The full path matters: `/usr/local/sbin` is not on the `pi` user's `PATH`.

Without installing anything:

```bash
python3 touch_watchdog.py status
python3 touch_watchdog.py run --dry-run    # logs what it would do, writes nothing
sudo python3 touch_watchdog.py once        # one recovery step now, if stuck
```

A different monitor needs its own ids: `--touch VID:PID --hub VID:PID`
(`lsusb` shows them).

## Limits

- If the monitor's hub itself is absent from USB, there is nothing for the
  watchdog to act on; that still needs the cable or the monitor's power checked.
- A recovery step interrupts touch for about a second.
- Frequent entries in the journal mean the cable, the monitor or its power
  still needs attention.

Tests: `python -m pytest development/tests/unit/test_touch_watchdog.py`
