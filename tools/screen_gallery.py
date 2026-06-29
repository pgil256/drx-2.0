"""Screen gallery — renders the full modern shell + each screen to PNG.

Phase 2 verification aid: builds the AppShell at the device resolution
(1366×768) and snapshots each page and modal so they can be eyeballed against
the design ``screenshots/``.

    python tools/screen_gallery.py                       # windowed
    QT_QPA_PLATFORM=offscreen python tools/screen_gallery.py --outdir OUT
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main"))

from PyQt5.QtWidgets import QApplication  # noqa: E402

from ui.theme import apply_theme  # noqa: E402
from ui.app_shell import AppShell  # noqa: E402

W, H = 1366, 768


def _grab(shell, app, path):
    app.processEvents()
    shell.grab().save(path)
    print(f"  saved {os.path.basename(path)}")


def render_all(outdir):
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    shell = AppShell()
    shell.setFixedSize(W, H)  # the device runs fullscreen at exactly 1366×768
    shell.show()
    app.processEvents()

    os.makedirs(outdir, exist_ok=True)

    # Logged-out home.
    shell.set_user(None)
    shell.navigate("home")
    _grab(shell, app, os.path.join(outdir, "01-home-logged-out.png"))

    # Login modal over home.
    shell.show_login()
    _grab(shell, app, os.path.join(outdir, "02-login-modal.png"))
    shell.login_modal.close_overlay()

    # Logged in → all pages.
    shell.set_user("Dr. Vasquez")
    shell.navigate("home")
    _grab(shell, app, os.path.join(outdir, "03-home-logged-in.png"))

    shell.navigate("setup")
    _grab(shell, app, os.path.join(outdir, "04-setup.png"))

    shell.navigate("protocols")
    _grab(shell, app, os.path.join(outdir, "05-treatment.png"))

    # Treatment mid-run state (exercise the run-state model + telemetry setters).
    shell.treatment.set_run_state(running=True, paused=False)
    shell.treatment.set_phase("holding")
    shell.treatment.set_progress(18)
    shell.treatment.set_pressure(52)
    shell.treatment.set_angle(-12)
    _grab(shell, app, os.path.join(outdir, "06-treatment-running.png"))
    shell.treatment.set_run_state(running=False, paused=False)
    shell.treatment.set_phase("idle")

    shell.navigate("help")
    _grab(shell, app, os.path.join(outdir, "07-help.png"))

    shell.navigate("support")
    _grab(shell, app, os.path.join(outdir, "08-support.png"))

    # Video modal.
    shell.show_video()
    _grab(shell, app, os.path.join(outdir, "09-video-modal.png"))
    shell.video_modal.close_overlay()

    print(f"Rendered shell screens to {outdir}")
    return app, shell


def main():
    parser = argparse.ArgumentParser(description="KneeSpa DRx modern screen gallery")
    parser.add_argument("--outdir", metavar="DIR", help="Render every screen to PNGs and exit")
    args = parser.parse_args()

    if args.outdir:
        render_all(args.outdir)
        return

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    shell = AppShell()
    shell.set_user("Dr. Vasquez")
    shell.resize(W, H)
    shell.setWindowTitle("KneeSpa DRx — Modern Shell")
    shell.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
