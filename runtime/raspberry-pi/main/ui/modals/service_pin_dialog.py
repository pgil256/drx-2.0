"""Touch entry for the separate technician credential, with no default PIN."""

from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QWidget

from helpers.service_auth import ServiceAccess
from ui.widgets.ds import DSButton, DSDialog, DSKeypad
from ui.widgets.ds._common import sans_font


class ServicePinDialog(DSDialog):
    """Authenticate each service visit; only an administrator can enroll a PIN."""

    def __init__(
        self, access: ServiceAccess, is_admin: bool, parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent, title="Technician access", width=440)
        self.access = access
        self.is_admin = is_admin
        self.first_pin = None
        self.setWindowModality(Qt.ApplicationModal)
        self.setFont(sans_font(size="--text-base"))
        layout = self.body_layout
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.message)
        self.keypad = DSKeypad(length=6, label="Service PIN", compact=True)
        self.keypad.submitted.connect(self.submit)
        layout.addWidget(self.keypad, 0, Qt.AlignCenter)
        close = DSButton("Cancel", variant="secondary", full_width=True)
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        self.add_action(close, 1)
        if access.configured:
            self.message.setText("Enter the separate six-digit technician PIN.")
        elif is_admin:
            self.message.setText("Create a six-digit service PIN. You will enter it twice.")
        else:
            self.message.setText("An administrator must create the service PIN first.")
            self.keypad.setEnabled(False)

    def submit(self, pin: str) -> None:
        """Never expose the PIN in logs, error messages, or the service report."""
        self.keypad.set_value("")
        try:
            if not self.access.configured:
                if self.first_pin is None:
                    self.first_pin = pin
                    self.message.setText("Enter the new service PIN again to confirm.")
                    return
                self.access.provision(self.first_pin, pin, self.is_admin)
                self.first_pin = None
                self.accept()
                return
            if self.access.verify(pin):
                self.accept()
            else:
                delay = self.access.lockout_remaining
                self.message.setText(
                    f"Too many attempts. Try again in {int(delay) + 1} seconds."
                    if delay else "Incorrect service PIN. Try again."
                )
        except (ValueError, PermissionError, OSError):
            self.first_pin = None
            self.message.setText("Could not set the PIN. Check both entries and device access.")

    def done(self, result: int) -> None:
        self.first_pin = None
        self.keypad.set_value("")
        super().done(result)
