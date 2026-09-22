"""Network and system boundaries never execute real commands in these tests."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from helpers import device_system as module

pytestmark = pytest.mark.unit


@pytest.fixture
def network_key() -> str:
    """Generate a throwaway credential used only by mocked network operations."""
    return uuid4().hex


@pytest.fixture
def system(tmp_path, monkeypatch):
    system = module.DeviceSystem(tmp_path)
    monkeypatch.setattr(module.DeviceSystem, "linux", staticmethod(lambda: None))
    monkeypatch.setattr(system, "_wifi_interface", lambda: "wlan0")
    monkeypatch.setattr(module, "run_command", Mock(side_effect=AssertionError("Unexpected command")))
    return system


def test_terse_network_fields_preserve_escaped_colons_and_backslashes():
    assert module.escaped_fields(r"Clinic\:Wi-Fi:85:WPA2") == ["Clinic:Wi-Fi", "85", "WPA2"]
    assert module.escaped_fields(r"Clinic\\:85:WPA2") == ["Clinic\\", "85", "WPA2"]


def test_nmcli_password_is_stdin_only_and_arguments_have_no_shell(
        system, monkeypatch, network_key):
    run = Mock(return_value="Connected")
    monkeypatch.setattr(module, "run_command", run)
    secret = network_key + "$`\\! "
    assert "connected" in system.wifi_connect("Clinic:Wi-Fi", secret, "nmcli", "WPA2")
    args = run.call_args.args[0]
    assert secret not in args
    assert "--ask" in args
    assert run.call_args.kwargs == {"timeout": 35, "input_text": secret + "\n"}


@pytest.mark.parametrize("ssid,credential_case,security", [
    ("", "valid", "WPA2"), ("A" * 33, "valid", "WPA2"),
    ("Clinic", "short", "WPA2"), ("Clinic", "newline", "WPA2"),
    ("Clinic", "valid", "WEP"), ("Clinic", "valid", "WPA2 802.1X"),
])
def test_invalid_or_enterprise_networks_do_not_execute(
        system, ssid, credential_case, security, network_key):
    if credential_case == "short":
        network_key = network_key[:4]
    elif credential_case == "newline":
        network_key = network_key[:8] + "\n" + network_key[8:]
    with pytest.raises(ValueError):
        system.wifi_connect(ssid, network_key, "nmcli", security)
    module.run_command.assert_not_called()


def test_wpa_config_derives_psk_without_argv_secret_and_saves_on_connection(
        system, monkeypatch, network_key):
    run = Mock(side_effect=["7", "OK\nOK", "OK", "OK"])
    monkeypatch.setattr(module, "run_command", run)
    monkeypatch.setattr(system, "_wpa_status", Mock(side_effect=[
        {"id": "2"}, {"wpa_state": "COMPLETED", "id": "7"},
    ]))
    result = system.wifi_connect("Clinic", network_key, "wpa_cli", "[WPA2-PSK-CCMP]")
    assert "connected and saved" in result
    commands = run.call_args_list[1].kwargs["input_text"]
    psk = hashlib.pbkdf2_hmac("sha1", network_key.encode(), b"Clinic", 4096, 32).hex()
    assert f"set_network 7 psk {psk}" in commands
    assert network_key not in commands
    assert all(psk not in str(call.args) for call in run.call_args_list)
    assert run.call_args.args[0][-1] == "save_config"


def test_wpa_failure_removes_new_network_and_reselects_previous(
        system, monkeypatch, network_key):
    run = Mock(side_effect=["7", "FAIL", "OK", "OK"])
    monkeypatch.setattr(module, "run_command", run)
    monkeypatch.setattr(system, "_wpa_status", lambda iface: {"id": "2"})
    with pytest.raises(RuntimeError, match="rejected"):
        system.wifi_connect("Clinic", network_key, "wpa_cli", "WPA2")
    assert run.call_args_list[-2].args[0][-2:] == ["remove_network", "7"]
    assert run.call_args_list[-1].args[0][-2:] == ["select_network", "2"]


def test_command_error_contains_no_stdout_stderr_or_password(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout="SECRET", stderr="password"))
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError) as error:
        module.run_command(["nmcli", "--ask"], input_text="SECRET\n")
    assert "SECRET" not in str(error.value) and "password" not in str(error.value)
    assert run.call_args.kwargs["timeout"] == 5
    assert not run.call_args.kwargs.get("shell")


def test_timezone_validates_from_system_catalog_and_power_is_allowlisted(system, monkeypatch):
    monkeypatch.setattr(system, "timezones", lambda: ["America/New_York", "UTC"])
    run = Mock(return_value="")
    monkeypatch.setattr(module, "run_command", run)
    with pytest.raises(ValueError):
        system.set_timezone("../../etc/shadow")
    with pytest.raises(ValueError):
        system.power("anything")
    run.assert_not_called()
    system.set_timezone("America/New_York")
    assert run.call_args.args[0] == [
        "timedatectl", "--no-ask-password", "set-timezone", "America/New_York",
    ]
    system.power("reboot")
    assert run.call_args.args[0] == ["systemctl", "--no-ask-password", "reboot"]
