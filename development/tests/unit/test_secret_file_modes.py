"""Device env files holding credentials end up owner-only on the Pi.

.env holds KNEESPA_SMTP_PASSWORD (and may hold plaintext PINs) and cloud.env
the cloud device token. Nothing enforced their permissions, and the legacy
migration's copystat kept a world-readable source mode. On POSIX they are now
made 0600, with a warning, when loaded and when migrated. Windows dev
machines are unchanged.
"""
import logging
import os
import stat

import pytest

from config import migrate_state as migration
from config import paths

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


@posix_only
def test_group_or_world_access_is_removed_with_a_warning(tmp_path, caplog):
    secret = tmp_path / "cloud.env"
    secret.write_text("KNEESPA_DEVICE_TOKEN=x\n")
    secret.chmod(0o644)

    with caplog.at_level(logging.WARNING, logger="KneeSpa.config"):
        assert migration.restrict_secret_file(secret) is True

    assert mode(secret) == 0o600
    assert "Restricted cloud.env to owner-only access (was 644)" in caplog.text
    assert "KNEESPA_DEVICE_TOKEN" not in caplog.text


@posix_only
def test_owner_only_and_missing_files_are_left_alone(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("A=1\n")
    secret.chmod(0o600)
    assert migration.restrict_secret_file(secret) is False
    assert mode(secret) == 0o600
    assert migration.restrict_secret_file(tmp_path / "missing.env") is False


def test_non_posix_systems_are_unchanged(tmp_path, monkeypatch):
    secret = tmp_path / ".env"
    secret.write_text("A=1\n")
    before = secret.stat().st_mode
    monkeypatch.setattr(migration, "_POSIX", False)
    assert migration.restrict_secret_file(secret) is False
    assert secret.stat().st_mode == before


@posix_only
def test_migrated_env_files_are_made_owner_only(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for name in (".env", "cloud.env"):
        source = project / name
        source.write_text("A=1\n")
        source.chmod(0o644)
    (project / "config").mkdir()
    (project / "config" / "kneespa.cfg").write_text("[Device]\n")
    (project / "config" / "kneespa.cfg").chmod(0o644)

    device = tmp_path / "device"
    migration.migrate_state(project, device)

    state = device / "raspberry-pi"
    assert mode(state / ".env") == 0o600
    assert mode(state / "cloud.env") == 0o600
    assert mode(state / "config" / "kneespa.cfg") == 0o644  # not a secrets file


@posix_only
def test_loading_the_device_environment_restricts_both_files(tmp_path, monkeypatch):
    for name in (".env", "cloud.env"):
        (tmp_path / name).write_text("KNEESPA_TEST_UNUSED=1\n")
        (tmp_path / name).chmod(0o640)
    monkeypatch.setattr(paths, "DEVICE_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("KNEESPA_TEST_UNUSED", raising=False)

    paths.load_device_environment()

    assert mode(tmp_path / ".env") == 0o600
    assert mode(tmp_path / "cloud.env") == 0o600
