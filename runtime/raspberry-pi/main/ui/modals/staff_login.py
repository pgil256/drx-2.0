"""Interactive cloud staff sign-in, MFA, and explicit clinic selection."""

from typing import Dict, Optional

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QWidget,
)

from ui.modals.text_keyboard import TextKeyboard
from ui.widgets.ds import DSButton, DSDialog


def open_text_keyboard(field: QLineEdit, parent: QWidget) -> TextKeyboard:
    """Use a masked keyboard for secrets and support every printable ASCII symbol."""
    keyboard = TextKeyboard(field.accessibleName(), field.text(), field.maxLength(), parent=parent)
    if field.echoMode() == QLineEdit.Password:
        keyboard.editor.setEchoMode(QLineEdit.Password)
    for symbols in ('#$%&*()=[]{}', '";<>\\|`~^'):
        row = QHBoxLayout()
        row.setSpacing(6)
        for symbol in symbols:
            button = keyboard._button(symbol)
            button.clicked.connect(lambda _checked, text=symbol: keyboard._insert(text))
            row.addWidget(button)
        keys = keyboard.key_layout()
        keys.insertLayout(keys.count() - 1, row)

    def finish(result: int) -> None:
        if result == QDialog.Accepted:
            field.setText(keyboard.value())
        keyboard.editor.clear()
        keyboard.deleteLater()

    keyboard.finished.connect(finish)
    keyboard.open()
    keyboard.editor.setFocus()
    return keyboard


class StaffLogin(DSDialog):
    login_requested = pyqtSignal(str, str)
    mfa_requested = pyqtSignal(str, bool)
    clinic_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None, purpose: str = "save patients") -> None:
        super().__init__(parent, title="Cloud staff sign-in", width=620)
        self._purpose = purpose
        self._stage = "login"
        self._keyboard = None
        layout = self.body_layout
        layout.setSpacing(12)
        self._instructions = QLabel(f"Sign in with your cloud staff account to {purpose}.")
        self._instructions.setWordWrap(True)
        layout.addWidget(self._instructions)
        self._email = self._field("Cloud email", 320)
        self._password = self._field("Cloud password", 1024)
        self._password.setEchoMode(QLineEdit.Password)
        self._code = self._field("Verification or recovery code", 64)
        self._recovery = QCheckBox("Use a recovery code")
        self._clinics = QComboBox()
        self._clinics.setMinimumHeight(52)
        self._clinics.setAccessibleName("Device clinic")
        for field in (self._email, self._password, self._code, self._recovery, self._clinics):
            layout.addWidget(field)
        self._status = QLabel()
        self._status.setTextFormat(Qt.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._cancel = DSButton("Cancel", variant="secondary")
        self._next = DSButton("Sign in")
        self._cancel.clicked.connect(self.reject)
        self._next.clicked.connect(self._submit)
        self.add_action_stretch(1)
        for button in (self._cancel, self._next):
            button.setAutoDefault(False)
            button.setMinimumWidth(160)
            self.add_action(button)
        self.set_stage("login")

    def _field(self, title: str, limit: int) -> QLineEdit:
        field = QLineEdit()
        field.setAccessibleName(title)
        field.setPlaceholderText(title)
        field.setMaxLength(limit)
        field.setMinimumHeight(52)
        field.installEventFilter(self)
        return field

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if isinstance(watched, QLineEdit) and event.type() == QEvent.MouseButtonRelease:
            self._keyboard = open_text_keyboard(watched, self)
            return True
        return super().eventFilter(watched, event)

    def set_stage(self, stage: str, context: Optional[Dict] = None) -> None:
        self._stage = stage
        self._email.setVisible(stage == "login")
        self._password.setVisible(stage == "login")
        self._code.setVisible(stage == "mfa")
        self._recovery.setVisible(stage == "mfa")
        self._clinics.setVisible(stage == "clinic")
        self._password.clear()
        self._code.clear()
        if stage == "clinic":
            self._instructions.setText("Select the clinic this device is registered to.")
            self._clinics.clear()
            self._clinics.addItem("Choose the device's clinic…", None)
            for clinic in (context or {}).get("clinics", []):
                self._clinics.addItem(f"{clinic['name']} · {clinic['id']}", clinic["id"])
        elif stage == "mfa":
            self._instructions.setText("Enter your authenticator code or a recovery code.")
        else:
            self._instructions.setText(f"Sign in with your cloud staff account to {self._purpose}.")
        self._next.setText({"login": "Sign in", "mfa": "Verify", "clinic": "Use clinic"}[stage])
        self.set_pending(False)
        self._status.clear()
        self.adjustSize()

    def _submit(self) -> None:
        if self._stage == "login":
            email, password = self._email.text().strip(), self._password.text()
            if not email or not password:
                self._status.setText("Enter your cloud email and password.")
                return
            self._password.clear()
            self.login_requested.emit(email, password)
        elif self._stage == "mfa":
            code = self._code.text().strip()
            self._code.clear()
            self.mfa_requested.emit(code, self._recovery.isChecked())
        elif self._clinics.currentData():
            self.clinic_requested.emit(self._clinics.currentData())
        else:
            self._status.setText("Choose the device's clinic before continuing.")

    def set_pending(self, pending: bool) -> None:
        for field in (self._email, self._password, self._code, self._recovery, self._clinics,
                      self._next, self._cancel):
            field.setEnabled(not pending)
        if pending:
            self._status.setText("Connecting to cloud…")

    def show_error(self, message: str) -> None:
        self.set_pending(False)
        self._status.setText(message)

    def done(self, result: int) -> None:
        for keyboard in self.findChildren(TextKeyboard):
            keyboard.reject()
        self._password.clear()
        self._code.clear()
        super().done(result)
