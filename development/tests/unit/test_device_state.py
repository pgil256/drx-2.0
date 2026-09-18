"""Verify migration and device profile isolation using disposable state."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

from config import migrate_state as migration


pytestmark = pytest.mark.unit
APP = Path(__file__).resolve().parents[3] / "runtime" / "raspberry-pi" / "main"


def test_migration_preserves_all_device_state_and_does_not_resurrect_files(tmp_path: Path) -> None:
    legacy = {
        "config/kneespa.cfg": b"[Device]\nid=unique-existing-id\nnumber=2\n",
        "main/config/kneespa.cfg": b"older calibration must not win",
        "main/data/user_pins.csv": b"hashed credentials",
        "main/data/auth_state.json": b'{"locked":true}',
        "main/data/pending_uploads.json": b'[{"session_id":"pending"}]',
        "cloud.env": b"KNEESPA_DEVICE_ID=cloud-device-2\n",
        ".env": b"ADMIN_USERNAME=Existing operator\n",
        "logs/run.log.1": b"older log segment",
        "main/logs/legacy.log": b"legacy log",
    }
    for name, content in legacy.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    device = tmp_path / "devices" / "local"
    migrated = migration.migrate_state(tmp_path, device)
    state = device / "raspberry-pi"
    assert len(migrated) == 8
    assert (state / "config/kneespa.cfg").read_bytes() == legacy["config/kneespa.cfg"]
    for name in ("user_pins.csv", "auth_state.json", "pending_uploads.json"):
        assert (state / "data" / name).read_bytes() == legacy[f"main/data/{name}"]
    for name in ("cloud.env", ".env", "logs/run.log.1"):
        assert (state / name).read_bytes() == legacy[name]
    assert (state / "logs/legacy.log").read_bytes() == legacy["main/logs/legacy.log"]
    (state / "data/user_pins.csv").unlink()
    assert migration.migrate_state(tmp_path, device) == []
    assert not (state / "data/user_pins.csv").exists()
    for name, content in legacy.items():
        assert (tmp_path / name).read_bytes() == content


def test_existing_destination_wins_and_failure_can_be_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "config/kneespa.cfg"
    source.parent.mkdir()
    source.write_text("original")
    device = tmp_path / "devices/local"
    destination = device / "raspberry-pi/config/kneespa.cfg"

    def fail_copy(*args: object) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(migration.shutil, "copyfileobj", fail_copy)
        with pytest.raises(OSError, match="disk full"):
            migration.migrate_state(tmp_path, device)
    assert not destination.exists()
    assert not (device / "raspberry-pi/.legacy-migrated").exists()
    destination.write_text("new device calibration")
    migration.migrate_state(tmp_path, device)
    assert destination.read_text() == "new device calibration"
    assert source.read_text() == "original"


def test_custom_profile_does_not_migrate_local_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KNEESPA_DEVICE_DIR", "selected-profile")
    monkeypatch.setattr(migration, "migrate_state", lambda *args: pytest.fail("mixed devices"))
    migration.migrate_default_state()


def test_completed_migration_does_not_restore_removed_config(tmp_path: Path) -> None:
    """The older config-only compatibility path must respect the full migration marker."""
    legacy = tmp_path / "main/config/kneespa.cfg"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[Device]\nid=obsolete-id\nnumber=3\n")
    state = tmp_path / "devices/local/raspberry-pi"
    migration.migrate_state(tmp_path, state.parent)
    (state / "config/kneespa.cfg").unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("KNEESPA_")}
    env["KNEESPA_BASE_DIR"] = str(tmp_path / "main")
    env["KNEESPA_SKIP_PATH_VALIDATION"] = "1"
    env["PYTHONPATH"] = str(APP)
    script = (
        "from config.config import Configuration; cfg = Configuration(); "
        "cfg.get_config(); assert cfg.device_id != 'obsolete-id'; "
        "assert cfg.device_number == 1"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_only_selected_device_environment_is_loaded(tmp_path: Path) -> None:
    profile = tmp_path / "profiles/device-2/raspberry-pi"
    profile.mkdir(parents=True)
    (tmp_path / ".env").write_text("KNEESPA_DEVICE_ID=wrong-device\n")
    (profile / ".env").write_text("KNEESPA_SMTP_USERNAME=device2@example.invalid\n")
    (profile / "cloud.env").write_text("KNEESPA_DEVICE_ID=selected-device\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KNEESPA_")}
    env["KNEESPA_DEVICE_DIR"] = str(profile.parent)
    env["PYTHONPATH"] = str(APP)
    command = [sys.executable, "-c", (
        "import os; from config.constants import EMAIL_CONFIG; "
        "print(os.environ['KNEESPA_DEVICE_ID']); print(EMAIL_CONFIG['SENDER_EMAIL'])"
    )]
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["selected-device", "device2@example.invalid"]
    env["KNEESPA_DEVICE_ID"] = "process-override"
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "process-override"


def test_application_import_uses_new_release_with_legacy_tree_present(tmp_path: Path) -> None:
    """Keeping the previous main/ for rollback must not load its Python constants."""
    legacy = tmp_path / "main/config"
    legacy.mkdir(parents=True)
    (legacy / "constants.py").write_text("raise RuntimeError('loaded old release')\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("KNEESPA_")}
    env["KNEESPA_DEVICE_DIR"] = str(tmp_path / "device")
    env["PYTHONPATH"] = os.pathsep.join((str(APP), str(tmp_path)))
    env["QT_QPA_PLATFORM"] = "offscreen"
    script = """
import sys
from unittest.mock import MagicMock
for name in ('RPi', 'RPi.GPIO', 'vlc', 'PyQt5.QtMultimedia', 'PyQt5.QtMultimediaWidgets'):
    sys.modules[name] = MagicMock()
import kneespa
from main.config import constants
assert '/runtime/raspberry-pi/' in constants.__file__.replace('\\\\', '/')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True,
        text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
