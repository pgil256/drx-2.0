"""Relaunch mode and arguments are retained; shutdown controls the launch boundary."""
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from helpers import app_restart
from fixtures.controllers import make_window
from kneespa import KneeSpa

pytestmark = pytest.mark.unit

@pytest.mark.parametrize("platform", ["nt", "posix"])
@pytest.mark.parametrize("entry", ["runtime/raspberry-pi/main/kneespa.py", "development/tools/run_local.py"])
def test_relaunch_preserves_interpreter_spaced_arguments_and_mode(monkeypatch, platform, entry):
    spawn, replace = Mock(), Mock()
    monkeypatch.setattr(app_restart, "os", SimpleNamespace(name=platform, path=os.path, execv=replace))
    monkeypatch.setattr(app_restart.subprocess, "Popen", spawn)
    args = ["--debug", "--config", "path with spaces/device.cfg", "--print-logs"]
    monkeypatch.setattr(sys, "argv", [entry, *args])
    app_restart.restart_app(entry)
    command = [sys.executable, os.path.abspath(entry), *args]
    if platform == "posix":
        replace.assert_called_once_with(sys.executable, command)
        spawn.assert_not_called()
    else:
        spawn.assert_called_once_with(command, close_fds=True)
        replace.assert_not_called()


def test_restart_requests_one_close_and_defers_launch():
    window = make_window()
    window.restart_requested = False
    window._block_active_treatment_exit.return_value = False
    window.close = Mock()
    KneeSpa._on_restart_app(window)
    KneeSpa._on_restart_app(window)
    assert window.restart_requested
    window.close.assert_called_once()


def test_close_waits_for_pool_and_cloud_before_finishing(qtbot):
    window = make_window()
    window.arduino = None
    window.threadpool.activeThreadCount.return_value = 1
    assert not KneeSpa.cleanup(window)
    assert window._closing
    window._cloud_close_thread.join(timeout=1)
    assert not KneeSpa.cleanup(window)
    window.threadpool.activeThreadCount.return_value = 0
    assert KneeSpa.cleanup(window)
    assert window._cleanup_complete
    window.shell.video_modal.cleanup.assert_called_once()
    assert KneeSpa.cleanup(window)
    window.cloud_client.close.assert_called_once_with(wait=True)


@pytest.mark.parametrize("cleaned_up", [False, True])
def test_release_installer_only_runs_after_cleanup_and_offers_restart(monkeypatch, cleaned_up):
    from ui.modals import release_install
    dialog = Mock(restart=True)
    create = Mock(return_value=dialog)
    monkeypatch.setattr(release_install, "ReleaseInstallDialog", create)
    installer, job = object(), {"release": {"version": "v2"}}
    window = SimpleNamespace(_release_install=(installer, job), _cleanup_complete=cleaned_up,
                             restart_requested=False)
    release_install.finish_release_install(window)
    if cleaned_up:
        create.assert_called_once_with(installer, job)
        dialog.exec_.assert_called_once()
        assert window.restart_requested
    else:
        create.assert_not_called()
        assert not window.restart_requested


def test_incomplete_firmware_flash_blocks_reset():
    from controllers.connection_manager import ConnectionManager
    window = make_window()
    window._firmware_update_recovery = "flashing"
    connection = ConnectionManager(window)
    connection.reset_arduino()
    window.threadpool.start.assert_not_called()
    assert "recovery" in window._show_timed_error.call_args.args[0]
