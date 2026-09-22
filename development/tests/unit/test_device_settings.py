"""System controls use bounded commands and report real readback values."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from helpers import device_settings as module

pytestmark = pytest.mark.unit


@pytest.fixture
def settings(monkeypatch, tmp_path):
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.shutil, "which", lambda name: name)
    return module.DeviceSettings(tmp_path)


def test_volume_uses_default_sink_and_reads_back(settings, monkeypatch):
    run = Mock(side_effect=["Volume: 42% 42%", "Mute: no", "", "", "Volume: 61%", "Mute: no"])
    monkeypatch.setattr(settings, "_run", run)
    assert settings.read("volume")[0] == 42
    assert settings.write("volume", 60)[0] == 61
    assert run.call_args_list[2].args[0] == [
        "pactl", "set-sink-volume", "@DEFAULT_SINK@", "60%",
    ]
    assert run.call_args_list[3].args[0] == ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"]


def test_volume_falls_back_to_alsa_and_detects_mute(settings, monkeypatch):
    run = Mock(side_effect=[OSError("No PulseAudio"), OSError("No Master"), "[45%] [off]"])
    monkeypatch.setattr(settings, "_run", run)
    assert settings.read("volume")[0] == 0
    assert settings._audio == ("amixer", "PCM")


def test_backlight_scales_to_hardware_range(settings):
    path = settings.backlights / "panel"
    path.mkdir()
    (path / "max_brightness").write_text("255")
    (path / "brightness").write_text("128")
    assert settings.read("brightness")[0] == 50
    actual, _ = settings.write("brightness", 80)
    assert actual == 80
    assert (path / "brightness").read_text() == "204"


@pytest.mark.parametrize("key,value", [
    ("brightness", 0), ("brightness", 9), ("volume", -1), ("volume", 101),
    ("volume", "50"), ("volume", True), ("arbitrary", 50),
])
def test_invalid_settings_do_not_execute_commands(settings, monkeypatch, key, value):
    run = Mock()
    monkeypatch.setattr(settings, "_run", run)
    with pytest.raises(ValueError):
        settings.write(key, value)
    run.assert_not_called()


def test_absent_hardware_is_not_a_fake_slider_value(settings, monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert settings.read("volume")[0] is None
    assert settings.read("brightness")[0] is None


def test_commands_have_timeout_and_do_not_use_shell(monkeypatch):
    run = Mock(return_value=SimpleNamespace(stdout="result"))
    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.DeviceSettings._run(["amixer", "sget", "PCM"]) == "result"
    assert run.call_args.kwargs == {
        "check": True, "capture_output": True, "text": True, "timeout": 3,
    }
