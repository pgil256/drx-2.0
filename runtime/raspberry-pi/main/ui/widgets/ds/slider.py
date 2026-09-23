"""DSSlider — labeled range row (label · track · mono value).

Two modes: ``mode='slider'`` (default) shows a QSlider track; ``mode='stepper'``
replaces the track with − / + buttons and the value between them.

QSlider is integer-only, so both modes map a float ``min/max/step`` domain onto
integer ticks and report real floats via ``valueChanged(float)``.
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from ui.theme import control_icon

from ._common import mark_caption, mono_font, pinned_height, resolve, sans_font

_LABEL_CSS = f"color: {resolve('--ink-800')}; background: transparent;"

_HANDLE_PX = 24
_ARROW_PX = 56  # frequent stepper controls


class _TouchSlider(QSlider):
    """Use the entire 48 px row for touch, retaining Qt's tracking contract."""

    def _position_at(self, x: int) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self,
        )
        span = max(1, self.width() - handle.width())
        position = max(0, min(span, x - handle.width() // 2))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), position, span, option.upsideDown,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.setFocus(Qt.MouseFocusReason)
            self.setSliderDown(True)
            self.setSliderPosition(self._position_at(event.x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.isSliderDown():
            self.setSliderPosition(self._position_at(event.x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderPosition(self._position_at(event.x()))
            self.setSliderDown(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _arrow_btn_css(size=_ARROW_PX):
    return (
        "QPushButton {"
        f" background: {resolve('--white')};"
        f" border: 1px solid {resolve('--border-control')};"
        f" border-radius: {resolve('--radius-md')};"
        f" padding: 0; {pinned_height(size, border=1)} }}"
        f" QPushButton:hover {{ background: {resolve('--gray-050')}; }}"
        f" QPushButton:pressed {{ background: {resolve('--blue-100')}; }}"
        f" QPushButton[keyboardFocus=\"true\"]:focus {{"
        f" border: 2px solid {resolve('--ink-900')}; }}"
        f" QPushButton:disabled {{ background: {resolve('--gray-100')};"
        f" border-color: {resolve('--gray-300')}; }}"
    )


class DSSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, label=None, value=0, minimum=0, maximum=100, step=1,
                 unit="", parent=None, mode="slider", label_width=110, with_steps=False,
                 hint=None, caption=None):
        super().__init__(parent)
        self._min = float(minimum)
        self._max = float(maximum)
        self._step = float(step)
        self._unit = unit
        self._value = self._min
        self._steps = max(1, round((self._max - self._min) / self._step))
        self._mode = mode
        self._with_steps = with_steps
        self._accessible_label = label or "Value"
        self._caption_text = caption

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self._hint = None
        if label is not None:
            self._label = QLabel(label, self)
            self._label.setFont(sans_font(size="--text-base"))
            self._label.setMinimumWidth(label_width)
            self._label.setStyleSheet(_LABEL_CSS)
            if hint:
                # A caption under the label, e.g. the allowed range "5–30 min".
                names = QVBoxLayout()
                names.setContentsMargins(0, 0, 0, 0)
                names.setSpacing(0)
                names.addStretch(1)
                names.addWidget(self._label)
                self._hint = QLabel(hint, self)
                self._hint.setFont(sans_font(size="--text-xs"))
                mark_caption(self._hint)
                self._hint.setStyleSheet(
                    f"color: {resolve('--text-muted')}; background: transparent;")
                names.addWidget(self._hint)
                names.addStretch(1)
                lay.addLayout(names)
            else:
                lay.addWidget(self._label)

        if mode == "stepper":
            self._build_stepper(lay)
        else:
            self._build_slider(lay)

        self.set_value(value)

    # -- build variants ------------------------------------------------
    def _build_slider(self, lay):
        if self._with_steps:
            self._left_btn = self._arrow_button("minus", self._decrement)
            lay.addWidget(self._left_btn)
        self._slider = _TouchSlider(Qt.Horizontal, self)
        self._slider.setRange(0, self._steps)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(max(1, self._steps // 10))
        self._slider.setMinimumHeight(48)
        self._slider.setMinimumWidth(70)
        self._slider.setAccessibleName(self._accessible_label)
        self._slider.valueChanged.connect(self._on_slider)
        lay.addWidget(self._slider, 1)
        if self._with_steps:
            self._right_btn = self._arrow_button("plus", self._increment)
            lay.addWidget(self._right_btn)

        self._value_label = QLabel(self)
        self._value_label.setFont(mono_font(size="--text-md", weight=600))
        self._value_label.setMinimumWidth(64)
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setStyleSheet(_LABEL_CSS)
        lay.addWidget(self._value_label)

    def _build_stepper(self, lay):
        self._left_btn = self._arrow_button("minus", self._decrement)
        lay.addWidget(self._left_btn)

        self._value_label = QLabel(self)
        self._value_label.setFont(mono_font(size="--text-md", weight=600))
        self._value_label.setMinimumWidth(80)
        self._value_label.setAlignment(Qt.AlignCenter)
        self._value_label.setStyleSheet(_LABEL_CSS)
        self._caption = None
        if self._caption_text:
            # A small caption over the value names what the number is.
            column = QVBoxLayout()
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(0)
            column.addStretch(1)
            self._caption = QLabel(self._caption_text, self)
            self._caption.setAlignment(Qt.AlignCenter)
            self._caption.setFont(sans_font(size="--text-xs", weight=600))
            self._caption.setStyleSheet(
                f"color: {resolve('--text-muted')}; background: transparent;")
            mark_caption(self._caption)
            column.addWidget(self._caption)
            column.addWidget(self._value_label)
            column.addStretch(1)
            lay.addLayout(column, 1)
        else:
            lay.addWidget(self._value_label, 1)

        self._right_btn = self._arrow_button("plus", self._increment)
        lay.addWidget(self._right_btn)

    def _arrow_button(self, icon, slot):
        btn = QPushButton(self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.TabFocus)
        btn.setIcon(control_icon(icon, resolve("--ink-800"), 24,
                                 disabled_color=resolve("--gray-400")))
        btn.setIconSize(QSize(24, 24))
        self._size_step_button(btn, _ARROW_PX)
        # Press-and-hold steps repeatedly (touch users expect this on ‹ ›).
        btn.setAutoRepeat(True)
        btn.setAutoRepeatDelay(400)
        btn.setAutoRepeatInterval(120)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _size_step_button(button, size):
        button.setFixedSize(size, size)
        button.setStyleSheet(_arrow_btn_css(size))

    def set_step_size(self, size: int) -> None:
        """Resize the − / + buttons (fixed size and matching stylesheet)."""
        for button in (getattr(self, "_left_btn", None), getattr(self, "_right_btn", None)):
            if button is not None:
                self._size_step_button(button, size)

    def set_accessible_label(self, label: str) -> None:
        """Name the value and its direction controls for assistive technology."""
        self._accessible_label = label
        self.setAccessibleName(label)
        if hasattr(self, "_slider"):
            self._slider.setAccessibleName(label)
        if hasattr(self, "_left_btn"):
            self._left_btn.setAccessibleName("Decrease " + label)
            self._right_btn.setAccessibleName("Increase " + label)

    # -- stepper actions -----------------------------------------------
    def _increment(self):
        new = round(min(self._max, self._value + self._step), 6)
        if new != self._value:
            self.set_value(new)
            self.valueChanged.emit(self._value)

    def _decrement(self):
        new = round(max(self._min, self._value - self._step), 6)
        if new != self._value:
            self.set_value(new)
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
        # A locked input is also a treatment summary: keep its value readable.

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
