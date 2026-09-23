"""Calibration data and atomic saving, plus the Device page's calibration entry.

The guided session UI is the hardware service wizard (see
test_hardware_service_controller / test_hardware_service_dialog); the retired
standalone calibration dialog and controller were removed with their tests.
"""

import configparser
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config.config import Configuration
from helpers.calibration import CalibrationDraft, distance_factor
from ui.app_shell import AppShell

pytestmark = pytest.mark.unit


@pytest.fixture
def config(tmp_path):
    result = Configuration(str(tmp_path / "device.cfg"))
    result._set_default_a_marks()
    result._set_default_b_marks()
    result._set_default_c_marks()
    result.calibration = -28369
    result._write_default_config()
    result.get_config()
    return result


def test_factor_uses_measured_distance_and_preserves_direction():
    assert distance_factor(100, 1340, 2) == 3720
    assert distance_factor(1340, 100, 2) == 3720


@pytest.mark.parametrize("inches", [0, -1, float("nan"), float("inf")])
def test_bad_distance_rejected(inches):
    with pytest.raises(ValueError):
        distance_factor(100, 1340, inches)


def test_stationary_anchors_rejected():
    with pytest.raises(ValueError):
        distance_factor(100, 101, 2)


def test_save_roundtrip_replaces_key_and_preserves_other_sections(config):
    config.config["Unrelated"] = {"keep": "yes"}
    config._atomic_write()
    original = Path(config.configFile).read_bytes()
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    draft.record("lateral", 0, 1690)
    draft.factors["horizontal"] = 3720
    assert config.BMarks["0"] == 1900  # not changed until Save
    backup = draft.save(config)
    assert Path(backup).read_bytes() == original
    assert not draft.dirty
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.BMarks["0.0"] == 1910
    assert "0" not in loaded.BMarks
    assert loaded.CMarks["0.0"] == 1690
    assert loaded.b_factor == 3720
    assert loaded.calibration == -28369
    assert loaded.AMarks == config.AMarks
    assert loaded.config["Unrelated"]["keep"] == "yes"
    loaded.update_config()
    parser = configparser.ConfigParser()
    parser.read(config.configFile)
    assert parser["BMarks"]["0.0"] == "1910"


def test_failed_save_preserves_live_config_and_original_file(config, monkeypatch):
    original = Path(config.configFile).read_bytes()
    parser = config.config
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    monkeypatch.setattr(config, "_atomic_write", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        draft.save(config)
    assert config.config is parser
    assert config.BMarks["0"] == 1900
    assert Path(config.configFile).read_bytes() == original
    assert draft.dirty


@pytest.mark.parametrize("fail_write", [False, True])
def test_save_publishes_only_after_atomic_replace(
    config: Configuration, monkeypatch: pytest.MonkeyPatch, fail_write: bool,
) -> None:
    """Readers see the original parser and calibration throughout the disk write."""
    path = Path(config.configFile)
    original = path.read_bytes()
    live = config.config
    marks = config.BMarks
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    draft.factors["horizontal"] = 3720
    replace = os.replace
    replacements = []

    def assert_unpublished() -> None:
        assert config.config is live
        assert config.BMarks is marks
        assert config.BMarks["0"] == 1900
        assert config.b_factor == 1900
        assert live["Options"]["b_factor"] == "1900"
        assert draft.dirty
        assert draft.original_marks["horizontal"]["0.0"] == 1900
        assert draft.original_factors["horizontal"] == 1900

    def inspect_replace(source: str, destination: str) -> None:
        assert_unpublished()
        assert path.read_bytes() == original
        backups = list(path.parent.glob("device.cfg.*.bak"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original
        pending = configparser.ConfigParser()
        pending.read(source, encoding="utf-8")
        assert pending["BMarks"]["0.0"] == "1910"
        assert "0" not in pending["BMarks"]
        assert pending["Options"]["b_factor"] == "3720"
        replacements.append(destination)
        if fail_write:
            raise OSError("disk full")
        replace(source, destination)
        assert_unpublished()

    monkeypatch.setattr("config.config.os.replace", inspect_replace)
    if fail_write:
        with pytest.raises(OSError, match="disk full"):
            draft.save(config)
        assert_unpublished()
        assert path.read_bytes() == original
    else:
        backup = draft.save(config)
        assert Path(backup).read_bytes() == original
        assert config.config is not live
        assert config.BMarks["0.0"] == 1910
        assert config.b_factor == 3720
        assert config.config["Options"]["b_factor"] == "3720"
        assert live["Options"]["b_factor"] == "1900"
        assert not draft.dirty
        assert draft.original_marks == draft.marks
        assert draft.original_factors == draft.factors
    assert replacements == [config.configFile]
    assert not list(path.parent.glob(".kneespa_cfg_*"))


@pytest.mark.parametrize("defaults", ["missing", "unmarked", "marked", "malformed"])
def test_factor_save_preserves_legacy_keys_defaults_and_unknown_values(
    config: Configuration, defaults: str,
) -> None:
    """Calibration saves preserve even ignored or malformed unrelated settings."""
    config.config["Unrelated"] = {"note": "Measured on service bench", "flag": None}
    config.config["Device"] = {"id": "test-device", "service_note": "keep"}
    config.config["Options"]["legacy_option"] = "keep"
    if defaults != "missing":
        config.config["ProtocolDefaults"] = {"max_pressure": "60", "pulse_rate": "3"}
        if defaults != "unmarked":
            config.config["ProtocolDefaults"]["marked"] = "1"
        if defaults == "malformed":
            config.config["ProtocolDefaults"]["max_pressure"] = "garbage"
    config._atomic_write()
    config.get_config()
    previous_defaults = config.protocol_defaults()
    previous_marked = config.protocol_defaults_marked
    sections = {name: dict(config.config[name]) for name in config.config.sections()}
    original = Path(config.configFile).read_bytes()
    draft = CalibrationDraft(config)
    draft.factors["horizontal"] = 3720
    draft.factors["lateral"] = 3800

    backup = draft.save(config)

    assert Path(backup).read_bytes() == original
    sections["Options"].update(b_factor="3720", c_factor="3800")
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert {name: dict(loaded.config[name]) for name in loaded.config.sections()} == sections
    assert loaded.BMarks["0"] == 1900
    assert "0.0" not in loaded.BMarks
    assert loaded.CMarks["0.0"] == 1688
    assert "0" not in loaded.CMarks
    assert loaded.AMarks == config.AMarks
    assert loaded.calibration == -28369
    assert (loaded.b_factor, loaded.c_factor) == (3720, 3800)
    assert loaded.protocol_defaults() == previous_defaults
    assert loaded.protocol_defaults_marked == previous_marked
    assert loaded.device_id == "test-device"


def test_unchanged_draft_does_not_write_or_create_backup(
    config: Configuration, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saving an unchanged draft remains a no-op."""
    path = Path(config.configFile)
    original = path.read_bytes()
    live = config.config
    writer = MagicMock(side_effect=AssertionError("unchanged draft attempted a write"))
    monkeypatch.setattr(config, "_atomic_write", writer)

    assert CalibrationDraft(config).save(config) is None

    writer.assert_not_called()
    assert config.config is live
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.bak"))


def test_save_without_existing_file_does_not_create_backup(config: Configuration) -> None:
    """A valid in-memory configuration can be saved when there is no prior file."""
    path = Path(config.configFile)
    path.unlink()
    draft = CalibrationDraft(config)
    draft.factors["horizontal"] = 3720

    assert draft.save(config) is None

    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.b_factor == 3720
    assert config.b_factor == 3720
    assert not draft.dirty
    assert not list(path.parent.glob("*.bak"))


def test_failed_backup_prevents_write_and_retains_draft(
    config: Configuration, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup errors propagate before any attempt to persist the candidate."""
    path = Path(config.configFile)
    original = path.read_bytes()
    live = config.config
    draft = CalibrationDraft(config)
    draft.factors["horizontal"] = 3720
    writer = MagicMock(side_effect=AssertionError("write attempted after failed backup"))
    monkeypatch.setattr(config, "_atomic_write", writer)
    monkeypatch.setattr(
        "helpers.calibration.shutil.copy2", MagicMock(side_effect=OSError("backup denied")),
    )

    with pytest.raises(OSError, match="backup denied"):
        draft.save(config)

    writer.assert_not_called()
    assert config.config is live
    assert config.b_factor == 1900
    assert draft.dirty
    assert path.read_bytes() == original


@pytest.mark.parametrize("change", ["missing_endpoint", "out_of_order", "out_of_range"])
def test_invalid_table_cannot_replace_file(config, change):
    original = Path(config.configFile).read_bytes()
    draft = CalibrationDraft(config)
    if change == "missing_endpoint":
        draft.marks["horizontal"].pop("-25.0")
    elif change == "out_of_order":
        draft.marks["horizontal"]["0.0"] = 100
    else:
        draft.marks["horizontal"]["5.0"] = 4501
    with pytest.raises(ValueError):
        draft.save(config)
    assert Path(config.configFile).read_bytes() == original


def test_factor_only_save_does_not_rewrite_existing_cmarks(config):
    config.CMarks = {"0": 10, "-10": 30, "10": 20}
    config.config["CMarks"] = {k: str(v) for k, v in config.CMarks.items()}
    draft = CalibrationDraft(config)
    draft.factors["horizontal"] = 3720
    draft.save(config)
    assert config.CMarks == {"0": 10, "-10": 30, "10": 20}
    assert dict(config.config["CMarks"]) == {"0": "10", "-10": "30", "10": "20"}


def test_bc_edits_do_not_certify_fallback_axial_data(config):
    config.calibration_errors.append("AMarks section missing; defaults in use")
    draft = CalibrationDraft(config)
    draft.record("horizontal", 0, 1910)
    draft.save(config)
    assert not config.marks_valid


def test_device_exposes_calibration_after_login(qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    assert not shell.device.calibration_button.isEnabled()
    shell.login_succeeded("Technician", goto="device")
    assert shell.device.calibration_button.isEnabled()
    assert not shell.device.calibration_button.isVisibleTo(shell.device)
    shell.device.unlock_service()
    assert shell.device.calibration_button.isVisibleTo(shell.device)
    shell.logout()
    assert not shell.device.calibration_button.isEnabled()
