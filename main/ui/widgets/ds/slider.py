"""DSSlider — labeled range row (label · track · mono value).

Mirrors `Slider`: optional left label, a track (styled by app.qss), and a right
monospace value+unit. QSlider is integer-only, so this maps a float
``min/max/step`` domain onto integer ticks and reports real floats via
``valueChanged(float)``. Used for treatment Settings and the Setup actuator rows.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget

from ._common import mono_font, resolve, sans_font

_LABEL_CSS = f"color: {resolve('--ink-800')}; background: transparent;"


class DSSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label=None, value=0, minimum=0, maximum=100, step=1, unit="", parent=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._step = float(step)
        self._unit = unit
        self._value = self._min
        self._steps = max(1, round((self._max - self._min) / self._step))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        if label is not None:
            self._label = QLabel(label, self)
            self._label.setFont(sans_font(size="--text-base"))
            self._label.setMinimumWidth(110)
            self._label.setStyleSheet(_LABEL_CSS)
            lay.addWidget(self._label)

        self._slider = QSlider(Qt.Horizontal, self)
        self._slider.setRange(0, self._steps)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(1, self._steps // 10))
        self._slider.valueChanged.connect(self._on_slider)
        lay.addWidget(self._slider, 1)

        self._value_label = QLabel(self)
        self._value_label.setFont(mono_font(size="--text-base", weight=600))
        self._value_label.setMinimumWidth(64)
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setStyleSheet(_LABEL_CSS)
        lay.addWidget(self._value_label)

        self.set_value(value)

    # -- value mapping -------------------------------------------------
    def _to_pos(self, v):
        return int(round((v - self._min) / self._step))

    def _from_pos(self, pos):
        return self._min + pos * self._step

    def set_value(self, value):
        value = max(self._min, min(self._max, float(value)))
        self._slider.blockSignals(True)
        self._slider.setValue(self._to_pos(value))
        self._slider.blockSignals(False)
        self._value = round(self._from_pos(self._slider.value()), 6)
        self._update_label()

    def value(self):
        return self._value

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
