"""Phone-approved patient/staff sign-in with an explicit local staff PIN option.

The view renders the complete approval URL locally and emits user intent only;
the controller owns cloud requests, polling, cancellation and session validation.

The card shares the DSDialog frame (title strip with close, body, footer).
While no request is active the QR area shows a placeholder frame with the
next step inside it instead of a blank square; the switch to the local staff
PIN is a quiet footer link so one action stays primary.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QFrame, QLabel, QStackedLayout, QVBoxLayout, QWidget

from ui.widgets.ds import DSButton, DSKeypad, DSSheet, DSSpinner
from ui.widgets.ds._common import drop_shadow, resolve, sans_font

from ._overlay import Overlay
from .patient_portal import portal_qr_pixmap

QR_PX = 320
PLACEHOLDER_TEXT = "Preparing a sign-in code…"


class LoginModal(Overlay):
    submitted = pyqtSignal(str)
    phone_requested = pyqtSignal()
    phone_cancelled = pyqtSignal()

    def __init__(self, parent=None, length=4):
        super().__init__(parent)
        card = DSSheet("Sign in", width=440)
        card.close_requested.connect(self.close_overlay)
        drop_shadow(card, blur=48, dy=8, alpha=51)  # --shadow-lg
        self._card_frame = card
        lay = card.body_layout
        lay.setContentsMargins(28, 18, 28, 16)
        lay.setSpacing(8)

        self._keypad = DSKeypad(length=length, label="Enter staff PIN")
        self._keypad.submitted.connect(self.submitted)
        lay.addWidget(self._keypad, 0, Qt.AlignCenter)

        self._phone = QWidget()
        phone_layout = QVBoxLayout(self._phone)
        phone_layout.setContentsMargins(0, 0, 0, 0)
        phone_layout.setSpacing(8)
        instructions = QLabel(
            "Scan with your phone, choose your role, and confirm the matching code."
        )
        instructions.setWordWrap(True)
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setFont(sans_font(size="--text-sm"))
        instructions.setStyleSheet(f"color: {resolve('--text-body')};")
        phone_layout.addWidget(instructions)

        # QR and its placeholder share one 320px slot.
        slot = QWidget()
        slot.setFixedSize(QR_PX, QR_PX)
        stack = QStackedLayout(slot)
        stack.setStackingMode(QStackedLayout.StackAll)
        self._placeholder = QFrame()
        self._placeholder.setObjectName("QrPlaceholder")
        self._placeholder.setStyleSheet(
            f"#QrPlaceholder {{ background: {resolve('--surface-page')};"
            f" border: 2px dashed {resolve('--gray-400')};"
            f" border-radius: {resolve('--radius-md')}; }}"
            " #QrPlaceholder QLabel { background: transparent; border: none; }"
        )
        holder = QVBoxLayout(self._placeholder)
        holder.setContentsMargins(24, 24, 24, 24)
        holder.setSpacing(12)
        holder.addStretch(1)
        self._placeholder_spinner = DSSpinner(28)
        holder.addWidget(self._placeholder_spinner, 0, Qt.AlignHCenter)
        self._placeholder_text = QLabel(PLACEHOLDER_TEXT)
        self._placeholder_text.setWordWrap(True)
        self._placeholder_text.setAlignment(Qt.AlignCenter)
        self._placeholder_text.setFont(sans_font(size="--text-base", weight=600))
        self._placeholder_text.setStyleSheet(f"color: {resolve('--text-muted')};")
        holder.addWidget(self._placeholder_text)
        holder.addStretch(1)
        stack.addWidget(self._placeholder)
        self._qr = QLabel()
        self._qr.setFixedSize(QR_PX, QR_PX)
        self._qr.setAccessibleName("Scan to approve sign-in on your phone")
        stack.addWidget(self._qr)
        self._qr.hide()  # until the controller supplies a request
        phone_layout.addWidget(slot, 0, Qt.AlignCenter)

        self._display_code = QLabel()
        self._display_code.setTextFormat(Qt.PlainText)
        self._display_code.setAlignment(Qt.AlignCenter)
        self._display_code.setFont(sans_font(size="--text-lg", weight=700))
        self._display_code.setStyleSheet(f"color: {resolve('--text-strong')};")
        phone_layout.addWidget(self._display_code)
        self._remaining = QLabel()
        self._remaining.setAlignment(Qt.AlignCenter)
        self._remaining.setFont(sans_font(size="--text-sm"))
        self._remaining.setStyleSheet(f"color: {resolve('--text-muted')};")
        phone_layout.addWidget(self._remaining)
        self._phone_status = QLabel()
        self._phone_status.setTextFormat(Qt.PlainText)
        self._phone_status.setWordWrap(True)
        self._phone_status.setAlignment(Qt.AlignCenter)
        self._phone_status.setFont(sans_font(size="--text-sm"))
        phone_layout.addWidget(self._phone_status)
        self._retry = DSButton("Get a new QR code", variant="secondary", full_width=True)
        self._retry.clicked.connect(self.phone_requested)
        phone_layout.addWidget(self._retry)
        lay.addWidget(self._phone)

        self._error = QLabel("")
        self._error.setMinimumHeight(22)
        self._error.setAlignment(Qt.AlignCenter)
        self._error.setFont(sans_font(size="--text-sm", weight=600))
        self._error.setStyleSheet(f"color: {resolve('--red-500')}; background: transparent;")
        lay.addWidget(self._error, 0, Qt.AlignCenter)

        self._switch = DSButton("Use local staff PIN", variant="ghost", full_width=True)
        self._switch.clicked.connect(self._switch_mode)
        card.add_action(self._switch, 1)
        self._phone_mode = True
        self._refresh_placeholder()

        self.set_card(card)

    def _refresh_placeholder(self) -> None:
        showing_qr = not self._qr.isHidden()
        self._placeholder.setVisible(not showing_qr)
        self._placeholder_spinner.setVisible(
            not showing_qr and self._placeholder_text.text() == PLACEHOLDER_TEXT)

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
        self._card_frame.set_title("Sign in" if enabled else "Staff PIN")
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
        self._placeholder_text.setText(PLACEHOLDER_TEXT)
        self._refresh_placeholder()

    def phone_status(self, message: str, retry: bool = True, keep_qr: bool = False) -> None:
        if not keep_qr:
            self.clear_phone()
            # Put the next step inside the empty frame rather than beside it.
            self._placeholder_text.setText(
                "Tap “Get a new QR code” to try again." if retry else message)
            self._refresh_placeholder()
        self._phone_status.setText(message)
        self._retry.setVisible(retry)

    def show_phone_request(self, request: dict) -> None:
        self._qr.setPixmap(portal_qr_pixmap(request["verification_url"]))
        self._qr.show()
        self._refresh_placeholder()
        self._display_code.setText(request["display_code"])
        self._phone_status.setText("Waiting for approval on your phone…")
        self._retry.hide()

    def set_phone_remaining(self, seconds: int) -> None:
        self._remaining.setText(f"Code expires in {seconds // 60}:{seconds % 60:02d}")

    def open_over(self, parent=None):
        self.reset()
        super().open_over(parent)
        self.phone_requested.emit()
