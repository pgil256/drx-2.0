"""AppShell — composition root for the modern KneeSpa DRx view layer.

Assembles the chrome (TopBar + NavRail) around a QStackedWidget of the five
screens, plus the Login / Video modal overlays. Owns view-level concerns only:
page switching, login gating (Setup/Protocols require a user), and modal
show/hide. It exposes every screen + modal as attributes and surfaces auth as
signals so the Phase-3 controller can wire the Arduino / Protocols backend and
the real ``SecureAuthHelper`` without this shell knowing any of it.

Signals:
    login_attempted(str)        — a PIN was entered in the login modal
    logout_requested            — Log Out was tapped on the Profile screen
    exit_requested              — Exit App was tapped on the Profile screen
    add_pin_submitted(str, str) — (username, pin) confirmed in the Add PIN modal
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ui.chrome import NavRail, TopBar
from ui.modals import AddPinModal, LoginModal, VideoModal
from ui.screens import (
    HelpScreen,
    HomeScreen,
    ProfileScreen,
    SetupScreen,
    SupportScreen,
    TreatmentScreen,
)

# Page key -> stack index. "profile" has no rail item; the top-bar avatar
# navigates there while logged in.
PAGES = ["home", "setup", "protocols", "help", "support", "profile"]
GATED = {"setup", "protocols", "profile"}  # require a logged-in user


class AppShell(QWidget):
    login_attempted = pyqtSignal(str)
    logout_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    add_pin_submitted = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self._username = None
        self._nav_guard = None  # optional callable: True -> block user nav

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
        self.profile = ProfileScreen()
        for screen in (self.home, self.setup, self.treatment, self.help,
                       self.support, self.profile):
            self.stack.addWidget(screen)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Modal overlays (children, not laid out — sized to the shell on show).
        self.login_modal = LoginModal(self)
        self.video_modal = VideoModal(self)
        self.add_pin_modal = AddPinModal(self)

        self._wire()
        self._go("home")
        self.set_user(None)

    # ----- wiring -----
    def _wire(self):
        self.top_bar.home_clicked.connect(lambda: self._on_nav("home"))
        self.top_bar.login_requested.connect(self.show_login)
        self.top_bar.profile_requested.connect(lambda: self._on_nav("profile"))
        self.profile.logout_requested.connect(self.logout_requested)
        self.profile.exit_requested.connect(self.exit_requested)
        self.profile.add_pin_requested.connect(self.show_add_pin)
        self.add_pin_modal.submitted.connect(self.add_pin_submitted)

        self.nav_rail.navigate.connect(self._on_nav)
        self.nav_rail.video_requested.connect(self.show_video)

        self.home.login_requested.connect(self.show_login)

        self.login_modal.submitted.connect(self.login_attempted)

    def _on_nav(self, key):
        if self._nav_guard is not None and self._nav_guard():
            # Blocked (e.g., a treatment is running); the guard owns the
            # operator feedback. Keep the rail on the current page.
            self.nav_rail.set_active(self._current)
            return
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

    def set_nav_guard(self, guard):
        """Register a callable returning True to BLOCK user-driven navigation
        (rail taps + top-bar home) — e.g., while a treatment protocol is
        active. Programmatic navigate() is unaffected."""
        self._nav_guard = guard

    def set_user(self, username, title="Clinician", is_admin=False):
        """Set the active clinician (or None when logged out) and refresh gating."""
        self._username = username
        self.top_bar.set_user(username, title)
        self.profile.set_user(username, title, is_admin)
        self.home.set_logged_in(bool(username))

    def show_login(self):
        self._go("home")
        self.login_modal.open_over(self)

    def show_video(self):
        self.video_modal.open_over(self)

    def show_add_pin(self):
        self.add_pin_modal.open_over(self)

    def login_succeeded(self, username, goto="protocols", title="Clinician",
                        is_admin=False):
        """Controller callback: a PIN verified — dismiss the modal and proceed."""
        self.login_modal.close_overlay()
        self.set_user(username, title, is_admin)
        self._go(goto)

    def login_failed(self, message="Invalid PIN. Please try again."):
        self.login_modal.show_error(message)

    def add_pin_succeeded(self):
        """Controller callback: the new PIN was persisted — dismiss the modal."""
        self.add_pin_modal.close_overlay()

    def add_pin_failed(self, message):
        self.add_pin_modal.show_error(message)

    def logout(self):
        self.set_user(None)
        self._go("home")

    # ----- keep modals covering the shell on resize -----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.login_modal.update_geometry()
        self.video_modal.update_geometry()
        self.add_pin_modal.update_geometry()
