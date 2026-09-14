"""Unit tests for the Phase 3.5 config persistence: [ProtocolDefaults] + [Device].

Uses a tmp config path so the real kneespa.cfg is never touched.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from config.config import Configuration

pytestmark = pytest.mark.unit


def make_config(tmp_path):
    cfg = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    cfg.get_config()  # missing file -> writes defaults
    return cfg


def test_protocol_defaults_fallbacks(tmp_path):
    cfg = make_config(tmp_path)
    d = cfg.protocol_defaults()
    assert d == {
        "max_pressure": 40.0,
        "max_left": 10.0,
        "max_right": 10.0,
        "pulse_rate": 2.0,
        "duration": 12.0,
    }


def test_save_and_reload_protocol_defaults(tmp_path):
    cfg = make_config(tmp_path)
    cfg.save_protocol_defaults(60, 15, 18, 3, 20)

    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    d = reloaded.protocol_defaults()
    assert d["max_pressure"] == 60.0
    assert d["max_left"] == 15.0
    assert d["max_right"] == 18.0
    assert d["pulse_rate"] == 3.0
    assert d["duration"] == 20.0


def test_duration_optional_keeps_existing(tmp_path):
    """save_protocol_defaults without a duration keeps the persisted one."""
    cfg = make_config(tmp_path)
    cfg.save_protocol_defaults(60, 15, 18, 3, 25)
    cfg.save_protocol_defaults(55, 12, 12, 2)  # no duration arg
    assert cfg.default_duration == 25.0


def test_unmarked_protocol_defaults_are_ignored_and_dropped(tmp_path):
    """A [ProtocolDefaults] section that was auto-written by an earlier build
    (no operator ever pressed Mark As Default) must not pin old code defaults:
    it is ignored on load and removed on the next save."""
    cfg = make_config(tmp_path)
    cfg._set_section("ProtocolDefaults", {
        "max_pressure": 40, "max_left": 10, "max_right": 10,
        "pulse_rate": 1.0, "duration": 12,
    })
    with open(cfg.configFile, "w", encoding="utf-8") as fh:
        cfg.config.write(fh)
    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    assert reloaded.default_pulse_rate == 2.0
    assert reloaded.protocol_defaults_marked is False
    reloaded.update_config()
    again = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    again.get_config()
    assert not again.config.has_section("ProtocolDefaults")


def test_marked_protocol_defaults_survive_unrelated_saves(tmp_path):
    cfg = make_config(tmp_path)
    cfg.save_protocol_defaults(60, 15, 18, 3, 20)
    cfg.update_config()  # e.g. a calibration save
    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    assert reloaded.protocol_defaults_marked is True
    assert reloaded.default_pulse_rate == 3.0


def test_legacy_config_without_duration_falls_back(tmp_path):
    """A pre-duration [ProtocolDefaults] section loads with the default duration."""
    cfg = make_config(tmp_path)
    cfg._set_section("ProtocolDefaults", {
        "marked": 1,
        "max_pressure": 60, "max_left": 15, "max_right": 18, "pulse_rate": 3,
    })
    with open(cfg.configFile, "w", encoding="utf-8") as fh:
        cfg.config.write(fh)

    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    assert reloaded.default_duration == 12.0  # DEFAULT_PROTOCOL_MINUTES fallback


def test_device_id_generated_and_persisted(tmp_path):
    cfg = make_config(tmp_path)
    assert cfg.device_id == ""
    first = cfg.ensure_device_id()
    assert first  # non-empty
    # Same instance returns the same id (no regeneration).
    assert cfg.ensure_device_id() == first

    # A fresh load from the same file sees the persisted id.
    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    assert reloaded.device_id == first


def test_malformed_protocol_default_keeps_fallback(tmp_path):
    cfg = make_config(tmp_path)
    cfg._set_section("ProtocolDefaults", {"marked": 1, "max_pressure": "garbage"})
    with open(cfg.configFile, "w", encoding="utf-8") as fh:
        cfg.config.write(fh)

    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    # Garbage value falls back to the __init__ default rather than crashing.
    assert reloaded.default_max_pressure == 40.0


@pytest.mark.parametrize("already_marked", [False, True])
def test_failed_defaults_save_keeps_live_values_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, already_marked: bool,
) -> None:
    cfg = make_config(tmp_path)
    if already_marked:
        cfg.save_protocol_defaults(55, 12, 14, 1, 15)
    live = cfg.config
    previous = cfg.protocol_defaults()
    original = Path(cfg.configFile).read_bytes()

    def fail_replace(source: str, destination: str) -> None:
        assert cfg.config is live
        assert cfg.protocol_defaults() == previous
        assert cfg.protocol_defaults_marked is already_marked
        raise OSError("disk full")

    monkeypatch.setattr("config.config.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk full"):
        cfg.save_protocol_defaults(70, 18, 20, 4, 25)
    assert cfg.config is live
    assert cfg.protocol_defaults() == previous
    assert cfg.protocol_defaults_marked is already_marked
    assert Path(cfg.configFile).read_bytes() == original
    assert not list(tmp_path.glob(".kneespa_cfg_*"))


def test_invalid_defaults_do_not_partially_change_live_values(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    previous = cfg.protocol_defaults()
    with pytest.raises(ValueError):
        cfg.save_protocol_defaults(70, "invalid", 20, 4, 25)
    assert cfg.protocol_defaults() == previous
    assert not cfg.protocol_defaults_marked


def test_defaults_publish_after_write_and_preserve_other_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = make_config(tmp_path)
    cfg.config["Unrelated"] = {"note": "keep", "flag": None}
    cfg.config["ProtocolDefaults"] = {"custom": "keep"}
    cfg.b_factor = 3720
    cfg.device_id = "test-device"
    previous = cfg.protocol_defaults()
    write = cfg._atomic_write

    def observe(candidate: object) -> None:
        assert cfg.protocol_defaults() == previous
        assert candidate is not cfg.config
        assert not cfg.protocol_defaults_marked
        write(candidate)

    monkeypatch.setattr(cfg, "_atomic_write", observe)
    cfg.save_protocol_defaults(70, 18, 20, 4, 25)
    loaded = Configuration(cfg.configFile)
    loaded.get_config()
    assert loaded.protocol_defaults() == cfg.protocol_defaults()
    assert loaded.default_max_pressure == 70
    assert loaded.protocol_defaults_marked
    assert loaded.b_factor == 3720
    assert loaded.device_id == "test-device"
    assert dict(loaded.config["Unrelated"]) == {"note": "keep", "flag": None}
    assert loaded.config["ProtocolDefaults"]["custom"] == "keep"


def test_failed_default_save_reports_error_without_applying_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kneespa import KneeSpa
    from fixtures.controllers import make_window

    window = make_window()
    window.config = make_config(tmp_path)
    window._clamp_minutes = KneeSpa._clamp_minutes
    writer = Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(window.config, "_atomic_write", writer)
    KneeSpa._on_mark_default(window)
    window._show_timed_error.assert_called_once_with("Could not save defaults.")
    window.shell.treatment.set_settings.assert_not_called()
    window.logger.error.assert_called_once()
