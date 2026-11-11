"""A mark table lost from kneespa.cfg stays reported until it is calibrated again.

The file still parses when a truncation or a hand edit removes whole
sections. The load fell back to generated default marks and said so, but the
next save wrote those defaults into the file, so one restart later it loaded
as a calibrated device running on generated geometry.
"""
import configparser
import io
from pathlib import Path

import pytest

from config.config import Configuration
from helpers.calibration_backup import CalibrationBackups
from helpers.hardware_service import HardwareServiceDraft

pytestmark = pytest.mark.unit

# Every position differs from the generated defaults, so a table that came
# from the file can be told from one that was generated.
MEASURED = """[Options]
flexion_position = 0
a_factor = 1900
b_factor = 1900
c_factor = 1900
calibration = -28369.0
axial_service_calibrated = False

[CMarks]
-20.0 = 520
-10.0 = 1050
0.0 = 1695
10.0 = 2170
20.0 = 2390

[AMarks]
0 = 12
1 = 480
2 = 955
3 = 1430
4 = 1890

[BMarks]
-25 = 8
-20 = 385
-15 = 765
-10 = 1145
-5 = 1525
0 = 1905
5 = 2270

[Device]
id = keep-this-id
number = 2
"""

TABLES = ("CMarks", "AMarks", "BMarks")


def parse(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(allow_no_value=True)
    parser.read_string(text)
    return parser


def without(text: str, *sections: str) -> str:
    parser = parse(text)
    for section in sections:
        assert parser.remove_section(section)
    output = io.StringIO()
    parser.write(output)
    return output.getvalue()


def on_disk(path: Path) -> configparser.ConfigParser:
    return parse(path.read_text(encoding="utf-8"))


def start(path: Path) -> Configuration:
    """Load the file and ask for the device id, as the application does at startup."""
    config = Configuration(config_path=str(path))
    config.get_config()
    config.ensure_device_id()
    return config


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    return tmp_path / "kneespa.cfg"


def test_the_measured_sample_loads_cleanly(cfg_path: Path) -> None:
    cfg_path.write_text(MEASURED, encoding="utf-8")
    config = start(cfg_path)
    assert config.calibration_errors == []
    assert config.calibrated is True
    assert cfg_path.read_text(encoding="utf-8") == MEASURED


@pytest.mark.parametrize("table", TABLES)
def test_a_lost_mark_table_is_reported_on_every_start(cfg_path: Path, table: str) -> None:
    """The reviewed failure: the table and [Device] are gone, and startup saves a new id."""
    cfg_path.write_text(without(MEASURED, table, "Device"), encoding="utf-8")
    ids = set()

    for _ in range(3):
        config = start(cfg_path)
        ids.add(config.device_id)
        assert f"{table} section missing; defaults in use" in config.calibration_errors
        assert config.marks_valid is False
        assert config.calibrated is False
        assert table not in on_disk(cfg_path).sections()

    assert len(ids) == 1 and len(ids.pop()) == 32  # generated once, then read back


def test_no_save_writes_generated_marks_into_the_file(cfg_path: Path) -> None:
    cfg_path.write_text(without(MEASURED, "CMarks"), encoding="utf-8")
    config = start(cfg_path)

    config.device_number = 3
    config.update_config()
    config.save_protocol_defaults(60, 15, 18, 3, 20)

    saved = on_disk(cfg_path)
    assert "CMarks" not in saved.sections()
    assert saved["Device"]["number"] == "3"
    assert saved["ProtocolDefaults"]["marked"] == "1"
    for table in ("AMarks", "BMarks"):
        assert dict(saved[table]) == dict(parse(MEASURED)[table])


def test_generated_marks_are_not_merged_into_a_table_with_a_mistyped_row(
    cfg_path: Path,
) -> None:
    """A save used to add every default row the table lacked; they outlived the typo."""
    mistyped = MEASURED.replace("0.0 = 1695", "0.0 = l695")
    cfg_path.write_text(mistyped, encoding="utf-8")
    config = start(cfg_path)
    assert any(error.startswith("CMarks malformed") for error in config.calibration_errors)

    config.update_config()

    assert dict(on_disk(cfg_path)["CMarks"]) == dict(parse(mistyped)["CMarks"])
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8").replace("l695", "1695"), encoding="utf-8"
    )
    repaired = start(cfg_path)
    assert repaired.calibration_errors == []
    assert repaired.CMarks == {
        "-20.0": 520, "-10.0": 1050, "0.0": 1695, "10.0": 2170, "20.0": 2390,
    }


def test_a_file_without_a_device_section_still_gets_an_id_saved(cfg_path: Path) -> None:
    cfg_path.write_text(without(MEASURED, "Device"), encoding="utf-8")

    first = start(cfg_path)

    assert first.calibrated is True
    assert len(first.device_id) == 32
    assert on_disk(cfg_path)["Device"]["id"] == first.device_id
    assert start(cfg_path).device_id == first.device_id


def test_a_hardware_service_save_of_the_lost_table_writes_it(cfg_path: Path) -> None:
    cfg_path.write_text(without(MEASURED, "CMarks"), encoding="utf-8")
    config = start(cfg_path)
    draft = HardwareServiceDraft(config)
    draft.record("lateral", -20, 520)
    draft.record("lateral", 20, 2390)

    draft.save(config)

    assert config.marks_valid is False  # the alert asks for a restart after recalibrating
    restarted = start(cfg_path)
    assert restarted.calibration_errors == []
    assert restarted.calibrated is True
    assert restarted.CMarks == draft.marks["lateral"]
    assert (restarted.CMarks["-20.0"], restarted.CMarks["20.0"]) == (520, 2390)


def test_a_hardware_service_save_of_another_table_leaves_the_lost_one_reported(
    cfg_path: Path,
) -> None:
    cfg_path.write_text(without(MEASURED, "CMarks"), encoding="utf-8")
    config = start(cfg_path)
    draft = HardwareServiceDraft(config)
    draft.record("horizontal", 0, 1910)

    draft.save(config)

    assert "CMarks" not in on_disk(cfg_path).sections()
    restarted = start(cfg_path)
    assert restarted.BMarks["0.0"] == 1910
    assert "CMarks section missing; defaults in use" in restarted.calibration_errors
    assert restarted.marks_valid is False


def test_a_calibration_restore_writes_the_lost_table(tmp_path: Path, cfg_path: Path) -> None:
    backups = CalibrationBackups(tmp_path / "state")
    cfg_path.write_text(MEASURED, encoding="utf-8")
    measured = start(cfg_path)
    saved = backups.create(measured, "Technician")
    cfg_path.write_text(without(MEASURED, "CMarks"), encoding="utf-8")
    config = start(cfg_path)

    backups.restore(saved.name, config, "Technician")

    restarted = start(cfg_path)
    assert restarted.calibration_errors == []
    assert restarted.calibrated is True
    assert restarted.CMarks == measured.CMarks
