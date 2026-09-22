"""A simple welcome screen with the KneeSpa logo and login."""

from typing import Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton
from ui.widgets.ds._common import image_path


class HomeScreen(QWidget):
    login_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#HomeScreen { background: #ffffff; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(24)
        layout.addStretch(1)

        self._logo = QLabel()
        self._logo.setAlignment(Qt.AlignCenter)
        self._logo.setStyleSheet("background: transparent;")
        pixmap = QPixmap(image_path("logos", "kneespa-logo-full.png"))
        if not pixmap.isNull():
            self._logo.setPixmap(
                pixmap.scaled(QSize(1080, 540), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        layout.addWidget(self._logo, 0, Qt.AlignCenter)

        self._login_btn = DSButton("Login", variant="primary", size="md")
        self._login_btn.setFixedWidth(240)
        self._login_btn.clicked.connect(self.login_requested)
        layout.addWidget(self._login_btn, 0, Qt.AlignCenter)
        layout.addStretch(1)

    def set_logged_in(self, logged_in: bool) -> None:
        """Show login only when there is no active clinician session."""
        self._login_btn.setVisible(not logged_in)
