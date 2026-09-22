"""Device administration with serialized workers, authentication and idle guards."""

from datetime import datetime, timezone
from pathlib import Path
import shutil
import threading
import time
from typing import Callable, Optional

from PyQt5.QtCore import QEvent, QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from main.config.constants import APP_VERSION, DATA_PATHS
from config.paths import DEVICE_STATE_DIR
from helpers.calibration_backup import CalibrationBackups
from helpers.device_records import DeviceRecords, write_json
from helpers.device_settings import DeviceSettings
from helpers.device_system import DeviceSystem
from helpers.logging import setup_logger
from ui.modals.device_dialogs import (
    CalibrationRestoreDialog, TimezoneDialog, WifiDialog, show_report,
)
from ui.modals.service_pin_dialog import ServicePinDialog


class DeviceController(QObject):
    """Keep every blocking call off Qt and recheck ownership before mutations."""

    completed = pyqtSignal(object, str)

    def __init__(self, window: object) -> None:
        super().__init__(window)
        self.window = window
        self.backend = DeviceSettings()
        self.system = DeviceSystem(Path(DEVICE_STATE_DIR))
        self.records = DeviceRecords(Path(DEVICE_STATE_DIR))
        self.backups = CalibrationBackups(Path(DEVICE_STATE_DIR))
        self.logger = setup_logger(component="Device settings")
        self._busy = False
        self._pending = {}
        self._running = None
        self._worker = None
        self._auth_dialog = None
        self._service_user = None
        self._last_activity = time.monotonic()
        self._last_user_activity = self._last_activity
        preferences = self.records.preferences()
        self._idle_minutes = preferences["idle_dim_minutes"]
        self._logout_minutes = preferences["logout_minutes"]
        self._brightness = None
        self._restore_level = None
        self._dim_pending = False
        self._swallow_touch = False
        self._swallow_key = False
        self._wake_failed_at = 0.0
        self._last_snapshot = 0.0
        self._details = {}
        self.completed.connect(self._complete)
        screen = window.shell.device
        screen.setting_requested.connect(self.change)
        screen.refresh_requested.connect(self.refresh)
        screen.action_requested.connect(self.action)
        screen.service_access_requested.connect(lambda: self.require_service(lambda _user: None))
        screen.service_locked.connect(self._lock_service)
        if hasattr(window.shell, "user_changed"):
            window.shell.user_changed.connect(self.session_changed)
        screen.idle_timeout.setCurrentIndex(screen.idle_timeout.findData(self._idle_minutes))
        screen.logout_timeout.setCurrentIndex(screen.logout_timeout.findData(self._logout_minutes))
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        QApplication.instance().installEventFilter(self)
        if self._idle_minutes:
            QTimer.singleShot(0, lambda: self._queue(
                "read_brightness", lambda: self.backend.read("brightness"),
                lambda result: self._setting_done("brightness", result),
            ))

    @property
    def screen(self) -> object:
        return self.window.shell.device

    def idle(self) -> bool:
        w = self.window
        return getattr(w, "protocol_state", "idle") == "idle" and not any(
            getattr(w, name, False) is True for name in (
                "protocol_running", "reset_in_progress", "actuator_command_in_progress",
                "_calibration_active", "_device_maintenance_active", "_closing",
                "_physical_stop_active",
            )
        )

    def _owned_idle(self, user: dict) -> bool:
        return bool(user) and user == self.window.current_user and self.idle()

    def service_authorized(self) -> bool:
        return bool(self._service_user and self._service_user == self.window.current_user
                    and self.screen.service_unlocked and not self.window._closing)

    def _lock_service(self) -> None:
        self._service_user = None
        updates = getattr(self, "updates", None)
        if updates is not None:
            updates.clear_session()

    def session_changed(self) -> None:
        self.screen.lock_service()
        self._last_user_activity = time.monotonic()
        self.refresh_profile()

    def refresh_profile(self) -> None:
        profile = getattr(self.window.shell, "profile", None)
        if profile is not None:
            user = self.window.current_user or {}
            patients = getattr(self.window, "patients", None)
            context = patients.staff.context if patients is not None else {}
            clinic = (context.get("clinic") or {}).get("name", "")
            profile.set_session_details(user.get("email", ""), self._logout_minutes, clinic)

    def require_service(self, callback: Callable) -> None:
        from controllers.machine_sign_in_controller import authorize
        if not authorize(self.window, "service", lambda: self.require_service(callback)):
            return
        if self.service_authorized() and self.window.calibration_controller._can_open():
            callback(dict(self.window.current_user))
            return

        def unlock(user: dict) -> None:
            self._service_user = dict(user)
            self.screen.unlock_service()
            callback(user)

        self._authorize(unlock, technician=True, service=True)

    def refresh_identity(self) -> None:
        arduino = getattr(self.window, "arduino", None)
        self.screen.set_firmware(getattr(arduino, "firmware_version", None),
                                 bool(arduino and arduino.connected))
        self.screen.set_details({"clock": "Current time: " +
                                 datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")})

    def tick(self) -> None:
        if getattr(self.window, "_closing", False):
            return
        self.refresh_identity()
        now = time.monotonic()
        self.refresh_profile()
        if self._service_user and not self.service_authorized():
            self.screen.lock_service()
        if not self.idle() or getattr(self.window, "_patient_lookup_pending", False) is True:
            self._last_user_activity = now
        elif (self._logout_minutes and self.window.current_user
              and now - self._last_user_activity >= self._logout_minutes * 60):
            self._last_user_activity = now
            self.screen.lock_service()
            for dialog in self.window.findChildren(QDialog):
                if dialog.isVisible():
                    dialog.reject()
            self.window._on_logout()
            self.wake()
            return
        if (self.screen.isVisible() and self._restore_level is None and not self._busy
                and not getattr(getattr(self, "updates", None), "busy", False)
                and now - self._last_snapshot >= 10):
            self._last_snapshot = now
            self._queue("snapshot", self._snapshot, self._show_snapshot)
        if not self.idle():
            self.wake()
        elif (self._idle_minutes and self._brightness is not None
              and self._brightness > 10 and self._restore_level is None and not self._dim_pending
              and not self._busy and not self._pending
              and QApplication.activeModalWidget() is None
              and time.monotonic() - self._last_activity >= self._idle_minutes * 60):
            self._dim_pending = True
            self._restore_level = self._brightness
            self._queue("idle_dim", lambda: self.backend.write("brightness", 10), self._dim_done,
                        condition=lambda: self.idle() and self._restore_level is not None)

    def _dim_done(self, result: object) -> None:
        self._dim_pending = False
        if not self.idle() or time.monotonic() - self._last_activity < self._idle_minutes * 60:
            self.wake()

    def wake(self) -> None:
        self._last_activity = time.monotonic()
        restoring = ("wake_brightness" in self._pending or
                     self._running is not None and self._running[0] == "wake_brightness")
        if (self._restore_level is not None and not restoring
                and self._last_activity - self._wake_failed_at >= 5):
            value = self._restore_level
            self._queue("wake_brightness", lambda: self.backend.write("brightness", value),
                        self._wake_done)

    def _wake_done(self, result: object) -> None:
        self._restore_level = None
        self._dim_pending = False
        self._wake_failed_at = 0.0
        self._setting_done("brightness", result)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.MouseButtonPress, QEvent.TouchBegin, QEvent.KeyPress,
                    QEvent.MouseMove, QEvent.Wheel, QEvent.TouchUpdate):
            self._last_user_activity = time.monotonic()
        if self._swallow_key and kind == QEvent.KeyRelease:
            self._swallow_key = False
            return True
        if self._swallow_touch and kind in (QEvent.MouseButtonRelease, QEvent.TouchEnd):
            self._swallow_touch = False
            return True
        if kind in (QEvent.MouseButtonPress, QEvent.TouchBegin, QEvent.KeyPress):
            dimmed = self._restore_level is not None
            self.wake()
            if dimmed:
                self._swallow_touch = kind != QEvent.KeyPress
                self._swallow_key = kind == QEvent.KeyPress
                return True
        elif kind in (QEvent.MouseMove, QEvent.Wheel):
            self.wake()
        return super().eventFilter(watched, event)

    def refresh(self) -> None:
        if getattr(self.window, "_closing", False):
            return
        self.refresh_identity()
        self._last_snapshot = time.monotonic()
        for key in ("volume", "brightness"):
            if key != "brightness" or self._restore_level is None:
                self._queue("read_" + key, lambda k=key: self.backend.read(k),
                            lambda result, k=key: self._setting_done(k, result))
        self._queue("snapshot", self._snapshot, self._show_snapshot)

    def _snapshot(self) -> dict:
        results = {}
        for key, read in (("network", self.system.network), ("clock", self.system.clock)):
            try:
                results[key] = read()
            except (RuntimeError, OSError, ValueError):
                results[key] = {}
        results["history"] = self.records.history()
        results["backups"] = self.backups.list()
        results["sync"] = self.window.cloud_client.sync_summary(DATA_PATHS["PENDING_UPLOADS"])
        return results

    def _show_snapshot(self, result: dict) -> None:
        network, clock, sync = result["network"], result["clock"], result["sync"]
        queued = sync["pending"]
        blocked = sync["blocked"]
        sync_time = "Last successful sync: " + self.screen.local_date(str(sync["last_sync"]))
        addresses = ", ".join(network.get("addresses", [])) or "Unavailable"
        ntp = "Automatic time: Unavailable"
        if clock:
            enabled = "Enabled" if clock.get("NTP") == "yes" else "Disabled"
            synced = ("Synchronized" if clock.get("NTPSynchronized") == "yes"
                      else "Not synchronized")
            ntp = f"Automatic time: {enabled} · {synced}"
        details = {
            "network": "Network: " + (network.get("network") or "Unavailable"),
            "addresses": "IP addresses: " + addresses,
            "wifi_backend": "Wi-Fi setup: " + network.get("wifi_backend", "Unavailable"),
            "timezone": "Time zone: " + clock.get("Timezone", "Unavailable"),
            "ntp": ntp,
            "pending": "Pending uploads: " + (str(queued) if queued is not None else "Unknown"),
            "last_sync": sync_time,
            "sync_time": sync_time,
            "sync_detail": (f"{queued} pending · {blocked} need attention. " + sync["message"])
                if queued is not None else sync["message"],
        }
        self._details.update(details)
        self.screen.set_details(details)
        self.screen.set_history(result["history"], result["backups"])

    def change(self, key: str, value: int) -> None:
        from controllers.machine_sign_in_controller import authorize
        if not authorize(self.window, "device", lambda: self.change(key, value)):
            return
        self.wake()

        def applied(result: tuple) -> None:
            if key == "brightness":
                self._restore_level = None
                self._wake_failed_at = 0.0
                self._dim_pending = False
            self._setting_done(key, result)

        self._queue("write_" + key, lambda: self.backend.write(key, value),
                    applied)

    def _setting_done(self, key: str, result: tuple) -> None:
        value, detail = result
        self.screen.set_setting(key, value, detail)
        if key == "brightness" and self._restore_level is None:
            self._brightness = value

    def _queue(self, key: str, work: Callable, done: Optional[Callable] = None,
               user: Optional[dict] = None, condition: Optional[Callable] = None) -> None:
        if getattr(self.window, "_closing", False):
            return
        self._pending[key] = (work, done, user, condition)
        self._next()

    def _next(self) -> None:
        if self._busy or not self._pending or getattr(self.window, "_closing", False):
            return
        key = next(iter(self._pending))
        work, done, user, condition = self._pending.pop(key)
        if (user is not None and not self._owned_idle(user)) or (condition and not condition()):
            if key == "idle_dim":
                self._dim_pending = False
                self._restore_level = None
            self.screen.set_status("Device state changed; the operation was not started.")
            self._next()
            return
        self._busy = True
        self._running = (key, done, user)
        if user is not None:
            self.window._device_maintenance_active = True
            self.window.disable_actuator_controls()
        if key not in ("snapshot", "idle_dim", "wake_brightness") and not key.startswith("read_"):
            self.screen.set_status("Working…")

        def run() -> None:
            try:
                result = work()
                self.completed.emit(result, "")
            except Exception as exc:
                # System exceptions can contain secrets or record contents. Log only the type.
                self.logger.error("Device operation %s failed (%s)", key, type(exc).__name__)
                safe = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else (
                    "The operation failed. Check device permissions and storage."
                )
                self.completed.emit(None, safe)

        self._worker = threading.Thread(target=run, daemon=True)
        try:
            self._worker.start()
        except RuntimeError:
            self._complete(None, "Unable to start the operation. Please retry.")

    def _complete(self, result: object, error: str) -> None:
        key, done, user = self._running
        self._running = None
        self._busy = False
        if user is not None:
            self.window._device_maintenance_active = False
            self.window.actuator_command_in_progress = False
            self.window.enable_actuator_controls()
        if getattr(self.window, "_closing", False):
            self._pending.clear()
            return
        if error:
            self.screen.set_status(error)
            if key in ("write_volume", "write_brightness"):
                setting = key[len("write_"):]
                self._queue("read_" + setting, lambda: self.backend.read(setting),
                            lambda actual: self._setting_done(setting, actual))
            if key == "idle_dim":
                self._dim_pending = False
                self.wake()
            if key == "wake_brightness":
                self._wake_failed_at = time.monotonic()
                self.screen.set_status("Could not restore brightness. Use the brightness control.")
        elif done is not None:
            done(result)
        elif isinstance(result, str):
            self.screen.set_status(result)
        self._next()

    def _authorize(self, callback: Callable, technician: bool = False,
                   service: bool = False) -> None:
        from controllers.machine_sign_in_controller import authorize
        if not authorize(self.window, "service" if technician else "device",
                         lambda: self._authorize(callback, technician, service)):
            return
        self.wake()
        user = dict(self.window.current_user or {})
        def eligible() -> bool:
            return (bool(user) and user == self.window.current_user and
                    (self.window.calibration_controller._can_open() if service else self.idle()))

        if not eligible():
            self.screen.set_status("Log in and finish treatment, movement, reset or service first.")
            return
        if self._auth_dialog is not None:
            self._auth_dialog.raise_()
            return
        if user.get("status") == "admin" and not technician:
            callback(user)
            return
        try:
            dialog = ServicePinDialog(self.window.calibration_controller.access,
                                      user.get("status") == "admin", self.window)
        except (OSError, ValueError):
            self.screen.set_status("The service credential is unavailable.")
            return
        self._auth_dialog = dialog

        def authorized(result: int) -> None:
            self._auth_dialog = None
            dialog.deleteLater()
            if result == QDialog.Accepted and eligible():
                callback(user)

        dialog.finished.connect(authorized)
        dialog.open()

    def action(self, name: str, value: object = None) -> None:
        self.wake()
        if name == "lock_service":
            self.screen.lock_service()
            return
        service_actions = ("view_report", "export_diagnostics", "backup_calibration",
                           "restore_calibration", "check_releases", "flash_software",
                           "flash_firmware")
        from controllers.machine_sign_in_controller import authorize
        if not authorize(self.window, "service" if name in service_actions else "device",
                         lambda: self.action(name, value)):
            return
        if name in service_actions and not self.service_authorized():
            self.require_service(lambda _user: self.action(name, value))
            return
        if name in ("check_releases", "flash_software", "flash_firmware"):
            if getattr(self, "updates", None) is None:
                from controllers.release_controller import ReleaseController
                self.updates = ReleaseController(self)
            self.updates.action(name)
            return
        if name == "test_connection":
            self._queue(name, self._test_connection, self._connection_done)
        elif name == "retry_sync":
            self._queue(name, self._retry_sync, lambda _result: self._system_done(
                "Sync retry finished. See upload status for any records needing attention."))
        elif name == "test_sound":
            self._queue(name, self.system.test_sound)
        elif name == "idle_timeout":
            self._queue(name, lambda: self.records.set_idle_timeout(value),
                        lambda _result: self._set_idle_timeout(value))
        elif name == "logout_timeout":
            self._queue(name, lambda: self.records.set_logout_timeout(value),
                        lambda _result: self._set_logout_timeout(value))
        elif name == "view_report":
            self._queue(name, lambda: self.records.report(str(value)),
                        lambda record: show_report("Service report", record, self.window)
                        if self.service_authorized() else None, condition=self.service_authorized)
        elif name == "export_diagnostics":
            context = self._diagnostic_context()
            self._queue(name, lambda: self.records.diagnostic_bundle(context),
                        lambda path: self._export_done(path) if self.service_authorized() else None,
                        condition=self.service_authorized)
        elif name == "backup_calibration":
            user = dict(self.window.current_user)
            self._queue(
                name, lambda: self.backups.create(self.window.config, user["username"]),
                lambda path: self._backup_done(path), user=user,
                condition=self.service_authorized,
            )
        elif name == "restore_calibration":
            self._review_restore(str(value), dict(self.window.current_user))
        elif name == "wifi":
            self._authorize(lambda user: self._queue(
                "wifi_scan", self.system.wifi_scan, lambda rows: self._wifi(rows, user),
            ))
        elif name == "timezone":
            self._authorize(lambda user: self._queue(
                "timezones", self.system.timezones, lambda zones: self._timezone(zones, user),
            ))
        elif name == "sync_clock":
            self._authorize(lambda user: self._queue(name, self.system.sync_clock,
                                                   self._system_done, user=user))
        elif name in ("restart_app", "reboot", "poweroff"):
            self._authorize(lambda user: self._power(name, user))

    def _set_idle_timeout(self, minutes: int) -> None:
        self._idle_minutes = minutes
        self.screen.set_status("Idle dimming timeout saved.")

    def _set_logout_timeout(self, minutes: int) -> None:
        self._logout_minutes = minutes
        self._last_user_activity = time.monotonic()
        self.refresh_profile()
        self.screen.set_status("Automatic logout timer saved.")

    def _test_connection(self) -> dict:
        cloud = self.window.cloud_client
        result = cloud.ping() if cloud.enabled else {"error": "disabled"}
        return {"internet": self.system.test_internet(), "cloud": result}

    def _connection_done(self, result: dict) -> None:
        error = result["cloud"].get("error")
        cloud = {"disabled": "Not configured", "unauthorized": "Authentication failed",
                 "forbidden": "Access denied"}.get(error, "Unavailable") if error else "Connected"
        details = {"internet": "Internet: " + result["internet"], "cloud": "Cloud: " + cloud}
        self._details.update(details)
        self.screen.set_details(details)
        self.screen.set_status("Connection checks finished.")
        self.refresh()

    def _retry_sync(self) -> None:
        self.window.cloud_client.retry_pending(DATA_PATHS["PENDING_UPLOADS"], retry_blocked=True)

    def _diagnostic_context(self) -> dict:
        arduino = getattr(self.window, "arduino", None)
        connected = bool(arduino and arduino.connected)
        return {
            "device_id": self.screen._device_id.text()[11:],
            "software_version": APP_VERSION,
            "firmware_version": getattr(arduino, "firmware_version", None) if connected else None,
            "controller": "Connected" if connected else "Disconnected",
            "device_state": self.window.protocol_state,
            "cloud": self._details.get("cloud", "Not checked"),
            "pending_uploads": self._details.get("pending", "Unknown"),
            "last_sync": self._details.get("last_sync", "Unknown"),
        }

    def _export_done(self, path: Path) -> None:
        self.screen.set_status(f"Diagnostics saved: {path}")
        target, _filter = QFileDialog.getSaveFileName(
            self.window, "Save diagnostics to USB or another folder", str(path), "ZIP (*.zip)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if target and Path(target).resolve() != path.resolve():
            self._queue("copy_export", lambda: shutil.copy2(str(path), target),
                        lambda _result: self.screen.set_status(f"Diagnostics saved: {target}"))

    def _backup_done(self, path: Path) -> None:
        self.screen.set_status(f"Calibration backup saved: {path.name}")
        self.refresh()

    def _review_restore(self, name: str, user: dict) -> None:
        def review(data: dict) -> None:
            if not self._owned_idle(user) or not self.service_authorized():
                return
            dialog = CalibrationRestoreDialog(data, self.window)

            def finish(result: int) -> None:
                if result == QDialog.Accepted:
                    self._queue("restore_calibration", lambda: self.backups.restore(
                        name, self.window.config, user["username"], reviewed=data),
                        self._restore_done, user=user, condition=self.service_authorized)
                dialog.deleteLater()

            dialog.finished.connect(finish)
            dialog.open()
        self._queue("read_backup", lambda: self.backups.load(name, self.window.config), review)

    def _restore_done(self, backup: Path) -> None:
        self.window.initial_setup_complete = False
        self.window._no_automatic_recovery = True
        self.window.set_protocol_state("fault")
        self.screen.set_status(
            "Calibration restored. Remove loads and reset from Setup, then verify.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        record = {"schema": 1, "mode": "calibration", "configuration_saved": True,
                  "updated_at": datetime.now(timezone.utc).isoformat(),
                  "technician": (self.window.current_user or {}).get("username", "Unknown"),
                  "results": {}, "restored": True, "pre_restore_backup": backup.name}
        self._queue("restore_report", lambda: write_json(
            self.records.root / "service-reports" / f"hardware-{stamp}.json", record),
            lambda _result: self.refresh())

    def _wifi(self, rows: list, user: dict) -> None:
        if not self._owned_idle(user):
            return
        if not rows:
            self.screen.set_status("No Wi-Fi networks found. Check the adapter and try again.")
            return
        dialog = WifiDialog(rows, self.window)

        def finish(result: int) -> None:
            if result == QDialog.Accepted and self._owned_idle(user):
                row = rows[dialog.network.currentIndex()]
                password = dialog.password.text()
                self._queue("wifi_connect", lambda: self.system.wifi_connect(
                    row["ssid"], password, row["backend"], row["security"]),
                    self._system_done, user=user)
            dialog.password.clear()
            dialog.deleteLater()

        dialog.finished.connect(finish)
        dialog.open()

    def _timezone(self, zones: list, user: dict) -> None:
        if not self._owned_idle(user):
            return
        current = self._details.get("timezone", "").replace("Time zone: ", "")
        if not zones:
            self.screen.set_status("No system time zones are available.")
            return
        dialog = TimezoneDialog(zones, current, self.window)

        def finish(result: int) -> None:
            if result == QDialog.Accepted:
                zone = dialog.choice.currentText()
                self._queue("set_timezone", lambda: self.system.set_timezone(zone),
                            self._system_done, user=user)
            dialog.deleteLater()

        dialog.finished.connect(finish)
        dialog.open()

    def _system_done(self, message: str) -> None:
        self.screen.set_status(message)
        self.refresh()

    def _power(self, action: str, user: dict) -> None:
        labels = {"restart_app": "Restart App", "reboot": "Restart Device", "poweroff": "Shut Down"}
        if not self._owned_idle(user):
            return
        answer = QMessageBox.question(
            self.window, labels[action],
            f"{labels[action]} now? Device controls will close first.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if not self._owned_idle(user):
            return
        if action == "restart_app":
            self.window._on_restart_app()
        else:
            try:
                self.system.linux()
            except RuntimeError as exc:
                self.screen.set_status(str(exc))
                return
            self.window._system_power_action = action
            self.window.close()

    def shutdown_ready(self) -> bool:
        self.timer.stop()
        self._pending.clear()
        updates = getattr(self, "updates", None)
        if updates is not None and not updates.shutdown_ready():
            return False
        if self._auth_dialog is not None:
            self._auth_dialog.reject()
        if self._worker is not None and self._worker.is_alive():
            return False
        if self._restore_level is not None:
            value = self._restore_level
            self._restore_level = None

            def restore() -> None:
                try:
                    self.backend.write("brightness", value)
                except Exception:
                    self.logger.warning("Could not restore brightness during shutdown")

            self._worker = threading.Thread(target=restore, daemon=True)
            self._worker.start()
            return False
        return True
