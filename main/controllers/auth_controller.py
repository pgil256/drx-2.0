# controllers/auth_controller.py
"""Login/PIN handling extracted from the KneeSpa window.

Owns the lockout state (it is security state, not UI state) and the
PIN-entry buffer; the window keeps thin delegating slots.
"""
import time

from helpers.secure_auth import SecureAuthHelper


class AuthController:
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_SECONDS = 60

    def __init__(self, window):
        self.window = window
        self.failed_logins = 0
        self.lockout_until = 0.0

    def append_digit(self, value):
        """Append a PIN digit; the field's password echo mode masks it.

        Appending a literal '*' on top of echoMode=Password used to
        double-mask the entry (each keypress displayed the mask of a
        mask), and the displayed length was all an operator had.
        """
        window = self.window
        if window.login_line_edit:
            from PyQt5 import QtWidgets

            window.login_line_edit.setEchoMode(QtWidgets.QLineEdit.Password)
            window.login_line_edit.setText(window.login_line_edit.text() + value)
            window.login_pin += value

    def backspace_digit(self):
        """Remove the last entered PIN digit (mis-keys used to force a
        full re-entry via Clear)."""
        window = self.window
        window.login_pin = window.login_pin[:-1]
        if window.login_line_edit:
            text = window.login_line_edit.text()
            window.login_line_edit.setText(text[:-1])

    def clear_pin(self):
        """Clear the login input field."""
        window = self.window
        window.login_line_edit.clear()
        window.login_pin = ""

    def handle_login(self):
        """Validate the entered PIN with lockout protection."""
        window = self.window
        print("Handling login")

        # Lockout: a kiosk with a short numeric PIN and unlimited instant
        # retries is brute-forceable in minutes
        now = time.time()
        if now < self.lockout_until:
            wait_s = int(self.lockout_until - now) + 1
            window._show_timed_error(
                f"Too many failed attempts. Try again in {wait_s} seconds."
            )
            self.clear_pin()
            return

        matched_user = None
        for stored_hash, user in window.users.items():
            if SecureAuthHelper.verify_pin(window.login_pin, stored_hash):
                matched_user = user
                break

        if matched_user:
            print("Login successful")
            self.failed_logins = 0
            window.current_user = matched_user
            window.login_pin = ""
            window.update_ui_after_login()
            window.login_dialog.accept()
            self.clear_pin()
        else:
            print("Login failed: Invalid PIN")
            self.failed_logins += 1
            if self.failed_logins >= self.LOCKOUT_THRESHOLD:
                self.lockout_until = time.time() + self.LOCKOUT_SECONDS
                self.failed_logins = 0
                window._show_timed_error(
                    "Too many failed attempts. Login locked for 60 seconds."
                )
            else:
                window._show_timed_error("Invalid PIN. Please try again.")
            self.clear_pin()
