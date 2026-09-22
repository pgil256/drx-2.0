"""Device archives preserve calibration and omit sensitive diagnostic content."""

import copy
import json
from pathlib import Path
import zipfile

import pytest

from config.config import Configuration
from helpers.calibration_backup import CalibrationBackups
from helpers.device_records import DeviceRecords, read_json, write_json

pytestmark = pytest.mark.unit


@pytest.fixture
def config(tmp_path):
    config = Configuration(str(tmp_path / "kneespa.cfg"))
    config._set_default_a_marks()
    config._set_default_b_marks()
    config._set_default_c_marks()
    config.calibration = -28369
    config._write_default_config()
    config.get_config()
    config.ensure_device_id()
    return config


def test_restore_saves_previous_values_and_preserves_unrelated_configuration(tmp_path, config):
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    original_marks = copy.deepcopy(config.BMarks)
    config.b_factor = 2800
    config.BMarks["0"] = 1950
    config.config["Private"] = {"token": "retain-this-value"}
    config.update_config()
    before = backups.restore(selected.name, config, "Administrator")
    assert config.b_factor == 1900
    assert config.BMarks == original_marks
    previous = read_json(before)
    assert previous["factors"]["horizontal"] == 2800
    assert previous["marks"]["horizontal"]["0"] == 1950
    assert "retain-this-value" not in selected.read_text()
    loaded = Configuration(config.configFile)
    loaded.get_config()
    assert loaded.b_factor == config.b_factor
    assert loaded.BMarks == original_marks
    assert loaded.config["Private"]["token"] == "retain-this-value"


@pytest.mark.parametrize("change", [
    lambda data: data.update(device_id="another-device"),
    lambda data: data.update(scale=float("inf")),
    lambda data: data.update(scale="-28369"),
    lambda data: data["factors"].update(axial=True),
    lambda data: data["marks"].update(lateral={"-20": 600, "20": 600}),
    lambda data: data["marks"].update(axial={"0": 0, "4": 9000}),
    lambda data: data.update(axial_service_calibrated="False"),
    lambda data: data.update(marks=[]),
])
def test_invalid_restore_never_mutates_config_or_creates_backup(tmp_path, config, change):
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    data = read_json(selected)
    change(data)
    selected.write_text(json.dumps(data), encoding="utf-8")
    original = Path(config.configFile).read_bytes()
    parser = config.config
    with pytest.raises(ValueError):
        backups.restore(selected.name, config, "Technician")
    assert Path(config.configFile).read_bytes() == original
    assert config.config is parser
    assert backups.list() == [selected.name]


def test_restore_write_failure_leaves_live_configuration_untouched(tmp_path, config, monkeypatch):
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    config.b_factor = 2400
    config.update_config()
    parser = config.config
    original = Path(config.configFile).read_bytes()

    def fail(_candidate):
        assert config.config is parser
        assert config.b_factor == 2400
        raise OSError("disk full")

    monkeypatch.setattr(config, "_atomic_write", fail)
    with pytest.raises(OSError):
        backups.restore(selected.name, config, "Technician")
    assert config.config is parser and config.b_factor == 2400
    assert Path(config.configFile).read_bytes() == original
    assert len(backups.list()) == 2  # The pre-restore backup still exists.


def test_backup_changed_after_review_must_be_reviewed_again(tmp_path, config):
    backups = CalibrationBackups(tmp_path)
    selected = backups.create(config, "Technician")
    reviewed = backups.load(selected.name, config)
    changed = copy.deepcopy(reviewed)
    changed["factors"]["horizontal"] = 2400
    write_json(selected, changed)
    with pytest.raises(ValueError, match="changed"):
        backups.restore(selected.name, config, "Technician", reviewed=reviewed)
    assert config.b_factor == 1900
    assert backups.list() == [selected.name]


def test_diagnostics_export_only_fixed_categories_and_allowlisted_metadata(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "python_2026.log").write_text(
        "2026-09-21 11:22:33,222 - ERROR - serial: patient=Jane token=SECRET pin=123456\n"
        "2026-09-21 11:22:34,222 - WARNING - smtp password=SECRET\n"
        "2026-09-21 11:22:35,222 - INFO - pressure=50 patient=Jane\n",
        encoding="utf-8",
    )
    path = DeviceRecords(tmp_path).diagnostic_bundle({
        "device_id": "device-01", "software_version": "test", "patient": "Jane",
        "password": "SECRET", "token": "SECRET",
    })
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {"device.json", "recent-errors.json", "README.txt"}
        text = archive.read("device.json") + archive.read("recent-errors.json")
        assert b"SECRET" not in text and b"Jane" not in text and b"123456" not in text
        errors = json.loads(archive.read("recent-errors.json"))
        assert [row["category"] for row in errors] == ["Serial communication", "Support delivery"]


def test_history_does_not_hide_skips_or_bench_failures(tmp_path):
    path = tmp_path / "service-reports" / "hardware-example.json"
    report = {"mode": "tests", "results": {"preparation": {"status": "pass"}}}
    write_json(path, report)
    records = DeviceRecords(tmp_path)
    assert records.history()[0]["result"] == "Incomplete / skipped checks"
    report["bench_observations"] = {"watchdog": {"status": "fail"}}
    report["configuration_saved"] = True
    write_json(path, report)
    assert "failure" in records.history()[0]["result"]
    assert records.history()[0]["saved"]


def test_preferences_persist_and_reject_invalid_timeout(tmp_path):
    records = DeviceRecords(tmp_path)
    assert records.preferences()["idle_dim_minutes"] == 0
    records.set_idle_timeout(5)
    assert DeviceRecords(tmp_path).preferences()["idle_dim_minutes"] == 5
    for bad in (-1, 4, True, "5"):
        with pytest.raises(ValueError):
            records.set_idle_timeout(bad)
    assert records.preferences()["idle_dim_minutes"] == 5


def test_report_path_cannot_escape_device_reports(tmp_path):
    records = DeviceRecords(tmp_path)
    with pytest.raises(ValueError):
        records.report("../credentials.json")


def test_logout_and_dimming_preferences_do_not_overwrite_each_other(tmp_path):
    records = DeviceRecords(tmp_path)
    records.set_idle_timeout(5)
    records.set_logout_timeout(15)
    records.set_idle_timeout(10)
    assert DeviceRecords(tmp_path).preferences() == {"idle_dim_minutes": 10, "logout_minutes": 15}
    for invalid in (True, -1, 2, 999, "5"):
        with pytest.raises(ValueError):
            records.set_logout_timeout(invalid)
