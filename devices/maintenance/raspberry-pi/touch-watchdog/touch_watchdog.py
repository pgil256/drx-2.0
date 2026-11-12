#!/usr/bin/env python3
"""Bring the monitor's USB touchscreen back when the kernel has given up on it.

The KneeSpa monitor carries a USB hub with the touch controller behind it. The
monitor restarts that hub whenever its HDMI input re-syncs, and the link is
noisy enough that the reconnect sometimes fails ("can't set config #1, error
-71"). Linux does not retry a device that failed to configure, so touch stays
dead until someone unplugs and replugs the cable.

This watchdog does what the replug does, from software, and only to the
monitor's own hub and touch controller (matched by USB vendor:product id):

  1. touch controller present but unconfigured -> select its configuration
  2. that did not help, or the controller is gone while the monitor's hub is
     still there -> detach and re-attach the kernel's hub driver so the hub's
     ports are probed again

It never acts on any other USB device and never touches the Pi's own ports,
so the Mega's USB connection is left alone. Standard library only; runs on the
Pi's Python 3.7. Needs root to write to sysfs.
"""

import argparse
import os
import sys
import time
from typing import Callable, List, Optional, Sequence, Tuple

DEFAULT_USB_ROOT = "/sys/bus/usb"
DEFAULT_TOUCH_ID = "27c0:0859"  # "wch.cn TouchScreen"
DEFAULT_HUB_ID = "1a86:8095"    # the hub inside the monitor

HEALTHY = "healthy"            # configured and bound to a driver
UNCONFIGURED = "unconfigured"  # enumerated, but the kernel gave up configuring it
MISSING = "missing"            # the monitor's hub is there, the controller is not
NO_MONITOR = "no-monitor"      # neither is there: unplugged or monitor off

POLL_SECONDS = 2.0
# A normal reconnect takes about a second; anything shorter than this is not a
# stuck device and must be left to the kernel.
GRACE_SECONDS = 6.0
FIRST_RETRY_SECONDS = 5.0
MAX_RETRY_SECONDS = 300.0
REBIND_PAUSE_SECONDS = 0.5

UsbId = Tuple[str, str]


def parse_usb_id(text: str) -> UsbId:
    """'27c0:0859' -> ('27c0', '0859'); raises ValueError on anything else."""
    vendor, separator, product = text.strip().lower().partition(":")
    if not separator or len(vendor) != 4 or len(product) != 4:
        raise ValueError("expected vendor:product as four hex digits each, got %r" % text)
    int(vendor, 16)
    int(product, 16)
    return vendor, product


def _read(path: str) -> str:
    """A sysfs attribute as stripped text; '' when absent or unreadable."""
    try:
        with open(path, "r") as handle:
            return handle.read().strip()
    except OSError:
        # Devices vanish between listing and reading; an unreadable attribute
        # is the same as a missing one for every caller here.
        return ""


def _write(path: str, value: str) -> Optional[str]:
    """Write a sysfs attribute. Returns None on success, the error text otherwise."""
    try:
        with open(path, "w") as handle:
            handle.write(value)
        return None
    except OSError as error:
        return "%s: %s" % (path, error.strerror or error)


class UsbTree:
    """The slice of /sys/bus/usb this watchdog reads and writes."""

    def __init__(self, root: str, touch_id: UsbId, hub_id: UsbId,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.devices_dir = os.path.join(root, "devices")
        self.hub_driver_dir = os.path.join(root, "drivers", "hub")
        self.touch_id = touch_id
        self.hub_id = hub_id
        self._sleep = sleep

    def _find(self, usb_id: UsbId) -> List[str]:
        """Device names (e.g. '1-1.1.1') with this vendor:product id."""
        try:
            names = sorted(os.listdir(self.devices_dir))
        except OSError:
            return []
        found = []
        for name in names:  # interfaces are listed here too; they carry no ids
            path = os.path.join(self.devices_dir, name)
            if (_read(os.path.join(path, "idVendor")).lower(),
                    _read(os.path.join(path, "idProduct")).lower()) == usb_id:
                found.append(name)
        return found

    def touch_devices(self) -> List[str]:
        return self._find(self.touch_id)

    def hubs(self) -> List[str]:
        return self._find(self.hub_id)

    def interfaces(self, device: str) -> List[str]:
        """Names of the device's interfaces (e.g. '1-1.1.1:1.0'), from its own folder."""
        path = os.path.join(self.devices_dir, device)
        try:
            names = sorted(os.listdir(path))
        except OSError:
            return []
        return [name for name in names
                if os.path.isfile(os.path.join(path, name, "bInterfaceNumber"))]

    def is_working(self, device: str) -> bool:
        """Configured, and every interface claimed by a driver.

        A controller whose HID driver failed to attach (the report descriptor
        read can fail on this link) is configured but delivers no touches.
        """
        path = os.path.join(self.devices_dir, device)
        if _read(os.path.join(path, "bConfigurationValue")) in ("", "0"):
            return False
        interfaces = self.interfaces(device)
        return bool(interfaces) and all(
            os.path.lexists(os.path.join(path, name, "driver")) for name in interfaces)

    def state(self) -> str:
        touch = self.touch_devices()
        if touch:
            return HEALTHY if any(self.is_working(name) for name in touch) else UNCONFIGURED
        return MISSING if self.hubs() else NO_MONITOR

    def configuration_value(self, device: str) -> str:
        """The device's first configuration number, read from its descriptors."""
        path = os.path.join(self.devices_dir, device, "descriptors")
        try:
            with open(path, "rb") as handle:
                raw = handle.read(64)
        except OSError:
            raw = b""
        # 18-byte device descriptor, then the first configuration descriptor
        # (type 2), whose sixth byte is bConfigurationValue.
        if len(raw) >= 24 and raw[0] == 18 and raw[19] == 2 and raw[23] != 0:
            return str(raw[23])
        return "1"

    def configure(self, device: str) -> Optional[str]:
        """Ask the kernel to select the device's configuration again."""
        path = os.path.join(self.devices_dir, device, "bConfigurationValue")
        return _write(path, self.configuration_value(device))

    def reprobe_hub(self, hub: str) -> Optional[str]:
        """Detach and re-attach the hub driver, which probes every port afresh."""
        interface = (self.interfaces(hub) or [hub + ":1.0"])[0]
        # Unbinding fails harmlessly when an earlier bind did not take.
        _write(os.path.join(self.hub_driver_dir, "unbind"), interface)
        self._sleep(REBIND_PAUSE_SECONDS)
        return _write(os.path.join(self.hub_driver_dir, "bind"), interface)


class Watchdog:
    """Decides when a touchscreen is stuck and which recovery step is due."""

    def __init__(self, usb: UsbTree, clock: Callable[[], float] = time.monotonic,
                 log: Callable[[str], None] = print, dry_run: bool = False,
                 grace: float = GRACE_SECONDS) -> None:
        self.usb = usb
        self.clock = clock
        self.log = log
        self.dry_run = dry_run
        self.grace = grace
        self.attempts = 0
        self._last_state = None  # type: Optional[str]
        self._stuck_since = None  # type: Optional[float]
        self._next_attempt = 0.0

    def step(self) -> str:
        """One poll: note the state, and act if the touchscreen has stayed stuck."""
        state = self.usb.state()
        now = self.clock()
        if state != self._last_state:
            self._report_change(state)
            self._last_state = state
        if state in (HEALTHY, NO_MONITOR):
            self.attempts = 0
            self._stuck_since = None
            self._next_attempt = 0.0
            return state
        if self._stuck_since is None:
            self._stuck_since = now
        if now - self._stuck_since < self.grace or now < self._next_attempt:
            return state
        self.attempts += 1
        self._next_attempt = now + min(
            FIRST_RETRY_SECONDS * 2 ** (self.attempts - 1), MAX_RETRY_SECONDS)
        self.recover(state)
        return state

    def _report_change(self, state: str) -> None:
        if state == HEALTHY:
            if self.attempts:
                self.log("touchscreen is working again after %d recovery attempt(s)"
                         % self.attempts)
            elif self._last_state is not None:
                self.log("touchscreen is working again")
            else:
                self.log("touchscreen is working")
        elif state == UNCONFIGURED:
            self.log("touchscreen is connected but the kernel has not configured it")
        elif state == MISSING:
            self.log("monitor hub is connected but its touchscreen is missing")
        else:
            self.log("no monitor hub or touchscreen on USB; nothing to recover")

    def recover(self, state: str) -> None:
        """Run the recovery step that is due for this attempt."""
        touch = self.usb.touch_devices()
        hubs = self.usb.hubs()
        # First try the gentle step on an unconfigured controller; after that,
        # or when the controller is gone, re-probe the monitor's hub.
        if state == UNCONFIGURED and touch and (self.attempts == 1 or not hubs):
            self._run("selecting the configuration of touchscreen %s" % touch[0],
                      lambda: self.usb.configure(touch[0]))
        elif hubs:
            self._run("re-probing monitor hub %s" % hubs[0],
                      lambda: self.usb.reprobe_hub(hubs[0]))

    def _run(self, description: str, action: Callable[[], Optional[str]]) -> None:
        prefix = "attempt %d: " % self.attempts
        if self.dry_run:
            self.log(prefix + "would be " + description + " (dry run)")
            return
        self.log(prefix + description)
        error = action()
        if error:
            self.log(prefix + "failed: " + error)


def _log(message: str) -> None:
    print(message, flush=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recover the KneeSpa monitor's USB touchscreen without a replug.")
    parser.add_argument("command", choices=("run", "status", "once"),
                        help="run: watch until stopped; status: print the state; "
                             "once: one recovery step now if the touchscreen is stuck")
    parser.add_argument("--dry-run", action="store_true",
                        help="log what would be done without writing to sysfs")
    parser.add_argument("--touch", default=DEFAULT_TOUCH_ID, metavar="VID:PID")
    parser.add_argument("--hub", default=DEFAULT_HUB_ID, metavar="VID:PID")
    parser.add_argument("--usb-root", default=DEFAULT_USB_ROOT, help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    try:
        usb = UsbTree(options.usb_root, parse_usb_id(options.touch), parse_usb_id(options.hub))
    except ValueError as error:
        parser.error(str(error))

    if options.command == "status":
        state = usb.state()
        print("%s  touchscreen=%s  monitor-hub=%s" % (
            state, ",".join(usb.touch_devices()) or "-", ",".join(usb.hubs()) or "-"))
        return 0 if state == HEALTHY else 1

    needs_root = not options.dry_run and options.usb_root == DEFAULT_USB_ROOT
    if needs_root and hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Recovery writes to sysfs and needs root; use sudo or --dry-run.",
              file=sys.stderr)
        return 2

    if options.command == "once":
        watchdog = Watchdog(usb, log=_log, dry_run=options.dry_run, grace=0.0)
        if watchdog.step() in (HEALTHY, NO_MONITOR):
            return 0
        time.sleep(3.0)  # let the kernel finish enumerating before judging
        state = usb.state()
        _log("state after the recovery step: " + state)
        return 0 if state == HEALTHY else 1

    watchdog = Watchdog(usb, log=_log, dry_run=options.dry_run)
    _log("watching touchscreen %s behind monitor hub %s" % (options.touch, options.hub))
    try:
        while True:
            watchdog.step()
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
