"""AppShell — composition root for the modern KneeSpa DRx view layer.

Assembles the chrome (TopBar + NavRail) around a QStackedWidget of the five
screens, plus the Login / Video modal overlays. Owns view-level concerns only:
page switching, login gating (Setup/Protocols require a user), and modal
show/hide. It exposes every screen + modal as attributes and surfaces auth as
signals so the Phase-3 controller can wire the Arduino / Protocols backend and
the real ``SecureAuthHelper`` without this shell knowing any of it.

Signals:
    login_attempted(str)  — a PIN was entered in the login modal
    logout_requested      — the top-bar avatar was tapped while logged in
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ui.chrome import NavRail, TopBar
from ui.modals import LoginModal, VideoModal
from ui.screens import (
    HelpScreen,
    HomeScreen,
    SetupScreen,
    SupportScreen,
    TreatmentScreen,
)

# Page key -> stack index.
PAGES = ["home", "setup", "protocols", "help", "support"]
GATED = {"setup", "protocols"}  # require a logged-in user


class AppShell(QWidget):
    login_attempted = pyqtSignal(str)
    logout_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self._username = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.top_bar = TopBar()
        root.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.nav_rail = NavRail()
        body.addWidget(self.nav_rail)

        self.stack = QStackedWidget()
        self.home = HomeScreen()
        self.setup = SetupScreen()
        self.treatment = TreatmentScreen()
        self.help = HelpScreen()
        self.support = SupportScreen()
        for screen in (self.home, self.setup, self.treatment, self.help, self.support):
            self.stack.addWidget(screen)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Modal overlays (children, not laid out — sized to the shell on show).
        self.login_modal = LoginModal(self)
        self.video_modal = VideoModal(self)

        self._wire()
        self._go("home")
        self.set_user(None)

    # ----- wiring -----
    def _wire(self):
        self.top_bar.home_clicked.connect(lambda: self._go("home"))
        self.top_bar.login_requested.connect(self.show_login)
        self.top_bar.logout_requested.connect(self.logout_requested)

        self.nav_rail.navigate.connect(self._on_nav)
        self.nav_rail.video_requested.connect(self.show_video)

        self.home.login_requested.connect(self.show_login)

        self.login_modal.submitted.connect(self.login_attempted)

    def _on_nav(self, key):
        if key in GATED and not self._username:
            # Gated: bounce to login, keep the rail on the current page.
            self.nav_rail.set_active(self._current)
            self.show_login()
            return
        self._go(key)

    def _go(self, key):
        if key not in PAGES:
            key = "home"
        self._current = key
        self.stack.setCurrentIndex(PAGES.index(key))
        self.nav_rail.set_active(key)

    # ----- public API (Phase 3 controller) -----
    def navigate(self, key):
        self._go(key)

    def set_user(self, username):
        """Set the active clinician (or None when logged out) and refresh gating."""
        self._username = username
        self.top_bar.set_user(username)
        self.home.set_logged_in(bool(username))

    def show_login(self):
        self._go("home")
        self.login_modal.open_over(self)

    def show_video(self):
        self.video_modal.open_over(self)

    def login_succeeded(self, username, goto="protocols"):
        """Controller callback: a PIN verified — dismiss the modal and proceed."""
        self.login_modal.close_overlay()
        self.set_user(username)
        self._go(goto)

    def login_failed(self, message="Invalid PIN. Please try again."):
        self.login_modal.show_error(message)

    def logout(self):
        self.set_user(None)
        self._go("home")

    # ----- keep modals covering the shell on resize -----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.login_modal.update_geometry()
        self.video_modal.update_geometry()
