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
from ui.widgets.ds import DSBadge
from ui.widgets.ds._common import image_path, mono_font, resolve, sans_font
from ui.widgets.press_feedback import install_press_feedback

BAR_HEIGHT = 84

# Status label (ui/presentation.py) -> badge tone. Unknown labels stay neutral.
_STATUS_TONES = {
    "Ready": "success",
    "Preparing": "info",
    "Treatment active": "info",
    "Stopping / recovering": "warning",
    "Resetting": "warning",
    "Calibration required": "warning",
    "Recovery required": "danger",
    "Controller offline": "danger",
    "Physical stop active": "danger",
}


def _status_tone(label: str) -> str:
    return _STATUS_TONES.get(label, "neutral")


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
        # Semibold at 30px sits beside the 60px mark without outweighing it.
        self._wordmark.setFont(sans_font(size="--text-xl", weight=600, tracking=-0.01))
        self._wordmark.setText(
            "<span style='color:#ffffff'>Knee</span>"
            f"<span style='color:{resolve('--brand-cyan')}'>Spa</span>"
            "<span style='color:#ffffff'> DRx</span>"
        )
        self._wordmark.setStyleSheet("background: transparent;")
        self._wordmark.clicked.connect(self.home_clicked)
        lay.addWidget(self._wordmark)
        # Labels have no pressed state of their own; the filter is parentless,
        # so keep a reference or it is garbage-collected.
        self._press_feedback = install_press_feedback(logo, self._wordmark)

        lay.addStretch(1)

        # Device status: a muted "Device" caption and a status pill whose dot
        # colour carries the state (green Ready, blue Preparing/active, amber
        # Stopping/Resetting, red Recovery/Offline), readable at a glance from
        # across the room instead of plain white text.
        status_block = QWidget()
        status_lay = QHBoxLayout(status_block)
        status_lay.setContentsMargins(0, 0, 0, 0)
        status_lay.setSpacing(12)
        caption = QLabel("Device")
        caption.setTextFormat(Qt.PlainText)
        caption.setFont(sans_font(size="--text-base", weight=500))
        caption.setStyleSheet("color: #c6ced3; background: transparent;")
        status_lay.addWidget(caption)
        self._device_status = DSBadge("Connecting", tone="neutral", dot=True, size="md")
        self._device_status.setAccessibleName("Device status")
        status_lay.addWidget(self._device_status)
        lay.addWidget(status_block)
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
        self._role.setFont(mono_font(size="--text-xs"))
        self._role.setProperty("dsCaption", True)
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
        self._avatar.clicked.connect(self._on_avatar)
        lay.addWidget(self._avatar)

        self._username = None
        self._style_avatar(signed_in=False)

    def _style_avatar(self, signed_in: bool) -> None:
        """A plain white disc when logged out; a cyan ring marks a signed-in user.

        (The previous 2px black ring was invisible against the dark bar.)
        """
        ring = (f"3px solid {resolve('--brand-cyan')}" if signed_in
                else f"2px solid {resolve('--white')}")
        self._avatar.setStyleSheet(
            f"QPushButton {{ border-radius: 27px; background: {resolve('--white')};"
            f" border: {ring}; }}"
            f" QPushButton[keyboardFocus=\"true\"]:focus"
            f" {{ border: 3px solid {resolve('--color-primary')}; }}"
            f" QPushButton:pressed {{ background: {resolve('--blue-100')}; }}"
        )

    def set_device_status(self, text: str) -> None:
        """Present controller-derived status independently of the signed-in user."""
        self._device_status.set_text(text)
        self._device_status.set_tone(_status_tone(text))

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
        self._style_avatar(signed_in=bool(username))
