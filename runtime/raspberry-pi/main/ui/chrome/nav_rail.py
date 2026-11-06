"""NavRail — persistent 108px white left rail with a hairline edge.

Five exclusive nav items (Home · Setup · Treatment · Support · Device), with the
Video launcher above Support and Device. The active item paints action blue on a
soft blue fill with a 4px left edge, the rail counterpart of the dashboard's
selected nav pill. The rail only reports the intent; ``app_shell`` applies login
gating and the actual page switch.

Signals:
    navigate(str)     — a nav item ('home'|'setup'|'protocols'|'support'|'device')
    video_requested   — the Video launcher
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QFrame, QSizePolicy, QToolButton, QVBoxLayout

from ui.theme import nav_icon
from ui.widgets.ds._common import px, resolve, sans_font
from ui.widgets.ds.nav_rail_button import DSNavRailButton

NAV_ITEMS = [
    ("home", "Home", "home"),
    ("setup", "Setup", "setup"),
    ("protocols", "Treatment", "protocols"),
    ("support", "Support", "support"),
    ("device", "Device", "device"),
]


def _icon_factory(name):
    return lambda color, size: nav_icon(name, color, size)


class NavRail(QFrame):
    navigate = pyqtSignal(str)
    video_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavRail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        rail = px("--rail-width")
        self.setFixedWidth(rail)
        self.setStyleSheet(
            f"#NavRail {{ background: {resolve('--surface-chrome')}; border: none;"
            f" border-right: 1px solid {resolve('--surface-chrome-divider')}; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        for key, label, icon_name in NAV_ITEMS:
            btn = DSNavRailButton(label, icon_factory=_icon_factory(icon_name), fill_height=True)
            btn.clicked.connect(lambda _checked, k=key: self.navigate.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            lay.addWidget(btn)

        self._video = self._make_video_button(rail)
        lay.insertWidget(3, self._video)

        self._buttons["home"].setChecked(True)

    def _make_video_button(self, rail):
        btn = QToolButton(self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setText("Video")
        btn.setToolTip("Demo video")
        btn.setFont(sans_font(size=19, weight=700))
        btn.setIcon(nav_icon("play", resolve("--text-chrome"), 28))
        btn.setIconSize(QSize(28, 28))
        btn.setFixedWidth(rail)
        btn.setMinimumHeight(80)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        btn.setStyleSheet(
            f"QToolButton {{ color: {resolve('--text-chrome')}; background: transparent;"
            f" border: none; padding: 18px 0; }}"
            f" QToolButton:hover {{ background: {resolve('--surface-chrome-hover')}; }}"
            f" QToolButton:pressed {{ background: {resolve('--surface-chrome-active')}; }}"
        )
        btn.clicked.connect(self.video_requested)
        return btn

    def set_active(self, key):
        """Sync the checked nav item to the current page (no signal emitted).

        A key with no rail item (e.g. "profile") clears the highlight."""
        btn = self._buttons.get(key)
        if btn is None:
            self._group.setExclusive(False)
            for b in self._buttons.values():
                b.setChecked(False)
            self._group.setExclusive(True)
        elif not btn.isChecked():
            btn.setChecked(True)

    def set_page_enabled(self, key: str, enabled: bool) -> None:
        """Reflect role restrictions without changing the selected page."""
        self._buttons[key].setEnabled(enabled)
