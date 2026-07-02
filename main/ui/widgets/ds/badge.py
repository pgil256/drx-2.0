"""DSBadge — small status pill (connection state, treatment phase, role tags).

Mirrors `Badge`: pill with optional leading dot, tone-driven bg/fg. Self-styles
from tokens. Sizes itself to its content so it can sit in a Card header.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QLayout

from ._common import resolve, sans_font

# tone -> (background token, foreground token/literal) — from Badge.jsx TONES.
TONES = {
    "neutral": ("--gray-200", "--ink-700"),
    "info": ("--blue-100", "--blue-700"),
    "success": ("--green-100", "--green-600"),
    "danger": ("--red-100", "--red-600"),
    "warning": ("--amber-100", "#9a6206"),
    "cyan": ("--brand-cyan-soft", "--brand-cyan-dark"),
}


class DSBadge(QFrame):
    def __init__(self, text="", tone="neutral", dot=False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 12, 4)
        lay.setSpacing(6)
        lay.setSizeConstraint(QLayout.SetFixedSize)  # pill hugs content

        self._dot = QFrame(self)
        self._dot.setFixedSize(8, 8)
        self._dot.setVisible(dot)
        self._label = QLabel(text, self)
        # text-xs / weight 600 / tracking-wide
        self._label.setFont(sans_font(size="--text-xs", weight=600, tracking=0.03))
        lay.addWidget(self._dot)
        lay.addWidget(self._label)

        self._tone = tone
        self.set_tone(tone)

    def set_tone(self, tone):
        self._tone = tone if tone in TONES else "neutral"
        bg_t, fg_t = TONES[self._tone]
        bg, fg = resolve(bg_t), resolve(fg_t)
        self.setStyleSheet(
            f"DSBadge {{ background: {bg}; border-radius: 999px; }}"
            f" QLabel {{ color: {fg}; background: transparent; }}"
        )
        self._dot.setStyleSheet(f"background: {fg}; border-radius: 4px;")

    def set_text(self, text):
        self._label.setText(text)

    def set_dot(self, on):
        self._dot.setVisible(on)
