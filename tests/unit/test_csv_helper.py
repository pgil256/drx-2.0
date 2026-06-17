# tests/unit/test_csv_helper.py
"""Unit tests for CSVHelper (main/helpers/csv.py).

CSVHelper loads user/PIN records either from environment variables (via
SecureAuthHelper) or, as a fallback, from a hashed CSV file. These tests cover:

  * load_csv() with a valid CSV, a missing file, and malformed rows
  * the legacy plaintext-pin -> hash conversion path
  * initialize_data() using the environment-variable override
  * initialize_data() falling back to the bundled CSV file

All tests assert CURRENT behavior and run on Windows (tmp_path + monkeypatch,
no pty / POSIX gating).
"""

import hashlib

import pytest

import helpers.csv as csv_module
from helpers.csv import CSVHelper
from helpers.secure_auth import SecureAuthHelper


# Environment variables that SecureAuthHelper reads. They are cleared at the
# start of every test so the host environment cannot leak into the results.
_AUTH_ENV_VARS = (
    "ADMIN_PIN_HASH",
    "ADMIN_PIN",
    "ADMIN_USERNAME",
    "ADMIN_EMAIL",
    "USER_PIN_HASH",
    "USER_PIN",
    "USER_USERNAME",
    "USER_EMAIL",
)


@pytest.fixture
def clean_auth_env(monkeypatch):
    """Ensure no SecureAuthHelper environment variables are set."""
    for name in _AUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture(autouse=True)
def stub_message_box(monkeypatch):
    """Replace QMessageBox.critical with a recorder.

    On Windows with a real PyQt5 installed, the production error handlers in
    load_csv call QMessageBox.critical(None, ...). Creating a real modal dialog
    without a running QApplication crashes the interpreter, so we patch the
    reference that helpers.csv resolves at runtime. This is a test-local stub of
    a UI side effect; no production logic is changed.

    The list of recorded (title, message) tuples is exposed via the fixture so
    tests can assert that an error dialog *would* have been shown.
    """
    calls = []

    class _StubMessageBox:
        @staticmethod
        def critical(parent, title, message):
            calls.append((title, message))

    monkeypatch.setattr(csv_module, "QMessageBox", _StubMessageBox)
    return calls


def _sha256(value):
    """Return the sha256 hex digest the helper uses for PINs."""
    return hashlib.sha256(str(value).encode()).hexdigest()


def _write_csv(tmp_path, rows, header="pin_hash,username,email,status"):
    """Write a CSV file from a list of raw row strings and return its path."""
    csv_path = tmp_path / "user_pins.csv"
    contents = header + "\n" + "\n".join(rows) + "\n"
    csv_path.write_text(contents, encoding="utf-8")
    return csv_path


@pytest.mark.unit
class TestLoadCsvValidFile:
    """Tests for load_csv() with a well-formed CSV file."""

    def test_loads_all_rows_keyed_by_pin_hash(self, tmp_path):
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            [
                "hash_admin,Administrator,admin@example.com,admin",
                "hash_user,User,user@example.com,user",
            ],
        )

        data = helper.load_csv(str(csv_path))

        assert set(data.keys()) == {"hash_admin", "hash_user"}
        assert data["hash_admin"]["username"] == "Administrator"
        assert data["hash_user"]["status"] == "user"

    def test_row_includes_pin_hash_field(self, tmp_path):
        """Each loaded row retains its pin_hash value as a field."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["hash_admin,Administrator,admin@example.com,admin"],
        )

        data = helper.load_csv(str(csv_path))

        assert data["hash_admin"]["pin_hash"] == "hash_admin"

    def test_empty_file_with_header_returns_empty(self, tmp_path):
        """A CSV with only a header (no data rows) yields an empty dict."""
        helper = CSVHelper()
        csv_path = _write_csv(tmp_path, [])  # header only

        data = helper.load_csv(str(csv_path))

        assert data == {}


@pytest.mark.unit
class TestLoadCsvLegacyPin:
    """Tests for the legacy plaintext-pin -> hashed-pin conversion."""

    def test_plaintext_pin_is_hashed(self, tmp_path):
        """A 'pin' column (no pin_hash) is hashed in memory and used as key."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["1234,Administrator,admin@example.com,admin"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        expected_hash = _sha256("1234")
        assert expected_hash in data
        assert data[expected_hash]["username"] == "Administrator"

    def test_plaintext_pin_removed_from_row(self, tmp_path):
        """The plaintext 'pin' value must not survive in the loaded row."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["1234,Administrator,admin@example.com,admin"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        row = data[_sha256("1234")]
        assert "pin" not in row
        assert row["pin_hash"] == _sha256("1234")

    def test_hash_matches_secure_auth_helper(self, tmp_path):
        """Legacy hashing uses the same algorithm as SecureAuthHelper.hash_pin."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["9999,User,user@example.com,user"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        assert SecureAuthHelper.hash_pin("9999") in data


@pytest.mark.unit
class TestLoadCsvMissingFile:
    """Tests for load_csv() when the file does not exist."""

    def test_missing_file_returns_empty_dict(self, tmp_path):
        """A missing file is handled gracefully and yields an empty dict."""
        helper = CSVHelper()
        missing = tmp_path / "does_not_exist.csv"

        data = helper.load_csv(str(missing))

        assert data == {}

    def test_missing_file_does_not_raise(self, tmp_path):
        """load_csv must not raise FileNotFoundError to the caller."""
        helper = CSVHelper()
        missing = tmp_path / "nope.csv"

        # Should simply return without propagating an exception.
        helper.load_csv(str(missing))

    def test_missing_file_shows_error_dialog(self, tmp_path, stub_message_box):
        """A missing file triggers the error dialog side effect."""
        helper = CSVHelper()
        missing = tmp_path / "absent.csv"

        helper.load_csv(str(missing))

        assert len(stub_message_box) == 1
        title, _message = stub_message_box[0]
        assert title == "Error"


@pytest.mark.unit
class TestLoadCsvMalformed:
    """Tests for load_csv() with malformed / incomplete data."""

    def test_missing_pin_hash_column_does_not_crash(self, tmp_path, stub_message_box):
        """A CSV lacking both pin_hash and pin is handled without crashing."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["Administrator,admin@example.com,admin"],
            header="username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        # The KeyError raised on the first row is caught; no valid rows loaded.
        assert data == {}
        # The format error surfaces via the error dialog rather than an exception.
        assert len(stub_message_box) == 1

    def test_partial_rows_loaded_before_bad_row(self, tmp_path):
        """Rows preceding a row missing pin_hash are still returned.

        load_csv catches the KeyError that aborts iteration, so any rows added
        before the offending row remain in the returned dict.
        """
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            [
                "hash_good,Good User,good@example.com,user",
                ",Bad User,bad@example.com,user",  # empty pin_hash -> KeyError
            ],
        )

        data = helper.load_csv(str(csv_path))

        assert "hash_good" in data
        assert data["hash_good"]["username"] == "Good User"

    def test_extra_columns_do_not_crash(self, tmp_path):
        """Rows with extra unmapped columns are tolerated (csv None key)."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["hash_admin,Administrator,admin@example.com,admin,EXTRA"],
        )

        data = helper.load_csv(str(csv_path))

        assert "hash_admin" in data
        assert data["hash_admin"]["username"] == "Administrator"


@pytest.mark.unit
class TestInitializeDataEnvOverride:
    """Tests for initialize_data() using environment-variable users."""

    def test_admin_plaintext_pin_hashed(self, clean_auth_env):
        """ADMIN_PIN is hashed and used as the user key."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = CSVHelper()
        helper.initialize_data()

        expected_hash = _sha256("1234")
        assert expected_hash in helper.users
        assert helper.users[expected_hash]["status"] == "admin"
        assert helper.users[expected_hash]["pin_hash"] == expected_hash

    def test_user_plaintext_pin_hashed(self, clean_auth_env):
        """USER_PIN is hashed and used as the user key."""
        clean_auth_env.setenv("USER_PIN", "5678")

        helper = CSVHelper()
        helper.initialize_data()

        expected_hash = _sha256("5678")
        assert expected_hash in helper.users
        assert helper.users[expected_hash]["status"] == "user"

    def test_admin_and_user_both_loaded(self, clean_auth_env):
        """Both ADMIN_PIN and USER_PIN produce two distinct user records."""
        clean_auth_env.setenv("ADMIN_PIN", "1111")
        clean_auth_env.setenv("USER_PIN", "2222")

        helper = CSVHelper()
        helper.initialize_data()

        assert _sha256("1111") in helper.users
        assert _sha256("2222") in helper.users
        assert len(helper.users) == 2

    def test_prehashed_pin_used_as_is(self, clean_auth_env):
        """ADMIN_PIN_HASH is used directly without re-hashing."""
        pin_hash = _sha256("9999")
        clean_auth_env.setenv("ADMIN_PIN_HASH", pin_hash)

        helper = CSVHelper()
        helper.initialize_data()

        assert pin_hash in helper.users
        # The stored key must be the provided hash, not a hash of the hash.
        assert _sha256(pin_hash) not in helper.users

    def test_username_and_email_overrides(self, clean_auth_env):
        """Custom ADMIN_USERNAME / ADMIN_EMAIL are reflected in the record."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")
        clean_auth_env.setenv("ADMIN_USERNAME", "Dr. Alice")
        clean_auth_env.setenv("ADMIN_EMAIL", "alice@clinic.example")

        helper = CSVHelper()
        helper.initialize_data()

        record = helper.users[_sha256("1234")]
        assert record["username"] == "Dr. Alice"
        assert record["email"] == "alice@clinic.example"


@pytest.mark.unit
class TestInitializeDataCsvFallback:
    """Tests for initialize_data() falling back to a CSV file."""

    def test_falls_back_to_bundled_csv(self, clean_auth_env):
        """With no env users, initialize_data loads the bundled hashed CSV.

        The repository ships main/data/user_pins.csv with two hashed records.
        With the auth environment cleared, initialize_data must read that file.
        """
        helper = CSVHelper()
        helper.initialize_data()

        # The bundled CSV contains exactly two user records, keyed by hash.
        assert len(helper.users) == 2
        for key, row in helper.users.items():
            assert row["pin_hash"] == key
            assert "status" in row

    def test_fallback_keys_are_hashes_not_plaintext(self, clean_auth_env):
        """Fallback records are keyed by pin_hash, never by a plaintext pin."""
        helper = CSVHelper()
        helper.initialize_data()

        # Bundled CSV uses 64-char sha256 hex digests as keys.
        assert all(len(key) == 64 for key in helper.users)
