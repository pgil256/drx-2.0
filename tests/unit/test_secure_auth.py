# tests/unit/test_secure_auth.py
import pytest

from helpers.secure_auth import SecureAuthHelper
from kneespa import KneeSpa


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


class LoginHarness:
    """Bare object binding the real handle_login without the full UI."""

    handle_login = KneeSpa.handle_login

    def __init__(self, users):
        self.users = users
        self.login_pin = ""
        self.current_user = None
        self.errors = []
        self.login_dialog = _DialogStub()
        self._failed_logins = 0
        self._lockout_until = 0

    def _show_timed_error(self, message):
        self.errors.append(message)

    def clear_login_line_edit(self):
        self.login_pin = ""

    def update_ui_after_login(self):
        pass


@pytest.mark.unit
class TestLoginLockout:
    def _make_harness(self):
        stored = SecureAuthHelper.hash_pin_secure("7531")
        users = {stored: {"pin_hash": stored, "username": "T", "email": "t@x", "status": "user"}}
        return LoginHarness(users)

    def test_successful_login(self):
        h = self._make_harness()
        h.login_pin = "7531"
        h.handle_login()
        assert h.current_user is not None

    def test_lockout_after_five_failures(self):
        h = self._make_harness()
        for _ in range(5):
            h.login_pin = "0000"
            h.handle_login()
        assert h._lockout_until > 0
        assert any("locked" in e.lower() for e in h.errors)

        # Even the correct PIN is refused during the lockout window
        h.login_pin = "7531"
        h.handle_login()
        assert h.current_user is None

    def test_success_resets_counter(self):
        h = self._make_harness()
        for _ in range(3):
            h.login_pin = "0000"
            h.handle_login()
        h.login_pin = "7531"
        h.handle_login()
        assert h.current_user is not None
        assert h._failed_logins == 0
