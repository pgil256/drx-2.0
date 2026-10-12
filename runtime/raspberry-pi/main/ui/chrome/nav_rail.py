"""NavRail — persistent 108px slate left rail.

Pages (Home · Setup · Treatment · Support) sit top-aligned as fixed 88px items;
a hairline separates the Video launcher, which opens a modal rather than a
page; Device is pinned to the bottom. The active item paints cyan with a 4px
cyan left edge. The rail only reports the intent; ``app_shell`` applies login
gating and the actual page switch.

Signals:
    navigate(str)     — a nav item ('home'|'setup'|'protocols'|'support'|'device')
    video_requested   — the Video launcher
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QFrame, QVBoxLayout

from ui.theme import nav_icon
from ui.widgets.ds._common import px, resolve
from ui.widgets.ds.nav_rail_button import DSNavRailButton

NAV_ITEMS = [
    ("home", "Home", "home"),
    ("setup", "Setup", "setup"),
    ("protocols", "Treatment", "protocols"),
    ("support", "Support", "support"),
    ("device", "Device", "device"),
]
PINNED_BOTTOM = {"device"}


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
            f"#NavRail {{ background: {resolve('--surface-chrome')}; border: none; }}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        pinned = []
        for key, label, icon_name in NAV_ITEMS:
            btn = DSNavRailButton(label, icon_factory=_icon_factory(icon_name))
            btn.clicked.connect(lambda _checked, k=key: self.navigate.emit(k))
            self._group.addButton(btn)
            self._buttons[key] = btn
            if key in PINNED_BOTTOM:
                pinned.append(btn)
            else:
                lay.addWidget(btn)

        # Video is a launcher, not a page: a hairline sets it apart.
        lay.addSpacing(8)
        lay.addWidget(self._hairline(rail))
        lay.addSpacing(8)
        self._video = DSNavRailButton(
            "Video", icon_factory=_icon_factory("play"), checkable=False)
        self._video.setToolTip("Demo videos")
        self._video.clicked.connect(self.video_requested)
        lay.addWidget(self._video)

        lay.addStretch(1)
        for btn in pinned:
            lay.addWidget(btn)

        self._buttons["home"].setChecked(True)

    @staticmethod
    def _hairline(rail):
        line = QFrame()
        line.setFixedSize(rail - 32, 1)
        line.setStyleSheet(f"background: {resolve('--surface-chrome-divider')}; border: none;")
        wrapper = QFrame()
        wrapper.setFixedHeight(1)
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(16, 0, 16, 0)
        box.addWidget(line)
        return wrapper

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
