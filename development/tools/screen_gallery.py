"""Screen gallery — renders the full modern shell + each screen to PNG.

Verification aid: builds the AppShell at the device resolution (1366×768) and
snapshots each page, overlay and dialog. Dialogs are frameless windows over an
in-shell scrim, so they are composited onto the shell grab. ``--baseline DIR``
also writes before/after sheets (baseline left, new right) to ``OUT/compare``.

    python development/tools/screen_gallery.py                       # windowed
    QT_QPA_PLATFORM=offscreen python development/tools/screen_gallery.py --outdir OUT
    QT_QPA_PLATFORM=offscreen python development/tools/screen_gallery.py --outdir OUT --baseline OLD
"""

import argparse
import os
import sys
from types import SimpleNamespace

os.environ.setdefault("KNEESPA_DEVICE_DIR", os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", ".cache", "screen-gallery-device"
)))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "raspberry-pi", "main"))
sys.path.insert(0, os.path.dirname(sys.path[0]))

from PyQt5.QtCore import QRect, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402

from ui.theme import apply_theme  # noqa: E402
from ui.app_shell import AppShell  # noqa: E402
from ui.modals.pressure_notice import PressureNotice  # noqa: E402
from ui.modals.service_pin_dialog import ServicePinDialog  # noqa: E402
from ui.modals.alert_dialog import DSAlertDialog  # noqa: E402
from ui.modals.hardware_service_dialog import HardwareServiceDialog  # noqa: E402
from ui.modals.treatment_review import TreatmentReviewDialog  # noqa: E402
from ui.widgets.treatment_status_panel import TreatmentStatusPanel  # noqa: E402

W, H = 1366, 768


def _settle(app):
    # Hidden pages and newly closed dialogs may schedule a second layout pass.
    for _ in range(3):
        app.sendPostedEvents()
        app.processEvents()
    QTest.qWait(60)


def _grab(shell, app, path, *dialogs):
    """Save the shell, compositing any open DSDialog windows over their scrim."""
    _settle(app)
    shell.repaint()
    app.processEvents()
    image = shell.grab()
    if dialogs:
        painter = QPainter(image)
        origin = shell.mapToGlobal(shell.rect().topLeft())
        for dialog in dialogs:
            painter.drawPixmap(dialog.pos() - origin, dialog.grab())
        painter.end()
    image.save(path)
    print(f"  saved {os.path.basename(path)}")


def render_all(outdir, width=W, height=H):
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    shell = AppShell()
    shell.setFixedSize(width, height)
    shell.show()
    app.processEvents()

    os.makedirs(outdir, exist_ok=True)
    shell.set_device_status("Ready", "Review settings and patient positioning.", True)
    shell.setup.set_arduino_connected(True)
    for key, value in (("axial", 1.2), ("horizontal", -10), ("lateral", 0), ("pressure", 0)):
        shell.setup.set_measured_position(key, value)

    # Logged-out home.
    shell.set_user(None)
    shell.navigate("home")
    _grab(shell, app, os.path.join(outdir, "01-home-logged-out.png"))

    # Login modal over home: staff PIN first, then the QR code option.
    shell.show_login()
    shell.login_modal._keypad.set_value("12")
    _grab(shell, app, os.path.join(outdir, "02-login-modal.png"))
    shell.login_modal._switch.click()
    shell.login_modal.show_phone_request({
        "verification_url": "https://example.invalid/connect#code=demo",
        "display_code": "R2QG-63MF",
    })
    shell.login_modal.set_phone_remaining(295)
    _grab(shell, app, os.path.join(outdir, "27-login-qr.png"))
    shell.login_modal.phone_status("Could not reach the cloud. Check the connection.")
    _grab(shell, app, os.path.join(outdir, "26-login-qr-retry.png"))
    shell.login_modal.close_overlay()

    # Logged in → all pages.
    shell.set_user("Dr. Vasquez")
    shell.navigate("home")
    _grab(shell, app, os.path.join(outdir, "03-home-logged-in.png"))

    shell.navigate("setup")
    _grab(shell, app, os.path.join(outdir, "04-setup.png"))

    shell.navigate("protocols")
    shell.treatment.set_pressure(0)
    shell.treatment.set_pressure_state("Pressure live")
    shell.treatment.set_angle(0)
    _grab(shell, app, os.path.join(outdir, "05-treatment.png"))
    shell.treatment.open_treatment_editor()
    _grab(shell, app, os.path.join(outdir, "05b-edit-treatment.png"), shell.treatment._editor)
    shell.treatment._editor.accept()

    # Treatment mid-run state (exercise the run-state model + telemetry setters).
    shell.treatment.set_run_state(running=True, paused=False)
    shell.set_device_status("Treatment active", "Duration and motor speed are locked.", False)
    shell.treatment.set_phase("holding")
    shell.treatment.set_progress(180, 720)
    shell.treatment.set_pressure(40)
    shell.treatment.set_angle(0)
    _grab(shell, app, os.path.join(outdir, "06-treatment-running.png"))
    # Videos stay available mid-treatment, with live status and STOP.
    shell.show_video()
    _grab(shell, app, os.path.join(outdir, "06b-video-during-treatment.png"))
    shell.video_modal.close_overlay()
    shell.treatment.set_run_state(running=False, paused=False)
    shell.treatment.set_phase("idle")
    shell.set_device_status("Ready", "Review settings and patient positioning.", True)

    shell.navigate("support")
    _grab(shell, app, os.path.join(outdir, "07-support-protocols.png"))
    shell.support._section_buttons[1].click()
    _grab(shell, app, os.path.join(outdir, "07b-support-controls.png"))
    shell.support._section_buttons[0].click()

    shell.navigate("support")
    shell.support._select_section(2)
    _grab(shell, app, os.path.join(outdir, "08-support-troubleshooting.png"))
    shell.support._select_section(3)
    _grab(shell, app, os.path.join(outdir, "08b-contact-support.png"))
    shell.navigate("device")
    shell.device.set_setting("volume", 65, "Adjusts the system's default audio output.")
    shell.device.set_setting("brightness", 80, "Minimum 10% keeps the display visible.")
    shell.device.set_device_id("drx-demo-01")
    shell.device.set_firmware("Demo firmware", True)
    shell.device.set_details({
        "network": "Network: Clinic Wi-Fi", "addresses": "IP addresses: wlan0: 192.168.1.25",
        "wifi_backend": "Wi-Fi setup: NetworkManager", "internet": "Internet: Reachable over HTTPS",
        "cloud": "Cloud: Connected", "pending": "Pending uploads: 2",
        "sync_detail": "2 pending · 0 need attention. Upload waiting for connection.",
        "last_sync": "Last successful sync: 2026-09-21 10:32",
        "sync_time": "Last successful sync: 2026-09-21 10:32",
        "clock": "Current time: 2026-09-21 10:40 EDT", "timezone": "Time zone: America/New_York",
        "ntp": "Automatic time: Enabled · Synchronized",
    })
    shell.device.set_history([
        {"file": "hardware-demo.json", "date": "2026-09-21T14:20:00+00:00",
         "operator": "Dr. Vasquez", "kind": "Hardware tests",
         "result": "Incomplete / skipped checks", "saved": False},
        {"file": "hardware-calibration.json", "date": "2026-09-20T15:30:00+00:00",
         "operator": "Technician", "kind": "Calibration", "result": "Calibration saved",
         "saved": True},
    ], ["calibration-20260921T142000Z.json"])
    _grab(shell, app, os.path.join(outdir, "08c-device.png"))
    for index, name in enumerate(("settings", "service"), 1):
        if index == 2:
            shell.device.unlock_service()
        else:
            shell.device._select_section(index)
        _grab(shell, app, os.path.join(outdir, f"08c{index}-device-{name}.png"))
        scroll = shell.device._sections.currentWidget()
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        _grab(shell, app, os.path.join(outdir, f"08c{index}-device-{name}-bottom.png"))
    shell.device._select_section(0)

    # Video modal.
    shell.show_video()
    _grab(shell, app, os.path.join(outdir, "09-video-modal.png"))
    shell.video_modal.close_overlay()

    shell.navigate("protocols")
    view = shell.treatment
    view.set_progress(0, view.settings_values()["duration"] * 60)
    view.set_pressure(0)
    view.set_angle(0)
    view.select_protocol(4)
    view.set_patient("Alexandria Example · demonstration patient")
    view.set_cloud_status("Records up to date")
    _grab(shell, app, os.path.join(outdir, "10-treatment-oscillating-ready.png"))
    view.set_patient_pending(True)
    shell.patient_modal.open_over(shell)
    shell.patient_modal.set_pending(True)
    _grab(shell, app, os.path.join(outdir, "11-patient-lookup.png"))
    shell.patient_modal.close_overlay()
    view.set_patient_pending(False)

    review = TreatmentReviewDialog(4, view.settings_values(), "Patient: Demonstration", shell)
    review.show()
    _grab(shell, app, os.path.join(outdir, "12-start-review.png"), review)
    review.close()

    view.set_run_state(True, False)
    view.set_busy(True)
    shell.set_device_status("Preparing", "Centering and zeroing resting pressure.", False)
    _grab(shell, app, os.path.join(outdir, "13-treatment-starting.png"))
    view.set_busy(False)
    view.set_run_state(True, True)
    view.set_progress(180, 720)
    view.set_pressure(40)
    view.set_phase("paused")
    shell.set_device_status("Treatment active", "Treatment paused.", False)
    _grab(shell, app, os.path.join(outdir, "14-treatment-paused.png"))
    view.set_run_state(True, False)
    view.set_busy(True)
    shell.set_device_status("Stopping / recovering", "Release requested · recovery pending.", False)
    _grab(shell, app, os.path.join(outdir, "15-treatment-stopping.png"))
    shell.set_device_status("Resetting", "Homing in progress. Wait for completion.", False)
    _grab(shell, app, os.path.join(outdir, "16-treatment-recovery.png"))
    view.set_run_state(False, False)
    view.set_outcome("fault", 180)
    shell.set_device_status("Recovery required", "Review the fault before resetting.", False)
    view.set_pressure_state("Controller fault — last reading stale")
    view.set_angle(None)
    _grab(shell, app, os.path.join(outdir, "17-treatment-fault.png"))
    view.set_busy(False)
    shell.set_device_status("Ready", "Review settings and patient positioning.", True)
    view.set_phase("complete")
    view.set_outcome("completed", 720)
    view.set_progress(720, 720)
    view.set_pressure(0)
    view.set_pressure_state("Pressure live")
    view.set_angle(0)
    view.set_cloud_status("Upload failed · record retained for retry")
    view.set_upload_error()
    _grab(shell, app, os.path.join(outdir, "18-completed-upload-failed.png"))
    view.clear_outcome()
    view.set_phase("idle")
    view.set_progress(0, view.settings_values()["duration"] * 60)
    view.set_angle(None)
    view.set_pressure_state("Waiting for pressure")
    _grab(shell, app, os.path.join(outdir, "19-pressure-missing.png"))
    view.set_pressure_state("Pressure stale")
    _grab(shell, app, os.path.join(outdir, "20-pressure-stale.png"))

    view.set_run_state(True, False)
    view.set_pressure_state("Pressure live")
    view.set_pressure(3.2)
    view.set_progress(40, 720)
    view.set_phase("ramping")
    notice = PressureNotice({"travel_counts": 200, "rise_lb": 0.1}, shell)
    notice.show()
    _grab(shell, app, os.path.join(outdir, "21-pressure-notice.png"), notice)
    notice.close()
    view.set_run_state(False, False)
    view.set_phase("idle")
    pin = ServicePinDialog(SimpleNamespace(configured=True), False, shell)
    pin.show()
    _grab(shell, app, os.path.join(outdir, "22-service-pin.png"), pin)
    pin.close()
    draft = SimpleNamespace(
        marks={"axial": {"0": 0, "4": 4000}, "horizontal": {"-25": 0, "5": 3000},
               "lateral": {"-20": 500, "20": 2500}},
        factors={"axial": 6000, "horizontal": 6000, "lateral": 6000},
        scale=10000, changes=lambda: [],
    )
    service = HardwareServiceDialog(draft, shell, mode="tests")
    service.show()
    _grab(shell, app, os.path.join(outdir, "23-service.png"), service)
    service.done(0)
    shell.navigate("support")
    shell.support._select_section(2)
    from ui.screens.support import _FailureItem
    for item in shell.support.findChildren(_FailureItem):
        item._toggle()
    shell.support.set_delivery_state("failed", "Request not sent. Check the connection and retry.")
    _grab(shell, app, os.path.join(outdir, "24-support-expanded.png"))
    shell.set_user("Dr. Vasquez", is_admin=True)
    shell.navigate("profile")
    _grab(shell, app, os.path.join(outdir, "25-profile.png"))

    # Idle-time banners over Setup (docked under the top bar) and a safety alert.
    shell.navigate("setup")
    banner = TreatmentStatusPanel(parent=shell)
    banner.set_warning("Lateral position limit reached")
    _grab(shell, app, os.path.join(outdir, "28-setup-warning-banner.png"))
    banner.set_fault("Pressure limit exceeded")
    _grab(shell, app, os.path.join(outdir, "29-setup-fault-banner.png"))
    banner.set_idle()
    alert = DSAlertDialog("SAFETY STOP", "Pressure exceeded the selected limit. Movement "
                          "stopped. Check the patient, then reset the device.", "critical", shell)
    alert.show()
    _grab(shell, app, os.path.join(outdir, "30-safety-alert.png"), alert)
    alert.close()

    print(f"Rendered shell screens to {outdir}")
    return app, shell


def compare(outdir, baseline):
    """Write baseline-left / new-right sheets for every image in both folders."""
    target = os.path.join(outdir, "compare")
    os.makedirs(target, exist_ok=True)
    count = 0
    for name in sorted(os.listdir(outdir)):
        before_path = os.path.join(baseline, name)
        if not name.endswith(".png") or not os.path.isfile(before_path):
            continue
        before, after = QImage(before_path), QImage(os.path.join(outdir, name))
        if before.isNull() or after.isNull():
            continue
        gap, label = 24, 40
        sheet = QImage(before.width() + after.width() + gap,
                       max(before.height(), after.height()) + label, QImage.Format_RGB32)
        sheet.fill(QColor("#ffffff"))
        painter = QPainter(sheet)
        font = QFont()
        font.setPixelSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#172f42"))
        painter.drawText(QRect(0, 0, before.width(), label), Qt.AlignCenter, "Before")
        painter.drawText(QRect(before.width() + gap, 0, after.width(), label), Qt.AlignCenter,
                         "After")
        painter.drawImage(0, label, before)
        painter.drawImage(before.width() + gap, label, after)
        painter.end()
        sheet.save(os.path.join(target, name))
        count += 1
    print(f"Wrote {count} before/after sheets to {target}")


def main():
    parser = argparse.ArgumentParser(description="KneeSpa DRx modern screen gallery")
    parser.add_argument("--outdir", metavar="DIR", help="Render every screen to PNGs and exit")
    parser.add_argument("--width", type=int, choices=(1352, 1360, 1366), default=W)
    parser.add_argument("--height", type=int, choices=(756, 768), default=H)
    parser.add_argument("--baseline", metavar="DIR",
                        help="Also write before/after sheets against a previous --outdir")
    args = parser.parse_args()

    if args.outdir:
        # Keep the application alive: compare() paints text after rendering.
        app, _shell = render_all(args.outdir, args.width, args.height)  # noqa: F841
        if args.baseline:
            compare(args.outdir, args.baseline)
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
