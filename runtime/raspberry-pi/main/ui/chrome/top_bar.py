"""TopBar — persistent 84px slate header with device status and clinician identity.

The knee mark and the "KneeSpa DRx" wordmark both navigate Home. The centre
shows the controller-derived device status as a pill with a dot (green Ready,
blue Preparing/Active, amber Stopping/Resetting, red Recovery/Offline). The
right side shows a login avatar when logged out, or the clinician identity +
avatar (cyan ring) when logged in.

Signals (wired to the controller in Phase 3):
    home_clicked      — logo / wordmark tapped
    login_requested   — avatar tapped while logged out
    profile_requested — avatar tapped while logged in (opens the Profile screen)
"""

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.presentation import device_status_tone
from ui.widgets.common import ClickableLabel, image_label
from ui.widgets.ds import DSBadge
from ui.widgets.ds._common import image_path, resolve, sans_font
from ui.widgets.press_feedback import install_press_feedback

BAR_HEIGHT = 84
AVATAR_PX = 54


class TopBar(QFrame):
    home_clicked = pyqtSignal()
    login_requested = pyqtSignal()
    profile_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self.setStyleSheet(
            f"#TopBar {{ background: {resolve('--surface-chrome')};"
            f" border: none; border-bottom: 1px solid {resolve('--surface-chrome-divider')}; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(16)

        logo = image_label(image_path("logos", "knee.png"), 56, 56, clickable=True)
        logo.setToolTip("Home")
        logo.setAccessibleName("Home")
        logo.clicked.connect(self.home_clicked)
        lay.addWidget(logo)

        white = resolve("--text-on-dark")
        self._wordmark = ClickableLabel()
        self._wordmark.setMinimumHeight(48)
        self._wordmark.setToolTip("Home")
        self._wordmark.setTextFormat(Qt.RichText)
        self._wordmark.setFont(sans_font(size="--text-xl", weight=600, tracking=-0.01))
        self._wordmark.setText(
            f"<span style='color:{white}'>Knee</span>"
            f"<span style='color:{resolve('--brand-cyan')}'>Spa</span>"
            f"<span style='color:{white}'> DRx</span>"
        )
        self._wordmark.setStyleSheet("background: transparent;")
        self._wordmark.clicked.connect(self.home_clicked)
        lay.addWidget(self._wordmark)
        self._press_feedback = install_press_feedback(logo, self._wordmark)

        lay.addStretch(1)

        status = QWidget()
        status_row = QHBoxLayout(status)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(10)
        caption = QLabel("Device")
        caption.setFont(sans_font(size="--text-sm", weight=600))
        caption.setStyleSheet(
            f"color: {resolve('--text-on-dark-muted')}; background: transparent;")
        status_row.addWidget(caption)
        self._device_status = DSBadge("Connecting", tone="neutral", dot=True, size="md")
        self._device_status.setAccessibleName("Device status: Connecting")
        status_row.addWidget(self._device_status)
        lay.addWidget(status)
        lay.addStretch(1)

        # Identity block (name + role), shown only when logged in.
        self._identity = QWidget()
        idlay = QVBoxLayout(self._identity)
        idlay.setContentsMargins(0, 0, 0, 0)
        idlay.setSpacing(0)
        idlay.setAlignment(Qt.AlignVCenter)
        self._name = QLabel()
        self._name.setTextFormat(Qt.PlainText)
        self._name.setMaximumWidth(280)
        self._name.setFont(sans_font(size="--text-base", weight=600))
        self._name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._name.setStyleSheet(f"color: {white}; background: transparent;")
        self._role = QLabel("Clinician")
        self._role.setFont(sans_font(size="--text-xs"))
        self._role.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._role.setStyleSheet(
            f"color: {resolve('--text-on-dark-muted')}; background: transparent;")
        idlay.addWidget(self._name)
        idlay.addWidget(self._role)
        self._identity.setVisible(False)
        lay.addWidget(self._identity)

        # Avatar — login launcher (logged out) / profile launcher (logged in).
        self._avatar = QPushButton()
        self._avatar.setAccessibleName("Clinician login or profile")
        self._avatar.setCursor(Qt.PointingHandCursor)
        self._avatar.setFocusPolicy(Qt.TabFocus)
        self._avatar.setFixedSize(AVATAR_PX, AVATAR_PX)
        self._avatar.setIconSize(QSize(30, 30))
        pix = QPixmap(image_path("buttons", "user-profile.png"))
        if not pix.isNull():
            self._avatar.setIcon(QIcon(pix))
        self._avatar.clicked.connect(self._on_avatar)
        lay.addWidget(self._avatar)

        self._username = None
        self._style_avatar(False)

    def _style_avatar(self, logged_in: bool) -> None:
        """Plain white disc when signed out; a cyan ring marks an active session."""
        ring = resolve("--brand-cyan") if logged_in else resolve("--white")
        self._avatar.setStyleSheet(
            f"QPushButton {{ border-radius: {AVATAR_PX // 2}px; padding: 0; min-height: 0;"
            f" background: {resolve('--white')}; border: 3px solid {ring}; }}"
            f" QPushButton:pressed {{ background: {resolve('--blue-100')}; }}"
            f" QPushButton[keyboardFocus=\"true\"]:focus {{"
            f" border: 3px solid {resolve('--brand-cyan')}; }}"
        )

    def set_device_status(self, text: str) -> None:
        """Present controller-derived status independently of the signed-in user."""
        self._device_status.set_text(text)
        self._device_status.set_tone(device_status_tone(text))
        self._device_status.setAccessibleName("Device status: " + text)

    def device_status(self) -> str:
        return self._device_status.text()

    def _on_avatar(self):
        if self._username:
            self.profile_requested.emit()
        else:
            self.login_requested.emit()

    def set_user(self, username, title="Clinician"):
        """Show the identity block + name when logged in, hide it when out."""
        self._username = username
        if username:
            self._name.setText(self._name.fontMetrics().elidedText(username, Qt.ElideRight, 280))
            self._role.setText(title)
            self._identity.setVisible(True)
            self._avatar.setToolTip(f"{username} — tap to view profile")
        else:
            self._identity.setVisible(False)
            self._avatar.setToolTip("Login")
        self._style_avatar(bool(username))
