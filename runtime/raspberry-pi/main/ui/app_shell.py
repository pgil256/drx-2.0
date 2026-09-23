"""AppShell — composition root for the modern KneeSpa DRx view layer.

Assembles the chrome (TopBar + NavRail) around a QStackedWidget of six
screens, plus the Login / Video modal overlays. Owns view-level concerns only:
page switching, login gating (Setup/Treatment/Device/Profile require a user), and modal
show/hide. It exposes every screen + modal as attributes and surfaces auth as
signals so the Phase-3 controller can wire the Arduino / Protocols backend and
the real ``SecureAuthHelper`` without this shell knowing any of it.

The video player stays available during a treatment: it mirrors the Treatment
monitor and its STOP routes to the same ``treatment.estop_requested`` signal.

Signals:
    login_attempted(str)        — a PIN was entered in the login modal
    logout_requested            — Log Out was tapped on the Profile screen
    exit_requested              — Exit App was tapped on the Profile screen
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from ui.chrome import NavRail, TopBar
from ui.modals import LoginModal, PatientModal, VideoModal
from ui.screens import (
    DeviceScreen,
    HomeScreen,
    ProfileScreen,
    SetupScreen,
    SupportScreen,
    TreatmentScreen,
)

# Page key -> stack index. "profile" has no rail item; the top-bar avatar
# navigates there while logged in.
PAGES = ["home", "setup", "protocols", "support", "device", "profile"]
GATED = {"setup", "protocols", "device", "profile"}  # require a logged-in user


class AppShell(QWidget):
    login_attempted = pyqtSignal(str)
    logout_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    user_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self._username = None
        self._nav_confirmation = None  # optional callable: True -> allow user nav
        self._overlay_guard = None  # optional callable: True -> block overlays
        self._video_guard = None  # optional callable: True -> block the video player
        self._login_destination = None
        self._access_role = None

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
        self.support = SupportScreen()
        self.device = DeviceScreen()
        self.profile = ProfileScreen()
        for screen in (self.home, self.setup, self.treatment, self.support,
                       self.device, self.profile):
            self.stack.addWidget(screen)
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # Modal overlays (children, not laid out — sized to the shell on show).
        self.login_modal = LoginModal(self)
        self.patient_modal = PatientModal(self)
        self.video_modal = VideoModal(self)

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

        self.nav_rail.navigate.connect(self._on_nav)
        self.nav_rail.video_requested.connect(self.show_video)

        self.home.login_requested.connect(self.show_login)
        self.home.navigate_requested.connect(self._on_nav)
        self.home.video_requested.connect(self.show_video)
        # Home's status card mirrors what the other screens already receive.
        self.treatment.cloud_status_changed.connect(self.home.set_cloud_status)
        self.treatment.outcome_recorded.connect(self.home.set_last_treatment)
        self.device.details_changed.connect(self.home.set_details)
        # The video player shows live treatment status and a working STOP.
        self.treatment.monitor_changed.connect(self._sync_video_treatment)
        self.video_modal.stop_requested.connect(self.treatment.estop_requested)
        self.video_modal.treatment_requested.connect(self._video_to_treatment)
        self._sync_video_treatment()

        self.login_modal.submitted.connect(self.login_attempted)

    def _on_nav(self, key):
        if self._access_role == "patient" and key in ("setup", "device"):
            return
        if self._access_role == "service_technician" and key == "protocols":
            return
        if not self._navigation_confirmed(key):
            self.nav_rail.set_active(self._current)
            return
        if key in GATED and not self._username:
            # Gated: bounce to login, keep the rail on the current page.
            self.nav_rail.set_active(self._current)
            self.show_login(key)
            return
        self._go(key)

    def _go(self, key):
        if self._access_role == "patient" and key in ("setup", "device"):
            key = "protocols"
        if self._access_role == "service_technician" and key == "protocols":
            key = "device"
        if key == "help":
            key = "support"
        if key not in PAGES:
            key = "home"
        self._current = key
        self.stack.setCurrentIndex(PAGES.index(key))
        self.nav_rail.set_active(key)

    # ----- public API (Phase 3 controller) -----
    def navigate(self, key):
        self._go(key)

    def set_nav_confirmation(self, confirmation):
        """Register a callable that confirms user-driven page navigation.

        The callable receives the current and destination page keys and returns
        ``True`` to continue. Programmatic ``navigate()`` is unaffected.
        """
        self._nav_confirmation = confirmation

    def set_overlay_guard(self, guard):
        """Register a callable returning True to block nonessential overlays."""
        self._overlay_guard = guard

    def set_video_guard(self, guard):
        """Register a callable returning True to block the video player.

        Without one, the general overlay guard applies to video as well."""
        self._video_guard = guard

    def set_nav_guard(self, guard):
        """Backward-compatible alias for the former overlay/navigation guard."""
        self.set_overlay_guard(guard)

    def _navigation_confirmed(self, destination: str) -> bool:
        """Return whether a user-requested page change may continue."""
        if destination == self._current or self._nav_confirmation is None:
            return True
        return bool(self._nav_confirmation(self._current, destination))

    def set_device_status(self, label: str, detail: str, can_start: bool = False) -> None:
        """Fan out one controller-derived status without mixing in cloud state."""
        self.top_bar.set_device_status(label)
        self.home.set_device_status(label, detail)
        self.treatment.set_device_status(label, detail, can_start)

    def set_user(self, username, title="Clinician", is_admin=False):
        """Set the active clinician (or None when logged out) and refresh gating."""
        if username != self._username:
            self.support.set_contact(username or "")
        self._username = username
        if not username:
            self.set_access_role(None)
        self.top_bar.set_user(username, title)
        self.profile.set_user(username, title, is_admin)
        self.home.set_logged_in(bool(username), username or "")
        self.device.hardware_button.setEnabled(bool(username))
        self.device.calibration_button.setEnabled(bool(username))
        self.device.lock_service()
        self.user_changed.emit()

    def set_access_role(self, role):
        """Patient accounts cannot open staff setup or change treatment plans."""
        self._access_role = role
        for key in ("setup", "device"):
            self.nav_rail.set_page_enabled(key, role != "patient")
        self.nav_rail.set_page_enabled("protocols", role != "service_technician")
        self.treatment.set_access_role(role)

    def close_nonessential_overlays(self, keep_video: bool = False) -> None:
        """Clear already-open overlays when treatment takes control of the screen.

        ``keep_video`` leaves the video player open: it carries its own STOP."""
        modals = [self.login_modal, self.patient_modal]
        if not keep_video:
            modals.append(self.video_modal)
        for modal in modals:
            if modal.isVisible():
                modal.close_overlay()

    def close_video(self) -> None:
        if self.video_modal.isVisible():
            self.video_modal.close_overlay()

    def show_login(self, destination=None, phone=False):
        """Open sign-in on the staff PIN keypad (``phone=True``: QR approval)."""
        if self._overlay_guard is not None and self._overlay_guard():
            return
        if not self._navigation_confirmed("home"):
            return
        self._login_destination = destination if destination in GATED else "protocols"
        self._go("home")
        self.login_modal.open_over(self, phone=phone)

    def show_video(self):
        guard = self._video_guard or self._overlay_guard
        if guard is not None and guard():
            return
        self._sync_video_treatment()
        self.video_modal.open_over(self)

    def _sync_video_treatment(self) -> None:
        self.video_modal.set_treatment_status(self.treatment.live_summary())

    def _video_to_treatment(self) -> None:
        """Leave the video for the Treatment monitor."""
        self.video_modal.close_overlay()
        self._on_nav("protocols")

    def login_succeeded(self, username, goto=None, title="Clinician",
                        is_admin=False):
        """Controller callback: a PIN verified — dismiss the modal and proceed."""
        self.login_modal.close_overlay()
        self.set_user(username, title, is_admin)
        destination = goto or self._login_destination or "protocols"
        self._login_destination = None
        self._go(destination)

    def login_failed(self, message="Invalid PIN. Please try again."):
        self.login_modal.show_error(message)

    def logout(self):
        self.patient_modal.close_overlay()
        self.set_user(None)
        self._go("home")

    # ----- keep modals covering the shell on resize -----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.login_modal.update_geometry()
        self.patient_modal.update_geometry()
        self.video_modal.update_geometry()
