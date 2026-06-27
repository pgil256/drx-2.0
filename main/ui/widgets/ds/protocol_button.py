"""DSProtocolButton — protocol selector tile (number over name).

Mirrors `ProtocolButton`: a checkable tile with a big number and an uppercase
name. Selected = filled primary; hover (unselected) = primary border; disabled =
dimmed. Put the four tiles in a QButtonGroup (exclusive) at the screen level.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QGraphicsOpacityEffect, QLabel, QPushButton, QVBoxLayout

from ._common import resolve, sans_font


class DSProtocolButton(QPushButton):
    def __init__(self, number, name, parent=None):
        super().__init__(parent)
        self.setObjectName("DSProtocolButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(76)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 14, 8, 14)
        lay.setSpacing(4)

        self._num = QLabel(str(number), self)
        self._num.setFont(sans_font(size="--text-lg", weight=700))
        self._num.setAlignment(Qt.AlignCenter)
        self._num.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._name = QLabel(str(name).upper(), self)
        self._name.setFont(sans_font(size="--text-2xs", weight=600, tracking=0.03))
        self._name.setAlignment(Qt.AlignCenter)
        self._name.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        lay.addWidget(self._num)
        lay.addWidget(self._name)

        self._dim = None  # QGraphicsOpacityEffect applied while disabled
        self.toggled.connect(lambda _checked: self._render())
        self._render()

    def changeEvent(self, event):
        super().changeEvent(event)
        # EnabledChange == QEvent.EnabledChange (value 98)
        if event.type() == event.EnabledChange:
            self._render()

    def _render(self):
        selected = self.isChecked()
        primary = resolve("--color-primary")
        if selected:
            bg, fg, border = primary, "#ffffff", primary
        else:
            bg = resolve("--gray-050")
            fg = resolve("--ink-800")
            border = resolve("--gray-300")
        # Disabled = uniform 0.5 opacity on the whole tile (matches the DS, which
        # dims fill+border+labels together and keeps the selected/unselected text
        # color — a disabled+selected tile stays white-on-primary, just dimmed).
        if not self.isEnabled():
            if self._dim is None:
                self._dim = QGraphicsOpacityEffect(self)
                self._dim.setOpacity(0.5)
                self.setGraphicsEffect(self._dim)
        elif self._dim is not None:
            self.setGraphicsEffect(None)
            self._dim = None
        self.setStyleSheet(
            f"#DSProtocolButton {{ background: {bg}; border: 2px solid {border};"
            f" border-radius: {resolve('--radius-md')}; }}"
            f"#DSProtocolButton:hover:enabled {{ border-color: {primary}; }}"
            f" QLabel {{ color: {fg}; background: transparent; }}"
        )
