"""A kneespa.cfg value that parses but cannot be used must not load as calibrated."""

import configparser

import pytest

from config.config import Configuration
from helpers.calibration_backup import CalibrationBackups
from helpers.hardware_service import HardwareServiceDraft

pytestmark = pytest.mark.unit

FACTORS = ("a_factor", "b_factor", "c_factor")


def _load(tmp_path, **options):
    """Load a calibrated device file with some [Options] text replaced."""
    path = tmp_path / "kneespa.cfg"
    seed = Configuration(str(path))
    seed._set_default_a_marks()
    seed._set_default_b_marks()
    seed._set_default_c_marks()
    seed.calibration = -28369.0
    seed._write_default_config()
    for name, text in options.items():
        seed.config["Options"][name] = text
    seed._atomic_write()
    config = Configuration(str(path))
    config.get_config()
    return config


def _on_disk(config, option):
    parser = configparser.ConfigParser(allow_no_value=True)
    parser.read(config.configFile, encoding="utf-8")
    return parser["Options"][option]


def _scale_errors(config):
    return [e for e in config.calibration_errors if e.startswith("Load-cell scale factor")]


def _factor_errors(config, option):
    return [
        e for e in config.calibration_errors
        if e.startswith("Distance factor") and option in e
    ]


def test_untouched_file_loads_calibrated(tmp_path):
    config = _load(tmp_path)
    assert config.calibrated is True
    assert config.calibration_errors == []


@pytest.mark.parametrize("text", ["nan", "NaN", "inf", "-inf", "Infinity", "1e999"])
def test_non_finite_scale_factor_is_not_calibrated(tmp_path, text):
    config = _load(tmp_path, calibration=text)
    assert config.scale_calibrated is False
    assert config.calibrated is False
    errors = _scale_errors(config)
    assert len(errors) == 1
    assert str(config.calibration) in errors[0]
    # The mark tables are still measured data: only pressure is in doubt.
    assert config.marks_valid is True


@pytest.mark.parametrize("text", ["100000001", "-1e9", "1e300"])
def test_scale_factor_above_the_service_limit_is_not_calibrated(tmp_path, text):
    config = _load(tmp_path, calibration=text)
    assert config.scale_calibrated is False
    assert config.calibrated is False
    errors = _scale_errors(config)
    assert len(errors) == 1
    assert str(config.calibration) in errors[0]


@pytest.mark.parametrize("text", ["1000", "-1000", "-28369.0", "100000000", "-100000000"])
def test_scale_factor_inside_the_service_limits_is_calibrated(tmp_path, text):
    config = _load(tmp_path, calibration=text)
    assert config.scale_calibrated is True
    assert config.calibrated is True
    assert config.calibration_errors == []


@pytest.mark.parametrize("option", FACTORS)
@pytest.mark.parametrize("text", ["0", "-1900", "1000001"])
def test_out_of_range_factor_flags_the_device_uncalibrated(tmp_path, option, text):
    config = _load(tmp_path, **{option: text})
    assert config.marks_valid is False
    assert config.calibrated is False
    errors = _factor_errors(config, option)
    assert len(errors) == 1
    assert "UNCALIBRATED" in errors[0]
    assert "{} = {}".format(option, text) in errors[0]
    # The load cell was not touched by the bad factor.
    assert config.scale_calibrated is True


@pytest.mark.parametrize("option", FACTORS)
@pytest.mark.parametrize("text", ["1", "1900", "1000000"])
def test_factor_inside_the_service_limits_is_calibrated(tmp_path, option, text):
    config = _load(tmp_path, **{option: text})
    assert config.calibrated is True
    assert config.calibration_errors == []


@pytest.mark.parametrize("option,text", [
    ("a_factor", "0"), ("b_factor", "-1900"), ("calibration", "nan"),
])
def test_a_save_leaves_the_unusable_value_in_the_file(tmp_path, option, text):
    """A routine save must not swap in a default that then loads cleanly."""
    config = _load(tmp_path, **{option: text})
    assert config.calibrated is False
    config.update_config()
    assert _on_disk(config, option) == text
    reloaded = Configuration(config.configFile)
    reloaded.get_config()
    assert reloaded.calibrated is False


def test_marking_protocol_defaults_leaves_the_unusable_value_in_the_file(tmp_path):
    config = _load(tmp_path, c_factor="0")
    config.save_protocol_defaults(40.0, 10.0, 10.0, 2.0)
    assert _on_disk(config, "c_factor") == "0"
    assert config.marks_valid is False
    assert len(_factor_errors(config, "c_factor")) == 1


def test_service_save_of_a_measured_factor_clears_the_flag(tmp_path):
    config = _load(tmp_path, a_factor="0")
    assert config.marks_valid is False
    draft = HardwareServiceDraft(config)
    with pytest.raises(ValueError, match="Axial: factor must be an integer"):
        draft.validate()
    draft.factors["axial"] = 2100
    draft.save(config)
    assert config.a_factor == 2100
    assert config.marks_valid is True
    assert config.calibrated is True
    assert _factor_errors(config, "a_factor") == []
    reloaded = Configuration(config.configFile)
    reloaded.get_config()
    assert reloaded.calibrated is True


def test_revalidating_does_not_repeat_the_factor_error(tmp_path):
    config = _load(tmp_path, b_factor="0")
    config._validate_calibration()
    config._validate_calibration()
    assert len(_factor_errors(config, "b_factor")) == 1
    assert config.marks_valid is False


def test_service_save_of_a_measured_scale_factor_restores_pressure(tmp_path):
    config = _load(tmp_path, calibration="nan")
    assert config.scale_calibrated is False
    draft = HardwareServiceDraft(config)
    with pytest.raises(ValueError, match="finite"):
        draft.validate()
    draft.scale = -29000.0
    draft.save(config)
    assert config.scale_calibrated is True
    assert config.calibrated is True
    assert config.calibration_errors == []


@pytest.mark.parametrize("text", ["1.0", "nan"])
def test_revalidating_does_not_repeat_the_scale_error(tmp_path, text):
    config = _load(tmp_path, calibration=text)
    config._validate_calibration()
    config._validate_calibration()
    assert len(_scale_errors(config)) == 1
    assert config.scale_calibrated is False


def test_calibration_restore_replaces_an_unusable_factor(tmp_path):
    config = _load(tmp_path)
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    config.config["Options"]["b_factor"] = "0"
    config._atomic_write()
    config.get_config()
    assert config.marks_valid is False
    backups.restore(selected.name, config, "Technician")
    assert config.b_factor == 1900
    assert config.calibrated is True
    assert config.calibration_errors == []


def test_calibration_restore_replaces_an_oversized_scale_factor(tmp_path):
    # A finite value: the backup taken before a restore cannot hold nan or inf.
    config = _load(tmp_path)
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    config.config["Options"]["calibration"] = "-1e9"
    config._atomic_write()
    config.get_config()
    assert config.scale_calibrated is False
    backups.restore(selected.name, config, "Technician")
    assert config.calibration == -28369.0
    assert config.calibrated is True
    assert config.calibration_errors == []
