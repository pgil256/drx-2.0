# tests/unit/test_secure_auth.py
import pytest
from unittest.mock import MagicMock

from helpers.secure_auth import SecureAuthHelper
from controllers.auth_controller import AuthController


@pytest.mark.unit
class TestPinHashing:
    def test_pbkdf2_roundtrip(self):
        stored = SecureAuthHelper.hash_pin_secure("4321")
        assert stored.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.verify_pin("4321", stored)
        assert not SecureAuthHelper.verify_pin("1234", stored)

    def test_salts_are_unique(self):
        a = SecureAuthHelper.hash_pin_secure("4321")
        b = SecureAuthHelper.hash_pin_secure("4321")
        assert a != b  # same PIN, different salt
        assert SecureAuthHelper.verify_pin("4321", a)
        assert SecureAuthHelper.verify_pin("4321", b)

    def test_legacy_sha256_still_verifies(self):
        """Deployed user files hold unsalted SHA-256 digests; they must
        keep working until re-provisioned."""
        legacy = SecureAuthHelper.hash_pin("1234")
        assert SecureAuthHelper.verify_pin("1234", legacy)
        assert not SecureAuthHelper.verify_pin("9999", legacy)

    def test_malformed_stored_hash_rejected(self):
        assert not SecureAuthHelper.verify_pin("1234", "pbkdf2_sha256$bad")
        assert not SecureAuthHelper.verify_pin("1234", "")
        assert not SecureAuthHelper.verify_pin("1234", None)


class _DialogStub:
    def accept(self):
        pass


class StubWindow:
    """Minimal window surface the AuthController operates on."""

    def __init__(self, users):
        self.users = users
        self.login_pin = ""
        self.current_user = None
        self.errors = []
        self.login_dialog = _DialogStub()
        self.login_line_edit = MagicMock()
        self.login_line_edit.text.return_value = ""

    def _show_timed_error(self, message):
        self.errors.append(message)

    def update_ui_after_login(self):
        pass


@pytest.mark.unit
class TestLoginLockout:
    def _make(self):
        stored = SecureAuthHelper.hash_pin_secure("7531")
        users = {stored: {"pin_hash": stored, "username": "T", "email": "t@x", "status": "user"}}
        window = StubWindow(users)
        return AuthController(window), window

    def test_successful_login(self):
        auth, w = self._make()
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is not None

    def test_lockout_after_five_failures(self):
        auth, w = self._make()
        for _ in range(5):
            w.login_pin = "0000"
            auth.handle_login()
        assert auth.lockout_until > 0
        assert any("locked" in e.lower() for e in w.errors)

        # Even the correct PIN is refused during the lockout window
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is None

    def test_success_resets_counter(self):
        auth, w = self._make()
        for _ in range(3):
            w.login_pin = "0000"
            auth.handle_login()
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is not None
        assert auth.failed_logins == 0

    def test_backspace_removes_last_digit(self):
        auth, w = self._make()
        w.login_pin = "753"
        w.login_line_edit.text.return_value = "753"
        auth.backspace_digit()
        assert w.login_pin == "75"
        w.login_line_edit.setText.assert_called_with("75")

    def test_backspace_on_empty_pin_is_safe(self):
        auth, w = self._make()
        w.login_pin = ""
        w.login_line_edit.text.return_value = ""
        auth.backspace_digit()
        assert w.login_pin == ""
