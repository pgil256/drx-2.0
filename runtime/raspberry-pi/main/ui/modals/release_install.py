"""Post-shutdown installer: no device-control window or serial owner remains."""

import threading
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QLabel, QMessageBox

from ui.widgets.ds import DSDialog
from ui.widgets.ds._common import resolve, sans_font


class ReleaseInstallDialog(DSDialog):
    progress = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(self, installer: object, job: dict) -> None:
        # Runs after the main window has closed, so it is its own window.
        super().__init__(None, title="Installing device release", closable=False)
        self.installer, self.job = installer, job
        self.running = True
        self.restart = False
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setMinimumWidth(650)
        layout = self.body_layout
        self.message = QLabel("Device controls are closed. Preparing backup…")
        self.message.setTextFormat(Qt.PlainText)
        self.message.setWordWrap(True)
        self.message.setFont(sans_font(size="--text-base"))
        layout.addWidget(self.message)
        power = QLabel("Keep power connected until installation finishes.")
        power.setFont(sans_font(size="--text-sm", weight=600))
        power.setStyleSheet(f"color: {resolve('--amber-500')};")
        layout.addWidget(power)
        self.progress.connect(self.message.setText)
        self.completed.connect(self._done)
        QTimer.singleShot(0, self._start)

    def reject(self) -> None:
        if not self.running:
            super().reject()

    def closeEvent(self, event: object) -> None:
        if self.running:
            event.ignore()
        else:
            super().closeEvent(event)

    def _start(self) -> None:
        def install() -> None:
            try:
                message = self.installer.install(self.job, self.progress.emit)
                self.completed.emit(True, message)
            except Exception:
                self.completed.emit(
                    False, "Installation failed. Do not use the device until service "
                    "recovery is complete. Backup and logs: " + self.job["work"])
        self.worker = threading.Thread(target=install, daemon=False)
        self.worker.start()

    def _done(self, success: bool, message: str) -> None:
        self.running = False
        self.message.setText(message)
        title = "Installation complete" if success else "Installation needs attention"
        self.restart = QMessageBox.question(
            self, title, message + "\n\nRestart App now?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        self.accept()


def finish_release_install(window: object) -> None:
    """Call after QApplication.exec_ returns and the main window has fully cleaned up."""
    pending = getattr(window, "_release_install", None)
    if pending is None or not getattr(window, "_cleanup_complete", False):
        return
    dialog = ReleaseInstallDialog(*pending)
    dialog.exec_()
    window.restart_requested = dialog.restart
