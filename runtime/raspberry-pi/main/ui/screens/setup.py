"""Manual positioning with independent targets, commands, and sensor readouts."""

import math
from typing import Dict, List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from main.config.constants import (
    ACTUATORS, DEFAULT_HORIZONTAL_POSITION, LEG_LENGTH_MAX, LEG_LENGTH_MIN, PRESSURE_MAX,
)
from ui.theme import GLYPH
from ui.widgets.common import hline
from ui.widgets.ds import DSButton, DSCard, DSSlider
from ui.widgets.ds._common import mono_font, resolve, sans_font


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


def _label(text: str, size: int = 16, bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setFont(sans_font(size=size, weight=600 if bold else 400))
    return label


class _PosRow(QWidget):
    """A sensor reading that can never be populated by target changes."""

    def __init__(self, unit: str, estimated: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.unit = unit
        self.estimated = estimated
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)
        self._caption = _label("Estimated" if estimated else "Measured", 16)
        self._value = _label("—", 22, True)
        self._value.setFont(mono_font(size=22, weight=600))
        for label in (self._caption, self._value):
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumHeight(label.minimumSizeHint().height())
            layout.addWidget(label)
        self.setFixedWidth(108)
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


class _ActuatorRow(QWidget):
    jog = pyqtSignal(str, str)
    go = pyqtSignal(str)
    stop = pyqtSignal(str)
    valueChanged = pyqtSignal(str, float)

    def __init__(self, cfg: Dict, parent=None) -> None:
        super().__init__(parent)
        self._key = cfg["key"]
        self._step = cfg["step"]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)

        names = QWidget()
        names.setFixedWidth(120)
        labels = QVBoxLayout(names)
        labels.setContentsMargins(0, 0, 0, 0)
        labels.setSpacing(2)
        labels.setAlignment(Qt.AlignVCenter)
        labels.addWidget(_label(cfg["name"], 19, True))
        labels.addWidget(_label(f"{cfg['min']:g} to {cfg['max']:g}{cfg['unit']}", 16))
        layout.addWidget(names)

        self.motion_buttons: List[QWidget] = []
        self.safety_buttons: List[QWidget] = []
        jogs = QHBoxLayout()
        jogs.setSpacing(8)
        specs = [
            ("jog_rev_fast", "rev_fast", -self._step * 4, "Fast reverse"),
            ("jog_rev", "rev", -self._step, "Reverse"),
            ("jog_fwd", "fwd", self._step, "Forward"),
            ("jog_fwd_fast", "fwd_fast", self._step * 4, "Fast forward"),
            ("reset", "reset", None, "Return / release"),
        ]
        for glyph, action, delta, name in specs:
            button = QPushButton(GLYPH[glyph])
            button.setFixedSize(56, 56)
            button.setFont(sans_font(size=22, weight=600))
            button.setAccessibleName(f"{cfg['name']}: {name}")
            button.setToolTip(name)
            button.setStyleSheet("QPushButton { padding: 0; }")
            button.clicked.connect(lambda _c, a=action, d=delta: self._on_jog(a, d))
            jogs.addWidget(button)
            self.motion_buttons.append(button)
        layout.addLayout(jogs)

        self.slider = DSSlider(
            value=cfg["value"], minimum=cfg["min"], maximum=cfg["max"], step=cfg["step"],
            unit=cfg["unit"], with_steps=True,
        )
        self.slider.set_accessible_label(cfg["name"] + " target")
        self.slider.valueChanged.connect(self._on_target)
        self.slider._value_label.setFixedWidth(90)
        layout.addWidget(self.slider, 1)

        self.readout = _PosRow(cfg["unit"], self._key == "leg_length")
        layout.addWidget(self.readout)
        go = DSButton("Go", size="sm")
        go.setFixedSize(56, 56)
        go.setStyleSheet("QPushButton { padding: 0; }")
        go.setAccessibleName("Move " + cfg["name"] + " to target")
        go.clicked.connect(lambda: self.go.emit(self._key))
        stop = DSButton("Stop", variant="secondary", size="sm")
        stop.setAccessibleName("Stop leg" if self._key == "leg_length" else "Stop axes")
        stop.setMinimumHeight(56)
        stop.clicked.connect(lambda: self.stop.emit(self._key))
        layout.addWidget(go)
        layout.addWidget(stop)
        self.safety_buttons.append(stop)
        self.motion_buttons.append(go)

    def _on_target(self, value: float) -> None:
        self.valueChanged.emit(self._key, value)

    def set_value(self, value: float) -> None:
        """Reflect a commanded target without changing any sensor reading."""
        self.slider.set_value(value)

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
        body.setContentsMargins(16, 8, 16, 8)
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
        actions.setSpacing(16)
        self._mark_btn = DSButton(
            "Save treatment defaults", variant="dark", size="lg", full_width=True,
        )
        self._reset_btn = DSButton(
            "Reset and home device", variant="secondary", size="lg", full_width=True,
        )
        self._reset_btn.setStyleSheet(
            "QPushButton:disabled {"
            f" background-color: {resolve('--gray-100')};"
            f" color: {resolve('--gray-600')};"
            f" border: 2px solid {resolve('--gray-400')}; }}"
        )
        self._estop_btn = DSButton("Stop", variant="danger", size="lg", full_width=True)
        self._mark_btn.clicked.connect(self.mark_default_requested)
        self._reset_btn.clicked.connect(self.reset_arduino_requested)
        self._estop_btn.clicked.connect(self.emergency_stop_requested)
        for button in (self._mark_btn, self._reset_btn, self._estop_btn):
            actions.addWidget(button, 1)
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
