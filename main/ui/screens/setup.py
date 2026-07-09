"""SetupScreen — manual actuator control.

Mirrors `SetupScreen` in `bundle.jsx`: a "Manual Actuator Control" card with one
row per actuator (jog cluster + slider + Go/Stop) and an action row
(Mark As Default · Reset Arduino · Emergency Stop), beside "Live Position" and
"Safety Limits" cards. The live-position values track the sliders locally so the
screen demos standalone; Phase 3 repoints them at real encoder telemetry.

Signals:
    jog_requested(str, str)        — (actuator key, action: rev_fast|rev|fwd|fwd_fast|reset)
    go_requested(str)              — per-row Go
    stop_requested(str)            — per-row Stop
    value_changed(str, float)      — a row's slider value changed
    mark_default_requested
    reset_arduino_requested
    emergency_stop_requested
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH
from ui.widgets.common import hline
from ui.widgets.ds import DSBadge, DSButton, DSCard, DSSlider
from ui.widgets.ds._common import mono_font, resolve, sans_font

from .content import SAFETY_LIMITS

_PAD = 20
_GAP = 16

# Per-actuator row config. Ranges follow the design; Phase 3 reconciles them
# with constants.py when wiring real actuator commands.
ROWS = [
    {"key": "axial", "name": "Axial", "sub": "0–4 in", "unit": " in",
     "min": 0, "max": 4, "step": 0.5, "value": 2, "pos_tone": "default"},
    {"key": "lateral", "name": "Lateral", "sub": "±20°", "unit": "°",
     "min": -20, "max": 20, "step": 2.5, "value": 0, "pos_tone": "cyan"},
    {"key": "horizontal", "name": "Horizontal", "sub": "−25° to +5°", "unit": "°",
     "min": -25, "max": 5, "step": 2.5, "value": -10, "pos_tone": "cyan"},
    {"key": "leg_length", "name": "Leg Length", "sub": "0–6 in", "unit": " in",
     "min": 0, "max": 6, "step": 0.5, "value": 0, "pos_tone": "default"},
    {"key": "pressure", "name": "Pressure", "sub": "0–80 lbs", "unit": " lbs",
     "min": 0, "max": 80, "step": 5, "value": 0, "pos_tone": "default"},
]

_POS_COLORS = {
    "cyan": "--brand-cyan",
    "danger": "--red-500",
    "default": "--ink-900",
}


def _jog_button(glyph, reset=False):
    btn = QPushButton(glyph)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(46, 46)
    btn.setFont(sans_font(size=16, weight=700))
    base = resolve("--gray-200") if reset else "#ffffff"
    btn.setStyleSheet(
        "QPushButton {"
        f" background: {base}; color: {resolve('--ink-800')}; padding: 0;"
        f" border: 2px solid {resolve('--gray-300')};"
        f" border-radius: {resolve('--radius-md')}; }}"
        f" QPushButton:hover {{ background: {resolve('--blue-050')};"
        f" border-color: {resolve('--color-primary')}; }}"
    )
    return btn


class _ActuatorRow(QWidget):
    jog = pyqtSignal(str, str)
    go = pyqtSignal(str)
    stop = pyqtSignal(str)
    valueChanged = pyqtSignal(str, float)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self._key = cfg["key"]
        self._step = cfg["step"]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 12, 0, 12)  # row breathing room (DS padding 20px 0)
        lay.setSpacing(14)

        # Name + sub block (132px).
        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        name = QLabel(cfg["name"])
        name.setFont(sans_font(size=19, weight=700))
        name.setStyleSheet(f"color: {resolve('--ink-800')}; background: transparent;")
        sub = QLabel(cfg["sub"])
        sub.setFont(mono_font(size="--text-xs"))
        sub.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        name_box.addWidget(name)
        name_box.addWidget(sub)
        name_host = QWidget()
        name_host.setLayout(name_box)
        name_host.setFixedWidth(132)
        lay.addWidget(name_host)

        # Jog cluster: «  ‹  ›  »  ↺
        self.buttons = []  # all enable/disable-able controls in this row
        jog_row = QHBoxLayout()
        jog_row.setSpacing(6)
        specs = [
            (GLYPH["jog_rev_fast"], "rev_fast", -self._step * 4, False),
            (GLYPH["jog_rev"], "rev", -self._step, False),
            (GLYPH["jog_fwd"], "fwd", self._step, False),
            (GLYPH["jog_fwd_fast"], "fwd_fast", self._step * 4, False),
            (GLYPH["reset"], "reset", None, True),
        ]
        for glyph, action, delta, is_reset in specs:
            b = _jog_button(glyph, reset=is_reset)
            b.setToolTip(action.replace("_", " ").title())
            b.clicked.connect(lambda _c, a=action, d=delta: self._on_jog(a, d))
            jog_row.addWidget(b)
            self.buttons.append(b)
        lay.addLayout(jog_row)

        # Slider (label-less; the name block is the label).
        self.slider = DSSlider(value=cfg["value"], minimum=cfg["min"], maximum=cfg["max"],
                               step=cfg["step"], unit=cfg["unit"])
        self.slider.valueChanged.connect(lambda v: self.valueChanged.emit(self._key, v))
        lay.addWidget(self.slider, 1)

        go = DSButton("Go", variant="primary", size="sm")
        go.clicked.connect(lambda: self.go.emit(self._key))
        stop = DSButton("Stop", variant="secondary", size="sm")
        stop.clicked.connect(lambda: self.stop.emit(self._key))
        lay.addWidget(go)
        lay.addWidget(stop)
        self.buttons.extend((go, stop))

    def set_value(self, value):
        """Set the slider without re-emitting (controller-driven reflect)."""
        self.slider.set_value(value)

    def _on_jog(self, action, delta):
        if action == "reset":
            self.slider.set_value(0)
        elif delta is not None:
            self.slider.set_value(self.slider.value() + delta)
        self.jog.emit(self._key, action)

    def value(self):
        return self.slider.value()


class _PosRow(QWidget):
    """A Live-Position line: caption left, big mono value right."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 5, 4, 5)
        lay.setSpacing(8)
        cap = QLabel(label.upper())
        cap.setFont(sans_font(size="--text-xs", weight=600, tracking=0.06))
        cap.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        self._value = QLabel()
        self._value.setTextFormat(Qt.RichText)
        self._value.setFont(mono_font(weight=600))
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(cap)
        lay.addStretch(1)
        lay.addWidget(self._value)

    def set_value(self, value_text, unit="", tone="default"):
        color = resolve(_POS_COLORS.get(tone, "--ink-900"))
        html = f"<span style='font-size:30px; color:{color};'>{value_text}</span>"
        if unit:
            html += (
                f"<span style='font-size:14px; color:{resolve('--gray-600')};'>"
                f"<span style='font-size:4px;'> </span>{unit}</span>"
            )
        self._value.setText(html)


class SetupScreen(QWidget):
    jog_requested = pyqtSignal(str, str)
    go_requested = pyqtSignal(str)
    stop_requested = pyqtSignal(str)
    value_changed = pyqtSignal(str, float)
    mark_default_requested = pyqtSignal()
    reset_arduino_requested = pyqtSignal()
    emergency_stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SetupScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#SetupScreen {{ background: {resolve('--surface-page')}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        outer.setSpacing(0)

        grid = QHBoxLayout()
        grid.setSpacing(_GAP)
        # Ratio follows the approved render (screenshots/06-setup-final.png ≈ 2.5:1),
        # which is wider on the left than bundle.jsx's 1.5fr/1fr — the wider control
        # card is what gives each actuator slider a usable track.
        grid.addWidget(self._control_card(), 5)
        grid.addLayout(self._right_column(), 2)
        outer.addLayout(grid)

        self._refresh_live()

    # ----- left: Manual Actuator Control -----
    def _control_card(self):
        self._arduino_badge = DSBadge("Arduino connected", tone="success", dot=True)
        card = DSCard("Manual Actuator Control", header_right=self._arduino_badge,
                      padded=False)
        host = QWidget()
        vlay = QVBoxLayout(host)
        vlay.setContentsMargins(20, 8, 20, 20)
        vlay.setSpacing(0)

        self._rows = {}
        for i, cfg in enumerate(ROWS):
            row = _ActuatorRow(cfg)
            row.jog.connect(self.jog_requested)
            row.go.connect(self.go_requested)
            row.stop.connect(self.stop_requested)
            row.valueChanged.connect(self._on_value)
            self._rows[cfg["key"]] = row
            vlay.addWidget(row)
            if i < len(ROWS) - 1:
                vlay.addWidget(hline())

        vlay.addSpacing(18)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        mark = DSButton("Mark As Default", variant="primary", full_width=True)
        mark.clicked.connect(self.mark_default_requested)
        reset = DSButton("Reset Arduino", variant="secondary", full_width=True)
        reset.clicked.connect(self.reset_arduino_requested)
        estop = DSButton(f"{GLYPH['estop']} Emergency Stop", variant="danger", full_width=True)
        estop.clicked.connect(self.emergency_stop_requested)
        self._mark_btn, self._reset_btn, self._estop_btn = mark, reset, estop
        for b in (mark, reset, estop):
            actions.addWidget(b, 1)
        vlay.addLayout(actions)
        vlay.addStretch(1)

        card.add_widget(host)
        return card

    # ----- right: Live Position + Safety Limits -----
    def _right_column(self):
        col = QVBoxLayout()
        col.setSpacing(_GAP)

        # padded=False + tight host margins: the default 24px card padding on
        # top of the row heights pushed the whole window past 768 on-device
        # (the fullscreen window can't go below the layout's minimum height).
        live = DSCard("Live Position", padded=False)
        live_host = QWidget()
        lv = QVBoxLayout(live_host)
        lv.setContentsMargins(20, 8, 20, 8)
        lv.setSpacing(0)
        self._pos = {}
        live_rows = ["Axial", "Lateral", "Horizontal", "Leg Length", "Pressure"]
        for i, label in enumerate(live_rows):
            pr = _PosRow(label)
            self._pos[ROWS[i]["key"]] = pr
            lv.addWidget(pr)
            if i < len(live_rows) - 1:
                lv.addWidget(hline("--gray-200"))
        live.add_widget(live_host)
        col.addWidget(live, 3)

        safety = DSCard("Safety Limits", padded=False)
        safety_host = QWidget()
        sv = QVBoxLayout(safety_host)
        sv.setContentsMargins(20, 4, 20, 4)
        sv.setSpacing(0)
        for i, (label, val, unit) in enumerate(SAFETY_LIMITS):
            sv.addWidget(self._safety_row(label, val, unit))
            if i < len(SAFETY_LIMITS) - 1:
                sv.addWidget(hline("--gray-200"))
        safety.add_widget(safety_host)
        col.addWidget(safety, 2)
        return col

    def _safety_row(self, label, val, unit):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 7, 0, 7)
        lay.setSpacing(8)
        lbl = QLabel(label)
        lbl.setFont(sans_font(size="--text-sm", weight=600))
        lbl.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        value = QLabel()
        value.setTextFormat(Qt.RichText)
        value.setText(
            f"<span style='font-size:24px; color:{resolve('--ink-900')};'>{val}</span>"
            f"<span style='font-size:13px; color:{resolve('--gray-600')};'>"
            f"<span style='font-size:4px;'> </span>{unit}</span>"
        )
        value.setFont(mono_font(weight=600))
        lay.addWidget(lbl)
        lay.addStretch(1)
        lay.addWidget(value)
        return w

    # ----- live-position binding -----
    def _on_value(self, key, value):
        self._refresh_live(key)
        self.value_changed.emit(key, value)

    def _refresh_live(self, only=None):
        for cfg in ROWS:
            key = cfg["key"]
            if only and key != only:
                continue
            v = self._rows[key].value() if hasattr(self, "_rows") else cfg["value"]
            pr = self._pos.get(key)
            if pr is None:
                continue
            if key in ("lateral", "horizontal"):
                pr.set_value(f"{int(round(v))}°", "", cfg["pos_tone"])
            elif key == "pressure":
                tone = "danger" if v > 70 else "default"
                pr.set_value(str(int(round(v))), "lbs", tone)
            else:  # axial, leg_length
                pr.set_value(f"{v:.1f}", "in", "default")

    # ----- external hooks (Phase 3) -----
    def set_arduino_connected(self, connected):
        self._arduino_badge.set_tone("success" if connected else "danger")
        self._arduino_badge.set_text("Arduino connected" if connected else "Arduino offline")

    def row_value(self, key):
        """Current slider value (natural units) for an actuator row."""
        row = self._rows.get(key)
        return row.value() if row is not None else 0.0

    def set_position(self, key, value):
        """Reflect a controller-commanded position back onto a row + Live Position.

        Sets the slider without re-emitting ``value_changed`` (DSSlider blocks its
        own signals in set_value), then refreshes the Live Position readout.
        """
        row = self._rows.get(key)
        if row is None:
            return
        row.set_value(value)
        self._refresh_live(key)

    def control_buttons(self):
        """Jog / Go / Stop buttons + Reset-Arduino — the set locked while the MCU
        is busy. The Emergency Stop and Mark-As-Default buttons are intentionally
        excluded so e-stop is always reachable."""
        widgets = []
        for cfg in ROWS:
            row = self._rows.get(cfg["key"])
            if row is not None:
                widgets.extend(row.buttons)
        widgets.append(self._reset_btn)
        return widgets
