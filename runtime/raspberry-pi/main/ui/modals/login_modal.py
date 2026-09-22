"""Phone-approved patient/staff sign-in with an explicit local staff PIN option.

The view renders the complete approval URL locally and emits user intent only;
the controller owns cloud requests, polling, cancellation and session validation.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ui.theme import GLYPH
from ui.widgets.ds import DSKeypad
from ui.widgets.ds._common import drop_shadow, image_path, resolve, sans_font

from ._overlay import Overlay
from .patient_portal import portal_qr_pixmap


class LoginModal(Overlay):
    submitted = pyqtSignal(str)
    phone_requested = pyqtSignal()
    phone_cancelled = pyqtSignal()

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
        lay.setContentsMargins(32, 20, 32, 20)
        lay.setSpacing(0)

        # Close — floats at the top-right corner (DS position:absolute top:14 right:14),
        # so it does not occupy a layout row and push the logo down.
        close = QPushButton(GLYPH["close"], card)
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(48, 48)
        close.setAccessibleName("Close login")
        close.setFont(sans_font(size="--text-md", weight=600))
        close.setStyleSheet(
            "QPushButton { border-radius: 24px; border: none; padding: 0; font-size: 24px;"
            f" background: {resolve('--gray-200')}; color: {resolve('--ink-700')}; }}"
            f" QPushButton:hover {{ background: {resolve('--gray-300')}; }}"
        )
        close.clicked.connect(self.close_overlay)
        close.move(408 - 14 - 48, 14)  # card is fixedWidth 408
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

        self._phone = QWidget()
        phone_layout = QVBoxLayout(self._phone)
        phone_layout.setContentsMargins(0, 0, 0, 0)
        phone_layout.setSpacing(8)
        instructions = QLabel(
            "Patient or clinician sign-in\nScan with your phone, choose your role, "
            "and confirm the matching code."
        )
        instructions.setWordWrap(True)
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setFont(sans_font(size=16))
        phone_layout.addWidget(instructions)
        self._qr = QLabel()
        self._qr.setFixedSize(320, 320)
        self._qr.setAccessibleName("Scan to approve sign-in on your phone")
        phone_layout.addWidget(self._qr, 0, Qt.AlignCenter)
        self._display_code = QLabel()
        self._display_code.setTextFormat(Qt.PlainText)
        self._display_code.setAlignment(Qt.AlignCenter)
        self._display_code.setFont(sans_font(size=26, weight=700))
        phone_layout.addWidget(self._display_code)
        self._remaining = QLabel()
        self._remaining.setAlignment(Qt.AlignCenter)
        phone_layout.addWidget(self._remaining)
        self._phone_status = QLabel()
        self._phone_status.setTextFormat(Qt.PlainText)
        self._phone_status.setWordWrap(True)
        self._phone_status.setAlignment(Qt.AlignCenter)
        phone_layout.addWidget(self._phone_status)
        self._retry = QPushButton("Get a new QR code")
        self._retry.setMinimumHeight(48)
        self._retry.clicked.connect(self.phone_requested)
        phone_layout.addWidget(self._retry)
        lay.addWidget(self._phone)

        self._switch = QPushButton("Use local staff PIN")
        self._switch.setMinimumHeight(48)
        self._switch.clicked.connect(self._switch_mode)
        lay.addWidget(self._switch)
        self._phone_mode = True

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
        self._set_phone_mode(True)

    def _set_phone_mode(self, enabled: bool) -> None:
        self._phone_mode = enabled
        self._phone.setVisible(enabled)
        self._keypad.setVisible(not enabled)
        self._error.setVisible(not enabled)
        self._switch.setText("Use local staff PIN" if enabled else "Sign in with your phone")

    def _switch_mode(self) -> None:
        self._set_phone_mode(not self._phone_mode)
        self.reset_pin()
        if self._phone_mode:
            self.phone_requested.emit()
        else:
            self.phone_cancelled.emit()

    def reset_pin(self) -> None:
        self._error.clear()
        self._keypad.set_value("")

    def clear_phone(self) -> None:
        self._qr.clear()
        self._qr.hide()
        self._display_code.clear()
        self._remaining.clear()

    def phone_status(self, message: str, retry: bool = True, keep_qr: bool = False) -> None:
        if not keep_qr:
            self.clear_phone()
        self._phone_status.setText(message)
        self._retry.setVisible(retry)

    def show_phone_request(self, request: dict) -> None:
        self._qr.setPixmap(portal_qr_pixmap(request["verification_url"]))
        self._qr.show()
        self._display_code.setText(request["display_code"])
        self._phone_status.setText("Waiting for approval on your phone…")
        self._retry.hide()

    def set_phone_remaining(self, seconds: int) -> None:
        self._remaining.setText(f"Code expires in {seconds // 60}:{seconds % 60:02d}")

    def open_over(self, parent=None):
        self.reset()
        super().open_over(parent)
        self.phone_requested.emit()
