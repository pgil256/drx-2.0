# controllers/auth_controller.py
"""Login/PIN handling extracted from the KneeSpa window.

Owns the lockout state (it is security state, not UI state) and the
PIN-entry buffer; the window keeps thin delegating slots.

Lockout state is persisted to disk (DATA_PATHS["AUTH_STATE"]) so that
power-cycling the kiosk does not reset the brute-force window, and the
lockout duration doubles on each consecutive lockout. Failed attempts
are logged for audit; the PIN itself is never logged.
"""
import json
import os
import time

from config.constants import DATA_PATHS
from helpers.logging import setup_logger
from helpers.secure_auth import SecureAuthHelper


class AuthController:
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_SECONDS = 60
    LOCKOUT_MAX_SECONDS = 3600

    def __init__(self, window, state_path=None):
        self.window = window
        self.logger = setup_logger(component="Auth")
        self.state_path = state_path or DATA_PATHS["AUTH_STATE"]
        self.failed_logins = 0
        self.lockout_until = 0.0
        # Consecutive lockouts served without a successful login in
        # between; drives the exponential backoff.
        self.lockout_count = 0
        self._load_state()

    # -- persistence --------------------------------------------------

    def _load_state(self):
        """Restore lockout state; a missing or corrupt file starts clean."""
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            self.failed_logins = int(state.get("failed_logins", 0))
            self.lockout_until = float(state.get("lockout_until", 0.0))
            self.lockout_count = int(state.get("lockout_count", 0))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as e:
            self.logger.warning(
                "Auth state file unreadable (%s); starting clean", e
            )

    def _save_state(self):
        """Persist lockout state atomically (kiosk power cuts are routine)."""
        state = {
            "failed_logins": self.failed_logins,
            "lockout_until": self.lockout_until,
            "lockout_count": self.lockout_count,
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.state_path)) or "."
            os.makedirs(directory, exist_ok=True)
            tmp_path = self.state_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)
        except OSError as e:
            # Never let bookkeeping failure block the login path; the
            # in-memory lockout still protects the running session.
            self.logger.error("Could not persist auth state: %s", e)

    def _lockout_duration(self):
        """Exponential backoff: 60 s, 120 s, 240 s, ... capped at 1 h."""
        return min(
            self.LOCKOUT_SECONDS * (2 ** self.lockout_count),
            self.LOCKOUT_MAX_SECONDS,
        )

    # -- PIN entry ----------------------------------------------------

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

    # -- login --------------------------------------------------------

    def handle_login(self):
        """Validate the entered PIN with persistent lockout protection."""
        window = self.window
        print("Handling login")

        # Lockout: a kiosk with a short numeric PIN and unlimited instant
        # retries is brute-forceable in minutes
        now = time.time()
        if now < self.lockout_until:
            wait_s = int(self.lockout_until - now) + 1
            self.logger.warning(
                "Login attempt during lockout (%d s remaining)", wait_s
            )
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
            self.logger.info(
                "Login successful for user %r", matched_user.get("username")
            )
            self.failed_logins = 0
            self.lockout_count = 0
            self._save_state()
            window.current_user = matched_user
            window.login_pin = ""
            window.update_ui_after_login()
            window.login_dialog.accept()
            self.clear_pin()
        else:
            print("Login failed: Invalid PIN")
            self.failed_logins += 1
            self.logger.warning(
                "Failed login attempt %d of %d",
                self.failed_logins, self.LOCKOUT_THRESHOLD,
            )
            if self.failed_logins >= self.LOCKOUT_THRESHOLD:
                duration = self._lockout_duration()
                self.lockout_until = time.time() + duration
                self.lockout_count += 1
                self.failed_logins = 0
                self.logger.warning(
                    "Login locked for %d s (consecutive lockout #%d)",
                    duration, self.lockout_count,
                )
                window._show_timed_error(
                    f"Too many failed attempts. Login locked for "
                    f"{duration} seconds."
                )
            else:
                window._show_timed_error("Invalid PIN. Please try again.")
            self._save_state()
            self.clear_pin()
