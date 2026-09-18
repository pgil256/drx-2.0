"""DSSlider — labeled range row (label · track · mono value).

Two modes: ``mode='slider'`` (default) shows a QSlider track; ``mode='stepper'``
replaces the track with left/right arrow buttons and the value between them.

QSlider is integer-only, so both modes map a float ``min/max/step`` domain onto
integer ticks and report real floats via ``valueChanged(float)``.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QWidget,
)

from ui.theme import GLYPH

from ._common import mono_font, resolve, sans_font

_LABEL_CSS = f"color: {resolve('--ink-800')}; background: transparent;"

_HANDLE_PX = 24
_ARROW_PX = 48  # stepper arrow buttons — touch target


def _arrow_btn_css():
    return (
        "QPushButton {"
        f" background: #ffffff;"
        f" color: {resolve('--ink-800')};"
        f" border: 2px solid {resolve('--gray-300')};"
        f" border-radius: {resolve('--radius-md')};"
        " padding: 0 0 4px 0; }"  # optical centering for the ‹ › glyphs
        f" QPushButton:hover {{ background: {resolve('--blue-050')};"
        f" border-color: {resolve('--color-primary')}; }}"
        f" QPushButton:pressed {{ background: {resolve('--blue-100')}; }}"
    )


class DSSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label=None, value=0, minimum=0, maximum=100, step=1,
                 unit="", parent=None, mode="slider", label_width=110):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._step = float(step)
        self._unit = unit
        self._value = self._min
        self._steps = max(1, round((self._max - self._min) / self._step))
        self._mode = mode

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        if label is not None:
            self._label = QLabel(label, self)
            self._label.setFont(sans_font(size="--text-base"))
            self._label.setMinimumWidth(label_width)
            self._label.setStyleSheet(_LABEL_CSS)
            lay.addWidget(self._label)

        if mode == "stepper":
            self._build_stepper(lay)
        else:
            self._build_slider(lay)

        self.set_value(value)

    # -- build variants ------------------------------------------------
    def _build_slider(self, lay):
        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(0, self._steps)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(1, self._steps // 10))
        self._slider.setMinimumHeight(_HANDLE_PX)
        self._slider.valueChanged.connect(self._on_slider)
        lay.addWidget(self._slider, 1)

        self._value_label = QLabel(self)
        self._value_label.setFont(mono_font(size="--text-base", weight=600))
        self._value_label.setMinimumWidth(64)
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setStyleSheet(_LABEL_CSS)
        lay.addWidget(self._value_label)

    def _build_stepper(self, lay):
        # Plex-safe arrow glyphs (‹ ›) — the design's ◀ ▶ tofu in IBM Plex; see
        # ui/theme/icons.py. Same glyphs as the Setup page's jog buttons.
        self._left_btn = self._arrow_button(GLYPH["jog_rev"], self._decrement)
        lay.addWidget(self._left_btn)

        self._value_label = QLabel(self)
        self._value_label.setFont(mono_font(size="--text-md", weight=600))
        self._value_label.setMinimumWidth(80)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(_LABEL_CSS)
        lay.addWidget(self._value_label, 1)

        self._right_btn = self._arrow_button(GLYPH["jog_fwd"], self._increment)
        lay.addWidget(self._right_btn)

    def _arrow_button(self, glyph, slot):
        btn = QPushButton(glyph, self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(_ARROW_PX, _ARROW_PX)
        btn.setFont(sans_font(size=28, weight=700))
        btn.setStyleSheet(_arrow_btn_css())
        # Press-and-hold steps repeatedly (touch users expect this on ‹ ›).
        btn.setAutoRepeat(True)
        btn.setAutoRepeatDelay(400)
        btn.setAutoRepeatInterval(120)
        btn.clicked.connect(slot)
        return btn

    # -- stepper actions -----------------------------------------------
    def _increment(self):
        new = round(min(self._max, self._value + self._step), 6)
        if new != self._value:
            self._value = new
            self._update_label()
            self.valueChanged.emit(self._value)

    def _decrement(self):
        new = round(max(self._min, self._value - self._step), 6)
        if new != self._value:
            self._value = new
            self._update_label()
            self.valueChanged.emit(self._value)

    # -- value mapping -------------------------------------------------
    def _to_pos(self, v):
        return int(round((v - self._min) / self._step))

    def _from_pos(self, pos):
        return self._min + pos * self._step

    def set_value(self, value):
        value = max(self._min, min(self._max, float(value)))
        if self._mode == "stepper":
            pos = self._to_pos(value)
            self._value = round(self._from_pos(pos), 6)
        else:
            self._slider.blockSignals(True)
            self._slider.setValue(self._to_pos(value))
            self._slider.blockSignals(False)
            self._value = round(self._from_pos(self._slider.value()), 6)
        self._update_label()

    def value(self):
        return self._value

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        if enabled:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.45)
            self.setGraphicsEffect(effect)

    def _on_slider(self, pos):
        self._value = round(self._from_pos(pos), 6)
        self._update_label()
        self.valueChanged.emit(self._value)

    # -- display -------------------------------------------------------
    def _fmt(self, v):
        if abs(v - round(v)) < 1e-9:
            return str(int(round(v)))
        return ("%f" % v).rstrip("0").rstrip(".")

    def _update_label(self):
        self._value_label.setText(self._fmt(self._value) + self._unit)
