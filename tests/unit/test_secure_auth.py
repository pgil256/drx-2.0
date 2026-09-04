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

    def test_non_ascii_legacy_hash_is_rejected_not_raised(self):
        """hmac.compare_digest raises TypeError on non-ASCII str; a mis-columned
        CSV row must fail that one user, not abort the whole login loop."""
        assert not SecureAuthHelper.verify_pin("1234", "Jäne Doe")
        assert not SecureAuthHelper.verify_pin("1234", 12345)


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
    def _make(self, tmp_path, state_name="auth_state.json"):
        stored = SecureAuthHelper.hash_pin_secure("7531")
        users = {stored: {"pin_hash": stored, "username": "T", "email": "t@x", "status": "user"}}
        window = StubWindow(users)
        state_path = str(tmp_path / state_name)
        return AuthController(window, state_path=state_path), window

    def test_successful_login(self, tmp_path):
        auth, w = self._make(tmp_path)
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is not None

    def test_lockout_after_five_failures(self, tmp_path):
        auth, w = self._make(tmp_path)
        for _ in range(5):
            w.login_pin = "0000"
            auth.handle_login()
        assert auth.lockout_until > 0
        assert any("locked" in e.lower() for e in w.errors)

        # Even the correct PIN is refused during the lockout window
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is None

    def test_success_resets_counter(self, tmp_path):
        auth, w = self._make(tmp_path)
        for _ in range(3):
            w.login_pin = "0000"
            auth.handle_login()
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is not None
        assert auth.failed_logins == 0

    def test_backspace_removes_last_digit(self, tmp_path):
        auth, w = self._make(tmp_path)
        w.login_pin = "753"
        w.login_line_edit.text.return_value = "753"
        auth.backspace_digit()
        assert w.login_pin == "75"
        w.login_line_edit.setText.assert_called_with("75")

    def test_backspace_on_empty_pin_is_safe(self, tmp_path):
        auth, w = self._make(tmp_path)
        w.login_pin = ""
        w.login_line_edit.text.return_value = ""
        auth.backspace_digit()
        assert w.login_pin == ""


@pytest.mark.unit
class TestLockoutPersistence:
    """Lockout state survives a process restart and backs off exponentially.

    A reboot used to reset the brute-force window: 5 attempts, power
    cycle, 5 more attempts -- unlimited retries on a physical kiosk.
    """

    def _make(self, tmp_path):
        stored = SecureAuthHelper.hash_pin_secure("7531")
        users = {stored: {"pin_hash": stored, "username": "T", "email": "t@x", "status": "user"}}
        window = StubWindow(users)
        return AuthController(window, state_path=str(tmp_path / "auth_state.json")), window

    def _trip_lockout(self, auth, window):
        for _ in range(AuthController.LOCKOUT_THRESHOLD):
            window.login_pin = "0000"
            auth.handle_login()

    def test_lockout_survives_restart(self, tmp_path):
        auth, w = self._make(tmp_path)
        self._trip_lockout(auth, w)
        assert auth.lockout_until > 0

        # New controller instance = process restart; same state file.
        auth2, w2 = self._make(tmp_path)
        assert auth2.lockout_until == pytest.approx(auth.lockout_until)
        w2.login_pin = "7531"
        auth2.handle_login()
        assert w2.current_user is None  # still locked

    def test_failed_count_survives_restart(self, tmp_path):
        auth, w = self._make(tmp_path)
        for _ in range(3):
            w.login_pin = "0000"
            auth.handle_login()

        auth2, w2 = self._make(tmp_path)
        assert auth2.failed_logins == 3
        # Two more failures after "reboot" trip the threshold of five.
        for _ in range(2):
            w2.login_pin = "0000"
            auth2.handle_login()
        assert auth2.lockout_until > 0

    def test_exponential_backoff_doubles_and_caps(self, tmp_path):
        auth, w = self._make(tmp_path)
        assert auth._lockout_duration() == 60
        auth.lockout_count = 1
        assert auth._lockout_duration() == 120
        auth.lockout_count = 2
        assert auth._lockout_duration() == 240
        auth.lockout_count = 10
        assert auth._lockout_duration() == AuthController.LOCKOUT_MAX_SECONDS

    def test_second_lockout_is_longer(self, tmp_path, monkeypatch):
        auth, w = self._make(tmp_path)
        self._trip_lockout(auth, w)
        first_until = auth.lockout_until

        # Fast-forward past the first lockout, fail five more times.
        monkeypatch.setattr(
            "controllers.auth_controller.time.time",
            lambda: first_until + 1,
        )
        self._trip_lockout(auth, w)
        assert auth.lockout_until - (first_until + 1) == pytest.approx(120, abs=1)

    def test_success_resets_backoff(self, tmp_path):
        auth, w = self._make(tmp_path)
        auth.lockout_count = 3
        w.login_pin = "7531"
        auth.handle_login()
        assert auth.lockout_count == 0
        # And the reset is persisted.
        auth2, _ = self._make(tmp_path)
        assert auth2.lockout_count == 0

    def test_corrupt_state_file_starts_clean(self, tmp_path):
        (tmp_path / "auth_state.json").write_text("{not json", encoding="utf-8")
        auth, w = self._make(tmp_path)
        assert auth.failed_logins == 0
        assert auth.lockout_until == 0.0
        w.login_pin = "7531"
        auth.handle_login()
        assert w.current_user is not None

    def test_pin_never_logged(self, tmp_path, caplog):
        """Audit logging must not leak the attempted PIN."""
        import logging as _logging

        auth, w = self._make(tmp_path)
        with caplog.at_level(_logging.DEBUG):
            w.login_pin = "13372"
            auth.handle_login()
            self._trip_lockout(auth, w)
        for record in caplog.records:
            assert "13372" not in record.getMessage()
            assert "0000" not in record.getMessage()


# ---------------------------------------------------------------------------
# Environment-driven user loading + validate_pin (from the GUI line, adapted:
# plaintext env PINs are now hashed with the salted hash_pin_secure, so the
# user key is no longer predictable from the PIN — verify through verify_pin).
# ---------------------------------------------------------------------------
import hashlib

# Environment variables that influence user loading. Cleared before each test
# so the OS/CI environment cannot leak real values into assertions.
_AUTH_ENV_VARS = [
    "ADMIN_PIN_HASH",
    "ADMIN_PIN",
    "ADMIN_USERNAME",
    "ADMIN_EMAIL",
    "USER_PIN_HASH",
    "USER_PIN",
    "USER_USERNAME",
    "USER_EMAIL",
]


@pytest.fixture
def clean_auth_env(monkeypatch):
    """Remove all auth-related env vars so each test starts from a clean slate."""
    for var in _AUTH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.mark.unit
class TestHashPinLegacy:
    """The legacy unsalted hash_pin (kept only so deployed hashes verify)."""

    def test_matches_sha256_hexdigest(self):
        expected = hashlib.sha256("1234".encode()).hexdigest()
        assert SecureAuthHelper.hash_pin("1234") == expected

    def test_is_deterministic(self):
        assert SecureAuthHelper.hash_pin("9999") == SecureAuthHelper.hash_pin("9999")

    def test_different_inputs_produce_different_hashes(self):
        assert SecureAuthHelper.hash_pin("1234") != SecureAuthHelper.hash_pin("4321")

    def test_returns_64_char_hex_string(self):
        result = SecureAuthHelper.hash_pin("0000")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_numeric_and_string_pin_hash_equal(self):
        """An int PIN and its string form hash identically (str() coercion)."""
        assert SecureAuthHelper.hash_pin(1234) == SecureAuthHelper.hash_pin("1234")


@pytest.mark.unit
class TestLoadSecureUsers:
    """Tests for environment-driven user loading via _load_secure_users."""

    def test_no_env_users_returns_none(self, clean_auth_env):
        """With no env vars set, user loading signals CSV fallback (None)."""
        helper = SecureAuthHelper()
        assert helper.users is None

    def test_admin_pin_hash_env_loads_admin(self, clean_auth_env):
        """ADMIN_PIN_HASH directly populates an admin user keyed by that hash."""
        admin_hash = SecureAuthHelper.hash_pin("1111")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)

        helper = SecureAuthHelper()

        assert admin_hash in helper.users
        entry = helper.users[admin_hash]
        assert entry["status"] == "admin"
        assert entry["pin_hash"] == admin_hash

    def test_admin_pin_plaintext_env_is_salted(self, clean_auth_env):
        """ADMIN_PIN (plaintext) is hashed with the SALTED hash_pin_secure —
        the legacy predictable-key behavior is deliberately gone."""
        clean_auth_env.setenv("ADMIN_PIN", "2222")

        helper = SecureAuthHelper()

        assert len(helper.users) == 1
        key = next(iter(helper.users))
        assert key.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.hash_pin("2222") not in helper.users
        assert SecureAuthHelper.verify_pin("2222", key)
        assert helper.users[key]["status"] == "admin"

    def test_admin_pin_hash_takes_precedence_over_plaintext(self, clean_auth_env):
        """When both ADMIN_PIN_HASH and ADMIN_PIN are set, the hash wins."""
        admin_hash = SecureAuthHelper.hash_pin("hashed-value")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)
        clean_auth_env.setenv("ADMIN_PIN", "9999")

        helper = SecureAuthHelper()

        assert admin_hash in helper.users
        # The plaintext PIN must not produce a second entry.
        assert len(helper.users) == 1

    def test_user_pin_hash_env_loads_user(self, clean_auth_env):
        """USER_PIN_HASH populates a regular user keyed by that hash."""
        user_hash = SecureAuthHelper.hash_pin("3333")
        clean_auth_env.setenv("USER_PIN_HASH", user_hash)

        helper = SecureAuthHelper()

        assert user_hash in helper.users
        assert helper.users[user_hash]["status"] == "user"

    def test_user_pin_plaintext_env_is_salted(self, clean_auth_env):
        """USER_PIN (plaintext) is hashed with the salted hash_pin_secure."""
        clean_auth_env.setenv("USER_PIN", "4444")

        helper = SecureAuthHelper()

        assert len(helper.users) == 1
        key = next(iter(helper.users))
        assert key.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.verify_pin("4444", key)
        assert helper.users[key]["status"] == "user"

    def test_both_admin_and_user_loaded(self, clean_auth_env):
        """Admin and user entries coexist when both env hashes are set."""
        admin_hash = SecureAuthHelper.hash_pin("1111")
        user_hash = SecureAuthHelper.hash_pin("2222")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)
        clean_auth_env.setenv("USER_PIN_HASH", user_hash)

        helper = SecureAuthHelper()

        assert len(helper.users) == 2
        assert helper.users[admin_hash]["status"] == "admin"
        assert helper.users[user_hash]["status"] == "user"

    def test_default_username_and_email_for_admin(self, clean_auth_env):
        """Admin defaults to Administrator / admin@example.com when unset."""
        admin_hash = SecureAuthHelper.hash_pin("1111")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)

        helper = SecureAuthHelper()

        entry = helper.users[admin_hash]
        assert entry["username"] == "Administrator"
        assert entry["email"] == "admin@example.com"

    def test_custom_admin_username_and_email(self, clean_auth_env):
        """ADMIN_USERNAME / ADMIN_EMAIL override the admin defaults."""
        admin_hash = SecureAuthHelper.hash_pin("1111")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)
        clean_auth_env.setenv("ADMIN_USERNAME", "Dr. Smith")
        clean_auth_env.setenv("ADMIN_EMAIL", "smith@clinic.test")

        helper = SecureAuthHelper()

        entry = helper.users[admin_hash]
        assert entry["username"] == "Dr. Smith"
        assert entry["email"] == "smith@clinic.test"

    def test_default_username_and_email_for_user(self, clean_auth_env):
        """Regular user defaults to User / user@example.com when unset."""
        user_hash = SecureAuthHelper.hash_pin("3333")
        clean_auth_env.setenv("USER_PIN_HASH", user_hash)

        helper = SecureAuthHelper()

        entry = helper.users[user_hash]
        assert entry["username"] == "User"
        assert entry["email"] == "user@example.com"


@pytest.mark.unit
class TestValidatePin:
    """Tests for PIN validation against loaded users (verify_pin loop)."""

    def test_correct_admin_pin_returns_user(self, clean_auth_env):
        """A matching admin PIN returns its user dict (salted verify)."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = SecureAuthHelper()
        result = helper.validate_pin("1234")

        assert result is not None
        assert result["status"] == "admin"

    def test_correct_user_pin_returns_user(self, clean_auth_env):
        """A matching regular-user PIN returns its user dict."""
        clean_auth_env.setenv("USER_PIN", "5678")

        helper = SecureAuthHelper()
        result = helper.validate_pin("5678")

        assert result is not None
        assert result["status"] == "user"

    def test_wrong_pin_returns_none(self, clean_auth_env):
        """A non-matching PIN returns None."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = SecureAuthHelper()
        assert helper.validate_pin("0000") is None

    def test_unknown_user_when_no_users_loaded(self, clean_auth_env):
        """With CSV-fallback (users is None), validation returns None."""
        helper = SecureAuthHelper()
        assert helper.users is None
        assert helper.validate_pin("1234") is None

    def test_validate_pin_rehashes_input(self, clean_auth_env):
        """Validation verifies the input PIN, never treats it as a hash."""
        pin = "4321"
        clean_auth_env.setenv("ADMIN_PIN_HASH", SecureAuthHelper.hash_pin(pin))

        helper = SecureAuthHelper()

        # Correct plaintext PIN validates (legacy hash still verifies)...
        assert helper.validate_pin(pin) is not None
        # ...but the raw hash string is NOT a valid PIN (it gets re-hashed).
        assert helper.validate_pin(SecureAuthHelper.hash_pin(pin)) is None

    def test_numeric_pin_validates(self, clean_auth_env):
        """An int PIN validates against a hash created from its string form."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = SecureAuthHelper()
        assert helper.validate_pin(1234) is not None
