"""A readable kneespa.cfg with one mistyped value must not run silently on a
default, and no save may replace the mistyped text with that default.

The file here parses: only a single [Options] or [Device] value is wrong, as
after a hand edit (`b_factor = 372O`, letter O). The technician can only
correct what is still in the file.
"""

from pathlib import Path

import pytest

from config.config import Configuration

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
