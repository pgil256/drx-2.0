"""Technician credentials cannot inherit patient credentials or bypass lockout."""

import json
from pathlib import Path

import pytest

from helpers.secure_auth import SecureAuthHelper
from helpers.service_auth import ServiceAccess

pytestmark = pytest.mark.unit


@pytest.fixture
def access(tmp_path, monkeypatch):
    monkeypatch.delenv("KNEESPA_SERVICE_PIN_HASH", raising=False)
    return ServiceAccess(str(tmp_path / "service-pin.json"))


def test_initial_pin_requires_admin_and_matching_six_digits(access):
    assert not access.configured
    assert not access.verify("123456")
    with pytest.raises(PermissionError):
        access.provision("123456", "123456", is_admin=False)
    with pytest.raises(ValueError, match="six digits"):
        access.provision("12345", "12345", is_admin=True)
    with pytest.raises(ValueError, match="does not match"):
        access.provision("123456", "654321", is_admin=True)
    assert not Path(access.path).exists()


def test_provision_stores_salted_hash_and_never_replaces_existing(access):
    access.provision("123456", "123456", is_admin=True)
    data = Path(access.path).read_text(encoding="utf-8")
    assert '"123456"' not in data
    assert json.loads(data)["pin_hash"].startswith("pbkdf2_sha256$200000$")
    assert access.configured
    assert access.verify("123456")
    assert ServiceAccess(access.path).verify("123456")
    with pytest.raises(ValueError, match="already configured"):
        access.provision("654321", "654321", is_admin=True)
    assert Path(access.path).read_text(encoding="utf-8") == data


def test_persistent_failures_and_lockout_across_reopened_wizards(access):
    access.provision("123456", "123456", is_admin=True)
    now = [100.0]
    for _ in range(5):
        attempt = ServiceAccess(access.path, clock=lambda: now[0])
        assert not attempt.verify("999999")
    assert attempt.lockout_remaining == 60
    reopened = ServiceAccess(access.path, clock=lambda: now[0])
    assert not reopened.verify("123456")
    now[0] += 59.1
    assert reopened.lockout_remaining == 1
    now[0] += 0.9
    assert reopened.verify("123456")
    assert reopened.lockout_remaining == 0
    assert json.loads(Path(access.path).read_text())["failures"] == 0


def test_failed_attempt_after_expiry_starts_new_window(access):
    access.provision("123456", "123456", is_admin=True)
    now = [100.0]
    subject = ServiceAccess(access.path, clock=lambda: now[0])
    for _ in range(5):
        assert not subject.verify("000000")
    now[0] += 61
    assert not subject.verify("000000")
    assert subject.lockout_remaining == 0
    assert json.loads(Path(access.path).read_text())["failures"] == 1


@pytest.mark.parametrize("pin", ["１２３４５６", "12345a", "12345", 123456, None])
def test_non_ascii_or_malformed_pins_are_rejected(access, pin):
    with pytest.raises(ValueError, match="six digits"):
        access.provision(pin, pin, is_admin=True)


def test_environment_hash_supports_service_access_without_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("KNEESPA_SERVICE_PIN_HASH", SecureAuthHelper.hash_pin_secure("654321"))
    subject = ServiceAccess(str(tmp_path / "service-pin.json"))
    assert subject.configured
    assert subject.verify("654321")
    assert not subject.verify("123456")
    assert subject.verify("654321")
    assert '"654321"' not in Path(subject.path).read_text()
    assert json.loads(Path(subject.path).read_text())["pin_hash"] == ""


def test_legacy_patient_hash_cannot_be_service_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("KNEESPA_SERVICE_PIN_HASH", SecureAuthHelper.hash_pin("123456"))
    subject = ServiceAccess(str(tmp_path / "service-pin.json"))
    assert subject.configured
    assert not subject.verify("123456")


@pytest.mark.parametrize("content", ["broken JSON", "[]", '{"pin_hash":"bad"}'])
def test_broken_existing_file_fails_closed(access, content):
    Path(access.path).write_text(content)
    subject = ServiceAccess(access.path)
    assert subject.configured
    with pytest.raises(ValueError, match="already configured"):
        subject.provision("123456", "123456", is_admin=True)
    with pytest.raises(ValueError, match="unreadable"):
        subject.verify("123456")
    assert Path(access.path).read_text() == content


def test_failed_credential_write_does_not_publish_or_leak_tempfile(access, monkeypatch):
    def fail_replace(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("helpers.service_auth.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        access.provision("123456", "123456", is_admin=True)
    assert not access.configured
    assert not list(Path(access.path).parent.iterdir())


def test_failed_rate_limit_reset_does_not_grant_access(access, monkeypatch):
    access.provision("123456", "123456", is_admin=True)
    assert not access.verify("999999")

    def fail_replace(*_args):
        raise OSError("read only")

    monkeypatch.setattr("helpers.service_auth.os.replace", fail_replace)
    with pytest.raises(OSError, match="read only"):
        access.verify("123456")
    assert json.loads(Path(access.path).read_text())["failures"] == 1


def test_access_requires_writable_attempt_state_even_without_prior_failures(access, monkeypatch):
    access.provision("123456", "123456", is_admin=True)

    def fail_replace(*_args):
        raise OSError("read only")

    monkeypatch.setattr("helpers.service_auth.os.replace", fail_replace)
    with pytest.raises(OSError, match="read only"):
        access.verify("123456")
