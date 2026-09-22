"""A service-scoped staff session and a reviewed, staged update flow."""

from copy import deepcopy
from pathlib import Path
import sys
import threading
from typing import Callable

from PyQt5.QtCore import QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QInputDialog, QMessageBox, QProgressDialog

from config.paths import DEVICE_STATE_DIR, PROJECT_DIR
from helpers.release_client import ReleaseClient
from helpers.release_installer import ReleaseInstaller
from helpers.staff_client import StaffError
from ui.modals.staff_login import StaffLogin


class ReleaseController(QObject):
    """Download/build off Qt; installation starts only after the main window closes."""

    completed = pyqtSignal(int, str, object)
    progress = pyqtSignal(int, str)

    def __init__(self, device: object) -> None:
        super().__init__(device)
        self.device, self.window = device, device.window
        self.client = ReleaseClient(self.window.cloud_client.cloud_url)
        self.installer = ReleaseInstaller(Path(PROJECT_DIR) / "runtime", Path(DEVICE_STATE_DIR))
        self.login = StaffLogin(self.window, purpose="download device releases")
        self.login.login_requested.connect(self._login)
        self.login.mfa_requested.connect(self._mfa)
        self.login.clinic_requested.connect(self._clinic)
        self.login.rejected.connect(self.clear_session)
        self.completed.connect(self._completed)
        self.progress.connect(self._progress)
        self.generation = 0
        self.busy = False
        self.worker = None
        self.cancel = threading.Event()
        self.releases = {}
        self.dialog = None

    def _allowed(self) -> bool:
        w = self.window
        return (self.device.service_authorized() and w.protocol_state in ("idle", "fault")
                and not w.protocol_running and not w.reset_in_progress
                and not getattr(w, "_calibration_active", False)
                and not getattr(w, "_physical_stop_active", False)
                and not w.actuator_command_in_progress)

    def clear_session(self) -> None:
        self.generation += 1
        self.cancel.set()
        old = self.client
        self.client = ReleaseClient(self.window.cloud_client.cloud_url)
        self.client._not_before = old._not_before
        if not self.busy and (old.context or list(old.cookies)):
            threading.Thread(target=old.logout, daemon=True).start()
        self.releases = {}
        self.login.accept()
        self.login.set_stage("login")
        self._close_progress()
        for name in ("flash_software", "flash_firmware"):
            self.device.screen.actions[name].setEnabled(False)
        self.device.screen.release_status.setText("Sign in to check the latest cloud releases.")

    def _close_progress(self) -> None:
        if self.dialog:
            self.dialog.blockSignals(True)
            self.dialog.reset()
            self.dialog.hide()
            self.dialog.deleteLater()
            self.dialog = None

    def action(self, name: str) -> None:
        if not self._allowed() or self.busy or self.device._busy:
            self.device.screen.set_status("Finish the current device operation first.")
            return
        if name == "check_releases":
            if self.client.context:
                self._run("latest", self.client.latest)
            else:
                self.login.set_stage("login")
                self.login.open()
        else:
            platform = "raspberry-pi" if name == "flash_software" else "arduino"
            self._prepare(platform)

    def _login(self, email: str, password: str) -> None:
        client = self.client
        self._run("login", lambda: client.login(email, password))

    def _mfa(self, code: str, recovery: bool) -> None:
        client = self.client
        self._run("login", lambda: client.verify_mfa(code, recovery))

    def _clinic(self, clinic: str) -> None:
        client = self.client
        self._run("clinic", lambda: client.select_clinic(clinic, "devices.view"))

    def _run(self, action: str, operation: Callable) -> None:
        if self.busy or not self._allowed() or self.device._busy:
            self._close_progress()
            message = "Device state changed. Finish the current operation and try again."
            self.device.screen.release_status.setText(message)
            self.login.show_error(message)
            return
        self.busy = True
        self.cancel = threading.Event()
        cancelled, client, generation = self.cancel, self.client, self.generation
        self.window._device_maintenance_active = True
        self.window.disable_actuator_controls()
        self.login.set_pending(True)
        self.device.screen.release_status.setText("Checking cloud…" if action != "prepare"
                                                   else "Downloading and verifying release…")

        def run() -> None:
            try:
                result = operation()
            except (StaffError, ValueError, RuntimeError) as exc:
                result = exc
            except Exception:
                self.device.logger.exception("Release %s failed", action)
                result = RuntimeError("Release preparation failed. See the device update logs.")
            finally:
                if cancelled.is_set():
                    client.logout()
            self.completed.emit(generation, action, result)

        self.worker = threading.Thread(target=run, daemon=True)
        try:
            self.worker.start()
        except RuntimeError:
            self._completed(generation, action, RuntimeError("Could not start the update worker."))

    def _completed(self, generation: int, action: str, result: object) -> None:
        self.busy = False
        self.window._device_maintenance_active = False
        self.login.set_pending(False)
        if not self.window._closing:
            self.window.enable_actuator_controls()
        if generation != self.generation or not self._allowed():
            return
        self._close_progress()
        if isinstance(result, Exception):
            if action in ("login", "clinic"):
                if isinstance(result, StaffError) and result.code == "mfa_challenge_expired":
                    self.login.set_stage("login")
                self.login.show_error(str(result))
            else:
                # Rechecking should always offer a fresh sign-in after an expired session.
                message = str(result)
                self.clear_session()
                self.device.screen.release_status.setText(message)
            return
        if action == "login":
            self.login.set_stage("mfa" if result.get("mfa_required") else "clinic", result)
        elif action == "clinic":
            self.login.accept()
            self._run("latest", self.client.latest)
        elif action == "latest":
            self.releases = result
            for platform, label, name in (
                    ("raspberry-pi", self.device.screen.software_release, "flash_software"),
                    ("arduino", self.device.screen.firmware_release, "flash_firmware")):
                release = result.get(platform)
                label.setText(("Latest upload: " + release["version"] + " · " +
                               release.get("created_at", "")) if release else "No release uploaded")
                self.device.screen.actions[name].setEnabled(release is not None)
            self.device.screen.release_status.setText(
                "Latest means most recently uploaded. Review the version before flashing.")
        elif action == "prepare":
            self._install_review(result)

    def _progress(self, generation: int, message: str) -> None:
        if generation == self.generation and self.dialog:
            self.dialog.setLabelText(message)

    def _prepare(self, platform: str) -> None:
        release = deepcopy(self.releases.get(platform))
        if not release:
            return
        if not sys.platform.startswith("linux") or not getattr(
                self.window, "_release_install_enabled", False):
            self.device.screen.set_status(
                "Flashing is available in the installed Raspberry Pi app.")
            return
        generation = self.generation
        port = ""
        if platform == "arduino":
            ports = sorted(str(p) for pattern in ("ttyACM*", "ttyUSB*")
                           for p in Path("/dev").glob(pattern))
            if not ports:
                self.device.screen.set_status("Connect the Mega 2560 USB cable before flashing.")
                return
            port, accepted = QInputDialog.getItem(
                self.window, "Mega 2560 USB port", "Select the connected Mega 2560:",
                ports, 0, False)
            if not accepted or not self._allowed() or generation != self.generation:
                return
        review = QMessageBox(self.window)
        review.setWindowTitle("Review release")
        review.setTextFormat(Qt.PlainText)
        review.setText(f"Download {release['version']} for {platform}?\n\n"
                       f"{release['filename']} · {release['size_bytes'] / 1048576:.1f} MB\n"
                       "This is the latest upload; it may be an older version.\n"
                       + ("Target: Arduino Mega 2560 over " + port if port else
                          "Target: this Raspberry Pi's application folder"))
        review.setDetailedText(release.get("notes") or "No release notes provided.")
        review.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        review.setDefaultButton(QMessageBox.No)
        if (review.exec_() != QMessageBox.Yes or not self._allowed()
                or generation != self.generation):
            return
        client = self.client
        technician = self.window.current_user.get("username", "Unknown")

        def prepare() -> dict:
            downloaded = client.download(
                release, self.installer.root / "downloads",
                lambda done, total: self.progress.emit(
                    generation, f"Downloading… {done * 100 // total}%"), self.cancel.is_set)
            if self.cancel.is_set():
                raise ValueError("Update cancelled before preparation.")
            self.progress.emit(generation, "Download verified. Checking package and preparing…")
            return self.installer.prepare(downloaded, release, port, technician)

        self.dialog = QProgressDialog("Preparing release…", "Cancel", 0, 0, self.window)
        self.dialog.setWindowTitle("Device update")
        self.dialog.setWindowModality(Qt.WindowModal)
        self.dialog.canceled.connect(self.clear_session)
        self.dialog.show()
        self._run("prepare", prepare)

    def _install_review(self, job: dict) -> None:
        generation = self.generation
        self.device.screen.release_status.setText("Downloaded and verified; not installed yet.")
        answer = QMessageBox.question(
            self.window, "Ready to flash",
            f"Flash {job['release']['version']} now?\n\nRemove the patient and all loads. "
            "Keep power connected. The app will close its device connection, back up the current "
            "installation, then install the verified release. "
            "You will be asked to restart afterward.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes or generation != self.generation or not self._allowed():
            return
        self.window._release_install = (self.installer, job)
        self.window.close()

    def shutdown_ready(self) -> bool:
        if not self.cancel.is_set():
            self.clear_session()
        return self.worker is None or not self.worker.is_alive()
