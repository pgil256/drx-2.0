"""Manual positioning with independent targets, commands, and sensor readouts."""

import math
from typing import Dict, List, Optional

from PyQt5.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from config.constants import (
    ACTUATORS, DEFAULT_HORIZONTAL_POSITION, HORIZONTAL_COMMAND_LIMITS, PRESSURE_MAX,
)
from ui.measurements import signed_text
from ui.theme import chevron_icon, rotate_icon
from ui.widgets.common import hline
from ui.widgets.ds import DSButton, DSCard, DSSlider
from ui.widgets.ds._common import mono_font, resolve, sans_font

from .content import rehome_notice


ROWS = [
    {"key": "axial", "name": "Axial", "unit": " in", "step": 0.5, "value": 2,
     "min": ACTUATORS["AXIAL"]["LIMITS"][0], "max": ACTUATORS["AXIAL"]["LIMITS"][1]},
    {"key": "lateral", "name": "Lateral", "unit": "°", "step": 2.5, "value": 0,
     "min": ACTUATORS["LATERAL"]["LIMITS"][0], "max": ACTUATORS["LATERAL"]["LIMITS"][1]},
    {"key": "horizontal", "name": "Horizontal", "unit": "°", "step": 2.5,
     "value": DEFAULT_HORIZONTAL_POSITION, "min": HORIZONTAL_COMMAND_LIMITS[0],
     "max": HORIZONTAL_COMMAND_LIMITS[1]},
    # Nothing measures the leg-length actuator, so its row has no range,
    # target, Go or reading: only the jogs, Return and Stop.
    {"key": "leg_length", "name": "Leg length"},
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

    def __init__(self, unit: str, parent=None, true_minus: bool = False) -> None:
        super().__init__(parent)
        self.unit = unit
        # Pressure shows a push on the footplate with the same minus sign as
        # the Protocols page. The angle rows keep their existing format.
        self.true_minus = true_minus
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)
        self._caption = _label("Measured", 16)
        self._value = _label("—", 22, True)
        self._value.setFont(mono_font(size=22, weight=600))
        for label in (self._caption, self._value):
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumHeight(label.minimumSizeHint().height())
            layout.addWidget(label)
        self.setFixedWidth(108)
        self.set_value(None, "Waiting")

    def set_value(self, value: Optional[float], reason: str = "") -> None:
        """Show a finite sensor value, or an explicit unavailable state."""
        valid = isinstance(value, (int, float)) and math.isfinite(value)
        if not valid:
            text = "—"
        elif self.true_minus:
            text = signed_text(value, "g") + self.unit
        else:
            text = f"{value:g}{self.unit}"
        self._value.setText(text)
        reason = _READING_REASONS.get(reason, reason)
        detail = reason or "From sensor"
        self.setToolTip(detail)
        self._value.setAccessibleDescription(detail)


class _ActuatorRow(QWidget):
    jog = pyqtSignal(str, str)
    go = pyqtSignal(str)
    stop = pyqtSignal(str)

    def __init__(self, cfg: Dict, parent=None) -> None:
        super().__init__(parent)
        self._key = cfg["key"]
        self._step = cfg.get("step", 0.0)
        measured = "min" in cfg
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
        if measured:
            labels.addWidget(_label(f"{cfg['min']:g} to {cfg['max']:g}{cfg['unit']}", 16))
        layout.addWidget(names)

        self.motion_buttons: List[QWidget] = []
        self.safety_buttons: List[QWidget] = []
        jogs = QHBoxLayout()
        jogs.setSpacing(8)
        ink = resolve("--ink-800")
        specs = [
            (chevron_icon("left", ink, 22, double=True), "rev_fast", -self._step * 4,
             "Fast reverse"),
            (chevron_icon("left", ink, 22), "rev", -self._step, "Reverse"),
            (chevron_icon("right", ink, 22), "fwd", self._step, "Forward"),
            (chevron_icon("right", ink, 22, double=True), "fwd_fast", self._step * 4,
             "Fast forward"),
            (rotate_icon(ink, 22), "reset", None, "Return / release"),
        ]
        for icon, action, delta, name in specs:
            # Drawn icons: the Plex guillemet substitutes read as punctuation.
            button = QPushButton()
            button.setIcon(icon)
            button.setIconSize(QSize(22, 22))
            button.setFixedSize(56, 56)
            button.setAccessibleName(f"{cfg['name']}: {name}")
            button.setToolTip(name)
            button.setStyleSheet("QPushButton { padding: 0; }")
            button.clicked.connect(lambda _c, a=action, d=delta: self._on_jog(a, d))
            jogs.addWidget(button)
            self.motion_buttons.append(button)
        layout.addLayout(jogs)

        self.slider: Optional[DSSlider] = None
        self.readout: Optional[_PosRow] = None
        if measured:
            self._add_target_and_reading(cfg, layout)
        else:
            # The firmware runs the leg-length actuator for a fixed time per
            # press and nothing measures it. A target, Go or reading would be
            # a made-up number (staff read the old "Estimated" column as a
            # measurement), so staff set leg length by watching the leg.
            layout.addStretch(1)
        stop = DSButton("STOP", variant="secondary", size="sm")
        stop.setAccessibleName("Stop leg" if self._key == "leg_length" else "Stop axes")
        # 56px like Go and the jogs, as a content-box minimum in the button's
        # own rule (38 + 8px padding and 1px border each side): the theme's
        # min-height is re-applied on polish and undoes setMinimumHeight().
        stop.setStyleSheet("QPushButton { min-height: 38px; }")
        stop.clicked.connect(lambda: self.stop.emit(self._key))
        layout.addWidget(stop)
        self.safety_buttons.append(stop)

    def _add_target_and_reading(self, cfg: Dict, layout: QHBoxLayout) -> None:
        self.slider = DSSlider(
            value=cfg["value"], minimum=cfg["min"], maximum=cfg["max"], step=cfg["step"],
            unit=cfg["unit"], with_steps=True,
        )
        self.slider.set_accessible_label(cfg["name"] + " target")
        layout.addWidget(self.slider, 1)

        # The selected target gets the same captioned column as the sensor
        # reading beside it, so "2 in" next to "Measured 1.2 in" cannot be
        # mistaken for a typo. The slider keeps updating the value label.
        target = QWidget()
        target_layout = QVBoxLayout(target)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(0)
        target_layout.setAlignment(Qt.AlignVCenter)
        self._target_caption = _label("Target", 16)
        value_label = self.slider._value_label
        self.slider.layout().removeWidget(value_label)
        value_label.setParent(target)
        value_label.setFont(mono_font(size=22, weight=600))
        value_label.setMinimumWidth(0)
        for label in (self._target_caption, value_label):
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumHeight(label.minimumSizeHint().height())
            target_layout.addWidget(label)
        target.setFixedWidth(96)
        layout.addWidget(target)

        self.readout = _PosRow(cfg["unit"], true_minus=self._key == "pressure")
        layout.addWidget(self.readout)
        go = DSButton("Go", size="sm")
        go.setFixedSize(56, 56)
        go.setStyleSheet("QPushButton { padding: 0; }")
        go.setAccessibleName("Move " + cfg["name"] + " to target")
        go.clicked.connect(lambda: self.go.emit(self._key))
        layout.addWidget(go)
        self.motion_buttons.append(go)

    def set_value(self, value: float) -> None:
        """Reflect a commanded target without changing any sensor reading."""
        if self.slider is not None:
            self.slider.set_value(value)

    def _on_jog(self, action: str, delta: Optional[float]) -> None:
        # Controller feedback owns commanded positions. Pressure arrows edit
        # a target only; its return button is the existing P0 release action.
        if self._key == "pressure" and delta is not None:
            self.slider.set_value(self.slider.value() + delta)
        self.jog.emit(self._key, action)

    def value(self) -> float:
        return self.slider.value() if self.slider is not None else 0.0


class SetupScreen(QWidget):
    jog_requested = pyqtSignal(str, str)
    go_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    mark_default_requested = pyqtSignal()
    reset_arduino_requested = pyqtSignal()
    reset_enabled_changed = pyqtSignal(bool)
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
            if row.readout is not None:
                self._pos[cfg["key"]] = row.readout
            row.jog.connect(self.jog_requested)
            row.go.connect(self.go_requested)
            row.stop.connect(self.stop_requested)
            body.addWidget(row, 1)
            if index < len(ROWS) - 1:
                body.addWidget(hline())
        layout.addWidget(card, 1)

        # Shown while a stopped device waits for its re-home; the Reset
        # button below is what answers it.
        self._rehome_notice = QLabel()
        self._rehome_notice.setWordWrap(True)
        self._rehome_notice.setFont(sans_font(size=16, weight=600))
        self._rehome_notice.hide()
        layout.addWidget(self._rehome_notice)

        actions = QHBoxLayout()
        actions.setSpacing(16)
        self._mark_btn = DSButton(
            "Save treatment defaults", variant="primary", size="lg", full_width=True,
        )
        self._reset_btn = DSButton(
            "RESET", variant="secondary", size="lg", full_width=True,
        )
        self._reset_btn.setAccessibleName("Reset and home device")
        self._reset_btn.setStyleSheet(
            "QPushButton:disabled {"
            f" background-color: {resolve('--gray-100')};"
            f" color: {resolve('--gray-600')};"
            f" border: 2px solid {resolve('--gray-400')}; }}"
        )
        # The motion lock and set_reset_enabled both enable and disable this
        # button, so its own state change is what the Treatment RESET follows.
        self._reset_btn.installEventFilter(self)
        self._estop_btn = DSButton("STOP", variant="danger", size="lg", full_width=True)
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
        if key in self._pos:
            self._pos[key].set_value(value, reason)

    def invalidate_measurements(self, reason: str) -> None:
        for key in self._pos:
            self.set_measured_position(key, None, reason)

    def set_reset_enabled(self, enabled: bool) -> None:
        self._reset_btn.setEnabled(enabled)

    def reset_enabled(self) -> bool:
        """Whether a reset may be requested, whatever this screen's own state."""
        return self._reset_btn.isEnabledTo(self)

    def eventFilter(self, obj, event):
        if obj is self._reset_btn and event.type() == QEvent.EnabledChange:
            self.reset_enabled_changed.emit(self.reset_enabled())
        return super().eventFilter(obj, event)

    def set_rehome_notice(self, visible: bool, load_cleared: bool = True) -> None:
        """Say that a stopped device waits for Reset. Nothing moves until the tap."""
        text = rehome_notice(load_cleared, self._reset_btn.text()) if visible else ""
        if text == self._rehome_notice.text():
            return
        tone = "--ink-900" if load_cleared else "--red-500"
        self._rehome_notice.setStyleSheet(f"color: {resolve(tone)}; background: transparent;")
        self._rehome_notice.setText(text)
        self._rehome_notice.setVisible(visible)

    def control_buttons(self) -> List[QWidget]:
        """Motion locks exclude Stop; target editing does not send movement."""
        buttons = [button for row in self._rows.values() for button in row.motion_buttons]
        return buttons + [self._reset_btn]
