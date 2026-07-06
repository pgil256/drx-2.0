"""TopBar — persistent 96px dark header (logo + wordmark + identity/login).

Mirrors `TopBar` in `bundle.jsx` (baked to dark chrome): the knee mark and the
"KneeSpa DRx" wordmark both navigate Home; the right side shows a login avatar
when logged out, or the clinician identity + avatar when logged in. A 2px cyan
line underlines the bar (the DS `box-shadow: inset 0 -2px 0 var(--brand-cyan)`).

Signals (wired to the controller in Phase 3):
    home_clicked      — logo / wordmark tapped
    login_requested   — avatar tapped while logged out
    logout_requested  — avatar tapped while logged in
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

BAR_HEIGHT = 96


class TopBar(QFrame):
    home_clicked = pyqtSignal()
    login_requested = pyqtSignal()
    logout_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(BAR_HEIGHT)
        self.setStyleSheet(
            f"#TopBar {{ background: {resolve('--ink-900')};"
            f" border-bottom: 2px solid {resolve('--brand-cyan')}; }}"
        )

        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(18)

        logo = image_label(image_path("logos", "knee.png"), 60, 60, clickable=True)
        logo.setToolTip("Home")
        logo.clicked.connect(self.home_clicked)
        lay.addWidget(logo)

        self._wordmark = ClickableLabel()
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

        # Identity block (name + role), shown only when logged in.
        self._identity = QWidget()
        idlay = QVBoxLayout(self._identity)
        idlay.setContentsMargins(0, 0, 0, 0)
        idlay.setSpacing(0)
        self._name = QLabel()
        self._name.setFont(sans_font(size="--text-base", weight=700))
        self._name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._name.setStyleSheet("color: #ffffff; background: transparent;")
        self._role = QLabel("Clinician")
        self._role.setFont(mono_font(size="--text-2xs"))
        self._role.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._role.setStyleSheet("color: rgba(255,255,255,0.5); background: transparent;")
        idlay.addWidget(self._name)
        idlay.addWidget(self._role)
        self._identity.setVisible(False)
        lay.addWidget(self._identity)

        # Avatar — login launcher (logged out) / identity + logout (logged in).
        self._avatar = QPushButton()
        self._avatar.setCursor(Qt.PointingHandCursor)
        self._avatar.setFixedSize(52, 52)
        self._avatar.setIconSize(QSize(34, 34))
        pix = QPixmap(image_path("buttons", "user-profile.png"))
        if not pix.isNull():
            self._avatar.setIcon(QIcon(pix))
        # Border is #000 — the bar is always dark (DS dark-chrome branch).
        self._avatar.setStyleSheet(
            "QPushButton { border-radius: 26px; background: #ffffff;"
            " border: 2px solid #000; }"
        )
        self._avatar.clicked.connect(self._on_avatar)
        lay.addWidget(self._avatar)

        self._username = None

    def _on_avatar(self):
        if self._username:
            self.logout_requested.emit()
        else:
            self.login_requested.emit()

    def set_user(self, username):
        """Show the identity block + name when logged in, hide it when out."""
        self._username = username
        if username:
            self._name.setText(username)
            self._identity.setVisible(True)
            self._avatar.setToolTip(f"{username} — tap to log out")
        else:
            self._identity.setVisible(False)
            self._avatar.setToolTip("Login")
