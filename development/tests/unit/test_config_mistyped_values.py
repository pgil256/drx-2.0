"""A readable kneespa.cfg with one mistyped value must not run silently on a
default, and no save may replace the mistyped text with that default.

The file here parses: only a single [Options] or [Device] value is wrong, as
after a hand edit (`b_factor = 372O`, letter O). The technician can only
correct what is still in the file.
"""

from pathlib import Path
from typing import Callable

import pytest

from config.config import Configuration
from config.constants import SERVICE_AXES
from helpers.calibration_backup import CalibrationBackups
from helpers.device_records import read_json
from helpers.hardware_service import HardwareServiceDraft

pytestmark = pytest.mark.unit

GOOD_LINES = {
    "a_factor": "a_factor = 3650",
    "b_factor": "b_factor = 3720",
    "c_factor": "c_factor = 3810",
    "calibration": "calibration = -28369.0",
    "flexion_position": "flexion_position = 0",
    "axial_service_calibrated": "axial_service_calibrated = False",
    "number": "number = 2",
}


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    """A calibrated device's file: real factors, scale factor, id and number."""
    path = tmp_path / "kneespa.cfg"
    cfg = Configuration(str(path))
    cfg._set_default_a_marks()
    cfg._set_default_b_marks()
    cfg._set_default_c_marks()
    cfg.a_factor, cfg.b_factor, cfg.c_factor = 3650, 3720, 3810
    cfg.calibration = -28369.0
    cfg.device_id = "keep-this-id"
    cfg.device_number = 2
    cfg._write_default_config()
    return path


def mistype(path: Path, option: str, text: str) -> str:
    """Replace one good line with `option = text`; return the new line."""
    content = path.read_text(encoding="utf-8")
    good = GOOD_LINES[option]
    assert good in content
    bad = f"{option} = {text}"
    path.write_text(content.replace(good, bad), encoding="utf-8")
    return bad


def load(path: Path) -> Configuration:
    cfg = Configuration(str(path))
    cfg.get_config()
    return cfg


def lines(path: Path) -> list:
    return [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_untouched_file_is_calibrated(cfg_path: Path) -> None:
    cfg = load(cfg_path)
    assert cfg.calibration_errors == []
    assert cfg.calibrated is True
    assert (cfg.b_factor, cfg.calibration, cfg.device_number) == (3720, -28369.0, 2)


# --- A mistyped value is reported, not silently defaulted -------------------

@pytest.mark.parametrize("option", ["a_factor", "b_factor", "c_factor"])
@pytest.mark.parametrize("text", ["372O", "3 720", ""])
def test_mistyped_factor_flags_the_device_uncalibrated(
    cfg_path: Path, option: str, text: str,
) -> None:
    mistype(cfg_path, option, text)
    cfg = load(cfg_path)
    assert getattr(cfg, option) == 1900
    assert cfg.marks_valid is False
    assert cfg.calibrated is False
    assert any(
        option in error and repr(text) in error and "UNCALIBRATED" in error
        for error in cfg.calibration_errors
    ), cfg.calibration_errors


@pytest.mark.parametrize("text", ["-28369.O", "-28,369", ""])
def test_mistyped_scale_factor_is_named_and_blocks_pressure_only(
    cfg_path: Path, text: str,
) -> None:
    mistype(cfg_path, "calibration", text)
    cfg = load(cfg_path)
    assert cfg.scale_calibrated is False
    assert cfg.calibrated is False
    assert any(
        "calibration" in error and repr(text) in error
        for error in cfg.calibration_errors
    ), cfg.calibration_errors
    # The mark tables and factors loaded, so jogging stays available, as it
    # is for a device whose scale factor is still the factory default.
    assert cfg.marks_valid is True


def test_mistyped_legacy_flexion_position_does_not_disable_the_device(cfg_path: Path) -> None:
    # flexion_position is read and written but used by nothing.
    mistype(cfg_path, "flexion_position", "O")
    cfg = load(cfg_path)
    assert cfg.flexion_position == 0
    assert cfg.calibrated is True


def test_mistyped_device_number_runs_as_one_without_disabling_the_device(cfg_path: Path) -> None:
    mistype(cfg_path, "number", "2O")
    cfg = load(cfg_path)
    assert cfg.device_number == 1
    assert cfg.calibrated is True
    assert cfg.device_id == "keep-this-id"


# --- No save replaces the mistyped text with the default --------------------

def _update_config(cfg: Configuration, state_dir: Path) -> None:
    cfg.update_config()


def _mark_as_default(cfg: Configuration, state_dir: Path) -> None:
    cfg.save_protocol_defaults(35.0, 8.0, 8.0, 1.5)


def _service_save_of_another_value(cfg: Configuration, state_dir: Path) -> None:
    draft = HardwareServiceDraft(cfg)
    draft.record("horizontal", 0, 1905)
    assert draft.save(cfg)


SAVES = [_update_config, _mark_as_default, _service_save_of_another_value]

MISTYPED = [
    ("a_factor", "365O"),
    ("b_factor", "372O"),
    ("c_factor", "381O"),
    ("calibration", "-28369.O"),
    ("flexion_position", "O"),
    ("axial_service_calibrated", "Ture"),
    ("number", "2O"),
    ("number", "7"),
]


@pytest.mark.parametrize("save", SAVES, ids=lambda save: save.__name__.lstrip("_"))
@pytest.mark.parametrize("option, text", MISTYPED)
def test_a_save_leaves_the_mistyped_text_in_the_file(
    cfg_path: Path, tmp_path: Path, option: str, text: str,
    save: Callable[[Configuration, Path], None],
) -> None:
    bad = mistype(cfg_path, option, text)
    first = load(cfg_path)
    errors = list(first.calibration_errors)
    save(first, tmp_path)
    assert bad in lines(cfg_path)
    # The next start reports exactly what this one did: a save used to make
    # the default load cleanly from then on.
    again = load(cfg_path)
    assert again.calibration_errors == errors
    assert again.calibrated is first.calibrated


@pytest.mark.parametrize("option, text", MISTYPED)
def test_startup_without_a_device_id_leaves_the_mistyped_text(
    cfg_path: Path, option: str, text: str,
) -> None:
    content = cfg_path.read_text(encoding="utf-8")
    assert "id = keep-this-id\n" in content
    cfg_path.write_text(content.replace("id = keep-this-id\n", ""), encoding="utf-8")
    bad = mistype(cfg_path, option, text)
    cfg = load(cfg_path)
    generated = cfg.ensure_device_id()
    assert bad in lines(cfg_path)
    assert f"id = {generated}" in lines(cfg_path)


def test_calibration_restore_leaves_a_mistyped_device_number(
    cfg_path: Path, tmp_path: Path,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    selected = backups.create(load(cfg_path), "Technician")
    bad = mistype(cfg_path, "number", "2O")
    backups.restore(selected.name, load(cfg_path), "Administrator")
    assert bad in lines(cfg_path)


# --- A value the technician supplies on purpose still replaces it -----------

def test_calibration_restore_replaces_a_mistyped_factor_with_the_reviewed_one(
    cfg_path: Path, tmp_path: Path,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    selected = backups.create(load(cfg_path), "Technician")
    mistype(cfg_path, "b_factor", "372O")
    backups.restore(selected.name, load(cfg_path), "Administrator")
    assert "b_factor = 3720" in lines(cfg_path)
    assert load(cfg_path).calibrated is True


def test_service_save_of_the_mistyped_factor_itself_replaces_it(cfg_path: Path) -> None:
    mistype(cfg_path, "b_factor", "372O")
    cfg = load(cfg_path)
    draft = HardwareServiceDraft(cfg)
    draft.factors["horizontal"] = 3725
    draft.save(cfg)
    assert "b_factor = 3725" in lines(cfg_path)
    # A later ordinary save must not bring the mistyped text back either.
    cfg.update_config()
    assert "b_factor = 3725" in lines(cfg_path)
    assert load(cfg_path).calibrated is True


def test_service_save_of_a_new_scale_factor_replaces_a_mistyped_one(cfg_path: Path) -> None:
    mistype(cfg_path, "calibration", "-28369.O")
    cfg = load(cfg_path)
    draft = HardwareServiceDraft(cfg)
    draft.scale = -29000.0
    draft.save(cfg)
    assert "calibration = -29000.0" in lines(cfg_path)
    assert load(cfg_path).calibrated is True


@pytest.mark.parametrize("option, text, attribute, value, written", [
    ("b_factor", "372O", "b_factor", 3720, "b_factor = 3720"),
    ("number", "2O", "device_number", 3, "number = 3"),
])
def test_a_value_set_in_code_replaces_the_mistyped_text(
    cfg_path: Path, option: str, text: str, attribute: str, value: int, written: str,
) -> None:
    mistype(cfg_path, option, text)
    cfg = load(cfg_path)
    setattr(cfg, attribute, value)
    cfg.update_config()
    assert written in lines(cfg_path)
    assert getattr(load(cfg_path), attribute) == value


# --- A calibration backup never holds the stand-in default ------------------
# A backup taken while a value is mistyped would record the default as if it
# were the device's own, and restoring that backup would write the default
# over the mistyped text.

CALIBRATION_MISTYPES = [
    ("a_factor", "365O"),
    ("b_factor", "372O"),
    ("c_factor", "381O"),
    ("calibration", "-28369.O"),
    ("axial_service_calibrated", "Ture"),
]


def recorded(data: dict, option: str) -> object:
    """What a backup file holds for one [Options] calibration value."""
    if option == "calibration":
        return data["scale"]
    if option == "axial_service_calibrated":
        return data[option]
    axis = next(axis for axis, spec in SERVICE_AXES.items() if spec["factor"] == option)
    return data["factors"][axis]


@pytest.mark.parametrize("option, text", CALIBRATION_MISTYPES)
def test_backup_is_refused_while_a_calibration_value_is_mistyped(
    cfg_path: Path, tmp_path: Path, option: str, text: str,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    bad = mistype(cfg_path, option, text)
    with pytest.raises(ValueError, match=option):
        backups.create(load(cfg_path), "Technician")
    assert backups.list() == []
    assert bad in lines(cfg_path)


@pytest.mark.parametrize("option, text", [("flexion_position", "1O"), ("number", "2O")])
def test_backup_is_taken_when_the_mistyped_value_is_not_calibration(
    cfg_path: Path, tmp_path: Path, option: str, text: str,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    mistype(cfg_path, option, text)
    cfg = load(cfg_path)
    saved = backups.create(cfg, "Technician")
    assert backups.load(saved.name, cfg)["factors"]["horizontal"] == 3720


def test_backup_records_a_factor_set_in_code_over_a_mistyped_one(
    cfg_path: Path, tmp_path: Path,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    mistype(cfg_path, "b_factor", "372O")
    cfg = load(cfg_path)
    cfg.b_factor = 2800
    saved = backups.create(cfg, "Technician")
    assert backups.load(saved.name, cfg)["factors"]["horizontal"] == 2800


@pytest.mark.parametrize("option, text", CALIBRATION_MISTYPES)
def test_restoring_an_earlier_backup_replaces_any_mistyped_calibration_value(
    cfg_path: Path, tmp_path: Path, option: str, text: str,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    earlier = backups.create(load(cfg_path), "Technician")
    mistype(cfg_path, option, text)
    backups.restore(earlier.name, load(cfg_path), "Administrator")
    assert GOOD_LINES[option] in lines(cfg_path)
    reloaded = load(cfg_path)
    assert reloaded.calibration_errors == []
    assert reloaded.calibrated is True


@pytest.mark.parametrize("option, text", CALIBRATION_MISTYPES)
def test_pre_restore_backup_cannot_bring_the_stand_in_default_back(
    cfg_path: Path, tmp_path: Path, option: str, text: str,
) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    earlier = backups.create(load(cfg_path), "Technician")
    mistype(cfg_path, option, text)
    cfg = load(cfg_path)
    previous = backups.restore(earlier.name, cfg, "Administrator")
    data = read_json(previous)
    # No value is recorded for the mistyped option; the rest is kept.
    assert recorded(data, option) is None
    assert data["marks"] == read_json(earlier)["marks"]
    after_restore = cfg_path.read_bytes()
    with pytest.raises(ValueError, match="mistyped"):
        backups.restore(previous.name, cfg, "Administrator")
    assert cfg_path.read_bytes() == after_restore
    assert len(backups.list()) == 2
