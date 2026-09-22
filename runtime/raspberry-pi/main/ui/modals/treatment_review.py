"""Explicit, touch-sized review of the next treatment before motion starts."""

from typing import Mapping, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QLabel, QWidget

from helpers.motor_speed import treatment_motor_speed
from ui.screens.content import PROTOCOLS
from ui.theme import play_icon
from ui.widgets.ds import DSButton, DSDialog, DSKeyValueList
from ui.widgets.ds._common import resolve, sans_font


class TreatmentReviewDialog(DSDialog):
    """Review only; the protocol controller retains all start/preflight checks."""

    def __init__(
        self, protocol: int, settings: Mapping, patient: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, title="Review treatment", width=680)
        layout = self.body_layout
        title = QLabel(f"{protocol} · {PROTOCOLS[protocol - 1]['title']}")
        title.setFont(sans_font(size="--text-lg", weight=600))
        title.setStyleSheet(f"color: {resolve('--text-strong')};")
        title.setWordWrap(True)
        layout.addWidget(title)
        self._patient = QLabel(patient)
        self._patient.setTextFormat(Qt.PlainText)
        self._patient.setWordWrap(True)
        self._patient.setFont(sans_font(size="--text-base", weight=600))
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
        self.summary = DSKeyValueList()
        for label, value in self._rows:
            self.summary.add_row(label.lower().replace(" ", "_"), label, value)
        layout.addWidget(self.summary)
        instruction = QLabel("Confirm the patient is positioned before starting treatment.")
        instruction.setWordWrap(True)
        instruction.setFont(sans_font(size="--text-base"))
        layout.addWidget(instruction)

        self.back_button = DSButton("Back to settings", variant="secondary")
        self.start_button = DSButton("Start treatment", variant="success",
                                     icon=play_icon(resolve("--white"), 18))
        self.back_button.setAutoDefault(False)
        self.start_button.setAutoDefault(False)
        self.back_button.clicked.connect(self.reject)
        self.start_button.clicked.connect(self.accept)
        self.add_action_stretch(1)
        self.add_action(self.back_button)
        self.add_action(self.start_button)

    @classmethod
    def confirm(cls, parent: QWidget, protocol: int, settings: Mapping, patient: str) -> bool:
        """Return True only after the operator explicitly selects Start treatment."""
        dialog = cls(protocol, settings, patient, parent)
        try:
            return dialog.exec_() == QDialog.Accepted
        finally:
            dialog.deleteLater()
