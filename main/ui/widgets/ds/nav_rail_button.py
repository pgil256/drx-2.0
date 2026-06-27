"""DSNavRailButton — dark left-rail nav item (icon over label, active = cyan).

Mirrors `NavRailButton`: square (rail-width), icon-over-label, checkable. Active
state paints black bg + cyan label + a 4px cyan left border. Icon recoloring on
active is wired in Phase 2 when the real Lucide SVGs are supplied.
"""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QToolButton

from ._common import px, repolish, resolve, sans_font


class DSNavRailButton(QToolButton):
    def __init__(self, label="", icon=None, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setText(label)
        self.setFont(sans_font(size="--text-md", weight=700))
        if icon is not None:
            self.setIcon(icon)
            self.setIconSize(QSize(26, 26))
        rail = px("--rail-width")
        self.setFixedSize(rail, rail)
        self.toggled.connect(lambda _checked: self._render())
        self._render()

    def _render(self):
        active = self.isChecked()
        fg = resolve("--brand-cyan") if active else "#ffffff"
        bg = "#000000" if active else resolve("--ink-900")
        hover = "#000000" if active else "#2a2a2a"
        left = resolve("--brand-cyan") if active else "transparent"
        self.setStyleSheet(
            f"QToolButton {{ color: {fg}; background: {bg}; border: none;"
            f" border-left: 4px solid {left}; }}"
            f" QToolButton:hover {{ background: {hover}; }}"
        )
        repolish(self)
