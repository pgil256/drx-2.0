# ui/widgets/treatment_status_panel.py
"""Always-visible treatment banner with a permanent emergency-stop control.

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

_DISMISS_STYLE = """
QPushButton {
    background-color: rgba(255, 255, 255, 35);
    color: white;
    border: 2px solid white;
    border-radius: 8px;
    font-size: 30px;
    font-weight: bold;
}
QPushButton:pressed {
    background-color: rgba(255, 255, 255, 80);
}
"""

PANEL_HEIGHT = 76

COLOR_RUNNING = "rgb(0, 90, 160)"
COLOR_STOPPING = "rgb(180, 120, 0)"
COLOR_WARNING = "rgb(196, 112, 0)"
COLOR_FAULT = "rgb(170, 0, 0)"


class TreatmentStatusPanel(QFrame):
    """Top banner: phase, pressure, target, time, and emergency stop."""

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

        self.stop_button = QPushButton("EMERGENCY STOP")
        self.stop_button.setMinimumSize(220, 60)
        self.stop_button.setStyleSheet(_STOP_STYLE)
        self.stop_button.clicked.connect(self.stop_requested.emit)

        self.dismiss_button = QPushButton("×")
        self.dismiss_button.setObjectName("dismissWarningButton")
        self.dismiss_button.setFixedSize(48, 48)
        self.dismiss_button.setCursor(Qt.PointingHandCursor)
        self.dismiss_button.setToolTip("Dismiss this advisory warning")
        self.dismiss_button.setAccessibleName("Dismiss safety warning")
        self.dismiss_button.setStyleSheet(_DISMISS_STYLE)
        self.dismiss_button.clicked.connect(self.dismiss_warning)
        self.dismiss_button.hide()

        layout.addWidget(self.phase_label)
        layout.addStretch(1)
        layout.addWidget(self.pressure_label)
        layout.addWidget(self.target_label)
        layout.addStretch(1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.dismiss_button)

        self._mode = "idle"
        self._warning_return_mode = "idle"
        self._warning_return_phase = ""
        self._warning_return_time = ""

        if parent is not None:
            parent.installEventFilter(self)
            self._fit_to_parent(parent)

        self.hide()

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def set_running(self, target_pressure: float, duration_s: int) -> None:
        self._mode = "running"
        self.dismiss_button.hide()
        self._apply_color(COLOR_RUNNING)
        self.phase_label.setText("TREATMENT RUNNING")
        self.set_target(target_pressure)
        self.update_remaining(duration_s)
        self.stop_button.setEnabled(True)
        self.show()

    def set_phase(self, text: str) -> None:
        if self._mode == "warning":
            self._warning_return_phase = text
            return
        self.phase_label.setText(text)

    def set_target(self, target_pressure: float) -> None:
        self.target_label.setText(f"target {target_pressure:.0f} lbs")

    def set_stopping(self) -> None:
        self._mode = "stopping"
        self.dismiss_button.hide()
        self._apply_color(COLOR_STOPPING)
        self.phase_label.setText("STOPPING - RELEASING TRACTION")
        # A graceful stop can stall or fail. The independent emergency-stop
        # path must remain available throughout release and recovery.
        self.stop_button.setEnabled(True)
        self.show()

    def set_fault(self, message: str) -> None:
        """Fault banners persist until the next protocol start or reset."""
        self._mode = "fault"
        self.dismiss_button.hide()
        self._apply_color(COLOR_FAULT)
        self.phase_label.setText(f"SAFETY STOP: {message}")
        self.time_label.setText("")
        self.stop_button.setEnabled(True)
        self.show()

    def set_warning(self, message: str) -> None:
        """Show a dismissible advisory without obscuring an active fault."""
        if self._mode == "fault":
            return
        if self._mode != "warning":
            self._warning_return_mode = self._mode
            self._warning_return_phase = self.phase_label.text()
            self._warning_return_time = self.time_label.text()
        self._mode = "warning"
        self._apply_color(COLOR_WARNING)
        self.phase_label.setText(f"DEVICE SAFETY WARNING: {message}")
        self.time_label.setText("")
        self.stop_button.setEnabled(True)
        self.dismiss_button.show()
        self.show()

    def dismiss_warning(self) -> None:
        """Dismiss only an advisory warning, restoring any active treatment."""
        if self._mode != "warning":
            return

        return_mode = self._warning_return_mode
        return_phase = self._warning_return_phase
        return_time = self._warning_return_time
        self.dismiss_button.hide()
        self._clear_warning_context()

        if return_mode == "running":
            self._mode = "running"
            self._apply_color(COLOR_RUNNING)
            self.phase_label.setText(return_phase or "TREATMENT RUNNING")
            self.time_label.setText(return_time)
            self.stop_button.setEnabled(True)
            self.show()
        elif return_mode == "stopping":
            self.set_stopping()
        else:
            self.set_idle()

    def set_idle(self) -> None:
        self._mode = "idle"
        self.dismiss_button.hide()
        self._clear_warning_context()
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
        remaining = f"{minutes}:{seconds:02d} left"
        self.time_label.setText(remaining)
        if self._mode == "warning" and self._warning_return_mode == "running":
            self._warning_return_time = remaining

    def _clear_warning_context(self) -> None:
        self._warning_return_mode = "idle"
        self._warning_return_phase = ""
        self._warning_return_time = ""

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
