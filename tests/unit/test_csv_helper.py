# tests/unit/test_csv_helper.py
"""Tests for the user-PIN CSV loader (the audit's last 0%-coverage
helper with a named missing test: the legacy plaintext-pin migration)."""
import pytest
from unittest.mock import patch

from helpers.csv import CSVHelper
from helpers.secure_auth import SecureAuthHelper


def write_csv(tmp_path, content):
    path = tmp_path / "user_pins.csv"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.mark.unit
class TestLoadCsv:
    def test_loads_hashed_rows(self, tmp_path):
        stored = SecureAuthHelper.hash_pin("1234")
        path = write_csv(
            tmp_path,
            "pin_hash,username,email,status\n"
            f"{stored},Admin,admin@x.test,admin\n",
        )
        users = CSVHelper().load_csv(path)
        assert stored in users
        assert users[stored]["username"] == "Admin"
        assert users[stored]["status"] == "admin"

    def test_legacy_plaintext_pin_migrates_in_memory(self, tmp_path):
        """A legacy 'pin' column must be converted to a salted hash in
        memory, the plaintext dropped, and the PIN still verifiable."""
        path = write_csv(
            tmp_path,
            "pin,username,email,status\n"
            "8642,Operator,op@x.test,user\n",
        )
        users = CSVHelper().load_csv(path)
        assert len(users) == 1
        stored_hash, row = next(iter(users.items()))
        # Plaintext is gone from the loaded data
        assert "pin" not in row
        assert "8642" not in stored_hash
        # The migrated hash is the salted PBKDF2 format, not bare SHA-256
        assert stored_hash.startswith("pbkdf2_sha256$")
        assert SecureAuthHelper.verify_pin("8642", stored_hash)
        assert not SecureAuthHelper.verify_pin("0000", stored_hash)

    def test_missing_file_returns_empty(self, tmp_path):
        # The error path pops a QMessageBox; creating a real widget
        # without a QApplication aborts the interpreter
        with patch("helpers.csv.QMessageBox") as box:
            users = CSVHelper().load_csv(str(tmp_path / "nope.csv"))
        assert users == {}
        assert box.critical.called

    def test_missing_pin_columns_handled(self, tmp_path):
        path = write_csv(
            tmp_path,
            "username,email,status\n"
            "Ghost,g@x.test,user\n",
        )
        with patch("helpers.csv.QMessageBox") as box:
            users = CSVHelper().load_csv(path)
        assert users == {}
        assert box.critical.called
