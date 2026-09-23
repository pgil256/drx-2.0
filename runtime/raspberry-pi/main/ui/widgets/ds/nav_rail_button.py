"""DSNavRailButton — slate left-rail nav item (icon over label, active = cyan).

Fixed 88px items, top-aligned in the rail, so five pages read as a list rather
than a stack of stretched slabs. The active item gets a darker slate fill,
cyan label + icon and a 4px cyan left edge. ``checkable=False`` makes a
launcher (Video) that shares the look without holding a selection.
"""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QSizePolicy, QToolButton

from ._common import px, repolish, resolve, sans_font

ITEM_HEIGHT = 88
ICON_PX = 26


class DSNavRailButton(QToolButton):
    def __init__(self, label="", icon=None, icon_factory=None, fill_height=False, parent=None,
                 checkable=True):
        super().__init__(parent)
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self.setAccessibleName(label)
        self.setFont(sans_font(size="--text-sm", weight=600))
        # icon_factory(color, size) -> QIcon lets the icon recolor with the
        # active label (cyan when checked); a static icon stays as given.
        self._icon_factory = icon_factory
        self.setIconSize(QSize(ICON_PX, ICON_PX))
        if icon is not None:
            self.setIcon(icon)
        rail = px("--rail-width")
        if fill_height:
            # Legacy stretch mode: share the column height (min 80px).
            self.setFixedWidth(rail)
            self.setMinimumHeight(80)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self.setFixedSize(rail, ITEM_HEIGHT)
        self.toggled.connect(lambda _checked: self._render())
        self._render()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == event.EnabledChange:
            self._render()

    def _render(self):
        active = self.isChecked()
        cyan = resolve("--brand-cyan")
        if not self.isEnabled():
            fg = resolve("--text-on-dark-disabled")
        else:
            fg = cyan if active else resolve("--text-on-dark")
        bg = resolve("--surface-chrome-active") if active else "transparent"
        hover = resolve("--surface-chrome-active") if active else resolve("--surface-chrome-hover")
        left = cyan if active else "transparent"
        if self._icon_factory is not None:
            self.setIcon(self._icon_factory(fg, ICON_PX))
        self.setStyleSheet(
            f"QToolButton {{ color: {fg}; background: {bg}; border: none;"
            f" border-left: 4px solid {left}; padding: 12px 0 10px 0; }}"
            f" QToolButton:hover {{ background: {hover}; }}"
            f" QToolButton:pressed {{ background: {resolve('--surface-chrome-active')}; }}"
            f" QToolButton[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--white')}; border-left: 4px solid {left}; }}"
        )
        repolish(self)
