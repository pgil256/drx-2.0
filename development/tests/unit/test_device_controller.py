"""Device mutations stay idle-only, authenticated, and serialized off the GUI thread."""

import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox

from controllers import device_controller as module
from helpers.service_auth import ServiceAccess
from ui.screens.device import DeviceScreen

pytestmark = pytest.mark.unit


@pytest.fixture
def controller(qapp, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DEVICE_STATE_DIR", str(tmp_path))
    window = QMainWindow()
    qtbot.addWidget(window)
    screen = DeviceScreen()
    window.setCentralWidget(screen)
    window.shell = SimpleNamespace(device=screen)
    window.protocol_state = "idle"
    window.protocol_running = False
    window.reset_in_progress = False
    window.actuator_command_in_progress = False
    window.current_user = {"username": "Operator", "status": "admin"}
    window._closing = False
    window.arduino = SimpleNamespace(connected=True, firmware_version="test")
    window.disable_actuator_controls = Mock()
    window.enable_actuator_controls = Mock()
    window._on_restart_app = Mock()
    window._on_logout = Mock()
    window.calibration_controller = SimpleNamespace(
        access=ServiceAccess(str(tmp_path / "pin.json")), _can_open=lambda: True)
    window.cloud_client = Mock(enabled=False)
    window.cloud_client.sync_summary.return_value = {
        "pending": 2, "blocked": 1, "last_sync": "Not recorded yet", "message": "Not configured",
    }
    window.config = Mock()
    controller = module.DeviceController(window)
    controller.timer.stop()
    controller.backend = Mock()
    controller.backend.read.return_value = (80, "Read from device")
    controller.backend.write.side_effect = lambda key, value: (value, "Updated")
    controller.system = Mock()
    controller.system.network.return_value = {}
    controller.system.clock.return_value = {}
    yield controller
    window._closing = True
    controller._pending.clear()
    if controller._worker is not None:
        controller._worker.join(3)
    QApplication.instance().removeEventFilter(controller)
    controller.timer.stop()


def settled(controller, qtbot):
    qtbot.waitUntil(lambda: not controller._busy and not controller._pending, timeout=4000)


def test_worker_blocks_motion_until_finish_and_returns_on_gui_thread(controller, qtbot):
    entered, release = threading.Event(), threading.Event()
    gui_thread = threading.get_ident()
    done = []

    def work():
        entered.set()
        assert threading.get_ident() != gui_thread
        assert release.wait(2)
        return "done"

    controller._queue("protected", work, lambda value: done.append((value, threading.get_ident())),
                      user=dict(controller.window.current_user))
    assert entered.wait(1)
    assert controller.window._device_maintenance_active
    assert not controller.idle()
    controller.window.disable_actuator_controls.assert_called_once()
    release.set()
    settled(controller, qtbot)
    assert not controller.window._device_maintenance_active
    assert done == [("done", gui_thread)]
    controller.window.enable_actuator_controls.assert_called_once()


@pytest.mark.parametrize("state", ["user", "protocol", "reset", "service", "movement"])
def test_queued_mutation_rechecks_user_and_device_before_execution(controller, state):
    user = dict(controller.window.current_user)
    work = Mock()
    controller._busy = True
    controller._queue("protected", work, user=user)
    if state == "user":
        controller.window.current_user = {"username": "Someone else", "status": "admin"}
    elif state == "protocol":
        controller.window.protocol_state = "running"
    else:
        flag = {"reset": "reset_in_progress", "service": "_calibration_active",
                "movement": "actuator_command_in_progress"}[state]
        setattr(controller.window, flag, True)
    controller._busy = False
    controller._next()
    work.assert_not_called()
    assert "not started" in controller.screen.status.text()


def test_technician_restore_requires_pin_even_for_admin_and_rechecks_after_dialog(controller):
    access = controller.window.calibration_controller.access
    access.provision("235689", "235689", True)
    called = Mock()
    controller._authorize(called, technician=True)
    dialog = controller._auth_dialog
    assert dialog is not None
    dialog.submit("999999")
    called.assert_not_called()
    controller.window.protocol_state = "running"
    dialog.submit("235689")
    called.assert_not_called()
    assert controller._auth_dialog is None


def test_clinician_cannot_reboot_without_technician_access(controller):
    controller.window.current_user["status"] = "user"
    controller.action("reboot")
    assert controller._auth_dialog is not None
    controller.system.linux.assert_not_called()
    controller._auth_dialog.reject()
    assert not hasattr(controller.window, "_system_power_action")


def test_power_rechecks_state_after_confirmation(controller, monkeypatch):
    def confirm(*args):
        controller.window.reset_in_progress = True
        return QMessageBox.Yes

    monkeypatch.setattr(module.QMessageBox, "question", confirm)
    controller.action("reboot")
    controller.system.linux.assert_not_called()
    assert not hasattr(controller.window, "_system_power_action")


def test_restore_rechecks_state_after_review(controller, monkeypatch, qtbot):
    controller._service_user = dict(controller.window.current_user)
    controller.screen.unlock_service()
    controller.backups = Mock()
    controller.backups.load.return_value = {
        "created_at": "2026-09-21", "operator": "Technician", "factors": {},
        "scale": -28369, "marks": {},
    }

    controller._review_restore("backup.json", dict(controller.window.current_user))
    settled(controller, qtbot)
    dialog = controller.window.findChild(module.CalibrationRestoreDialog)
    assert dialog is not None
    controller.window.protocol_state = "running"
    dialog.accept()
    controller.backups.restore.assert_not_called()


def test_dimming_wakes_on_first_touch_without_activating_button(controller, qtbot):
    controller._idle_minutes = 1
    controller._brightness = 80
    controller._last_activity = time.monotonic() - 61
    controller.tick()
    settled(controller, qtbot)
    assert controller._restore_level == 80
    assert controller.backend.write.call_args.args == ("brightness", 10)
    button = controller.screen.hardware_button
    clicked = Mock()
    button.clicked.connect(clicked)
    qtbot.mouseClick(button, Qt.LeftButton)
    settled(controller, qtbot)
    clicked.assert_not_called()
    assert controller.backend.write.call_args.args == ("brightness", 80)
    assert controller._restore_level is None
    qtbot.mouseClick(button, Qt.LeftButton)
    clicked.assert_called_once()


def test_dimming_skips_treatment_and_restores_on_service_entry(controller, qtbot):
    controller._idle_minutes = 1
    controller._brightness = 80
    controller._last_activity = time.monotonic() - 61
    controller.window.protocol_state = "running"
    controller.tick()
    controller.backend.write.assert_not_called()
    controller.window.protocol_state = "idle"
    controller._restore_level = 80
    controller.window._calibration_active = True
    controller.tick()
    settled(controller, qtbot)
    assert controller.backend.write.call_args.args == ("brightness", 80)


def test_wake_failure_is_throttled_and_manual_brightness_recovers(controller, qtbot):
    controller._restore_level = 80
    controller.backend.write.side_effect = RuntimeError("Backlight unavailable")
    controller.wake()
    settled(controller, qtbot)
    for _ in range(4):
        controller.wake()
    assert controller.backend.write.call_count == 1
    controller.backend.write.side_effect = lambda key, value: (value, "Updated")
    controller.change("brightness", 70)
    settled(controller, qtbot)
    assert controller._restore_level is None and controller._brightness == 70


def test_wake_key_release_is_consumed(controller, qtbot):
    controller._restore_level = 80
    assert controller.eventFilter(controller.screen, QEvent(QEvent.KeyPress))
    settled(controller, qtbot)
    assert controller.eventFilter(controller.screen, QEvent(QEvent.KeyRelease))


def test_shutdown_waits_for_brightness_restore(controller, qtbot):
    controller._restore_level = 80
    controller.window._closing = True
    assert not controller.shutdown_ready()
    controller._worker.join(2)
    assert controller.shutdown_ready()
    controller.backend.write.assert_called_once_with("brightness", 80)


def test_failed_setting_write_refreshes_actual_readback(controller, qtbot):
    controller.screen.set_setting("volume", 65)
    controller.backend.write.side_effect = RuntimeError("Audio output is unavailable")
    controller.backend.read.return_value = (65, "Current volume")
    controller.screen.sliders["volume"].setValue(90)
    settled(controller, qtbot)
    assert controller.screen.sliders["volume"].value() == 65
    assert "unavailable" in controller.screen.status.text()


def test_service_requires_pin_for_admin_and_locks_when_leaving(controller):
    controller.window.calibration_controller.access.provision("235689", "235689", True)
    controller.require_service(lambda _user: None)
    assert not controller.service_authorized()
    controller._auth_dialog.submit("235689")
    assert controller.service_authorized()
    assert controller.screen._sections.currentIndex() == 2
    controller.screen._select_section(1)
    assert not controller.service_authorized()
    controller.require_service(lambda _user: None)
    assert controller._auth_dialog is not None
    controller._auth_dialog.reject()


def test_automatic_logout_waits_for_safe_idle_and_clears_service(controller):
    controller._logout_minutes = 1
    controller._last_user_activity = time.monotonic() - 70
    controller.window.protocol_running = True
    controller.tick()
    controller.window._on_logout.assert_not_called()
    assert time.monotonic() - controller._last_user_activity < 2
    controller.window.protocol_running = False
    controller._service_user = dict(controller.window.current_user)
    controller.screen.unlock_service()
    controller._last_user_activity = time.monotonic() - 70
    controller.tick()
    controller.window._on_logout.assert_called_once()
    assert not controller.service_authorized()


def release_flow(controller):
    from controllers.release_controller import ReleaseController
    controller.window.cloud_client.cloud_url = "https://cloud.example.test"
    controller._service_user = dict(controller.window.current_user)
    controller.screen.unlock_service()
    updates = ReleaseController(controller)
    controller.updates = updates
    return updates


def test_release_auth_late_result_does_not_restore_locked_session(controller, qtbot):
    updates = release_flow(controller)
    entered, release = threading.Event(), threading.Event()
    old_client = updates.client
    old_client.logout = Mock()

    def request():
        entered.set()
        release.wait(2)
        return {"clinics": []}

    updates._run("login", request)
    assert entered.wait(1)
    assert controller.window._device_maintenance_active
    controller.screen.lock_service()
    release.set()
    qtbot.waitUntil(lambda: not updates.busy)
    old_client.logout.assert_called_once()
    assert not controller.window._device_maintenance_active
    assert not updates.login.isVisible()
    assert not updates.client.context
    assert not controller.screen.actions["flash_software"].isEnabled()


def test_release_selection_displays_latest_without_installing(controller, qtbot):
    updates = release_flow(controller)
    updates._run("latest", lambda: {"raspberry-pi": {"version": "v2", "created_at": "today"},
                                   "arduino": None})
    qtbot.waitUntil(lambda: not updates.busy)
    assert "v2" in controller.screen.software_release.text()
    assert controller.screen.actions["flash_software"].isEnabled()
    assert not controller.screen.actions["flash_firmware"].isEnabled()
    assert not hasattr(controller.window, "_release_install")


def test_verified_release_review_rechecks_service_before_shutdown(controller, monkeypatch):
    from controllers import release_controller
    updates = release_flow(controller)
    controller.window.close = Mock()
    job = {"release": {"version": "v2"}}

    def changed(*args):
        controller.screen.lock_service()
        return QMessageBox.Yes

    monkeypatch.setattr(release_controller.QMessageBox, "question", changed)
    updates._install_review(job)
    controller.window.close.assert_not_called()
    assert not hasattr(controller.window, "_release_install")


def test_verified_release_hands_install_to_shutdown_not_live_controller(controller, monkeypatch):
    from controllers import release_controller
    updates = release_flow(controller)
    controller.window.close = Mock()
    updates.installer.install = Mock()
    monkeypatch.setattr(release_controller.QMessageBox, "question", lambda *args: QMessageBox.Yes)
    job = {"release": {"version": "v2"}}
    updates._install_review(job)
    controller.window.close.assert_called_once()
    assert controller.window._release_install == (updates.installer, job)
    updates.installer.install.assert_not_called()
