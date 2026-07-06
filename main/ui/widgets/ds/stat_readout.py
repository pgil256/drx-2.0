"""DSStatReadout — big monospace numeric readout with an uppercase caption.

Mirrors `StatReadout`: a large mono `value` with a small mono `unit` span and an
uppercase sans caption below. Tone drives the value color; size drives the value
font (sm=30, md=44, lg=56). Used for live pressure / angle / timer.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ._common import mono_font, px, resolve, sans_font

# tone -> value color token (from StatReadout.jsx TONES)
TONES = {
    "default": "--ink-900",
    "cyan": "--brand-cyan",
    "success": "--green-600",
    "warning": "--amber-500",
    "danger": "--red-500",
}
# size -> value font px (sm=text-xl, md=44, lg=text-3xl)
SIZES = {"sm": "--text-xl", "md": "44px", "lg": "--text-3xl"}


class DSStatReadout(QWidget):
    def __init__(self, value="", unit="", label=None, tone="default", size="md", parent=None):
        super().__init__(parent)
        self._value = value
        self._unit = unit
        self._tone = tone if tone in TONES else "default"
        self._size = size if size in SIZES else "md"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._value_label = QLabel(self)
        self._value_label.setTextFormat(Qt.RichText)
        self._value_label.setFont(mono_font(weight=600))  # family/weight; size via rich text
        self._value_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._value_label)

        self._caption = None
        if label:  # truthy — empty-string label renders no caption (matches DS)
            self._caption = QLabel(str(label).upper(), self)
            self._caption.setFont(sans_font(size="--text-xs", weight=600, tracking=0.06))
            self._caption.setAlignment(Qt.AlignCenter)
            self._caption.setStyleSheet(f"color: {resolve('--gray-600')};")
            lay.addWidget(self._caption)

        self._render()

    def _render(self):
        vpx = px(SIZES[self._size])
        color = resolve(TONES[self._tone])
        muted = resolve("--gray-600")
        html = f"<span style='font-size:{vpx}px; color:{color};'>{self._value}</span>"
        if self._unit:
            # Fixed 4px gap (matches the DS marginLeft:4) rather than a unit-sized
            # &nbsp; that would scale with the value size.
            html += (
                f"<span style='font-size:{int(round(vpx * 0.45))}px; color:{muted};'>"
                f"<span style='font-size:4px;'> </span>{self._unit}</span>"
            )
        self._value_label.setText(html)

    def set_value(self, value, unit=None):
        self._value = value
        if unit is not None:
            self._unit = unit
        self._render()

    def set_tone(self, tone):
        self._tone = tone if tone in TONES else "default"
        self._render()

    def set_size(self, size):
        self._size = size if size in SIZES else "md"
        self._render()
