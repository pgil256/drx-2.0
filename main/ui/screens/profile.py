"""ProfileScreen — the logged-in clinician's identity + logout.

Reached from the top-bar avatar while logged in (the avatar no longer logs
out directly). A single centered card shows the avatar mark, "Name — Title",
and the account actions: Add PIN (admins only), Log Out, and Exit App.
``app_shell`` forwards the buttons as signals so the controller keeps one
logout / shutdown path.

Signals:
    add_pin_requested — the Add PIN button was tapped (admin only)
    logout_requested  — the Log Out button was tapped
    exit_requested    — the Exit App button was tapped
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.widgets.common import image_label
from ui.widgets.ds import DSButton, DSCard
from ui.widgets.ds._common import image_path, mono_font, resolve, sans_font

_PAD = 20


class ProfileScreen(QWidget):
    add_pin_requested = pyqtSignal()
    logout_requested = pyqtSignal()
    exit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProfileScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#ProfileScreen {{ background: {resolve('--surface-page')}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._profile_card(), 0)
        row.addStretch(1)
        lay.addLayout(row, 0)
        lay.addStretch(2)

    def _profile_card(self):
        card = DSCard("Profile", padded=False)
        card.setMinimumWidth(440)
        host = QWidget()
        vlay = QVBoxLayout(host)
        vlay.setContentsMargins(32, 28, 32, 28)
        vlay.setSpacing(8)

        avatar = image_label(image_path("buttons", "user-profile.png"), 88, 88)
        vlay.addWidget(avatar, 0, Qt.AlignHCenter)
        vlay.addSpacing(8)

        self._name = QLabel()
        self._name.setAlignment(Qt.AlignHCenter)
        self._name.setFont(sans_font(size="--text-xl", weight=700))
        self._name.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        vlay.addWidget(self._name)

        self._title = QLabel()
        self._title.setAlignment(Qt.AlignHCenter)
        self._title.setFont(mono_font(size="--text-sm"))
        self._title.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        vlay.addWidget(self._title)

        vlay.addSpacing(16)
        self._add_pin = DSButton("Add PIN", variant="secondary", full_width=True)
        self._add_pin.clicked.connect(self.add_pin_requested)
        self._add_pin.setVisible(False)  # admins only (see set_user)
        vlay.addWidget(self._add_pin)

        vlay.addSpacing(10)
        self._logout = DSButton("Log Out", variant="danger", full_width=True)
        self._logout.clicked.connect(self.logout_requested)
        vlay.addWidget(self._logout)

        vlay.addSpacing(10)
        self._exit = DSButton("Exit App", variant="ghost", full_width=True)
        self._exit.clicked.connect(self.exit_requested)
        vlay.addWidget(self._exit)

        card.add_widget(host)
        return card

    def set_user(self, username, title="Clinician", is_admin=False):
        """Refresh the identity card (None clears it, e.g. after logout)."""
        self._name.setText(username or "")
        self._title.setText(title if username else "")
        self._add_pin.setVisible(bool(username) and is_admin)
