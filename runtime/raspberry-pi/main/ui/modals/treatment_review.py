"""Explicit, touch-sized review of the next treatment before motion starts."""

from typing import Mapping, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from helpers.motor_speed import treatment_motor_speed
from ui.screens.content import PROTOCOLS
from ui.widgets.ds import DSButton
from ui.widgets.ds._common import sans_font


class TreatmentReviewDialog(QDialog):
    """Review only; the protocol controller retains all start/preflight checks."""

    def __init__(
        self, protocol: int, settings: Mapping, patient: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review treatment")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setFixedWidth(680)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        title = QLabel(f"{protocol} · {PROTOCOLS[protocol - 1]['title']}")
        title.setFont(sans_font(size=24, weight=600))
        title.setWordWrap(True)
        layout.addWidget(title)
        self._patient = QLabel(patient)
        self._patient.setTextFormat(Qt.PlainText)
        self._patient.setWordWrap(True)
        self._patient.setFont(sans_font(size=18, weight=600))
        layout.addWidget(self._patient)
        self._rows = [
            ("Duration", f"{settings['duration']:g} min"),
            ("Pressure limit", f"{settings['max_pressure']:g} lbs"),
        ]
        if protocol in (2, 4):
            self._rows.append(("Left angle", f"{settings['max_left']:g}°"))
        if protocol in (3, 4):
            self._rows.append(("Right angle", f"{settings['max_right']:g}°"))
        rate = settings.get("pulse_rate", 0)
        self._rows.append(("Pulse rate", f"{rate:g}/sec" if rate else "Off"))
        self._rows.append(("Motor speed", f"{treatment_motor_speed(settings):g}%"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(32)
        grid.setVerticalSpacing(8)
        for index, (label, value) in enumerate(self._rows):
            for col, text in enumerate((label, value)):
                widget = QLabel(text)
                widget.setFont(sans_font(size=18, weight=600 if col else 400))
                grid.addWidget(widget, index, col)
        layout.addLayout(grid)
        instruction = QLabel("Confirm the patient is positioned before starting treatment.")
        instruction.setWordWrap(True)
        instruction.setFont(sans_font(size=18))
        layout.addWidget(instruction)
        actions = QHBoxLayout()
        self.back_button = DSButton("Back to settings", variant="secondary")
        self.start_button = DSButton("Start treatment", variant="primary")
        self.back_button.setAutoDefault(False)
        self.start_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.accept)
        actions.addWidget(self.back_button)
        actions.addWidget(self.start_button)
        layout.addLayout(actions)
        self.back_button.setFocus()

    @classmethod
    def confirm(cls, parent: QWidget, protocol: int, settings: Mapping, patient: str) -> bool:
        """Return True only after the operator explicitly selects Start treatment."""
        dialog = cls(protocol, settings, patient, parent)
        try:
            return dialog.exec_() == QDialog.Accepted
        finally:
            dialog.deleteLater()
