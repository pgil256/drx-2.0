"""DSKeypad — numeric PIN keypad (dots + 1–9 / Clear / 0 / ⌫ grid).

Mirrors `Keypad`: a controlled widget that tracks an entered value, renders one
dot per expected digit, and reports edits via ``valueChanged(str)``. When the
value reaches ``length`` it also emits ``submitted(str)`` (the login modal can
verify the PIN there). Fixes the legacy keypad's missing-`0` bug by design.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
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


class DSKeypad(QWidget):
    valueChanged = pyqtSignal(str)
    submitted = pyqtSignal(str)

    def __init__(self, length=4, value="", label="Enter User PIN", parent=None):
        super().__init__(parent)
        self._length = length
        self._value = value
        self.setFixedWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._title = QLabel(label, self)
        self._title.setFont(sans_font(size="--text-md", weight=600))
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(f"color: {resolve('--ink-800')};")
        outer.addWidget(self._title)
        outer.addSpacing(14)

        dots_row = QHBoxLayout()
        dots_row.setContentsMargins(0, 0, 0, 0)
        dots_row.setSpacing(14)
        dots_row.addStretch(1)
        self._dots = []
        for _ in range(length):
            dot = QLabel(self)
            # 20px outer = 16px core + 2px ring each side (the JS dot is
            # content-box 16px + 2px border; Qt borders are inside the box).
            dot.setFixedSize(20, 20)
            self._dots.append(dot)
            dots_row.addWidget(dot)
        dots_row.addStretch(1)
        outer.addLayout(dots_row)
        outer.addSpacing(18)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
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
        # 76px outer = 72px (touch-large, content-box) + 2px border each side.
        btn.setFixedHeight(px("--touch-large") + 4)
        btn.setFont(sans_font(size="--text-lg", weight=600))
        btn.clicked.connect(slot)
        if muted:
            btn.setStyleSheet(_KEY_CSS.format(
                bg=resolve("--gray-200"), fg=resolve("--ink-700"),
                border=resolve("--gray-300"), radius=resolve("--radius-md"),
                hover=resolve("--gray-300"),
            ))
        else:
            btn.setStyleSheet(_KEY_CSS.format(
                bg="#ffffff", fg=resolve("--ink-900"),
                border=resolve("--gray-300"), radius=resolve("--radius-md"),
                hover=resolve("--blue-050"),
            ))
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

    def _refresh_dots(self):
        primary = resolve("--color-primary")
        for i, dot in enumerate(self._dots):
            filled = i < len(self._value)
            dot.setStyleSheet(
                f"background: {primary if filled else 'transparent'};"
                f" border: 2px solid {primary}; border-radius: 10px;"
            )
