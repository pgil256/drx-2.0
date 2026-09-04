"""Launch the KneeSpa GUI on a dev machine (no Raspberry Pi hardware).

The app imports Pi-only libraries (``RPi.GPIO``) and an optional video backend
(``vlc``) at module load, and on boot it spins up a worker thread that tries to
open the Arduino serial port. None of that exists on a laptop, so this launcher:

  1. stubs ``RPi.GPIO`` / ``vlc`` in ``sys.modules`` before importing the app
     (the same trick the test ``conftest.py`` uses), and
  2. swaps in a no-hardware ``Arduino`` that reports "ready" instantly instead
     of probing a serial port that isn't there.

It then boots the real ``KneeSpa`` window in ``--debug`` (windowed) mode, so you
can click through the whole UI — nav, login, Setup, Treatment, the duration
slider, and the modals — with no device attached.

Usage:
    python tools/run_local.py            # windowed GUI on your desktop
    QT_QPA_PLATFORM=offscreen python tools/run_local.py   # headless (CI/grab)

Default local credentials:
    admin / 1234
    user  / 5678

This is a developer convenience ONLY: it does not change application code, it is
never imported by the app, and the Arduino/connection state it shows is faked
(the badge reads "connected" even though nothing is plugged in). Use the real
device for any hardware/treatment verification.
"""

import os
import sys
from unittest.mock import MagicMock


def _seed_local_credentials():
    """Provide predictable sandbox users without touching production data."""
    os.environ.setdefault("ADMIN_PIN", "1234")
    os.environ.setdefault("ADMIN_USERNAME", "Sandbox Administrator")
    os.environ.setdefault("USER_PIN", "5678")
    os.environ.setdefault("USER_USERNAME", "Sandbox User")


# 1) stub Pi-only / optional native deps before the app imports them
for _name in ("RPi", "RPi.GPIO", "vlc"):
    sys.modules.setdefault(_name, MagicMock())

# A missing demo-video file shouldn't refuse launch on a dev box.
os.environ.setdefault("KNEESPA_SKIP_PATH_VALIDATION", "1")
_seed_local_credentials()

# The app uses imports rooted at main/ (config.*, ui.*, helpers.*).
_MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main")
if _MAIN not in sys.path:
    sys.path.insert(0, _MAIN)

from PyQt5.QtWidgets import QApplication  # noqa: E402

import kneespa  # noqa: E402
import controllers.connection_manager as _connection_manager  # noqa: E402
import helpers.arduino as _ardmod  # noqa: E402


class _DevArduino(_ardmod.Arduino):
    """No-hardware Arduino: report ready instantly, never touch a serial port.

    Without this the boot-time connection probe fails repeatedly and the
    controller's connection-failed path spawns error dialogs in a tight loop.
    """

    def connect_to_arduino(self, *args, **kwargs):
        self.connected = True
        self._running = True
        self.connection_ready_event.set()
        self.connection_ready.emit()
        return True

    def run(self):
        self.connect_to_arduino()

    def verify_connection(self, *args, **kwargs):
        return self.connected

    def send(self, *args, **kwargs):
        return True


def main():
    # ConnectionManager owns Arduino construction after the controller split,
    # so patch the dependency at that boundary rather than on kneespa.py.
    _connection_manager.Arduino = _DevArduino
    # The I2C reset handshake also needs the (absent) hardware; skip it. The
    # reset callback now lives on ConnectionManager as well.
    _connection_manager.ConnectionManager.reset_arduino = (
        lambda self, *a, **k: self.window.loading_spinner.hide()
    )

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        # Some unit-test harnesses replace QApplication with a lightweight
        # stand-in. Font registration requires a real Qt application and can
        # crash the process when none exists.
        if not hasattr(QApplication, "instance") or QApplication.instance() is None:
            raise RuntimeError("no real Qt application instance")
        from ui.theme import apply_theme
        print(f"Theme applied: {apply_theme(app)}")
    except Exception as err:  # never let a theme issue block launch
        print(f"Theme not applied, continuing with default style: {err}")

    # Same crash guard as the device launcher (PyQt5 aborts on an unhandled
    # slot exception otherwise).
    kneespa._install_excepthook()
    window = kneespa.KneeSpa(debug_mode=True)
    # Match the device panel exactly (production runs fullscreen on a fixed
    # 1366x768 touchscreen; windowed debug mode would otherwise size to hint).
    window.setFixedSize(1366, 768)
    window.show()
    print("KneeSpa launched (debug/windowed, no hardware). Close the window to exit.")
    app.exec_()


if __name__ == "__main__":
    main()
