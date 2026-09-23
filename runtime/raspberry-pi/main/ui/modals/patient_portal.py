"""Hand off patient registration to the clinician web app."""

from typing import Optional
from urllib.parse import urlsplit

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QLabel, QWidget

from ui.widgets.ds import DSButton, DSDialog
from ui.widgets.ds._common import sans_font


def validated_portal_url(value: str) -> str:
    """Accept a public HTTPS page URL without credentials or token parameters."""
    value = value.strip()
    if not value or len(value) > 512 or any(ord(char) <= 32 for char in value):
        return ""
    try:
        url = urlsplit(value)
        url.port  # Reject malformed ports before displaying the address.
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment
                or url.hostname in ("localhost", "127.0.0.1", "::1")
                or "\\" in value):
            return ""
    except ValueError:
        return ""
    return value


def portal_qr_pixmap(url: str) -> QPixmap:
    """Render locally with whole pixels per module and a four-module quiet zone."""
    import qrcode

    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    code.add_data(url)
    code.make(fit=True)
    matrix = code.get_matrix()
    size = 320
    scale = size // len(matrix)
    if scale < 4:
        raise ValueError("The portal address needs a shorter QR code")
    offset = (size - len(matrix) * scale) // 2
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.white)
    painter = QPainter(pixmap)
    try:
        for row, modules in enumerate(matrix):
            for column, dark in enumerate(modules):
                if dark:
                    painter.fillRect(offset + column * scale, offset + row * scale,
                                     scale, scale, Qt.black)
    finally:
        painter.end()
    return pixmap


class PatientPortal(DSDialog):
    """Show the registration link, then return to explicit patient PIN entry."""

    INSTRUCTIONS = (
        "Scan with your phone or tablet. Sign in to the clinician app, select "
        "this device’s clinic, and add the patient and their treatment plan."
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent, title="Add patient in clinician app", width=640)
        layout = self.body_layout
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(16)
        self._instructions = QLabel(self.INSTRUCTIONS)
        self._instructions.setWordWrap(True)
        self._instructions.setAlignment(Qt.AlignCenter)
        self._instructions.setFont(sans_font(size="--text-base"))
        layout.addWidget(self._instructions)
        self._qr = QLabel()
        self._qr.setFixedSize(320, 320)
        self._qr.setAccessibleName("Scan to open patient registration in the clinician app")
        layout.addWidget(self._qr, 0, Qt.AlignHCenter)
        self._address = QLabel()
        self._address.setTextFormat(Qt.PlainText)
        self._address.setWordWrap(True)
        self._address.setAlignment(Qt.AlignCenter)
        self._address.setFont(sans_font(size="--text-sm"))
        layout.addWidget(self._address)
        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setFont(sans_font(size="--text-base"))
        layout.addWidget(self._status)
        self._back = DSButton("Back to patient PIN", full_width=True)
        self._back.clicked.connect(self.accept)
        self.add_action(self._back, 1)

    def set_portal_url(self, value: str) -> None:
        """Replace previous content; never display an unvalidated address."""
        url = validated_portal_url(value)
        self._qr.clear()
        self._qr.hide()
        self._instructions.setText(self.INSTRUCTIONS)
        self._instructions.setVisible(bool(url))
        self._address.setText(url)
        self._address.setVisible(bool(url))
        if not url:
            self._status.setText(
                "Patient registration is not set up on this device. Ask your clinic "
                "administrator for the clinician app address, then return with the patient PIN."
            )
        else:
            self._status.setText(
                "When registration is complete, return here and enter the patient’s "
                "four-digit PIN."
            )
            try:
                self._qr.setPixmap(portal_qr_pixmap(url))
                self._qr.show()
            except (ImportError, ValueError):
                self._instructions.setText(
                    "Open the address below on your phone or computer. Sign in to the "
                    "clinician app, select this device’s clinic, and add the patient."
                )
        # adjustSize() can shrink to the screen's preferred size and overlap the QR.
        # Reserve the full content height at the card width, including wrapped text.
        self.ensurePolished()
        self.layout().invalidate()
        self.setFixedHeight(self.layout().totalHeightForWidth(self.width()))
