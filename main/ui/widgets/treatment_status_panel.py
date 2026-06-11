# ui/widgets/treatment_status_panel.py
"""Always-visible treatment banner with a permanent STOP control.

Live measured pressure, target, phase, and time remaining used to be
opt-in floating dialogs (off by default), so an operator could run a
traction protocol completely blind; the on-screen emergency stop only
existed on the Setup page. This panel overlays the top of the main
window whenever a protocol is active or the device is in a fault state.
"""
from typing import Optional

from PyQt5.QtCore import Qt, QEvent, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

_BASE_STYLE = """
QFrame#treatmentPanel {{
    background-color: {bg};
    border: none;
}}
QLabel {{
    color: white;
    background: transparent;
}}
"""

_STOP_STYLE = """
QPushButton {
    background-color: rgb(200, 0, 0);
    color: white;
    border: 3px solid white;
    border-radius: 10px;
    font-size: 26px;
    font-weight: bold;
}
QPushButton:pressed {
    background-color: rgb(140, 0, 0);
}
"""

PANEL_HEIGHT = 76

COLOR_RUNNING = "rgb(0, 90, 160)"
COLOR_STOPPING = "rgb(180, 120, 0)"
COLOR_FAULT = "rgb(170, 0, 0)"


class TreatmentStatusPanel(QFrame):
    """Top-of-screen banner: phase, live pressure, target, time, STOP."""

    stop_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("treatmentPanel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(20)

        self.phase_label = QLabel("")
        self.phase_label.setStyleSheet("font-size: 22px; font-weight: bold;")

        self.pressure_label = QLabel("-- lbs")
        self.pressure_label.setStyleSheet("font-size: 30px; font-weight: bold;")

        self.target_label = QLabel("")
        self.target_label.setStyleSheet("font-size: 18px;")

        self.time_label = QLabel("")
        self.time_label.setStyleSheet("font-size: 26px; font-weight: bold;")

        self.stop_button = QPushButton("STOP")
        self.stop_button.setMinimumSize(150, 60)
        self.stop_button.setStyleSheet(_STOP_STYLE)
        self.stop_button.clicked.connect(self.stop_requested.emit)

        layout.addWidget(self.phase_label)
        layout.addStretch(1)
        layout.addWidget(self.pressure_label)
        layout.addWidget(self.target_label)
        layout.addStretch(1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.stop_button)

        if parent is not None:
            parent.installEventFilter(self)
            self._fit_to_parent(parent)

        self.hide()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def set_running(self, target_pressure: float, duration_s: int) -> None:
        self._apply_color(COLOR_RUNNING)
        self.phase_label.setText("TREATMENT RUNNING")
        self.set_target(target_pressure)
        self.update_remaining(duration_s)
        self.stop_button.setEnabled(True)
        self.show()

    def set_phase(self, text: str) -> None:
        self.phase_label.setText(text)

    def set_target(self, target_pressure: float) -> None:
        self.target_label.setText(f"target {target_pressure:.0f} lbs")

    def set_stopping(self) -> None:
        self._apply_color(COLOR_STOPPING)
        self.phase_label.setText("STOPPING - RELEASING TRACTION")
        self.stop_button.setEnabled(False)
        self.show()

    def set_fault(self, message: str) -> None:
        """Fault banners persist until the next protocol start or reset."""
        self._apply_color(COLOR_FAULT)
        self.phase_label.setText(f"SAFETY STOP: {message}")
        self.time_label.setText("")
        self.stop_button.setEnabled(True)
        self.show()

    def set_idle(self) -> None:
        self.hide()
        self.phase_label.setText("")
        self.pressure_label.setText("-- lbs")
        self.target_label.setText("")
        self.time_label.setText("")
        self.stop_button.setEnabled(True)

    # ------------------------------------------------------------------
    # Live values
    # ------------------------------------------------------------------

    def update_pressure(self, pressure: float) -> None:
        """Measured pressure from device status, not the commanded value."""
        try:
            self.pressure_label.setText(f"{float(pressure):.1f} lbs")
        except (TypeError, ValueError):
            pass

    def update_remaining(self, seconds_left) -> None:
        try:
            seconds_left = max(0, int(seconds_left))
        except (TypeError, ValueError):
            return
        minutes, seconds = divmod(seconds_left, 60)
        self.time_label.setText(f"{minutes}:{seconds:02d} left")

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _apply_color(self, bg: str) -> None:
        self.setStyleSheet(_BASE_STYLE.format(bg=bg))

    def _fit_to_parent(self, parent: QWidget) -> None:
        self.setGeometry(0, 0, parent.width(), PANEL_HEIGHT)

    def show(self) -> None:  # noqa: A003 - QWidget API
        super().show()
        self.raise_()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Resize:
            self._fit_to_parent(watched)
        return super().eventFilter(watched, event)
