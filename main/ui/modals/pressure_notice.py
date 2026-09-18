"""Nonmodal pressure-progress notice with explicit operator actions."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import resolve, sans_font


class PressureNotice(QDialog):
    """Keep an advisory visible until the operator dismisses it or stops."""

    stop_requested = pyqtSignal()

    def __init__(self, notice: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pressure is not building")
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFont(sans_font(size="--text-base"))
        self.setStyleSheet(f"QDialog {{ background: {resolve('--surface-page')}; }}")
        self.setFixedWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)
        text = QLabel(
            f"The axial actuator moved {notice['travel_counts']} counts with only "
            f"{notice['rise_lb']:.1f} lb of pressure increase.", self
        )
        text.setWordWrap(True)
        root.addWidget(text)
        buttons = QHBoxLayout()
        self.dismiss_button = DSButton("Dismiss", variant="secondary")
        self.stop_button = DSButton("Stop", variant="danger")
        self.dismiss_button.clicked.connect(self.close)
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.dismiss_button)
        buttons.addWidget(self.stop_button)
        root.addLayout(buttons)

    def _stop(self) -> None:
        self.stop_requested.emit()
        self.close()
