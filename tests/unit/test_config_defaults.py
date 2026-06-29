"""Unit tests for the Phase 3.5 config persistence: [ProtocolDefaults] + [Device].

Uses a tmp config path so the real kneespa.cfg is never touched.
"""

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
        "max_pressure": 50.0,
        "max_left": 10.0,
        "max_right": 10.0,
        "pulse_rate": 2.0,
    }


def test_save_and_reload_protocol_defaults(tmp_path):
    cfg = make_config(tmp_path)
    cfg.save_protocol_defaults(60, 15, 18, 3)

    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    d = reloaded.protocol_defaults()
    assert d["max_pressure"] == 60.0
    assert d["max_left"] == 15.0
    assert d["max_right"] == 18.0
    assert d["pulse_rate"] == 3.0


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
    cfg._set_section("ProtocolDefaults", {"max_pressure": "garbage"})
    with open(cfg.configFile, "w", encoding="utf-8") as fh:
        cfg.config.write(fh)

    reloaded = Configuration(config_path=str(tmp_path / "kneespa.cfg"))
    reloaded.get_config()
    # Garbage value falls back to the __init__ default rather than crashing.
    assert reloaded.default_max_pressure == 50.0
