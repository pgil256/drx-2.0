"""Explicit reconciliation after a patient-create response is lost."""

from typing import Dict, Optional

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from ui.modals.staff_login import open_text_keyboard
from ui.widgets.ds import DSButton


class PatientReconcile(QDialog):
    search_requested = pyqtSignal(int)
    existing_requested = pyqtSignal(str, str)
    not_created_confirmed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check saved patients")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedWidth(780)
        self._page = 1
        self._pages = 1
        self._loaded = False
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        info = QLabel("The save may have succeeded. Review the cloud patient list before retrying. "
                      "A matching name alone does not identify a patient.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self._results = QComboBox()
        self._results.setMinimumHeight(52)
        layout.addWidget(self._results)
        paging = QHBoxLayout()
        self._previous = DSButton("Previous page", variant="secondary")
        self._next = DSButton("Next page", variant="secondary")
        self._previous.clicked.connect(lambda: self.search_requested.emit(max(1, self._page - 1)))
        self._next.clicked.connect(lambda: self.search_requested.emit(self._page + 1))
        paging.addWidget(self._previous)
        paging.addWidget(self._next)
        layout.addLayout(paging)
        self._pin = QLineEdit()
        self._pin.setPlaceholderText("Selected patient's four-digit PIN")
        self._pin.setAccessibleName("Patient PIN")
        self._pin.setMaxLength(4)
        self._pin.setMinimumHeight(52)
        self._pin.installEventFilter(self)
        layout.addWidget(self._pin)
        self._use = DSButton("Use selected patient")
        self._use.clicked.connect(self._select)
        layout.addWidget(self._use)
        self._confirmed = QCheckBox(
            "I checked the cloud records and confirmed this patient was not created."
        )
        self._confirmed.toggled.connect(
            lambda checked: self._retry.setEnabled(checked and self._loaded)
        )
        layout.addWidget(self._confirmed)
        self._retry = DSButton("Return to form to retry", variant="secondary")
        self._retry.setEnabled(False)
        self._retry.clicked.connect(self._allow_retry)
        layout.addWidget(self._retry)
        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._close = DSButton("Close", variant="secondary")
        self._close.clicked.connect(self.reject)
        layout.addWidget(self._close)
        self._results.currentIndexChanged.connect(self._fill_pin)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self._pin and event.type() == QEvent.MouseButtonRelease:
            self._keyboard = open_text_keyboard(self._pin, self)
            return True
        return super().eventFilter(watched, event)

    def _fill_pin(self) -> None:
        patient = self._results.currentData() or {}
        self._pin.setText(patient.get("pin") or "")

    def _select(self) -> None:
        patient = self._results.currentData()
        pin = self._pin.text()
        if not patient or len(pin) != 4 or not pin.isascii() or not pin.isdigit():
            self._status.setText("Select the saved patient and enter their four-digit PIN.")
            return
        self.existing_requested.emit(patient["id"], pin)

    def _allow_retry(self) -> None:
        if self._loaded and self._confirmed.isChecked():
            self.not_created_confirmed.emit()
            self.accept()

    def set_pending(self, pending: bool) -> None:
        for widget in (self._results, self._pin, self._use, self._close, self._confirmed):
            widget.setEnabled(not pending)
        self._previous.setEnabled(not pending and self._page > 1)
        self._next.setEnabled(not pending and self._page < self._pages)
        self._retry.setEnabled(not pending and self._loaded and self._confirmed.isChecked())
        if pending:
            self._status.setText("Checking cloud patients…")

    def show_results(self, result: Dict) -> None:
        self._page = result.get("page", 1)
        self._pages = max(1, result.get("pages", 1))
        self._loaded = True
        self._confirmed.setChecked(False)
        self._results.clear()
        self._results.addItem("Choose a saved patient…", None)
        for patient in result.get("items", []):
            text = (f"{patient.get('display_name') or '(unnamed)'} · "
                    f"{patient.get('external_ref') or ''} · "
                    f"{patient.get('status')} · {patient['id']}")
            self._results.addItem(text, patient)
        self.set_pending(False)
        self._status.setText(
            f"Page {self._page} of {self._pages} · {result.get('total', 0)} matches. "
            "If the PIN is not shown, ask a clinician to retrieve it in the dashboard."
        )

    def show_error(self, message: str) -> None:
        self.set_pending(False)
        self._status.setText(message)
