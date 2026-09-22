"""DSProtocolButton — protocol selector tile (number over name).

Mirrors `ProtocolButton`: a checkable tile with a big number and an uppercase
name. Selected = filled primary; hover (unselected) = primary border; disabled =
neutral fill with readable text. Put the four tiles in an exclusive QButtonGroup.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout

from ._common import resolve, sans_font


class DSProtocolButton(QPushButton):
    def __init__(self, number, name, parent=None):
        super().__init__(parent)
        self.setObjectName("DSProtocolButton")
        self.setCheckable(True)
        self.setAccessibleName(f"Protocol {number}: {name}")
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

        self.toggled.connect(lambda _checked: self._render())
        self._render()

    # QPushButton.sizeHint() sizes to its (empty) text + style padding and
    # ignores the child layout, so the tile collapsed to ~51px and squeezed the
    # number label down to ~10px — clipping the digit top and bottom. Defer to
    # the layout so the tile grows to fit the number + name, like the DS flex
    # button (padding 14px 8px, no fixed height).
    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()

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
            border = resolve("--border-control")
        # Keep identity readable when editing is locked; avoid nested opacity
        # effects inside shadowed cards, which can also disrupt Qt repainting.
        if not self.isEnabled():
            bg, fg = resolve("--gray-200"), resolve("--ink-800")
        self.setStyleSheet(
            f"#DSProtocolButton {{ background: {bg}; border: 2px solid {border};"
            f" border-radius: {resolve('--radius-md')}; }}"
            f"#DSProtocolButton:hover:enabled {{ border-color: {primary}; }}"
            f"#DSProtocolButton:focus {{ border: 3px solid {resolve('--ink-900')}; }}"
            f"#DSProtocolButton:pressed {{ border: 3px solid {resolve('--ink-900')}; }}"
            f" QLabel {{ color: {fg}; background: transparent; }}"
        )
