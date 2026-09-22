"""Operator account and current-session information.

A tinted initials avatar with the operator's name and role, then account and
session facts as key/value rows. Actions follow the action grammar: Restart
app is a plain outline; Exit app and Log out are destructive outlines, so no
button here looks like the primary call to action.
"""

from datetime import datetime
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton, DSCard, DSKeyValueList
from ui.widgets.ds._common import resolve, sans_font

AVATAR_PX = 64


def _initials(name: Optional[str]) -> str:
    parts = [part for part in (name or "").replace(".", " ").split() if part[:1].isalpha()]
    if not parts:
        return "?"
    letters = parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")
    return letters.upper()


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

        head = QHBoxLayout()
        head.setSpacing(20)
        self._avatar = QLabel("?")
        self._avatar.setFixedSize(AVATAR_PX, AVATAR_PX)
        self._avatar.setAlignment(Qt.AlignCenter)
        self._avatar.setFont(sans_font(size="--text-lg", weight=600))
        self._avatar.setStyleSheet(
            f"background: {resolve('--blue-100')}; color: {resolve('--blue-700')};"
            f" border-radius: {AVATAR_PX // 2}px;"
        )
        head.addWidget(self._avatar)
        text = QVBoxLayout()
        text.setSpacing(2)
        self._name = self._label("", large=True)
        self._name.setStyleSheet(f"color: {resolve('--text-strong')};")
        self._title = self._label("")
        self._title.setStyleSheet(f"color: {resolve('--text-muted')};")
        text.addWidget(self._name)
        text.addWidget(self._title)
        head.addLayout(text, 1)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(20)
        account = DSCard("Account details")
        self.account_rows = DSKeyValueList()
        self._email = self.account_rows.add_row("email", "Email", "Not provided")
        self._access = self.account_rows.add_row("access", "Access", "Signed out")
        self._clinic = self.account_rows.add_row("clinic", "Cloud clinic", "No staff session")
        account.add_widget(self.account_rows)
        account.body_layout.addStretch(1)
        grid.addWidget(account, 0, 0)
        session = DSCard("Current session")
        self.session_rows = DSKeyValueList()
        self._login = self.session_rows.add_row("login", "Logged in", "—")
        self._duration = self.session_rows.add_row("duration", "Session duration", "—")
        self._automatic = self.session_rows.add_row("automatic", "Automatic logout", "Never")
        session.add_widget(self.session_rows)
        session.body_layout.addStretch(1)
        grid.addWidget(session, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addLayout(grid)
        note = self._label(
            "Your operator login identifies who is using this device. Technician service and "
            "cloud staff access require their own sign-in."
        )
        note.setStyleSheet(f"color: {resolve('--text-muted')};")
        root.addWidget(note)
        root.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self._restart = DSButton("Restart app", variant="secondary")
        self._exit = DSButton("Exit app", variant="destructive")
        self._logout = DSButton("Log out", variant="destructive")
        for button, signal in ((self._restart, self.restart_requested),
                               (self._exit, self.exit_requested),
                               (self._logout, self.logout_requested)):
            button.setMinimumWidth(200)
            button.clicked.connect(signal)
        actions.addWidget(self._restart)
        actions.addStretch(1)
        actions.addWidget(self._exit)
        actions.addWidget(self._logout)
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
                                weight=600 if large else 400))
        return label

    def set_user(self, username: Optional[str], title: str = "Clinician",
                 is_admin: bool = False) -> None:
        if username != self._username:
            self._started = time.monotonic() if username else None
            self._login_time = datetime.now().astimezone() if username else None
            self._email.setText("Not provided")
            self._clinic.setText("No staff session")
        self._username = username
        self._avatar.setText(_initials(username))
        self._name.setText(username or "Signed out")
        self._title.setText(title if username else "Log in to view your session")
        self._access.setText("Administrator" if is_admin else
                             "Operator" if username else "Signed out")
        stamp = self._login_time.strftime("%b %d, %Y · %I:%M %p") if self._login_time else "—"
        self._login.setText(stamp)
        self._update_duration()

    def set_session_details(self, email: str = "", logout_minutes: int = 0,
                            clinic: str = "") -> None:
        self._email.setText(email or "Not provided")
        self._automatic.setText(
            f"After {logout_minutes} minutes idle" if logout_minutes else "Never")
        self._clinic.setText(clinic or "No staff session")

    def _update_duration(self) -> None:
        if self._started is None:
            self._duration.setText("—")
            return
        elapsed = max(0, int(time.monotonic() - self._started))
        self._duration.setText(f"{elapsed // 3600}h {(elapsed // 60) % 60}m")
