"""Patient PIN entry, separate from local operator authentication."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton, DSKeypad
from ui.widgets.ds._common import resolve, sans_font

from ._overlay import Overlay


class PatientModal(Overlay):
    submitted = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        card = QWidget()
        card.setObjectName("PatientCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(420)
        card.setStyleSheet("#PatientCard { background: white; border-radius: 16px; }")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(16)
        self._keypad = DSKeypad(length=4, label="Enter Patient PIN", compact=True)
        self._keypad.submitted.connect(self.submitted)
        layout.addWidget(self._keypad, 0, Qt.AlignHCenter)
        self._status = QLabel("Use the patient PIN from the cloud dashboard.")
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFont(sans_font(size="--text-sm", weight=600))
        self._status.setStyleSheet(f"color: {resolve('--ink-800')}; background: transparent;")
        layout.addWidget(self._status)
        self._manual = DSButton("Continue without cloud patient", variant="secondary",
                                full_width=True)
        self._manual.clicked.connect(self.close_overlay)
        layout.addWidget(self._manual)
        self.set_card(card)

    def set_pending(self, pending: bool) -> None:
        self._keypad.setEnabled(not pending)
        if pending:
            self._status.setText("Looking up patient…")

    def show_error(self, message: str) -> None:
        self.set_pending(False)
        self._status.setText(message)
        self._keypad.set_value("")

    def open_over(self, parent: Optional[QWidget] = None) -> None:
        self.set_pending(False)
        self._status.setText("Use the patient PIN from the cloud dashboard.")
        self._keypad.set_value("")
        super().open_over(parent)
