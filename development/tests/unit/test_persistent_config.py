"""Persistent config migration must preserve device calibration across updates."""

from pathlib import Path
from typing import Optional

import pytest

from config import config as config_module
from config.config import Configuration

pytestmark = pytest.mark.unit


@pytest.fixture
def config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    """Redirect default and legacy locations to an isolated device layout."""
    legacy = tmp_path / "main" / "config" / "kneespa.cfg"
    current = tmp_path / "config" / "kneespa.cfg"
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(current))
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", str(current))
    monkeypatch.setattr(config_module, "LEGACY_CONFIG_PATH", str(legacy))
    return legacy, current


def test_legacy_calibration_copied_once_and_saved_outside_main(config_paths: tuple) -> None:
    legacy, current = config_paths
    original = Configuration(str(legacy))
    original.get_config()
    original.calibration = -28369.0
    original.device_id = "existing-support-id"
    original.device_number = 3
    original.CMarks["0.0"] = 1451
    original.config["CMarks"]["0.0"] = "1451"
    original.update_config()
    legacy_bytes = legacy.read_bytes()

    migrated = Configuration()
    migrated.get_config()
    assert current.read_bytes() == legacy_bytes
    assert migrated.calibration == -28369.0
    assert migrated.CMarks["0.0"] == 1451
    assert migrated.device_id == "existing-support-id"
    assert migrated.device_number == 3

    migrated.device_number = 2
    migrated.update_config()
    assert legacy.read_bytes() == legacy_bytes
    reloaded = Configuration()
    reloaded.get_config()
    assert reloaded.device_number == 2  # Legacy data must not overwrite the new file.


def test_custom_path_does_not_import_legacy_calibration(
    config_paths: tuple, tmp_path: Path,
) -> None:
    legacy, current = config_paths
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[Device]\nnumber = 3\n", encoding="utf-8")
    custom = Configuration(str(tmp_path / "custom.cfg"))
    custom.get_config()
    assert custom.device_number == 1
    assert not current.exists()


def test_migration_failure_does_not_generate_default_calibration(
    config_paths: tuple, monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy, current = config_paths
    legacy.parent.mkdir(parents=True)
    legacy.write_text("[Device]\nnumber = 3\n", encoding="utf-8")

    def fail_copy(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(config_module.shutil, "copyfileobj", fail_copy)
    with pytest.raises(OSError, match="disk full"):
        Configuration().get_config()
    assert not current.exists()
    assert "number = 3" in legacy.read_text()


@pytest.mark.parametrize(
    "setting, expected",
    [(None, 1), ("1", 1), ("2", 2), ("3", 3), ("0", 1), ("4", 1),
     ("bad", 1), ("", 1), ("2.5", 1)],
)
def test_device_number_load_and_round_trip(
    tmp_path: Path, setting: Optional[str], expected: int,
) -> None:
    path = tmp_path / "device.cfg"
    device = "[Device]\nid = keep-this-id\n"
    if setting is not None:
        device += f"number = {setting}\n"
    path.write_text(device, encoding="utf-8")
    cfg = Configuration(str(path))
    cfg.get_config()
    assert cfg.device_number == expected
    cfg.update_config()
    reloaded = Configuration(str(path))
    reloaded.get_config()
    assert reloaded.device_number == expected
    assert reloaded.device_id == "keep-this-id"


def test_generated_config_contains_device_number(config_paths: tuple) -> None:
    _, current = config_paths
    cfg = Configuration()
    cfg.get_config()
    assert cfg.device_number == 1
    assert "number = 1" in current.read_text()
