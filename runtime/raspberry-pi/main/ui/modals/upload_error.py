"""Persistent treatment-upload failure notice with optional recovery action."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QWidget

from ui.widgets.ds import DSButton, DSDialog
from ui.widgets.ds._common import sans_font


class UploadErrorDialog(DSDialog):
    """Nonmodal: an upload problem must never prevent access to device controls."""

    retry_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        # No scrim: the app underneath, including STOP, stays reachable.
        super().__init__(parent, title="Treatment upload failed", tone="warning",
                         scrim=False, width=620)
        self.setWindowModality(Qt.NonModal)
        self._message = QLabel()
        self._message.setTextFormat(Qt.PlainText)
        self._message.setWordWrap(True)
        self._message.setFont(sans_font(size="--text-base"))
        self.body_layout.addWidget(self._message)
        self._retry = DSButton("Retry upload", variant="secondary")
        self._close = DSButton("Close")
        self.add_action_stretch(1)
        for button in (self._retry, self._close):
            button.setAutoDefault(False)
            button.setMinimumWidth(160)
            self.add_action(button)
        self._retry.clicked.connect(self._retry_upload)
        self._close.clicked.connect(self.close)

    def _retry_upload(self) -> None:
        self.close()
        self.retry_requested.emit()

    def set_message(self, message: str, can_retry: bool) -> None:
        self._message.setText(message)
        self._retry.setVisible(can_retry)
        self.adjustSize()
