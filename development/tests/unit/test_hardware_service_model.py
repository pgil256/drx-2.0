"""Measured service data validates safely and persists as one transaction."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from config.config import Configuration
from helpers.hardware_service import HardwareServiceDraft, axial_position, load_cell_factor

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


def test_axial_first_opt_in_requires_measured_endpoints_even_when_values_match(config):
    draft = HardwareServiceDraft(config)
    assert not draft.dirty
    draft.record("axial", 0, 0)
    assert draft.dirty
    with pytest.raises(ValueError, match="capture measured 0 and 4"):
        draft.validate()
    draft.record("axial", 4, 1900)
    draft.validate()
    assert ("Use measured axial positions", "Disabled", "Enabled") in draft.changes()
    backup = draft.save(config)
    assert Path(backup).is_file()
    assert config.axial_service_calibrated
    assert not draft.dirty
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.axial_service_calibrated
    loaded.update_config()
    again = Configuration(config.configFile)
    again.get_config()
    assert again.axial_service_calibrated


def test_unedited_legacy_config_does_not_enable_axial(config):
    config.config.remove_option("Options", "axial_service_calibrated")
    config._atomic_write()
    config.get_config()
    assert not config.axial_service_calibrated
    draft = HardwareServiceDraft(config)
    draft.scale = -29000.0
    draft.save(config)
    assert not config.axial_service_calibrated
    config.update_config()
    config.get_config()
    assert not config.axial_service_calibrated


@pytest.mark.parametrize("marked", [False, True])
def test_only_opted_in_axial_tables_get_strict_load_validation(config, marked):
    config.config["AMarks"] = {"0": "3000", "4": "5000"}
    config.config["Options"]["axial_service_calibrated"] = str(marked)
    config._atomic_write()
    config.get_config()
    assert config.marks_valid is not marked
    assert config.AMarks == {"0": 3000, "4": 5000}


def test_repairing_opted_in_table_clears_its_service_validation_errors(config):
    config.config["AMarks"] = {"0": "100", "4": "5000"}
    config.config["Options"]["axial_service_calibrated"] = "True"
    config._atomic_write()
    config.get_config()
    assert not config.marks_valid
    assert any(error.startswith("Axial service calibration:")
               for error in config.calibration_errors)
    draft = HardwareServiceDraft(config)
    draft.record("axial", 4, 2000)
    draft.save(config)
    assert config.marks_valid
    assert not any(error.startswith("Axial service calibration:")
                   for error in config.calibration_errors)


def test_invalid_axial_opt_in_flag_fails_closed(config):
    config.config["Options"]["axial_service_calibrated"] = "invalid"
    config._atomic_write()
    config.get_config()
    assert not config.marks_valid
    assert not config.axial_service_calibrated


def test_save_all_measurements_backs_up_and_preserves_unrelated_values(config):
    config.config["Unrelated"] = {"keep": "unchanged", "bare": None}
    config.config["Options"]["vendor_option"] = "keep"
    config._atomic_write()
    original = Path(config.configFile).read_bytes()
    draft = HardwareServiceDraft(config)
    draft.record("axial", 0, 50)
    draft.record("axial", 4, 2000)
    draft.record("horizontal", 0, 1910)
    draft.record("lateral", 0, 1690)
    draft.factors["axial"] = 2925
    draft.scale = load_cell_factor(500000, -670000, 40)
    backup = draft.save(config)
    assert Path(backup).read_bytes() == original
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.AMarks["0.0"] == 50
    assert loaded.AMarks["4.0"] == 2000
    assert loaded.BMarks["0.0"] == 1910
    assert loaded.CMarks["0.0"] == 1690
    assert loaded.a_factor == 2925
    assert loaded.calibration == -29250
    assert dict(loaded.config["Unrelated"]) == {"keep": "unchanged", "bare": None}
    assert loaded.config["Options"]["vendor_option"] == "keep"
    assert not draft.dirty
    assert draft.changes() == []


@pytest.mark.parametrize("failure", ["backup", "write"])
def test_save_failures_leave_live_data_and_file_unchanged(config, monkeypatch, failure):
    original = Path(config.configFile).read_bytes()
    live = config.config
    draft = HardwareServiceDraft(config)
    draft.scale = -29000
    if failure == "backup":
        monkeypatch.setattr("helpers.hardware_service.shutil.copy2", Mock(side_effect=OSError()))
        writer = Mock()
        monkeypatch.setattr(config, "_atomic_write", writer)
    else:
        monkeypatch.setattr(config, "_atomic_write", Mock(side_effect=OSError()))
    with pytest.raises(OSError):
        draft.save(config)
    assert config.config is live
    assert config.calibration == -28369
    assert Path(config.configFile).read_bytes() == original
    assert draft.dirty
    if failure == "backup":
        writer.assert_not_called()


def test_atomic_write_precedes_publication(config, monkeypatch):
    live = config.config
    draft = HardwareServiceDraft(config)
    draft.record("axial", 0, 10)
    draft.record("axial", 4, 1910)
    write = config._atomic_write

    def inspect(candidate):
        assert config.config is live
        assert not config.axial_service_calibrated
        assert config.AMarks["0"] == 0
        assert candidate.getboolean("Options", "axial_service_calibrated")
        assert candidate["AMarks"]["0.0"] == "10"
        write(candidate)

    monkeypatch.setattr(config, "_atomic_write", inspect)
    draft.save(config)
    assert config.AMarks["0.0"] == 10
    assert config.axial_service_calibrated


@pytest.mark.parametrize("axis,measured,position", [
    ("axial", float("nan"), 100), ("axial", 4.1, 100), ("axial", 0, 4096),
    ("horizontal", -26, 100), ("horizontal", 0, 4200), ("lateral", 0, 499),
    ("lateral", 0, 2401), ("axial", 0, 100.5), ("axial", 0, float("inf")),
    ("axial", 0, True),
])
def test_bad_measurements_never_enter_draft(config, axis, measured, position):
    draft = HardwareServiceDraft(config)
    with pytest.raises(ValueError):
        draft.record(axis, measured, position)
    assert not draft.dirty


@pytest.mark.parametrize("factor", [float("nan"), float("inf"), 0, 1000001, 12.5, True])
def test_invalid_distance_factors_are_rejected(config, factor):
    draft = HardwareServiceDraft(config)
    draft.factors["axial"] = factor
    with pytest.raises(ValueError):
        draft.validate()


@pytest.mark.parametrize("scale", [float("nan"), float("inf"), 0, 999, -999, 1e9])
def test_invalid_load_cell_factors_are_rejected(config, scale):
    draft = HardwareServiceDraft(config)
    draft.scale = scale
    with pytest.raises(ValueError):
        draft.validate()


def test_axial_decreasing_and_duplicate_measurements_are_rejected(config):
    draft = HardwareServiceDraft(config)
    draft.marks["axial"] = {"0.0": 2000, "4.0": 0}
    draft.recorded["axial"] = {"0.0", "4.0"}
    with pytest.raises(ValueError, match="increase"):
        draft.validate()
    draft.marks["axial"] = {"0": 0, "0.0": 10, "4.0": 2000}
    with pytest.raises(ValueError, match="duplicate"):
        draft.validate()


def test_unedited_device_geometry_is_preserved(config):
    config.CMarks = {"0": 10, "-10": 30, "10": 20}
    config.config["CMarks"] = {key: str(value) for key, value in config.CMarks.items()}
    draft = HardwareServiceDraft(config)
    draft.scale = -29000
    draft.save(config)
    assert config.CMarks == {"0": 10, "-10": 30, "10": 20}
    assert dict(config.config["CMarks"]) == {"0": "10", "-10": "30", "10": "20"}


def test_no_changes_does_not_write_or_backup(config, monkeypatch):
    writer = Mock(side_effect=AssertionError("unexpected write"))
    monkeypatch.setattr(config, "_atomic_write", writer)
    assert HardwareServiceDraft(config).save(config) is None
    assert not list(Path(config.configFile).parent.glob("*.bak"))


def test_axial_interpolation_uses_measured_offset_and_nonuniform_points():
    marks = {"0": 100, "1": 700, "3": 1500, "4": 1800}
    assert axial_position(marks, 0) == 100
    assert axial_position(marks, 1) == 700
    assert axial_position(marks, 2) == 1100
    assert axial_position(marks, 3.5) == 1650
    assert axial_position(marks, 4) == 1800


@pytest.mark.parametrize("inches", [-0.1, 4.1, float("nan"), float("inf"), True])
def test_axial_interpolation_rejects_invalid_distances(inches):
    with pytest.raises(ValueError):
        axial_position({"0": 0, "4": 1900}, inches)


@pytest.mark.parametrize("marks", [
    {"0": 0, "4": 4096}, {"0": 1900, "4": 0}, {"1": 200, "4": 1900},
    {"0": 0, "nan": 100, "4": 1900}, {"0": 0, "3": 2100, "4": 1900},
])
def test_axial_interpolation_rejects_invalid_tables(marks):
    with pytest.raises(ValueError):
        axial_position(marks, 2)


@pytest.mark.parametrize("marked,command", [(False, "A122.0"), (True, "I121100")])
def test_axial_go_uses_measured_table_only_after_service_opt_in(config, marked, command):
    from kneespa import KneeSpa

    config.AMarks = {"0": 100, "1": 700, "3": 1500, "4": 1800}
    config.axial_service_calibrated = marked
    window = MagicMock()
    window.config = config
    window.arduino.send.return_value = True
    assert KneeSpa.set_to_distance(window, 2, "12", 1900)
    window.arduino.send.assert_called_once_with(command)


@pytest.mark.parametrize("marked,command", [(False, "A120.5"), (True, "I12400")])
def test_axial_jog_uses_measured_table_only_after_service_opt_in(config, marked, command):
    from kneespa import KneeSpa

    config.AMarks = {"0": 100, "1": 700, "3": 1500, "4": 1800}
    config.axial_service_calibrated = marked
    window = MagicMock()
    window.config = config
    window.actuator_a, window.actuator_b, window.actuator_c = "12", "13", "14"
    window.actuator_command_in_progress = False
    window.axial_flexion_position = 0
    window.arduino.send.return_value = True
    KneeSpa.move_actuator(window, "12", None, "1", 1)
    window.arduino.send.assert_called_once_with(command)
    assert window.axial_flexion_position == 0.5


@pytest.mark.parametrize("operation", ["go", "jog"])
def test_invalid_service_axial_table_never_sends_motion(config, operation):
    from kneespa import KneeSpa

    config.AMarks = {"0": 100, "4": 5000}
    config.axial_service_calibrated = True
    window = MagicMock()
    window.config = config
    window.actuator_a, window.actuator_b, window.actuator_c = "12", "13", "14"
    window.actuator_command_in_progress = False
    window.axial_flexion_position = 0
    if operation == "go":
        assert KneeSpa.set_to_distance(window, 2, "12", 1900) is False
    else:
        assert KneeSpa.move_actuator(window, "12", None, "1", 1) is False
        assert window.axial_flexion_position == 0
    window.arduino.send.assert_not_called()
    window._show_timed_error.assert_called_once()


def test_load_cell_reference_calculation_preserves_polarity_and_tare_offset():
    assert load_cell_factor(500000, -670000, 40) == -29250
    assert load_cell_factor(-500000, 670000, 40) == 29250


@pytest.mark.parametrize("unloaded,loaded,known", [
    (0, 100000, 0), (0, 100000, -1), (float("nan"), 100000, 10),
    (0, float("inf"), 10), (0, 100000, float("nan")), (0, 8388607, 40),
    (-8388608, 0, 40), (0, 500, 0.01), (0, 100000, 200),
])
def test_invalid_load_reference_is_rejected(unloaded, loaded, known):
    with pytest.raises(ValueError):
        load_cell_factor(unloaded, loaded, known)
