# tests/unit/test_secure_auth.py
"""Unit tests for SecureAuthHelper (main/helpers/secure_auth.py).

These tests assert CURRENT behavior of PIN hashing, validation, and the
environment-variable-driven user loading. They are Windows-runnable: all
environment manipulation is done via pytest's monkeypatch, with no pty/POSIX
dependencies.
"""

import hashlib

import pytest

from helpers.secure_auth import SecureAuthHelper


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
class TestHashPin:
    """Tests for the static hash_pin method."""

    def test_matches_sha256_hexdigest(self):
        """hash_pin returns the SHA-256 hex digest of the stringified PIN."""
        expected = hashlib.sha256("1234".encode()).hexdigest()
        assert SecureAuthHelper.hash_pin("1234") == expected

    def test_is_deterministic(self):
        """Hashing the same PIN twice yields identical results."""
        assert SecureAuthHelper.hash_pin("9999") == SecureAuthHelper.hash_pin("9999")

    def test_different_inputs_produce_different_hashes(self):
        """Distinct PINs map to distinct hashes."""
        assert SecureAuthHelper.hash_pin("1234") != SecureAuthHelper.hash_pin("4321")

    def test_returns_64_char_hex_string(self):
        """SHA-256 hex digests are 64 lowercase hex characters."""
        result = SecureAuthHelper.hash_pin("0000")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_numeric_and_string_pin_hash_equal(self):
        """An int PIN and its string form hash identically (str() coercion)."""
        assert SecureAuthHelper.hash_pin(1234) == SecureAuthHelper.hash_pin("1234")

    def test_callable_without_instance(self):
        """hash_pin is a staticmethod callable on the class directly."""
        # Should not raise even though no instance is constructed.
        assert isinstance(SecureAuthHelper.hash_pin("abc"), str)


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

    def test_admin_pin_plaintext_env_is_hashed(self, clean_auth_env):
        """ADMIN_PIN (plaintext) is hashed and used as the user key."""
        clean_auth_env.setenv("ADMIN_PIN", "2222")
        expected_hash = SecureAuthHelper.hash_pin("2222")

        helper = SecureAuthHelper()

        assert expected_hash in helper.users
        assert helper.users[expected_hash]["status"] == "admin"

    def test_admin_pin_hash_takes_precedence_over_plaintext(self, clean_auth_env):
        """When both ADMIN_PIN_HASH and ADMIN_PIN are set, the hash wins."""
        admin_hash = SecureAuthHelper.hash_pin("hashed-value")
        clean_auth_env.setenv("ADMIN_PIN_HASH", admin_hash)
        clean_auth_env.setenv("ADMIN_PIN", "9999")

        helper = SecureAuthHelper()

        assert admin_hash in helper.users
        # The plaintext PIN's hash should NOT be used as a key.
        assert SecureAuthHelper.hash_pin("9999") not in helper.users

    def test_user_pin_hash_env_loads_user(self, clean_auth_env):
        """USER_PIN_HASH populates a regular user keyed by that hash."""
        user_hash = SecureAuthHelper.hash_pin("3333")
        clean_auth_env.setenv("USER_PIN_HASH", user_hash)

        helper = SecureAuthHelper()

        assert user_hash in helper.users
        assert helper.users[user_hash]["status"] == "user"

    def test_user_pin_plaintext_env_is_hashed(self, clean_auth_env):
        """USER_PIN (plaintext) is hashed and used as the user key."""
        clean_auth_env.setenv("USER_PIN", "4444")
        expected_hash = SecureAuthHelper.hash_pin("4444")

        helper = SecureAuthHelper()

        assert expected_hash in helper.users
        assert helper.users[expected_hash]["status"] == "user"

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
    """Tests for PIN validation against loaded users."""

    def test_correct_admin_pin_returns_user(self, clean_auth_env):
        """A matching admin PIN returns its user dict."""
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

    def test_validate_pin_uses_hash_lookup(self, clean_auth_env):
        """Validation hashes the input PIN before lookup (not plaintext)."""
        pin = "4321"
        clean_auth_env.setenv("ADMIN_PIN_HASH", SecureAuthHelper.hash_pin(pin))

        helper = SecureAuthHelper()

        # Correct plaintext PIN validates...
        assert helper.validate_pin(pin) is not None
        # ...but the raw hash string is NOT a valid PIN (it gets re-hashed).
        assert helper.validate_pin(SecureAuthHelper.hash_pin(pin)) is None

    def test_numeric_pin_validates(self, clean_auth_env):
        """An int PIN validates against a hash created from its string form."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = SecureAuthHelper()
        # str(1234) == "1234", so the hashes match.
        assert helper.validate_pin(1234) is not None
