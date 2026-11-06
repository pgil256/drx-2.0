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
    "cyan": ("--brand-cyan-soft", "--blue-700"),
}


# size -> (label font token, dot px, horizontal pad, vertical pad). "sm" is the
# in-card badge; "md" is read at arm's length (the top bar's device status).
_SIZES = {"sm": ("--text-xs", 8, 12, 4), "md": ("--text-base", 10, 16, 6)}


class DSBadge(QFrame):
    def __init__(self, text="", tone="neutral", dot=False, parent=None, size="sm"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        font_token, dot_px, pad_x, pad_y = _SIZES.get(size, _SIZES["sm"])
        lay = QHBoxLayout(self)
        lay.setContentsMargins(pad_x, pad_y, pad_x, pad_y)
        lay.setSpacing(8 if size == "md" else 6)
        lay.setSizeConstraint(QLayout.SetFixedSize)  # pill hugs content

        self._dot = QFrame(self)
        self._dot.setFixedSize(dot_px, dot_px)
        self._dot_radius = dot_px // 2
        self._dot.setVisible(dot)
        self._label = QLabel(text, self)
        # text-xs / weight 600 / tracking-wide (sm); text-base / 600 (md)
        self._label.setFont(sans_font(size=font_token, weight=600, tracking=0.03))
        if size == "sm":
            self._label.setProperty("dsCaption", True)
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
        self._dot.setStyleSheet(f"background: {fg}; border-radius: {self._dot_radius}px;")

    def set_text(self, text):
        self._label.setText(text)
