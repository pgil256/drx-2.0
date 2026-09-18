"""DSNavRailButton — dark left-rail nav item (icon over label, active = cyan).

Mirrors `NavRailButton`: square (rail-width), icon-over-label, checkable. Active
state paints black bg + cyan label + a 4px cyan left border. Icon recoloring on
active is wired in Phase 2 when the real Lucide SVGs are supplied.
"""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QSizePolicy, QToolButton

from ._common import px, repolish, resolve, sans_font


class DSNavRailButton(QToolButton):
    def __init__(self, label="", icon=None, icon_factory=None, fill_height=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self.setFont(sans_font(size="--text-md", weight=700))
        # icon_factory(color, size) -> QIcon lets the icon recolor with the
        # active label (cyan when checked); a static icon stays as given.
        self._icon_factory = icon_factory
        self.setIconSize(QSize(26, 26))
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

    def _render(self):
        active = self.isChecked()
        fg = resolve("--brand-cyan") if active else "#ffffff"
        bg = "#000000" if active else resolve("--ink-900")
        hover = "#000000" if active else "#2a2a2a"
        left = resolve("--brand-cyan") if active else "transparent"
        if self._icon_factory is not None:
            self.setIcon(self._icon_factory(fg, 26))
        self.setStyleSheet(
            f"QToolButton {{ color: {fg}; background: {bg}; border: none;"
            f" border-left: 4px solid {left}; }}"
            f" QToolButton:hover {{ background: {hover}; }}"
        )
        repolish(self)
