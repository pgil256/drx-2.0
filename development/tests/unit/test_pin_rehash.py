"""Legacy unsalted PIN hashes are upgraded to PBKDF2 at login, never rejected.

A leaked user_pins.csv with bare SHA-256 digests of short numeric PINs is
reversible instantly. Legacy hashes keep working, but a successful login
rewrites that CSV row with a salted PBKDF2 hash. Environment hashes cannot be
rewritten and are only reported. Stored PBKDF2 hashes are bounded to the
100k-1M iteration range, so a tampered row cannot freeze the login screen.
"""
import csv
import hashlib
import logging

import pytest

from config.constants import APP_NAME, DATA_PATHS
from controllers.auth_controller import AuthController
from helpers.csv import CSVHelper
from helpers.secure_auth import SecureAuthHelper

pytestmark = pytest.mark.unit

PIN = "7531"
LEGACY = hashlib.sha256(PIN.encode()).hexdigest()
FIELDS = ["pin_hash", "username", "email", "status", "note"]


class Window:
    def __init__(self, users, csv_helper=None):
        self.users = users
        self.csv = csv_helper
        self.current_user = None
        self.errors = []

    def _show_timed_error(self, message):
        self.errors.append(message)

    def update_ui_after_login(self):
        pass


def write_users(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_users(path):
    with open(path, newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def pins(tmp_path, monkeypatch):
    path = tmp_path / "user_pins.csv"
    write_users(path, [
        {"pin_hash": LEGACY, "username": "Legacy", "email": "l@x", "status": "user",
         "note": "keep me"},
        {"pin_hash": SecureAuthHelper.hash_pin_secure("2468"), "username": "Other",
         "email": "o@x", "status": "admin", "note": ""},
    ])
    monkeypatch.setitem(DATA_PATHS, "USER_PINS", str(path))
    monkeypatch.delenv("ADMIN_PIN_HASH", raising=False)
    monkeypatch.delenv("USER_PIN_HASH", raising=False)
    helper = CSVHelper()
    helper.users = helper.load_csv(str(path))
    return path, helper


def login(tmp_path, window, pin=PIN):
    auth = AuthController(window, state_path=str(tmp_path / "auth_state.json"))
    auth.handle_login(pin)
    return auth


def test_legacy_csv_hash_is_rewritten_after_a_successful_login(tmp_path, pins, caplog):
    path, helper = pins
    window = Window(helper.users, helper)
    other_before = read_users(path)[1]

    with caplog.at_level(logging.WARNING, logger=APP_NAME):
        login(tmp_path, window)

    assert window.current_user["username"] == "Legacy"
    legacy_row, other_row = read_users(path)
    assert legacy_row["pin_hash"].startswith("pbkdf2_sha256$")
    assert SecureAuthHelper.verify_pin(PIN, legacy_row["pin_hash"])
    assert legacy_row["note"] == "keep me" and other_row == other_before
    assert LEGACY not in window.users and legacy_row["pin_hash"] in window.users
    assert "Upgraded a legacy unsalted PIN hash" in caplog.text

    # The next login uses the new hash and rewrites nothing.
    rewritten = path.read_bytes()
    window.current_user = None
    login(tmp_path, window)
    assert window.current_user["username"] == "Legacy"
    assert path.read_bytes() == rewritten


def test_legacy_hash_from_the_environment_is_reported_not_rewritten(
        tmp_path, pins, monkeypatch, caplog):
    path, helper = pins
    monkeypatch.setenv("USER_PIN_HASH", LEGACY)
    before = path.read_bytes()
    window = Window(helper.users, helper)

    with caplog.at_level(logging.WARNING, logger=APP_NAME):
        login(tmp_path, window)

    assert window.current_user["username"] == "Legacy"
    assert path.read_bytes() == before
    assert "from the environment" in caplog.text


def test_a_failed_rewrite_still_logs_in(tmp_path, pins, monkeypatch, caplog):
    _, helper = pins
    monkeypatch.setattr(helper, "replace_pin_hash", lambda *args: False)
    window = Window(helper.users, helper)

    with caplog.at_level(logging.WARNING, logger=APP_NAME):
        login(tmp_path, window)

    assert window.current_user["username"] == "Legacy"
    assert LEGACY in window.users
    assert "could not be upgraded" in caplog.text


def test_replace_pin_hash_refuses_unknown_rows_and_extra_cells(tmp_path):
    path = tmp_path / "user_pins.csv"
    write_users(path, [{"pin_hash": LEGACY, "username": "L", "email": "", "status": "user",
                        "note": ""}])
    helper = CSVHelper()
    assert not helper.replace_pin_hash(str(path), "0" * 64, "new")

    with open(path, "a", newline="", encoding="utf-8") as stream:
        stream.write("abc,U,,user,,unexpected-extra-cell\r\n")
    before = path.read_bytes()
    assert not helper.replace_pin_hash(str(path), LEGACY, "new")
    assert path.read_bytes() == before
    assert not (tmp_path / "user_pins.csv.tmp").exists()


def test_is_legacy_hash():
    assert SecureAuthHelper.is_legacy_hash(LEGACY)
    assert not SecureAuthHelper.is_legacy_hash(SecureAuthHelper.hash_pin_secure(PIN))
    assert not SecureAuthHelper.is_legacy_hash(LEGACY.upper())
    assert not SecureAuthHelper.is_legacy_hash(None)


@pytest.mark.parametrize("iterations,accepted", [
    (99_999, False), (100_000, True), (1_000_000, True), (1_000_001, False),
])
def test_pbkdf2_iteration_count_is_bounded(iterations, accepted):
    salt = bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", PIN.encode(), salt, iterations).hex()
    stored = f"pbkdf2_sha256${iterations}${salt.hex()}${digest}"
    assert SecureAuthHelper.verify_pin(PIN, stored) is accepted
