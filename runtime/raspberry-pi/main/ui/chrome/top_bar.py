"""TopBar — persistent 84px header with device status and clinician identity.

Mirrors `TopBar` in `bundle.jsx` (baked to dark chrome): the knee mark and the
"KneeSpa DRx" wordmark both navigate Home; the right side shows a login avatar
when logged out, or the clinician identity + avatar when logged in.

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

from ui.widgets.common import ClickableLabel, image_label
from ui.widgets.ds._common import image_path, mono_font, resolve, sans_font

BAR_HEIGHT = 84


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
            f"#TopBar {{ background: {resolve('--surface-chrome')}; border: none; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(16)

        logo = image_label(image_path("logos", "knee.png"), 60, 60, clickable=True)
        logo.setToolTip("Home")
        logo.clicked.connect(self.home_clicked)
        lay.addWidget(logo)

        self._wordmark = ClickableLabel()
        self._wordmark.setMinimumHeight(48)
        self._wordmark.setToolTip("Home")
        self._wordmark.setTextFormat(Qt.RichText)
        self._wordmark.setFont(sans_font(size=34, weight=700, tracking=-0.01))
        self._wordmark.setText(
            "<span style='color:#ffffff'>Knee</span>"
            f"<span style='color:{resolve('--brand-cyan')}'>Spa</span>"
            "<span style='color:#ffffff'> DRx</span>"
        )
        self._wordmark.setStyleSheet("background: transparent;")
        self._wordmark.clicked.connect(self.home_clicked)
        lay.addWidget(self._wordmark)

        lay.addStretch(1)

        self._device_status = QLabel("Device · connecting")
        self._device_status.setTextFormat(Qt.PlainText)
        self._device_status.setFont(sans_font(size=18, weight=600))
        self._device_status.setStyleSheet("color: white; background: transparent;")
        lay.addWidget(self._device_status)
        lay.addStretch(1)

        # Identity block (name + role), shown only when logged in.
        self._identity = QWidget()
        idlay = QVBoxLayout(self._identity)
        idlay.setContentsMargins(0, 0, 0, 0)
        idlay.setSpacing(2)
        idlay.setAlignment(Qt.AlignVCenter)
        self._name = QLabel()
        self._name.setTextFormat(Qt.PlainText)
        self._name.setMaximumWidth(280)
        self._name.setFont(sans_font(size="--text-base", weight=700))
        self._name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._name.setStyleSheet("color: #ffffff; background: transparent;")
        self._role = QLabel("Clinician")
        self._role.setFont(mono_font(size="--text-2xs"))
        self._role.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._role.setStyleSheet("color: #c6ced3; background: transparent;")
        idlay.addWidget(self._name)
        idlay.addWidget(self._role)
        self._identity.setVisible(False)
        lay.addWidget(self._identity)

        # Avatar — login launcher (logged out) / profile launcher (logged in).
        self._avatar = QPushButton()
        self._avatar.setAccessibleName("Clinician login or profile")
        self._avatar.setCursor(Qt.PointingHandCursor)
        self._avatar.setFixedSize(54, 54)
        self._avatar.setIconSize(QSize(34, 34))
        pix = QPixmap(image_path("buttons", "user-profile.png"))
        if not pix.isNull():
            self._avatar.setIcon(QIcon(pix))
        # Border is #000 — the bar is always dark (DS dark-chrome branch).
        self._avatar.setStyleSheet(
            "QPushButton { border-radius: 27px; background: #ffffff;"
            " border: 2px solid #000; }"
            " QPushButton:focus { border: 3px solid #176b9a; }"
            " QPushButton:pressed { background: #e6f3ff; }"
        )
        self._avatar.clicked.connect(self._on_avatar)
        lay.addWidget(self._avatar)

        self._username = None

    def set_device_status(self, text: str) -> None:
        """Present controller-derived status independently of the signed-in user."""
        self._device_status.setText("Device · " + text)

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
