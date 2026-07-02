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
import logging

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


@pytest.fixture
def no_qapplication(monkeypatch):
    """Make load_csv observe that no QApplication event loop is running.

    Forcing QApplication.instance() to return None makes the headless code
    path deterministic regardless of whether an earlier Qt test left a
    session-wide QApplication alive.
    """

    class _NoQApplication:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr(csv_module, "QApplication", _NoQApplication)
    return _NoQApplication


@pytest.fixture
def with_qapplication(monkeypatch):
    """Make load_csv observe a running QApplication event loop."""
    sentinel = object()

    class _RunningQApplication:
        @staticmethod
        def instance():
            return sentinel

    monkeypatch.setattr(csv_module, "QApplication", _RunningQApplication)
    return _RunningQApplication


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
    """Tests for the legacy plaintext-pin -> hashed-pin conversion.

    Since the FAILSAFE branch the in-memory migration is SALTED
    (hash_pin_secure), so the resulting key is non-deterministic: assert
    on the format and on verify_pin round-trips, never on a precomputed
    digest.
    """

    def test_plaintext_pin_is_hashed(self, tmp_path):
        """A 'pin' column (no pin_hash) is hashed in memory and used as key."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["1234,Administrator,admin@example.com,admin"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        assert len(data) == 1
        stored_hash, row = next(iter(data.items()))
        assert "1234" not in stored_hash
        assert row["username"] == "Administrator"

    def test_plaintext_pin_removed_from_row(self, tmp_path):
        """The plaintext 'pin' value must not survive in the loaded row."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["1234,Administrator,admin@example.com,admin"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        stored_hash, row = next(iter(data.items()))
        assert "pin" not in row
        assert row["pin_hash"] == stored_hash

    def test_migrated_hash_is_salted_and_verifiable(self, tmp_path):
        """The migration uses the salted PBKDF2 format (no reversible
        digest is ever held) and the PIN still verifies against it."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["9999,User,user@example.com,user"],
            header="pin,username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        assert len(data) == 1
        stored_hash = next(iter(data))
        assert stored_hash.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.verify_pin("9999", stored_hash)
        assert not SecureAuthHelper.verify_pin("0000", stored_hash)


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

    def test_missing_file_shows_error_dialog_when_qapp_present(
        self, tmp_path, stub_message_box, with_qapplication
    ):
        """With a running QApplication, a missing file shows the error dialog."""
        helper = CSVHelper()
        missing = tmp_path / "absent.csv"

        helper.load_csv(str(missing))

        assert len(stub_message_box) == 1
        title, _message = stub_message_box[0]
        assert title == "Error"


@pytest.mark.unit
class TestLoadCsvMalformed:
    """Tests for load_csv() with malformed / incomplete data."""

    def test_missing_pin_hash_column_does_not_crash(
        self, tmp_path, stub_message_box, with_qapplication
    ):
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
        # With a QApplication running, the format error surfaces via the dialog.
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
        """ADMIN_PIN is salted-hashed (hash_pin_secure) and used as the key."""
        clean_auth_env.setenv("ADMIN_PIN", "1234")

        helper = CSVHelper()
        helper.initialize_data()

        assert len(helper.users) == 1
        stored_hash, record = next(iter(helper.users.items()))
        assert stored_hash.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.verify_pin("1234", stored_hash)
        assert record["status"] == "admin"
        assert record["pin_hash"] == stored_hash

    def test_user_plaintext_pin_hashed(self, clean_auth_env):
        """USER_PIN is salted-hashed and used as the user key."""
        clean_auth_env.setenv("USER_PIN", "5678")

        helper = CSVHelper()
        helper.initialize_data()

        assert len(helper.users) == 1
        stored_hash, record = next(iter(helper.users.items()))
        assert SecureAuthHelper.verify_pin("5678", stored_hash)
        assert record["status"] == "user"

    def test_admin_and_user_both_loaded(self, clean_auth_env):
        """Both ADMIN_PIN and USER_PIN produce two distinct user records."""
        clean_auth_env.setenv("ADMIN_PIN", "1111")
        clean_auth_env.setenv("USER_PIN", "2222")

        helper = CSVHelper()
        helper.initialize_data()

        assert len(helper.users) == 2
        by_status = {rec["status"]: h for h, rec in helper.users.items()}
        assert SecureAuthHelper.verify_pin("1111", by_status["admin"])
        assert SecureAuthHelper.verify_pin("2222", by_status["user"])

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

        assert len(helper.users) == 1
        record = next(iter(helper.users.values()))
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


@pytest.mark.unit
class TestLoadCsvHeadlessRobustness:
    """load_csv must not crash when no QApplication event loop is running.

    QMessageBox.critical(None, ...) constructs a modal dialog. Without a
    running QApplication -- a missing or malformed user_pins.csv at startup
    before the Qt event loop is up, or any headless context -- constructing
    that dialog aborts the interpreter (observed as STATUS_STACK_BUFFER_OVERRUN,
    exit -1073740791). On a patient-facing device that turns a recoverable data
    error into a hard crash. The fix guards the dialog behind
    QApplication.instance() and logs the error instead, degrading to an empty
    user set rather than crashing.
    """

    def test_missing_file_no_dialog_without_qapp(
        self, tmp_path, stub_message_box, no_qapplication
    ):
        """Missing file + no QApplication: empty dict, dialog suppressed."""
        helper = CSVHelper()
        missing = tmp_path / "absent.csv"

        data = helper.load_csv(str(missing))

        assert data == {}
        # The dialog (and thus the process-aborting code path) is never reached.
        assert len(stub_message_box) == 0

    def test_malformed_no_dialog_without_qapp(
        self, tmp_path, stub_message_box, no_qapplication
    ):
        """Malformed CSV + no QApplication: empty dict, dialog suppressed."""
        helper = CSVHelper()
        csv_path = _write_csv(
            tmp_path,
            ["Administrator,admin@example.com,admin"],
            header="username,email,status",
        )

        data = helper.load_csv(str(csv_path))

        assert data == {}
        assert len(stub_message_box) == 0

    def test_real_message_box_never_constructed_without_qapp(
        self, tmp_path, no_qapplication, monkeypatch
    ):
        """The guard must short-circuit before QMessageBox is ever touched.

        Replaces QMessageBox with one that raises if .critical is called, so
        the test fails loudly if the guard regresses (rather than relying only
        on a recording stub returning zero calls).
        """

        class _ExplodingMessageBox:
            @staticmethod
            def critical(parent, title, message):
                raise AssertionError(
                    "QMessageBox.critical called without a QApplication"
                )

        monkeypatch.setattr(csv_module, "QMessageBox", _ExplodingMessageBox)

        helper = CSVHelper()
        missing = tmp_path / "absent.csv"

        # Must not raise.
        assert helper.load_csv(str(missing)) == {}

    def test_error_is_logged_without_qapp(self, tmp_path, no_qapplication, caplog):
        """The failure is logged even when no dialog can be shown."""
        helper = CSVHelper()
        missing = tmp_path / "absent.csv"

        with caplog.at_level(logging.ERROR):
            helper.load_csv(str(missing))

        assert any(
            "absent.csv" in record.getMessage() for record in caplog.records
        )

    def test_initialize_data_survives_missing_csv(
        self, clean_auth_env, no_qapplication, monkeypatch, tmp_path
    ):
        """Startup with no env users and a missing CSV degrades to no users.

        This mirrors the real device scenario: SecureAuthHelper finds nothing,
        the bundled user_pins.csv is absent, and initialize_data falls back to
        load_csv. It must not crash even though no Qt event loop exists yet.
        """
        missing = str(tmp_path / "user_pins.csv")  # tmp_path is empty
        real_join = csv_module.os.path.join

        def fake_join(*parts):
            if parts and str(parts[-1]) == "user_pins.csv":
                return missing
            return real_join(*parts)

        monkeypatch.setattr(csv_module.os.path, "join", fake_join)

        helper = CSVHelper()
        helper.initialize_data()

        assert helper.users == {}
