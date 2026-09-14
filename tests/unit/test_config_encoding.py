"""Configuration reloads preserve UTF-8 even on legacy Windows locales."""

import builtins
import configparser
from pathlib import Path

import pytest

from config.config import Configuration
from helpers.calibration import CalibrationDraft

pytestmark = pytest.mark.unit


def test_unicode_survives_defaults_and_calibration_round_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = Configuration(str(tmp_path / "kneespa.cfg"))
    cfg.get_config()
    cfg.calibration = -28369
    note = "Clinique café – Zoë – 膝"
    cfg.config["Service"] = {"note": note}
    cfg.update_config()

    def locale_open(file: str, mode: str = "r", *, encoding: str = None) -> object:
        return builtins.open(file, mode, encoding=encoding or "cp1252")

    # Only ConfigParser's file opens use the simulated non-UTF-8 locale.
    monkeypatch.setattr(configparser, "open", locale_open, raising=False)
    for _ in range(3):
        cfg.get_config()
        assert cfg.config["Service"]["note"] == note
        cfg.save_protocol_defaults(55, 12, 14, 2, 15)
        draft = CalibrationDraft(cfg)
        draft.factors["horizontal"] += 1
        draft.save(cfg)
    cfg.get_config()
    assert cfg.config["Service"]["note"] == note
