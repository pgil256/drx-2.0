"""Nonmodal pressure-progress notice with explicit operator actions."""

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QWidget

from ui.theme import control_icon
from ui.widgets.ds import DSButton, DSDialog
from ui.widgets.ds._common import resolve, sans_font


class PressureNotice(DSDialog):
    """Keep an advisory visible until the operator dismisses it or stops."""

    stop_requested = pyqtSignal()

    def __init__(self, notice: dict, parent: Optional[QWidget] = None) -> None:
        # No scrim: the treatment page and its STOP stay live underneath.
        # Wide and short, so it sits above the monitor's pressure readout.
        super().__init__(parent, title="Pressure is not building", tone="warning",
                         scrim=False, closable=False, width=780)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFont(sans_font(size="--text-base"))
        root = self.body_layout
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
        self.details.setStyleSheet(f"color: {resolve('--text-muted')};")
        self.details.hide()
        root.addWidget(self.details)
        self.details_button = DSButton("Show details", variant="ghost")
        self.details_button.clicked.connect(self._toggle_details)
        self.dismiss_button = DSButton("Dismiss", variant="secondary")
        self.stop_button = DSButton("STOP", variant="danger",
                                    icon=control_icon("stop", resolve("--white"), 20))
        self.dismiss_button.clicked.connect(self.close)
        self.stop_button.clicked.connect(self._stop)
        self.footer_layout.setContentsMargins(24, 12, 24, 12)
        self.add_action(self.details_button)
        self.add_action_stretch(1)
        for button in (self.dismiss_button, self.stop_button):
            button.setMinimumWidth(200)
            self.add_action(button)

    def _toggle_details(self) -> None:
        """Keep encoder counts available without obscuring the operator action."""
        visible = self.details.isHidden()
        self.details.setVisible(visible)
        self.details_button.setText("Hide details" if visible else "Show details")
        self.adjustSize()

    def _stop(self) -> None:
        self.stop_requested.emit()
        self.close()
