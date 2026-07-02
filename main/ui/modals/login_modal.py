"""LoginModal — PIN entry over a dim scrim (replaces login.ui).

Mirrors `LoginModal` in `bundle.jsx`: a centered white card with the knee mark,
the KneeSpa DRx wordmark, a 4-digit DS Keypad, and an error line. Uses
``DSKeypad`` (which has a 0 key, fixing the legacy keypad's missing-0 bug).

The modal is transport-only: it emits ``submitted(pin)`` when four digits are
entered; the controller verifies against the real auth backend (Phase 3) and
calls :meth:`show_error` or lets the shell dismiss it on success.

Signals:
    submitted(str)  — a full-length PIN was entered
    closed          — backdrop / close / Esc dismissed the modal
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.theme import GLYPH
from ui.widgets.ds import DSKeypad
from ui.widgets.ds._common import drop_shadow, image_path, resolve, sans_font

from ._overlay import Overlay


class LoginModal(Overlay):
    submitted = pyqtSignal(str)

    def __init__(self, parent=None, length=4):
        super().__init__(parent)
        card = QWidget()
        card.setObjectName("LoginCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(408)
        card.setStyleSheet(
            f"#LoginCard {{ background: #ffffff; border-radius: {resolve('--radius-lg')}; }}"
        )
        drop_shadow(card, blur=48, dy=8, alpha=51)  # --shadow-lg

        lay = QVBoxLayout(card)
        lay.setContentsMargins(44, 36, 44, 36)  # DS padding 36px 44px
        lay.setSpacing(0)

        # Close — floats at the top-right corner (DS position:absolute top:14 right:14),
        # so it does not occupy a layout row and push the logo down.
        close = QPushButton(GLYPH["close"], card)
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(38, 38)
        close.setFont(sans_font(size="--text-md", weight=600))
        close.setStyleSheet(
            "QPushButton { border-radius: 19px; border: none;"
            f" background: {resolve('--gray-200')}; color: {resolve('--ink-700')}; }}"
            f" QPushButton:hover {{ background: {resolve('--gray-300')}; }}"
        )
        close.clicked.connect(self.close_overlay)
        close.move(408 - 14 - 38, 14)  # card is fixedWidth 408
        close.raise_()

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        pix = QPixmap(image_path("logos", "knee.png"))
        if not pix.isNull():
            logo.setPixmap(pix.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(logo, 0, Qt.AlignCenter)
        lay.addSpacing(6)

        wordmark = QLabel(
            f"<span style='color:{resolve('--ink-900')}'>Knee</span>"
            f"<span style='color:{resolve('--brand-cyan')}'>Spa</span>"
            f"<span style='color:{resolve('--ink-900')}'> DRx</span>"
        )
        wordmark.setTextFormat(Qt.RichText)
        wordmark.setAlignment(Qt.AlignCenter)
        wordmark.setFont(sans_font(size="--text-lg", weight=700))
        wordmark.setStyleSheet("background: transparent;")
        lay.addWidget(wordmark, 0, Qt.AlignCenter)
        lay.addSpacing(22)

        self._keypad = DSKeypad(length=length, label="Enter User PIN")
        self._keypad.submitted.connect(self.submitted)
        lay.addWidget(self._keypad, 0, Qt.AlignCenter)

        self._error = QLabel("")
        self._error.setMinimumHeight(22)
        self._error.setAlignment(Qt.AlignCenter)
        self._error.setFont(sans_font(size="--text-sm", weight=600))
        self._error.setStyleSheet(f"color: {resolve('--red-500')}; background: transparent;")
        lay.addSpacing(14)
        lay.addWidget(self._error, 0, Qt.AlignCenter)

        self.set_card(card)

    def show_error(self, message):
        self._error.setText(message)
        self._keypad.set_value("")

    def reset(self):
        self._error.setText("")
        self._keypad.set_value("")

    def open_over(self, parent=None):
        self.reset()
        super().open_over(parent)
