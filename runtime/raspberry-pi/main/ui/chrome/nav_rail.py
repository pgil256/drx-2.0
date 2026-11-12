"""NavRail — persistent 108px white left rail with a hairline edge.

The first item is the session button, as in the previous app: "Login" while
nobody is signed in, "Logout" once someone is. Below it sit four exclusive nav
items (Setup · Treatment · Support · Device), with the Video launcher above
Support and Device. Home has no rail item; the top-bar logo goes there. The
active item paints action blue on a soft blue fill with a 4px left edge, the
rail counterpart of the dashboard's selected nav pill. The rail only reports the
intent; ``app_shell`` applies login gating and the actual page switch.

Signals:
    navigate(str)     — a nav item ('setup'|'protocols'|'support'|'device')
    login_requested   — the session button, signed out
    logout_requested  — the session button, signed in
    video_requested   — the Video launcher
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import QButtonGroup, QFrame, QSizePolicy, QToolButton, QVBoxLayout

from ui.theme import nav_icon
from ui.widgets.ds._common import px, resolve, sans_font
from ui.widgets.ds.nav_rail_button import DSNavRailButton

NAV_ITEMS = [
    ("setup", "Setup", "setup"),
    ("protocols", "Treatment", "protocols"),
    ("support", "Support", "support"),
    ("device", "Device", "device"),
]


def _icon_factory(name):
    return lambda color, size: nav_icon(name, color, size)


class NavRail(QFrame):
    navigate = pyqtSignal(str)
    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()
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

        # An action, not a page: it never takes the active highlight.
        self._signed_in = False
        self._session = DSNavRailButton(
            "Login", icon_factory=self._session_icon, fill_height=True)
        self._session.setCheckable(False)
        self._session.clicked.connect(self._on_session)
        lay.addWidget(self._session)

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

    def _session_icon(self, color, size):
        return nav_icon("logout" if self._signed_in else "login", color, size)

    def _on_session(self):
        (self.logout_requested if self._signed_in else self.login_requested).emit()

    def set_signed_in(self, signed_in: bool) -> None:
        """Turn the session button into Logout while someone is signed in."""
        self._signed_in = bool(signed_in)
        self._session.setText("Logout" if self._signed_in else "Login")
        self._session._render()

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

        A key with no rail item ("home", "profile") clears the highlight."""
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
