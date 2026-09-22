"""Persistent treatment-upload failure window with optional recovery action."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import sans_font


class UploadErrorDialog(QDialog):
    """Nonmodal: an upload problem must never prevent access to device controls."""

    retry_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Treatment upload failed")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowModality(Qt.NonModal)
        self.setFixedWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        title = QLabel("Treatment upload failed")
        title.setFont(sans_font(size=24, weight=600))
        layout.addWidget(title)
        self._message = QLabel()
        self._message.setTextFormat(Qt.PlainText)
        self._message.setWordWrap(True)
        self._message.setFont(sans_font(size=18))
        layout.addWidget(self._message)
        actions = QHBoxLayout()
        self._retry = DSButton("Retry upload", variant="secondary")
        self._close = DSButton("Close")
        for button in (self._retry, self._close):
            button.setAutoDefault(False)
            actions.addWidget(button)
        self._retry.clicked.connect(self._retry_upload)
        self._close.clicked.connect(self.close)
        layout.addLayout(actions)

    def _retry_upload(self) -> None:
        self.close()
        self.retry_requested.emit()

    def set_message(self, message: str, can_retry: bool) -> None:
        self._message.setText(message)
        self._retry.setVisible(can_retry)
        self.adjustSize()
