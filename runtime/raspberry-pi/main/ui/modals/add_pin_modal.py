"""AddPinModal — admin provisioning of a new user PIN (over a dim scrim).

Two-step DS Keypad flow: enter the new 4-digit PIN, then confirm it, with an
optional name field above (defaults to "User" when left blank). The modal is
transport-only: it emits ``submitted(username, pin)`` once the two entries
match; the controller persists via ``CSVHelper.add_user`` and calls
:meth:`show_error` (e.g. duplicate PIN) or lets the shell dismiss it.

Signals:
    submitted(str, str) — (username, pin) after a matching confirm entry
    closed              — backdrop / close / Esc dismissed the modal
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ui.theme import GLYPH
from ui.widgets.ds import DSKeypad
from ui.widgets.ds._common import drop_shadow, resolve, sans_font

from ._overlay import Overlay

_ENTER = "Enter New PIN"
_CONFIRM = "Confirm New PIN"


class AddPinModal(Overlay):
    submitted = pyqtSignal(str, str)

    def __init__(self, parent=None, length=4):
        super().__init__(parent)
        self._first_pin = None

        card = QWidget()
        card.setObjectName("AddPinCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(408)
        card.setStyleSheet(
            f"#AddPinCard {{ background: #ffffff; border-radius: {resolve('--radius-lg')}; }}"
        )
        drop_shadow(card, blur=48, dy=8, alpha=51)  # --shadow-lg

        lay = QVBoxLayout(card)
        lay.setContentsMargins(44, 36, 44, 36)
        lay.setSpacing(0)

        # Close — floats at the top-right corner (matches LoginModal).
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
        close.move(408 - 14 - 38, 14)
        close.raise_()

        title = QLabel("Add User PIN")
        title.setAlignment(Qt.AlignCenter)
        title.setFont(sans_font(size="--text-lg", weight=700))
        title.setStyleSheet(f"color: {resolve('--ink-900')}; background: transparent;")
        lay.addWidget(title, 0, Qt.AlignCenter)
        lay.addSpacing(18)

        self._name = QLineEdit()
        self._name.setPlaceholderText("New user name (optional)")
        self._name.setAlignment(Qt.AlignCenter)
        self._name.setFont(sans_font(size="--text-md"))
        self._name.setFixedHeight(48)
        self._name.setStyleSheet(
            f"QLineEdit {{ border: 2px solid {resolve('--gray-300')};"
            f" border-radius: {resolve('--radius-md')};"
            f" color: {resolve('--ink-900')}; background: #ffffff; }}"
            f" QLineEdit:focus {{ border-color: {resolve('--brand-cyan')}; }}"
        )
        lay.addWidget(self._name)
        lay.addSpacing(20)

        self._keypad = DSKeypad(length=length, label=_ENTER)
        self._keypad.submitted.connect(self._on_pin_entered)
        lay.addWidget(self._keypad, 0, Qt.AlignCenter)

        self._error = QLabel("")
        self._error.setMinimumHeight(22)
        self._error.setAlignment(Qt.AlignCenter)
        self._error.setFont(sans_font(size="--text-sm", weight=600))
        self._error.setStyleSheet(f"color: {resolve('--red-500')}; background: transparent;")
        lay.addSpacing(14)
        lay.addWidget(self._error, 0, Qt.AlignCenter)

        self.set_card(card)

    def _on_pin_entered(self, pin):
        if self._first_pin is None:
            self._first_pin = pin
            self._error.setText("")
            self._keypad.set_value("")
            self._keypad._title.setText(_CONFIRM)
            return
        if pin != self._first_pin:
            self._restart_entry("PINs did not match. Try again.")
            return
        first, self._first_pin = self._first_pin, None
        self.submitted.emit(self._name.text(), first)

    def _restart_entry(self, message=""):
        self._first_pin = None
        self._error.setText(message)
        self._keypad.set_value("")
        self._keypad._title.setText(_ENTER)

    def show_error(self, message):
        """Controller feedback (e.g. duplicate PIN) — restart the entry flow."""
        self._restart_entry(message)

    def reset(self):
        self._name.setText("")
        self._restart_entry()

    def open_over(self, parent=None):
        self.reset()
        super().open_over(parent)
