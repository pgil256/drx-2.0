"""A kneespa.cfg that fails to load is never replaced by the application.

One bad line from a hand edit (or SD-card corruption) used to make startup
overwrite the file: the load fell back to generated defaults with an empty
device id, the startup id check generated a new one and saved, and the save
replaced the calibration, device number and identity with defaults.
"""
import builtins
import logging
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from config import config as config_module
from config.config import ConfigUnreadableError, Configuration
from helpers.calibration_backup import CalibrationBackups

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sample_configs"

CALIBRATED = (
    (FIXTURES / "valid.cfg").read_text(encoding="utf-8")
    .replace("calibration = 1.0", "calibration = -28369.0").rstrip("\n")
    + "\n\n[Device]\nid = keep-this-id\nnumber = 2\n"
).encode("utf-8")

UNREADABLE = {
    "duplicate key": CALIBRATED.replace(b"-20 = 380\n", b"-20 = 380\n-20 = 381\n"),
    "duplicate section": CALIBRATED + b"\n[BMarks]\n-25 = 0\n",
    "text before the first section": b"edited by hand\n" + CALIBRATED,
    "interpolation character": CALIBRATED.replace(b"a_factor = 1900", b"a_factor = 19%"),
    "not utf-8": CALIBRATED.replace(b"[AMarks]", b"[AMarks\xff\xfe]"),
    "nul bytes": b"\x00" * 512,
}


@pytest.fixture
def cfg_path(tmp_path: Path) -> Path:
    return tmp_path / "kneespa.cfg"


def load(path: Path, content: bytes) -> Configuration:
    path.write_bytes(content)
    config = Configuration(config_path=str(path))
    config.get_config()
    return config


def test_the_calibrated_sample_loads_cleanly(cfg_path: Path) -> None:
    config = load(cfg_path, CALIBRATED)
    assert config.unreadable is False
    assert config.calibrated is True
    assert (config.device_id, config.device_number) == ("keep-this-id", 2)


@pytest.mark.parametrize("content", list(UNREADABLE.values()), ids=list(UNREADABLE))
def test_startup_leaves_an_unreadable_file_unchanged(cfg_path: Path, content: bytes) -> None:
    """The reviewed failure: load, then the startup device-id check."""
    config = load(cfg_path, content)

    assert config.ensure_device_id()

    assert cfg_path.read_bytes() == content
    assert not list(cfg_path.parent.glob(".kneespa_cfg_*"))


@pytest.mark.parametrize("content", list(UNREADABLE.values()), ids=list(UNREADABLE))
def test_a_failed_load_is_explicit_and_uncalibrated(cfg_path: Path, content: bytes) -> None:
    config = load(cfg_path, content)

    assert config.unreadable is True
    assert config.marks_valid is False
    assert config.calibrated is False
    assert len(config.calibration_errors) == 1
    error = config.calibration_errors[0]
    assert error.startswith("Config file unreadable (")
    assert "Device is UNCALIBRATED" in error
    assert "left unchanged" in error


def test_update_config_does_not_write_and_says_why(
    cfg_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    config = load(cfg_path, UNREADABLE["duplicate key"])
    caplog.clear()

    config.device_number = 3
    with caplog.at_level(logging.ERROR, logger="KneeSpa.config"):
        assert config.update_config() is None

    assert cfg_path.read_bytes() == UNREADABLE["duplicate key"]
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "not written" in messages[0] and str(cfg_path) in messages[0]


def test_every_write_path_refuses(cfg_path: Path) -> None:
    content = UNREADABLE["duplicate key"]
    config = load(cfg_path, content)
    live, defaults = config.config, config.protocol_defaults()

    with pytest.raises(ConfigUnreadableError, match="failed to load"):
        config._atomic_write()
    with pytest.raises(ConfigUnreadableError):
        config._atomic_write(config.config)
    with pytest.raises(ConfigUnreadableError):
        config._write_default_config()
    with pytest.raises(ConfigUnreadableError):
        config.commit(config.config, {"b_factor": 3720})
    with pytest.raises(ConfigUnreadableError):
        config.save_protocol_defaults(60, 15, 18, 3, 20)

    assert cfg_path.read_bytes() == content
    assert not list(cfg_path.parent.glob(".kneespa_cfg_*"))
    assert config.config is live
    assert config.b_factor == 1900
    assert config.protocol_defaults() == defaults
    assert config.protocol_defaults_marked is False


def test_the_refusal_is_an_oserror_like_other_write_failures() -> None:
    """Callers already report OSError from a failed save; none needs changing."""
    assert issubclass(ConfigUnreadableError, OSError)


def test_a_repaired_file_loads_and_saves_again(cfg_path: Path) -> None:
    config = load(cfg_path, UNREADABLE["duplicate key"])
    cfg_path.write_bytes(CALIBRATED)

    config.get_config()

    assert config.unreadable is False
    assert config.calibrated is True
    assert config.ensure_device_id() == "keep-this-id"
    config.device_number = 3
    config.update_config()
    reloaded = Configuration(config_path=str(cfg_path))
    reloaded.get_config()
    assert reloaded.device_number == 3
    assert reloaded.calibration == -28369.0


def test_a_missing_file_still_gets_defaults_written(cfg_path: Path) -> None:
    config = Configuration(config_path=str(cfg_path))
    config.get_config()

    assert config.unreadable is False
    assert os.path.isfile(str(cfg_path))
    assert any("Config file missing" in error for error in config.calibration_errors)
    assert config.ensure_device_id() == config.device_id != ""
    reloaded = Configuration(config_path=str(cfg_path))
    reloaded.get_config()
    assert reloaded.device_id == config.device_id


def test_malformed_values_in_a_readable_file_are_handled_as_before(cfg_path: Path) -> None:
    config = load(cfg_path, (FIXTURES / "corrupt.cfg").read_bytes())

    assert config.unreadable is False
    assert config.calibrated is False
    assert any("CMarks malformed" in error for error in config.calibration_errors)


def test_the_device_id_for_this_run_is_temporary_and_never_saved(cfg_path: Path) -> None:
    config = load(cfg_path, UNREADABLE["duplicate key"])

    first = config.ensure_device_id()

    assert first.startswith("temporary-") and len(first) > len("temporary-")
    assert config.ensure_device_id() == first
    assert config.device_id == ""

    cfg_path.write_bytes(CALIBRATED)
    config.get_config()
    assert config.ensure_device_id() == "keep-this-id"
    assert b"temporary-" not in cfg_path.read_bytes()


def test_a_temporary_id_is_not_saved_into_a_repaired_file_without_one(cfg_path: Path) -> None:
    config = load(cfg_path, UNREADABLE["duplicate key"])
    temporary = config.ensure_device_id()
    cfg_path.write_bytes(CALIBRATED.replace(b"id = keep-this-id\n", b""))

    config.get_config()
    permanent = config.ensure_device_id()

    assert permanent != temporary and not permanent.startswith("temporary-")
    reloaded = Configuration(config_path=str(cfg_path))
    reloaded.get_config()
    assert reloaded.device_id == permanent
    assert reloaded.calibration == -28369.0


def test_calibration_backups_are_refused_while_unreadable(
    tmp_path: Path, cfg_path: Path,
) -> None:
    """A backup would file generated defaults under an id that is never saved."""
    backups = CalibrationBackups(tmp_path / "state")
    saved = backups.create(load(cfg_path, CALIBRATED), "Technician")
    content = UNREADABLE["duplicate key"]
    config = load(cfg_path, content)

    with pytest.raises(ValueError, match="failed to load"):
        backups.create(config, "Technician")
    with pytest.raises(ValueError, match="failed to load"):
        backups.load(saved.name, config)
    with pytest.raises(ValueError, match="failed to load"):
        backups.restore(saved.name, config, "Technician")

    assert backups.list() == [saved.name]
    assert cfg_path.read_bytes() == content


def kept_copies(path: Path) -> list:
    return sorted(path.parent.glob(path.name + ".unreadable-*"))


@pytest.mark.parametrize("content", list(UNREADABLE.values()), ids=list(UNREADABLE))
def test_the_unreadable_file_is_copied_beside_itself(
    cfg_path: Path, caplog: pytest.LogCaptureFixture, content: bytes,
) -> None:
    with caplog.at_level(logging.WARNING, logger="KneeSpa.config"):
        config = load(cfg_path, content)

    [kept] = kept_copies(cfg_path)
    assert kept.read_bytes() == content
    assert re.fullmatch(r"kneespa\.cfg\.unreadable-\d{8}T\d{6}Z", kept.name)
    assert config.unreadable_copy == str(kept)
    assert any(
        record.levelname == "WARNING" and str(kept) in record.getMessage()
        for record in caplog.records
    )
    config.ensure_device_id()
    assert cfg_path.read_bytes() == content
    assert kept.read_bytes() == content


def test_restarting_on_the_same_bad_file_keeps_one_copy(cfg_path: Path) -> None:
    content = UNREADABLE["duplicate key"]
    first = load(cfg_path, content)
    [kept] = kept_copies(cfg_path)

    second = load(cfg_path, content)
    second.get_config()

    assert kept_copies(cfg_path) == [kept]
    assert first.unreadable_copy == second.unreadable_copy == str(kept)


def test_a_different_bad_file_gets_its_own_copy(cfg_path: Path) -> None:
    load(cfg_path, UNREADABLE["duplicate key"])
    [earlier] = kept_copies(cfg_path)

    later = load(cfg_path, UNREADABLE["duplicate section"])

    assert len(kept_copies(cfg_path)) == 2
    assert earlier.read_bytes() == UNREADABLE["duplicate key"]
    assert Path(later.unreadable_copy).read_bytes() == UNREADABLE["duplicate section"]
    assert later.unreadable_copy != str(earlier)


def test_an_earlier_copy_is_never_overwritten(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different bad files in the same second: both copies are kept."""
    class FixedClock:
        @staticmethod
        def now(tz: object) -> datetime:
            return datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(config_module, "datetime", FixedClock)
    earlier = cfg_path.parent / "kneespa.cfg.unreadable-20261110T120000Z"
    earlier.write_bytes(b"an earlier unreadable file")

    config = load(cfg_path, UNREADABLE["duplicate key"])

    assert earlier.read_bytes() == b"an earlier unreadable file"
    assert config.unreadable_copy == str(earlier) + "-1"
    assert Path(config.unreadable_copy).read_bytes() == UNREADABLE["duplicate key"]
    assert len(kept_copies(cfg_path)) == 2


def test_a_failed_copy_does_not_stop_startup(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    content = UNREADABLE["duplicate key"]
    cfg_path.write_bytes(content)
    config = Configuration(config_path=str(cfg_path))

    def fail(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("config.config.os.fsync", fail)
    with caplog.at_level(logging.ERROR, logger="KneeSpa.config"):
        config.get_config()

    assert config.unreadable is True and config.unreadable_copy is None
    assert kept_copies(cfg_path) == []  # no partial copy left to mislead anyone
    assert "Could not keep a copy" in caplog.text
    assert config.ensure_device_id().startswith("temporary-")
    assert cfg_path.read_bytes() == content


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_the_copy_is_owner_only_whatever_the_original_allowed(cfg_path: Path) -> None:
    cfg_path.write_bytes(UNREADABLE["duplicate key"])
    cfg_path.chmod(0o644)
    config = Configuration(config_path=str(cfg_path))
    config.get_config()

    [kept] = kept_copies(cfg_path)
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600


@pytest.mark.parametrize("content", [None, CALIBRATED, (FIXTURES / "corrupt.cfg").read_bytes()],
                         ids=["missing", "calibrated", "malformed values"])
def test_only_a_file_that_failed_to_load_is_copied(cfg_path: Path, content: bytes) -> None:
    if content is not None:
        cfg_path.write_bytes(content)
    config = Configuration(config_path=str(cfg_path))
    config.get_config()

    assert config.unreadable_copy is None
    assert kept_copies(cfg_path) == []


def test_a_file_that_cannot_be_opened_is_not_replaced(
    cfg_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ConfigParser.read() skips a file it cannot open, which looked like an
    empty one: every section "missing", no device id, defaults saved over it."""
    cfg_path.write_bytes(CALIBRATED)
    real_open = builtins.open

    def deny(file: object, *args: object, **kwargs: object) -> object:
        if str(file) == str(cfg_path):
            raise PermissionError(13, "Permission denied", str(file))
        return real_open(file, *args, **kwargs)

    config = Configuration(config_path=str(cfg_path))
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", deny)
        config.get_config()
        device_id = config.ensure_device_id()

    assert cfg_path.read_bytes() == CALIBRATED
    assert config.unreadable is True
    assert device_id.startswith("temporary-")
    assert "Permission denied" in config.calibration_errors[0]
    assert config.unreadable_copy is None and kept_copies(cfg_path) == []
