"""DSAlertDialog — acknowledged safety and device alerts.

Replaces the stock message boxes for safety stops, device warnings and timed
errors: a red (critical) or amber (warning) title strip, the message, and one
large Acknowledge button. It is non-modal and has no scrim, docks under the top
bar and stays on top, so STOP controls remain reachable while it is open.
Follow-on messages from the same event can be folded into an open alert, and a
warning can be upgraded to critical in place.
"""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QWidget

from ui.theme import control_icon
from ui.widgets.ds import DSButton, DSDialog
from ui.widgets.ds._common import resolve, sans_font

_SEVERITY = {
    "critical": ("danger", "--red-600"),
    "warning": ("warning", "--amber-500"),
}


class DSAlertDialog(DSDialog):
    def __init__(self, title: str, message: str, severity: str = "critical",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, title=title, scrim=False, closable=False, width=600)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowModality(Qt.NonModal)
        row = QHBoxLayout()
        row.setSpacing(16)
        self._icon = QLabel()
        self._icon.setFixedSize(40, 40)
        row.addWidget(self._icon, 0, Qt.AlignTop)
        self._message = QLabel(message)
        self._message.setTextFormat(Qt.PlainText)
        self._message.setWordWrap(True)
        self._message.setFont(sans_font(size="--text-md", weight=600))
        self._message.setStyleSheet(f"color: {resolve('--text-strong')};")
        row.addWidget(self._message, 1)
        self.body_layout.addLayout(row)
        self.acknowledge_button = DSButton("Acknowledge", variant="primary", size="lg",
                                           full_width=True)
        self.acknowledge_button.setAutoDefault(False)
        self.acknowledge_button.clicked.connect(self.accept)
        self.add_action(self.acknowledge_button, 1)
        self._severity = "critical"
        self.set_severity(severity)

    def set_severity(self, severity: str) -> None:
        self._severity = severity if severity in _SEVERITY else "critical"
        tone, color = _SEVERITY[self._severity]
        self.set_tone(tone)
        self._icon.setPixmap(control_icon("alert", resolve(color), 40).pixmap(40, 40))

    def severity(self) -> str:
        return self._severity

    def text(self) -> str:
        return self._message.text()

    def setText(self, text: str) -> None:  # noqa: N802 - QMessageBox-compatible
        self._message.setText(text)
        self.adjustSize()
