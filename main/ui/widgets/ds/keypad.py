"""DSKeypad — numeric PIN keypad (dots + 1–9 / Clear / 0 / ⌫ grid).

Mirrors `Keypad`: a controlled widget that tracks an entered value, renders one
dot per expected digit, and reports edits via ``valueChanged(str)``. When the
value reaches ``length`` it also emits ``submitted(str)`` (the login modal can
verify the PIN there). Fixes the legacy keypad's missing-`0` bug by design.

``compact=True`` is the in-page variant (Protocols → Patient card): 44px keys
in a 216px grid. Pass ``label=None`` to omit the title in either size.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._common import px, resolve, sans_font

_KEY_CSS = (
    "QPushButton {{ background: {bg}; color: {fg};"
    " border: 2px solid {border}; border-radius: {radius}; }}"
    "QPushButton:hover {{ background: {hover}; }}"
)

#: Backspace key label. "←" (U+2190) renders in IBM Plex; "⌫" (U+232B) does not.
BACKSPACE = "←"

# compact? -> (key height | None = --touch-large + 4, pad width, key font,
#              dot px, dot gap, gap below dots, grid gap)
_METRICS = {
    False: (None, 300, "--text-lg", 20, 14, 18, 10),
    True: (44, 216, "--text-md", 16, 10, 12, 8),
}


class DSKeypad(QWidget):
    valueChanged = pyqtSignal(str)
    submitted = pyqtSignal(str)

    def __init__(self, length=4, value="", label="Enter User PIN", parent=None,
                 compact=False):
        super().__init__(parent)
        self._length = length
        self._value = value
        self._compact = bool(compact)
        key_h, width, key_font, dot_px, dot_gap, dots_below, grid_gap = _METRICS[self._compact]
        # 76px outer = 72px (touch-large, content-box) + 2px border each side.
        self._key_h = key_h if key_h is not None else px("--touch-large") + 4
        self._key_font = key_font
        self._dot_px = dot_px
        self.setFixedWidth(width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = None
        if label:
            self._title = QLabel(label, self)
            self._title.setFont(sans_font(size="--text-md", weight=600))
            self._title.setAlignment(Qt.AlignCenter)
            self._title.setStyleSheet(f"color: {resolve('--ink-800')};")
            outer.addWidget(self._title)
            outer.addSpacing(14)

        dots_row = QHBoxLayout()
        dots_row.setContentsMargins(0, 0, 0, 0)
        dots_row.setSpacing(dot_gap)
        dots_row.addStretch(1)
        self._dots = []
        for _ in range(length):
            dot = QLabel(self)
            # 20px outer = 16px core + 2px ring each side (the JS dot is
            # content-box 16px + 2px border; Qt borders are inside the box).
            dot.setFixedSize(dot_px, dot_px)
            self._dots.append(dot)
            dots_row.addWidget(dot)
        dots_row.addStretch(1)
        outer.addLayout(dots_row)
        outer.addSpacing(dots_below)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(grid_gap)
        for i in range(1, 10):
            r, c = divmod(i - 1, 3)
            grid.addWidget(self._make_key(str(i), self._press_factory(str(i))), r, c)
        grid.addWidget(self._make_key("Clear", self._clear, muted=True), 3, 0)
        grid.addWidget(self._make_key("0", self._press_factory("0")), 3, 1)
        # Backspace uses "←" (U+2190): IBM Plex has it, but not "⌫" (U+232B).
        grid.addWidget(self._make_key(BACKSPACE, self._back, muted=True), 3, 2)
        outer.addLayout(grid)

        self._refresh_dots()

    # -- keys ----------------------------------------------------------
    def _make_key(self, text, slot, muted=False):
        btn = QPushButton(text, self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(self._key_h)
        btn.setFont(sans_font(size=self._key_font, weight=600))
        btn.clicked.connect(slot)
        if muted:
            css = _KEY_CSS.format(
                bg=resolve("--gray-200"), fg=resolve("--ink-700"),
                border=resolve("--gray-300"), radius=resolve("--radius-md"),
                hover=resolve("--gray-300"),
            )
        else:
            css = _KEY_CSS.format(
                bg="#ffffff", fg=resolve("--ink-900"),
                border=resolve("--gray-300"), radius=resolve("--radius-md"),
                hover=resolve("--blue-050"),
            )
        if self._compact:
            css += "QPushButton { padding: 0 2px; }"  # "Clear" fits a 66px key
        btn.setStyleSheet(css)
        return btn

    def _press_factory(self, digit):
        return lambda: self._press(digit)

    def _press(self, digit):
        if len(self._value) < self._length:
            self._set_value(self._value + digit)
            if len(self._value) == self._length:
                self.submitted.emit(self._value)

    def _clear(self):
        self._set_value("")

    def _back(self):
        self._set_value(self._value[:-1])

    # -- value ---------------------------------------------------------
    def _set_value(self, value):
        self._value = value[: self._length]
        self._refresh_dots()
        self.valueChanged.emit(self._value)

    def set_value(self, value):
        self._set_value(value)

    def value(self):
        return self._value

    def setEnabled(self, enabled):
        """Dim the whole pad when disabled — the key QSS has no ``:disabled``
        state, so a locked pad would otherwise look live."""
        super().setEnabled(enabled)
        if enabled:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.45)
            self.setGraphicsEffect(effect)

    def _refresh_dots(self):
        primary = resolve("--color-primary")
        for i, dot in enumerate(self._dots):
            filled = i < len(self._value)
            dot.setStyleSheet(
                f"background: {primary if filled else 'transparent'};"
                f" border: 2px solid {primary}; border-radius: {self._dot_px // 2}px;"
            )
