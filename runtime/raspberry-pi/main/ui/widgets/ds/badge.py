"""DSBadge — small status pill (connection state, treatment phase, role tags).

Mirrors `Badge`: pill with optional leading dot, tone-driven bg/fg. Self-styles
from tokens. Sizes itself to its content so it can sit in a Card header.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout

from ._common import mark_caption, resolve, sans_font

# tone -> (background token, foreground token) — from Badge.jsx TONES.
TONES = {
    "neutral": ("--gray-200", "--ink-700"),
    "info": ("--blue-100", "--blue-700"),
    "success": ("--green-100", "--green-600"),
    "danger": ("--red-100", "--red-600"),
    "warning": ("--amber-100", "--amber-500"),
    "cyan": ("--brand-cyan-soft", "--blue-700"),
}
# size -> (label font, dot px, horizontal pad, vertical pad)
SIZES = {"sm": ("--text-xs", 8, 12, 4), "md": ("--text-sm", 10, 14, 7)}


class DSBadge(QFrame):
    def __init__(self, text="", tone="neutral", dot=False, parent=None, size="sm"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        font, self._dot_px, pad_x, pad_y = SIZES.get(size, SIZES["sm"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        lay.setSpacing(8 if size == "md" else 6)
        lay.setSizeConstraint(QLayout.SetFixedSize)  # pill hugs content

        self._dot = QFrame(self)
        self._dot.setFixedSize(self._dot_px, self._dot_px)
        self._dot.setVisible(dot)
        self._label = QLabel(text, self)
        self._label.setFont(sans_font(size=font, weight=600, tracking=0.03))
        mark_caption(self._label)
        lay.addWidget(self._dot)
        lay.addWidget(self._label)
        # Qt draws square corners when a radius exceeds half the height, so a
        # "999px" pill must be spelled out as the real half-height.
        self._radius = (self._label.fontMetrics().height() + 2 * pad_y) // 2

        self._tone = tone
        self.set_tone(tone)

    def set_tone(self, tone):
        self._tone = tone if tone in TONES else "neutral"
        bg_t, fg_t = TONES[self._tone]
        bg, fg = resolve(bg_t), resolve(fg_t)
        self.setStyleSheet(
            f"DSBadge {{ background: {bg}; border-radius: {self._radius}px; }}"
            f" QLabel {{ color: {fg}; background: transparent; }}"
        )
        self._dot.setStyleSheet(f"background: {fg}; border-radius: {self._dot_px // 2}px;")

    def set_text(self, text):
        self._label.setText(text)

    def text(self):
        return self._label.text()

    def tone(self):
        return self._tone

    def set_dot(self, on):
        self._dot.setVisible(on)
