"""HomeScreen — splash page (full logo + login).

Mirrors `HomeScreen` in `bundle.jsx`: the full KneeSpa DRx logo centered on
white, with a large primary Login button when logged out, or a quiet hint to
pick a protocol when logged in.

Signal:
    login_requested — the Login button (logged-out state)
"""

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import image_path, resolve, sans_font


class HomeScreen(QWidget):
    login_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomeScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#HomeScreen { background: #ffffff; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 24, 40, 24)
        lay.setSpacing(0)

        lay.addStretch(1)

        self._logo = QLabel()
        self._logo.setAlignment(Qt.AlignCenter)
        self._logo.setStyleSheet("background: transparent;")
        pix = QPixmap(image_path("logos", "kneespa-logo-full.png"))
        if not pix.isNull():
            # Bound by width AND height so the logo never crowds the footer
            # (the DS caps it at maxWidth 1100 / maxHeight 92%).
            self._logo.setPixmap(
                pix.scaled(QSize(960, 470), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        lay.addWidget(self._logo, 0, Qt.AlignCenter)

        lay.addStretch(1)

        # Footer area: Login button (logged out) or hint text (logged in).
        self._login_btn = DSButton("Login", variant="primary", size="lg")
        self._login_btn.clicked.connect(self.login_requested)

        self._hint = QLabel("Select Protocols to begin a treatment.")
        self._hint.setAlignment(Qt.AlignCenter)
        self._hint.setFont(sans_font(size="--text-sm"))
        self._hint.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        self._hint.setVisible(False)

        footer = QWidget()
        flay = QVBoxLayout(footer)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(0)
        flay.addWidget(self._login_btn, 0, Qt.AlignCenter)
        flay.addWidget(self._hint, 0, Qt.AlignCenter)
        lay.addWidget(footer, 0, Qt.AlignCenter)

    def set_logged_in(self, logged_in):
        self._login_btn.setVisible(not logged_in)
        self._hint.setVisible(logged_in)
