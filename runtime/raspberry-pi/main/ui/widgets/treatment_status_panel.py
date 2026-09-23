# ui/widgets/treatment_status_panel.py
"""Device warning / fault banner with a permanent emergency-stop control.

Live measured pressure, target, phase, and time remaining used to be
opt-in floating dialogs (off by default), so an operator could run a
traction protocol completely blind; the on-screen emergency stop only
existed on the Setup page. This banner docks under the top bar (so the
brand and device status stay visible) for device warnings and faults
raised while no protocol is active (e.g. a jog on the Setup page tripping
a limit).

While a protocol is active the banner stays hidden: navigation is locked
to the Protocols page, which already shows phase, pressure and time
remaining inline with its own STOP control, and safety events are raised
through the acknowledged safety alert. ``suppress_when`` (a callable)
gates every ``show()``.

Tones come from the design tokens (``--banner-warning`` / ``--banner-fault``);
the pressure readout only shows when the banner carries a live reading, and
the advisory dismiss control is a drawn close icon. ``DSBanner`` is the
design-system name for this widget.
"""
from typing import Callable, Optional

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from ui.theme import control_icon, resolve
from ui.widgets.ds._common import mono_font, pinned_height, px, sans_font

PANEL_HEIGHT = 72
TOP_OFFSET = 84  # docks under the top bar (ui.chrome.top_bar.BAR_HEIGHT)
NO_READING = "-- lbs"

COLOR_RUNNING = resolve("--blue-600")
COLOR_STOPPING = resolve("--banner-warning")
COLOR_WARNING = resolve("--banner-warning")
COLOR_FAULT = resolve("--banner-fault")

_BASE_STYLE = """
QFrame#treatmentPanel {{
    background-color: {bg};
    border: none;
    border-bottom: 1px solid rgba(0, 0, 0, 0.18);
}}
QLabel {{
    color: {fg};
    background: transparent;
}}
"""


def _stop_style(inverse: bool) -> str:
    """Red on light banners; a white face on the red fault banner so it still reads."""
    bg, fg, border = ((resolve("--white"), resolve("--red-600"), resolve("--white")) if inverse
                      else (resolve("--red-600"), resolve("--white"), resolve("--white")))
    return (
        f"QPushButton {{ background-color: {bg}; color: {fg}; border: 2px solid {border};"
        f" border-radius: {resolve('--radius-md')}; padding: 0 20px; min-height: 44px;"
        f" font-size: {resolve('--text-base')}; font-weight: 700; }}"
        f"QPushButton:pressed {{ background-color: {resolve('--red-800')};"
        f" color: {resolve('--white')}; }}"
    )


_DISMISS_STYLE = (
    "QPushButton { border: none; border-radius: 12px; padding: 0;"
    f" {pinned_height(48)}"
    f" background: {resolve('--on-dark-subtle')}; }}"
    f"QPushButton:pressed {{ background: {resolve('--on-dark-subtle-hover')}; }}"
)


class TreatmentStatusPanel(QFrame):
    """Docked banner: message, optional pressure/target/time, and emergency stop."""

    stop_requested = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        suppress_when: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("treatmentPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Callable returning True while the banner must stay off-screen.
        # State (mode, labels, colours) keeps tracking normally so nothing
        # is lost; only the overlay is withheld.
        self._suppress_when = suppress_when

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 8, 12, 8)
        layout.setSpacing(16)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(28, 28)

        self.phase_label = QLabel("")
        self.phase_label.setFont(sans_font(size="--text-base", weight=600))
        self.phase_label.setWordWrap(True)

        self.pressure_label = QLabel(NO_READING)
        self.pressure_label.setFont(mono_font(size="--text-lg", weight=600))

        self.target_label = QLabel("")
        self.target_label.setFont(sans_font(size="--text-sm"))

        self.time_label = QLabel("")
        self.time_label.setFont(mono_font(size="--text-md", weight=600))

        self.stop_button = QPushButton("EMERGENCY STOP")
        self.stop_button.setMinimumSize(220, 52)
        self.stop_button.setIcon(control_icon("stop", resolve("--white"), 20))
        self.stop_button.setIconSize(QSize(20, 20))
        self.stop_button.clicked.connect(self.stop_requested.emit)

        self.dismiss_button = QPushButton()
        self.dismiss_button.setObjectName("dismissWarningButton")
        self.dismiss_button.setFixedSize(48, 48)
        self.dismiss_button.setCursor(Qt.PointingHandCursor)
        self.dismiss_button.setIcon(control_icon("close", resolve("--white"), 22))
        self.dismiss_button.setIconSize(QSize(22, 22))
        self.dismiss_button.setToolTip("Dismiss this advisory warning")
        self.dismiss_button.setAccessibleName("Dismiss safety warning")
        self.dismiss_button.setStyleSheet(_DISMISS_STYLE)
        self.dismiss_button.clicked.connect(self.dismiss_warning)
        self.dismiss_button.hide()

        layout.addWidget(self.icon_label)
        layout.addWidget(self.phase_label, 1)
        layout.addWidget(self.pressure_label)
        layout.addWidget(self.target_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.dismiss_button)

        self._mode = "idle"
        self._warning_return_mode = "idle"
        self._warning_return_phase = ""
        self._warning_return_time = ""
        self._apply_color(COLOR_RUNNING)

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
        self.pressure_label.setText(NO_READING)
        self.target_label.setText("")
        self.time_label.setText("")
        self.stop_button.setEnabled(True)
        self._refresh_readouts()

    # ------------------------------------------------------------------
    # Live values
    # ------------------------------------------------------------------

    def update_pressure(self, pressure: float) -> None:
        """Measured pressure from device status, not the commanded value."""
        try:
            self.pressure_label.setText(f"{float(pressure):.1f} lbs")
        except (TypeError, ValueError):
            pass
        self._refresh_readouts()

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
        self._refresh_readouts()

    def _clear_warning_context(self) -> None:
        self._warning_return_mode = "idle"
        self._warning_return_phase = ""
        self._warning_return_time = ""

    def _refresh_readouts(self) -> None:
        """Show pressure, target and time only while they describe a treatment."""
        treatment = self._mode in ("running", "stopping")
        has_reading = self.pressure_label.text() != NO_READING
        self.pressure_label.setVisible(treatment and has_reading)
        self.target_label.setVisible(treatment and bool(self.target_label.text()))
        self.time_label.setVisible(bool(self.time_label.text()))

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def _apply_color(self, bg: str) -> None:
        fault = bg == COLOR_FAULT
        self.setStyleSheet(_BASE_STYLE.format(bg=bg, fg=resolve("--white")))
        self.stop_button.setStyleSheet(_stop_style(inverse=fault))
        self.stop_button.setIcon(control_icon(
            "stop", resolve("--red-600") if fault else resolve("--white"), 20))
        icon = "info" if bg == COLOR_RUNNING else "alert"
        self.icon_label.setPixmap(control_icon(icon, resolve("--white"), 28).pixmap(28, 28))
        self._refresh_readouts()

    def _fit_to_parent(self, parent: QWidget) -> None:
        # Dock under the top bar and beside the rail, so the brand, device
        # status and navigation all stay visible while the banner is up.
        left = px("--rail-width") if parent.width() > 4 * px("--rail-width") else 0
        self.setGeometry(left, TOP_OFFSET, max(0, parent.width() - left), PANEL_HEIGHT)

    def set_suppressed_when(self, predicate: Optional[Callable[[], bool]]) -> None:
        """Install (or clear) the predicate that keeps the banner hidden."""
        self._suppress_when = predicate

    def is_suppressed(self) -> bool:
        if self._suppress_when is None:
            return False
        try:
            return bool(self._suppress_when())
        except Exception:
            return False

    def show(self) -> None:  # noqa: A003 - QWidget API
        if self.is_suppressed():
            # A banner left over from an idle-time warning must not linger
            # into a run either.
            super().hide()
            return
        self._refresh_readouts()
        super().show()
        self.raise_()

    def eventFilter(self, watched, event):
        if watched is self.parent() and event.type() == QEvent.Resize:
            self._fit_to_parent(watched)
        return super().eventFilter(watched, event)


#: Design-system name for the docked warning / fault banner.
DSBanner = TreatmentStatusPanel
