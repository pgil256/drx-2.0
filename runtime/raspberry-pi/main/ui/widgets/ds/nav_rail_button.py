"""DSNavRailButton — left-rail nav item (icon over label, active = action blue).

Mirrors `NavRailButton`: square (rail-width), icon-over-label, checkable. The
active item gets the soft action fill, an action-blue label + icon and a 4px left
edge in the same blue; the rest sit quietly in ink on the white rail. The icon
recolours with the label through ``icon_factory``.
"""

from PyQt5.QtCore import QEvent, QSize, Qt
from PyQt5.QtWidgets import QSizePolicy, QToolButton

from ._common import px, repolish, resolve, sans_font


class DSNavRailButton(QToolButton):
    def __init__(self, label="", icon=None, icon_factory=None, fill_height=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self.setFont(sans_font(size=19, weight=700))
        # icon_factory(color, size) -> QIcon lets the icon recolor with the
        # active label (cyan when checked); a static icon stays as given.
        self._icon_factory = icon_factory
        self.setIconSize(QSize(28, 28))
        if icon is not None:
            self.setIcon(icon)
        rail = px("--rail-width")
        if fill_height:
            # In the real vertical rail the items share the column height
            # (DS flex:1, minHeight:80); fix the width, let height expand.
            self.setFixedWidth(rail)
            self.setMinimumHeight(80)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self.setFixedSize(rail, rail)
        self.toggled.connect(lambda _checked: self._render())
        self._render()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self._render()

    def _render(self):
        active = self.isChecked()
        accent = resolve("--chrome-accent")
        if not self.isEnabled():
            fg = resolve("--text-chrome-disabled")
        else:
            fg = accent if active else resolve("--text-chrome")
        bg = resolve("--surface-chrome-active") if active else "transparent"
        hover = resolve("--surface-chrome-active") if active else resolve("--surface-chrome-hover")
        left = accent if active else "transparent"
        if self._icon_factory is not None:
            self.setIcon(self._icon_factory(fg, 28))
        self.setStyleSheet(
            f"QToolButton {{ color: {fg}; background: {bg}; border: none;"
            f" border-left: 4px solid {left}; padding: 18px 0; }}"
            f" QToolButton:hover {{ background: {hover}; }}"
            f" QToolButton:pressed {{ background: {resolve('--surface-chrome-active')}; }}"
            f" QToolButton[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--border-focus')}; border-left: 4px solid {left}; }}"
        )
        repolish(self)
