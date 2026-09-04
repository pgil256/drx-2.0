"""Regression tests for the Windows no-hardware launcher."""
import os
from unittest.mock import MagicMock

import pytest

from tools import run_local


@pytest.mark.unit
def test_local_credentials_are_seeded_without_overriding_explicit_values(monkeypatch):
    for name in ("ADMIN_PIN", "ADMIN_USERNAME", "USER_PIN", "USER_USERNAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "Custom Admin")

    run_local._seed_local_credentials()

    assert os.environ["ADMIN_PIN"] == "1234"
    assert os.environ["ADMIN_USERNAME"] == "Custom Admin"
    assert os.environ["USER_PIN"] == "5678"
    assert os.environ["USER_USERNAME"] == "Sandbox User"


@pytest.mark.unit
def test_dev_arduino_reports_connected_without_serial_port():
    arduino = run_local._DevArduino()

    assert arduino.connect_to_arduino() is True
    assert arduino.verify_connection() is True
    assert arduino.send("T") is True


@pytest.mark.unit
def test_main_patches_connection_manager_backend(monkeypatch):
    class FakeApplication:
        def __init__(self, _args):
            pass

        def setStyle(self, _style):
            pass

        def exec_(self):
            return 0

    class FakeWindow:
        def __init__(self, debug_mode):
            assert debug_mode is True
            self.loading_spinner = MagicMock()

        def setFixedSize(self, _width, _height):
            pass

        def show(self):
            pass

    manager_module = run_local._connection_manager
    original_reset = manager_module.ConnectionManager.reset_arduino
    monkeypatch.setattr(run_local, "QApplication", FakeApplication)
    monkeypatch.setattr(run_local.kneespa, "KneeSpa", FakeWindow)
    monkeypatch.setattr(manager_module, "Arduino", object)
    monkeypatch.setattr(
        manager_module.ConnectionManager,
        "reset_arduino",
        original_reset,
    )

    run_local.main()

    assert manager_module.Arduino is run_local._DevArduino
    assert manager_module.ConnectionManager.reset_arduino is not original_reset
