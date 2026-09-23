"""Patient PIN entry, separate from local operator authentication.

Shares the DSDialog frame. While a lookup is pending the keypad keeps its
white keys with faded labels and a spinner sits beside "Looking up patient…",
so the pad never looks broken.
"""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

from ui.widgets.ds import DSButton, DSKeypad, DSSheet, DSSpinner
from ui.widgets.ds._common import resolve, sans_font

from ._overlay import Overlay

READY_TEXT = "Use the patient PIN from the cloud dashboard."


class PatientModal(Overlay):
    submitted = pyqtSignal(str)
    add_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        card = DSSheet("Patient PIN", width=420)
        card.close_requested.connect(self.close_overlay)
        layout = card.body_layout
        layout.setContentsMargins(28, 18, 28, 20)
        layout.setSpacing(14)
        self._keypad = DSKeypad(length=4, label="Enter patient PIN", compact=True)
        self._keypad.submitted.connect(self.submitted)
        layout.addWidget(self._keypad, 0, Qt.AlignHCenter)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_row.addStretch(1)
        self._spinner = DSSpinner(18)
        self._spinner.hide()
        status_row.addWidget(self._spinner, 0, Qt.AlignVCenter)
        self._status = QLabel(READY_TEXT)
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFont(sans_font(size="--text-sm", weight=600))
        self._status.setStyleSheet(f"color: {resolve('--ink-800')}; background: transparent;")
        status_row.addWidget(self._status)
        status_row.addStretch(1)
        layout.addLayout(status_row)
        self._add = DSButton("Add patient in clinician app", variant="secondary",
                             full_width=True)
        self._add.clicked.connect(self.add_requested)
        layout.addWidget(self._add)
        self._manual = DSButton("Continue without patient", variant="ghost",
                                full_width=True)
        self._manual.clicked.connect(self.close_overlay)
        layout.addWidget(self._manual)
        self.set_card(card)

    def set_pending(self, pending: bool) -> None:
        self._keypad.setEnabled(not pending)
        self._add.setEnabled(not pending)
        self._spinner.setVisible(pending)
        if pending:
            self._status.setText("Looking up patient…")

    def show_error(self, message: str) -> None:
        self.set_pending(False)
        self._status.setText(message)
        self._keypad.set_value("")

    def open_over(self, parent: Optional[QWidget] = None) -> None:
        self.set_pending(False)
        self._status.setText(READY_TEXT)
        self._keypad.set_value("")
        super().open_over(parent)
