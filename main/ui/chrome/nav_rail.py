"""NavRail — persistent 120px dark left rail.

Mirrors `NavRail` in `bundle.jsx` (dark chrome): five exclusive nav items
(Home · Setup · Protocols · Help · Support) over a separated Video launcher.
Active item paints cyan with a 4px cyan left border. The rail only reports the
intent; ``app_shell`` applies login gating and the actual page switch.

Signals:
    navigate(str)     — a nav item ('home'|'setup'|'protocols'|'help'|'support')
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
    ("protocols", "Protocols", "protocols"),
    ("help", "Help", "help"),
    ("support", "Support", "support"),
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
            f"#NavRail {{ background: {resolve('--ink-900')}; border-right: 1px solid #000; }}"
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
        lay.addWidget(self._video)

        self._buttons["home"].setChecked(True)

    def _make_video_button(self, rail):
        btn = QToolButton(self)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setText("Video")
        btn.setToolTip("Demo video")
        btn.setFont(sans_font(size="--text-md", weight=700))
        btn.setIcon(nav_icon("play", "#ffffff", 28))
        btn.setIconSize(QSize(28, 28))
        btn.setFixedWidth(rail)
        btn.setMinimumHeight(80)
        btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        btn.setStyleSheet(
            "QToolButton { color: #ffffff; background: %s; border: none;"
            " border-top: 1px solid #000; }"
            " QToolButton:hover { background: #2a2a2a; }" % resolve("--ink-900")
        )
        btn.clicked.connect(self.video_requested)
        return btn

    def set_active(self, key):
        """Sync the checked nav item to the current page (no signal emitted)."""
        btn = self._buttons.get(key)
        if btn is not None and not btn.isChecked():
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
