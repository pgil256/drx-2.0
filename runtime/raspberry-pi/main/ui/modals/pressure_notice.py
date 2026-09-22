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
            "The axial actuator moved, but pressure increased very little. "
            "Check the patient positioning and device. Dismiss closes this notice; "
            "Stop ends movement without automatic homing.", self
        )
        text.setWordWrap(True)
        root.addWidget(text)
        self.details = QLabel(
            f"Axial travel: {notice['travel_counts']} counts\n"
            f"Pressure increase: {notice['rise_lb']:.1f} lb", self
        )
        self.details.setWordWrap(True)
        self.details.hide()
        self.details_button = DSButton("Show details", variant="secondary", size="sm")
        self.details_button.clicked.connect(self._toggle_details)
        root.addWidget(self.details_button)
        root.addWidget(self.details)
        buttons = QHBoxLayout()
        self.dismiss_button = DSButton("Dismiss", variant="secondary")
        self.stop_button = DSButton("Stop", variant="danger")
        self.dismiss_button.clicked.connect(self.close)
        self.stop_button.clicked.connect(self._stop)
        buttons.addWidget(self.dismiss_button)
        buttons.addWidget(self.stop_button)
        root.addLayout(buttons)

    def _toggle_details(self) -> None:
        """Keep encoder counts available without obscuring the operator action."""
        visible = self.details.isHidden()
        self.details.setVisible(visible)
        self.details_button.setText("Hide details" if visible else "Show details")
        self.adjustSize()

    def _stop(self) -> None:
        self.stop_requested.emit()
        self.close()
