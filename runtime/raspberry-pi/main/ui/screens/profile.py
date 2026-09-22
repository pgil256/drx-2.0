"""Operator account and current-session information."""

from datetime import datetime
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.common import image_label
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import image_path, resolve, sans_font


class ProfileScreen(QWidget):
    logout_requested = pyqtSignal()
    exit_requested = pyqtSignal()
    restart_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._username = None
        self._started = None
        self._login_time = None
        self.setObjectName("ProfileScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#ProfileScreen {{ background: {resolve('--surface-page')}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(20)
        identity = DSCard("Your profile")
        head = QWidget()
        row = QHBoxLayout(head)
        row.setSpacing(24)
        row.addWidget(image_label(image_path("buttons", "user-profile.png"), 88, 88))
        text = QVBoxLayout()
        self._name = self._label("", large=True)
        self._title = self._label("")
        text.addWidget(self._name)
        text.addWidget(self._title)
        row.addLayout(text, 1)
        identity.add_widget(head)
        root.addWidget(identity)
        grid = QGridLayout()
        grid.setSpacing(20)
        account = DSCard("Account details")
        self._email = self._label("Email: Not provided")
        self._access = self._label("Access: Signed out")
        self._clinic = self._label("Cloud clinic: No staff session")
        for label in (self._email, self._access, self._clinic):
            account.add_widget(label)
        grid.addWidget(account, 0, 0)
        session = DSCard("Current session")
        self._login = self._label("Logged in: —")
        self._duration = self._label("Session duration: —")
        self._automatic = self._label("Automatic logout: Never")
        for label in (self._login, self._duration, self._automatic):
            session.add_widget(label)
        grid.addWidget(session, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        root.addWidget(self._label(
            "Your operator login identifies who is using this device. Technician service and "
            "cloud staff access require their own sign-in."
        ))
        root.addStretch(1)
        actions = QHBoxLayout()
        self._restart = DSButton("Restart App", variant="dark", full_width=True)
        self._exit = DSButton("Exit App", variant="secondary", full_width=True)
        self._logout = DSButton("Log Out", variant="danger", full_width=True)
        for button, signal in ((self._restart, self.restart_requested),
                               (self._exit, self.exit_requested),
                               (self._logout, self.logout_requested)):
            button.clicked.connect(signal)
            actions.addWidget(button)
        root.addLayout(actions)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_duration)
        self._timer.start()

    @staticmethod
    def _label(text: str, large: bool = False) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setFont(sans_font(size="--text-xl" if large else "--text-base",
                                weight=700 if large else 400))
        return label

    def set_user(self, username: Optional[str], title: str = "Clinician",
                 is_admin: bool = False) -> None:
        if username != self._username:
            self._started = time.monotonic() if username else None
            self._login_time = datetime.now().astimezone() if username else None
            self._email.setText("Email: Not provided")
            self._clinic.setText("Cloud clinic: No staff session")
        self._username = username
        self._name.setText(username or "Signed out")
        self._title.setText(title if username else "Log in to view your session")
        self._access.setText("Access: " + ("Administrator" if is_admin else
                                          "Operator" if username else "Signed out"))
        stamp = self._login_time.strftime("%b %d, %Y · %I:%M %p") if self._login_time else "—"
        self._login.setText("Logged in: " + stamp)
        self._update_duration()

    def set_session_details(self, email: str = "", logout_minutes: int = 0,
                            clinic: str = "") -> None:
        self._email.setText("Email: " + (email or "Not provided"))
        self._automatic.setText("Automatic logout: " + (
            f"After {logout_minutes} minutes idle" if logout_minutes else "Never"))
        self._clinic.setText("Cloud clinic: " + (clinic or "No staff session"))

    def _update_duration(self) -> None:
        if self._started is None:
            self._duration.setText("Session duration: —")
            return
        elapsed = max(0, int(time.monotonic() - self._started))
        self._duration.setText(f"Session duration: {elapsed // 3600}h {(elapsed // 60) % 60}m")
