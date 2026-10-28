"""systemd watchdog pings sent from the GUI thread.

When ``kneespa.service`` sets ``WatchdogSec=``, systemd expects a ``WATCHDOG=1``
datagram at least that often and otherwise aborts and restarts the service. The
pings come from a ``QTimer`` on the GUI thread on purpose: a hung event loop
stops them, which is the failure an operator cannot recover from on a kiosk.

Everything here is a no-op when systemd did not start the process (desktop
launcher, simulator, tests, Windows). The protocol is one datagram on the
``NOTIFY_SOCKET`` unix socket, so no systemd Python binding is needed.
"""

import os
import socket
from typing import Optional

from PyQt5.QtCore import QObject, QTimer

# Time allowed for release install, log sync and power actions after the event
# loop has ended and the pings have stopped.
SHUTDOWN_GRACE_S = 30 * 60


def notify(state: str) -> bool:
    """Send one sd_notify message; False when there is no socket or it fails."""
    address = os.environ.get("NOTIFY_SOCKET", "")
    if not address or not hasattr(socket, "AF_UNIX"):
        return False
    if address[0] == "@":  # abstract namespace
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode("ascii"), address)
        return True
    except OSError:
        # A missed ping is retried by the timer; diagnostics must not stop the app.
        return False


def _timeout_us() -> int:
    """The unit's WatchdogSec in microseconds, or 0 when no watchdog applies."""
    try:
        timeout_us = int(os.environ.get("WATCHDOG_USEC", "0"))
        pid = os.environ.get("WATCHDOG_PID")
        if timeout_us <= 0 or (pid and int(pid) != os.getpid()):
            return 0
    except ValueError:
        return 0
    return timeout_us


def watchdog_interval_ms() -> int:
    """Half of the unit's WatchdogSec in ms, or 0 when no watchdog applies."""
    timeout_us = _timeout_us()
    return max(1000, timeout_us // 2000) if timeout_us else 0


def start_watchdog(parent: Optional[QObject] = None) -> Optional[QTimer]:
    """Ping now and then on a GUI-thread timer; None when no watchdog is set."""
    interval = watchdog_interval_ms()
    if not interval:
        return None
    timer = QTimer(parent)
    timer.timeout.connect(lambda: notify("WATCHDOG=1"))
    timer.start(interval)
    # An in-app restart keeps this PID (os.execv), so the long shutdown
    # deadline set by the previous run would still be in force.
    notify("WATCHDOG_USEC=%d" % _timeout_us())
    notify("WATCHDOG=1")
    return timer


def extend_watchdog_for_shutdown(timer: Optional[QTimer]) -> None:
    """Stop pinging and give the remaining exit work a long deadline."""
    if timer is None:
        return
    timer.stop()
    notify("WATCHDOG_USEC=%d" % (SHUTDOWN_GRACE_S * 1000000))
    notify("WATCHDOG=1")
