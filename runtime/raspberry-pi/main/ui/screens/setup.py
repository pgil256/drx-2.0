"""Manual positioning with independent targets, commands, and sensor readouts.

Each actuator row reads left to right: name and range │ one segmented jog
group (drawn « ‹ › » chevrons) │ return/release │ a captioned target stepper │
the measured (or estimated) reading │ Go │ a quiet per-row stop. A thin,
non-interactive track under the controls shows the range with a ring at the
target and a fill to the measured position; targets change only through the
stepper. The action row keeps the rare "Save defaults" quiet and gives STOP
the red, widest slot.
"""

import math
from typing import Dict, List, Optional

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from main.config.constants import (
    ACTUATORS, DEFAULT_HORIZONTAL_POSITION, LEG_LENGTH_MAX, LEG_LENGTH_MIN, PRESSURE_MAX,
)
from ui.theme import control_icon
from ui.widgets.common import hline
from ui.widgets.ds import DSButton, DSCard, DSSlider
from ui.widgets.ds._common import mark_caption, mono_font, pinned_height, resolve, sans_font


ROWS = [
    {"key": "axial", "name": "Axial", "unit": " in", "step": 0.5, "value": 2,
     "min": ACTUATORS["AXIAL"]["LIMITS"][0], "max": ACTUATORS["AXIAL"]["LIMITS"][1]},
    {"key": "lateral", "name": "Lateral", "unit": "°", "step": 2.5, "value": 0,
     "min": ACTUATORS["LATERAL"]["LIMITS"][0], "max": ACTUATORS["LATERAL"]["LIMITS"][1]},
    {"key": "horizontal", "name": "Horizontal", "unit": "°", "step": 2.5,
     "value": DEFAULT_HORIZONTAL_POSITION, "min": ACTUATORS["HORIZONTAL"]["LIMITS"][0],
     "max": ACTUATORS["HORIZONTAL"]["LIMITS"][1]},
    {"key": "leg_length", "name": "Leg length", "unit": " in", "step": 0.25,
     "value": 0, "min": LEG_LENGTH_MIN, "max": LEG_LENGTH_MAX},
    {"key": "pressure", "name": "Pressure", "unit": " lbs", "step": 5, "value": 0,
     "min": 0, "max": PRESSURE_MAX},
]

_READING_REASONS = {
    "Pressure live": "From sensor",
    "Pressure stale": "Stale",
    "Pressure unavailable": "Unavailable",
    "Pressure zero required": "Zero required",
    "Waiting for pressure": "Waiting",
    "Waiting for controller": "Offline",
    "Controller fault — last reading stale": "Fault / stale",
}

_CONTROL_PX = 52
_NAME_WIDTH = 132


def _label(text: str, size: str = "--text-sm", bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setFont(sans_font(size=size, weight=600 if bold else 400))
    return label


class _PositionTrack(QWidget):
    """A thin, read-only range track: target ring and a fill to the measurement."""

    def __init__(self, minimum: float, maximum: float, parent=None) -> None:
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._target: Optional[float] = None
        self._measured: Optional[float] = None
        self.setFixedHeight(16)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)

    def set_target(self, value: Optional[float]) -> None:
        self._target = value
        self.update()

    def set_measured(self, value: Optional[float]) -> None:
        self._measured = value
        self.update()

    def _x(self, value: float, left: float, width: float) -> float:
        span = self._max - self._min or 1.0
        fraction = max(0.0, min(1.0, (value - self._min) / span))
        return left + fraction * width

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ring = 12.0
        left, width = ring / 2 + 1, self.width() - ring - 2
        mid = self.height() / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(resolve("--gray-300")))
        painter.drawRoundedRect(QRectF(left, mid - 2, width, 4), 2, 2)
        if self._measured is not None:
            # Bidirectional ranges fill from zero; one-sided ranges from the minimum.
            origin = 0.0 if self._min < 0 < self._max else self._min
            a, b = sorted((self._x(origin, left, width), self._x(self._measured, left, width)))
            painter.setBrush(QColor(resolve("--color-primary")))
            painter.drawRoundedRect(QRectF(a, mid - 2, max(4.0, b - a), 4), 2, 2)
        if self._target is not None:
            x = self._x(self._target, left, width)
            painter.setBrush(QColor(resolve("--white")))
            pen = QPen(QColor(resolve("--ink-900")))
            pen.setWidthF(2.0)
            painter.setPen(pen)
            painter.drawEllipse(QRectF(x - ring / 2, mid - ring / 2, ring, ring))
        painter.end()


class _PosRow(QWidget):
    """A sensor reading that can never be populated by target changes."""

    def __init__(self, unit: str, estimated: bool = False, parent=None, on_value=None) -> None:
        super().__init__(parent)
        self.unit = unit
        self.estimated = estimated
        self._on_value = on_value
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)
        self._caption = _label("Estimated" if estimated else "Measured", "--text-xs", True)
        self._caption.setStyleSheet(f"color: {resolve('--text-muted')};")
        mark_caption(self._caption)
        self._value = _label("—", "--text-md", True)
        self._value.setFont(mono_font(size="--text-md", weight=600))
        self._value.setStyleSheet(f"color: {resolve('--text-strong')};")
        for label in (self._caption, self._value):
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumHeight(label.minimumSizeHint().height())
            layout.addWidget(label)
        self.setFixedWidth(112)
        self.set_value(None, "Zero required" if estimated else "Waiting")

    def set_value(self, value: Optional[float], reason: str = "") -> None:
        """Show a finite sensor/estimate value, or an explicit unavailable state."""
        valid = isinstance(value, (int, float)) and math.isfinite(value)
        text = f"{value:g}{self.unit}" if valid else "—"
        self._value.setText(text)
        reason = _READING_REASONS.get(reason, reason)
        detail = reason or ("Open loop" if self.estimated else "From sensor")
        self.setToolTip(detail)
        self._value.setAccessibleDescription(detail)
        if self._on_value is not None:
            self._on_value(value if valid else None)


class _JogGroup(QFrame):
    """Four jog segments in one rounded container, separated by hairlines."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("JogGroup")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(1, 1, 1, 1)
        self._layout.setSpacing(0)
        self.setFixedHeight(_CONTROL_PX + 2)
        radius = resolve("--radius-md")
        self.setStyleSheet(
            f"#JogGroup {{ background: {resolve('--white')};"
            f" border: 1px solid {resolve('--border-control')}; border-radius: {radius}; }}"
            "#JogSegment { border: none; border-radius: 0; padding: 0;"
            f" {pinned_height(_CONTROL_PX)}"
            " background: transparent; }"
            f"#JogSegment:hover {{ background: {resolve('--gray-050')}; }}"
            f"#JogSegment:pressed {{ background: {resolve('--blue-100')}; }}"
            f"#JogSegment:disabled {{ background: {resolve('--gray-100')}; }}"
            f"#JogSegment[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--ink-900')}; }}"
            f"#JogRule {{ background: {resolve('--border-divider')}; border: none; }}"
        )

    def add_segment(self, button: QPushButton) -> None:
        if self._layout.count():
            rule = QFrame(self)
            rule.setObjectName("JogRule")
            rule.setFixedWidth(1)
            self._layout.addWidget(rule)
        button.setObjectName("JogSegment")
        button.setParent(self)
        self._layout.addWidget(button)


class _ActuatorRow(QWidget):
    jog = pyqtSignal(str, str)
    go = pyqtSignal(str)
    stop = pyqtSignal(str)
    valueChanged = pyqtSignal(str, float)

    def __init__(self, cfg: Dict, parent=None) -> None:
        super().__init__(parent)
        self._key = cfg["key"]
        self._step = cfg["step"]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 6)
        outer.setSpacing(4)
        layout = QHBoxLayout()
        layout.setSpacing(12)
        outer.addLayout(layout)

        names = QWidget()
        names.setFixedWidth(_NAME_WIDTH)
        labels = QVBoxLayout(names)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(0)
        labels.setAlignment(Qt.AlignVCenter)
        title = _label(cfg["name"], "--text-md", True)
        title.setStyleSheet(f"color: {resolve('--text-strong')};")
        labels.addWidget(title)
        span = _label(f"{cfg['min']:g} to {cfg['max']:g}{cfg['unit']}")
        span.setStyleSheet(f"color: {resolve('--text-muted')};")
        labels.addWidget(span)
        layout.addWidget(names)

        self.motion_buttons: List[QWidget] = []
        self.safety_buttons: List[QWidget] = []
        ink = resolve("--ink-800")
        muted = resolve("--gray-400")
        jogs = _JogGroup()
        specs = [
            ("chevrons-left", "rev_fast", -self._step * 4, "Fast reverse"),
            ("chevron-left", "rev", -self._step, "Reverse"),
            ("chevron-right", "fwd", self._step, "Forward"),
            ("chevrons-right", "fwd_fast", self._step * 4, "Fast forward"),
        ]
        for icon, action, delta, name in specs:
            button = self._icon_button(icon, ink, muted, f"{cfg['name']}: {name}", name)
            button.clicked.connect(lambda _c, a=action, d=delta: self._on_jog(a, d))
            jogs.add_segment(button)
            self.motion_buttons.append(button)
        layout.addWidget(jogs)

        reset = self._icon_button("rotate-ccw", ink, muted,
                                  f"{cfg['name']}: Return / release", "Return / release")
        reset.setObjectName("ResetButton")
        reset.setStyleSheet(f"#ResetButton {{ padding: 0; {pinned_height(_CONTROL_PX, 1)} }}")
        reset.clicked.connect(lambda: self._on_jog("reset", None))
        self.motion_buttons.append(reset)
        layout.addWidget(reset)
        layout.addSpacing(8)

        self.slider = DSSlider(
            value=cfg["value"], minimum=cfg["min"], maximum=cfg["max"], step=cfg["step"],
            unit=cfg["unit"], mode="stepper", caption="Target",
        )
        self.slider.set_accessible_label(cfg["name"] + " target")
        self.slider.set_step_size(_CONTROL_PX)
        self.slider._value_label.setFixedWidth(104)
        self.slider.layout().setSpacing(6)
        self.slider.valueChanged.connect(self._on_target)
        layout.addWidget(self.slider)
        layout.addStretch(1)

        self.track = _PositionTrack(cfg["min"], cfg["max"])
        self.readout = _PosRow(cfg["unit"], self._key == "leg_length",
                               on_value=self.track.set_measured)
        layout.addWidget(self.readout)
        layout.addSpacing(8)
        go = DSButton("Go", size="sm")
        go.setFixedSize(76, _CONTROL_PX)
        go.setAccessibleName("Move " + cfg["name"] + " to target")
        go.clicked.connect(lambda: self.go.emit(self._key))
        stop = self._icon_button(
            "stop", resolve("--color-danger"), muted,
            "Stop leg" if self._key == "leg_length" else "Stop axes", "Stop this movement")
        stop.setObjectName("RowStop")
        stop.setStyleSheet(f"#RowStop {{ padding: 0; {pinned_height(_CONTROL_PX, 1)} }}")
        stop.clicked.connect(lambda: self.stop.emit(self._key))
        layout.addWidget(go)
        layout.addWidget(stop)
        self.safety_buttons.append(stop)
        self.motion_buttons.append(go)

        track_row = QHBoxLayout()
        track_row.setContentsMargins(_NAME_WIDTH + 12, 0, 0, 0)
        track_row.addWidget(self.track)
        outer.addLayout(track_row)
        self.track.set_target(self.slider.value())

    @staticmethod
    def _icon_button(icon: str, color: str, disabled: str, name: str, tip: str) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(_CONTROL_PX, _CONTROL_PX)
        button.setIcon(control_icon(icon, color, 24, disabled_color=disabled))
        button.setIconSize(QSize(24, 24))
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.TabFocus)
        button.setAccessibleName(name)
        button.setToolTip(tip)
        return button

    def _on_target(self, value: float) -> None:
        self.track.set_target(value)
        self.valueChanged.emit(self._key, value)

    def set_value(self, value: float) -> None:
        """Reflect a commanded target without changing any sensor reading."""
        self.slider.set_value(value)
        self.track.set_target(self.slider.value())

    def _on_jog(self, action: str, delta: Optional[float]) -> None:
        # Controller feedback owns commanded positions. Pressure arrows edit
        # a target only; its return button is the existing P0 release action.
        if self._key == "pressure" and delta is not None:
            self.slider.set_value(self.slider.value() + delta)
            self._on_target(self.slider.value())
        self.jog.emit(self._key, action)

    def value(self) -> float:
        return self.slider.value()


class SetupScreen(QWidget):
    jog_requested = pyqtSignal(str, str)
    go_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    value_changed = pyqtSignal(str, float)
    mark_default_requested = pyqtSignal()
    reset_arduino_requested = pyqtSignal()
    emergency_stop_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SetupScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#SetupScreen {{ background: {resolve('--surface-page')}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        card = DSCard(padded=False)
        body = card.body_layout
        body.setContentsMargins(20, 6, 20, 6)
        body.setSpacing(0)
        self._rows = {}
        self._pos = {}
        for index, cfg in enumerate(ROWS):
            row = _ActuatorRow(cfg)
            self._rows[cfg["key"]] = row
            self._pos[cfg["key"]] = row.readout
            row.jog.connect(self.jog_requested)
            row.go.connect(self.go_requested)
            row.stop.connect(self.stop_requested)
            row.valueChanged.connect(self.value_changed)
            body.addWidget(row, 1)
            if index < len(ROWS) - 1:
                body.addWidget(hline())
        layout.addWidget(card, 1)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self._reset_btn = DSButton(
            "Reset and home", variant="secondary", size="lg",
            icon=control_icon("rotate-ccw", resolve("--ink-800"), 22,
                              disabled_color=resolve("--gray-600")),
        )
        self._reset_btn.setMinimumWidth(260)
        self._mark_btn = DSButton("Save defaults", variant="secondary", size="lg")
        self._mark_btn.setMinimumWidth(220)
        self._estop_btn = DSButton("STOP", variant="danger", size="lg",
                                   icon=control_icon("stop", resolve("--white"), 22))
        self._estop_btn.setMinimumWidth(420)
        self._mark_btn.clicked.connect(self.mark_default_requested)
        self._reset_btn.clicked.connect(self.reset_arduino_requested)
        self._estop_btn.clicked.connect(self.emergency_stop_requested)
        actions.addWidget(self._reset_btn)
        actions.addWidget(self._mark_btn)
        actions.addStretch(1)
        actions.addWidget(self._estop_btn)
        layout.addLayout(actions)

    def set_arduino_connected(self, connected: bool) -> None:
        if not connected:
            self.invalidate_measurements("Controller offline")

    def row_value(self, key: str) -> float:
        row = self._rows.get(key)
        return row.value() if row else 0.0

    def set_position(self, key: str, value: float) -> None:
        """Reflect a command (legacy controller seam); never a measurement."""
        if key in self._rows:
            self._rows[key].set_value(value)

    def set_measured_position(self, key: str, value: Optional[float], reason: str = "") -> None:
        """Telemetry cannot overwrite a selected target or fabricate leg feedback."""
        if key in self._pos and key != "leg_length":
            self._pos[key].set_value(value, reason)

    def set_leg_length_estimate(self, value: Optional[float], reason: str = "") -> None:
        """Show command-derived travel from retracted zero, including quarter inches."""
        self._pos["leg_length"].set_value(value, reason)

    def invalidate_measurements(self, reason: str) -> None:
        for key in self._pos:
            if key != "leg_length":
                self.set_measured_position(key, None, reason)

    def set_reset_enabled(self, enabled: bool) -> None:
        self._reset_btn.setEnabled(enabled)

    def control_buttons(self) -> List[QWidget]:
        """Motion locks exclude Stop; target editing does not send movement."""
        buttons = [button for row in self._rows.values() for button in row.motion_buttons]
        return buttons + [self._reset_btn]
