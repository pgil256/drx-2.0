# KneeSpa main window — modern AppShell view layer on the FAILSAFE controller base.
#
# Union of the two development lines (Phase B replay):
#   * Backend/controllers (improvement-plan): the Arduino QThread, controllers/
#     (auth, connection, protocol, safety), frozen calibration math
#     (set_to_distance / set_to_c_distance / move_actuator, now in
#     controllers/motion_controller.py),
#     GPIO handling with auto-release timers, and the reset paths are preserved
#     from the improvement-plan KneeSpa.
#   * View (feat/gui-modernization): the monolithic kneespa.ui + findChild wiring
#     is replaced by ui.app_shell.AppShell; the screens' pyqtSignals/setters are
#     the seam between view and backend.
#
# Treatment presentation is owned by ProtocolController and uses the modern
# view setters directly. Window slots delegate lifecycle changes to it.
import logging
import traceback
import sys
import os
import RPi.GPIO as GPIO
import time
import smtplib
import threading
import shutil
from email.mime.text import MIMEText
from datetime import datetime
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QObject,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
)

# Application modules import from this directory only (config.constants, not
# main.config.constants): two roots load separate copies of the same module,
# and main.* could resolve to the legacy main/ tree kept for rollback.
if __name__ == "__main__":
    from config.migrate_state import migrate_default_state

    migrate_default_state()

from config.constants import (
    APP_VERSION,
    WINDOW_TITLE,
    ACTUATORS,
    SUCCESS_MESSAGES,
    EMERGENCYSTOP,
    EXTRAFORWARD,
    EXTRABACKWARD,
    EXTRAENABLE,
    EMAIL_CONFIG,
    PRESSURE_MAX,
    LATERAL_MAX_DEGREES,
    DEFAULT_HORIZONTAL_POSITION,
    DEFAULT_PROTOCOL_MINUTES,
    PROTOCOL_MINUTES_MIN,
    PROTOCOL_MINUTES_MAX,
    DATA_PATHS,
)

from ui.modals.pressure_notice import PressureNotice
from ui.modals.rehome_prompt import RehomePrompt
from ui.modals.upload_error import UploadErrorDialog
from config.config import Configuration
from helpers.csv import CSVHelper
from helpers.measurement_state import MeasurementState, diagnostics_max_age_s
from helpers.app_restart import restart_app
from helpers.device_system import DeviceSystem
from helpers.cloud_client import CloudClient
from helpers.cloud_contract import cloud_error_message, validate_patient
from controllers.hardware_service_controller import HardwareServiceController
from controllers.device_controller import DeviceController
from controllers.device_state import DeviceStateAttributes
from controllers.motion_controller import (
    MotionAttributes, MotionController, WindowSetupView,
)
from controllers.linked_patient import link_patient, unlink_patient
from controllers.patient_controller import PatientController
from controllers.machine_sign_in_controller import MachineSignInController, authorize
from helpers.support_ticket import create_ticket, validate_ticket
from controllers.leg_length_controller import LegLengthController

from helpers.logging import LoggerSetup, read_recent_log_lines, setup_logger
from helpers.watchdog import extend_watchdog_for_shutdown, start_watchdog

# Modern view layer — the composition root for chrome + screens + modals.
from ui.app_shell import AppShell
from ui.measurements import calibrated_reading
from ui.presentation import device_presentation, present
from ui.widgets.loading_spinner import LoadingSpinner
from ui.widgets.treatment_status_panel import TreatmentStatusPanel

from controllers.safety_monitor import SafetyMonitor
from controllers.stop_controller import SHUTDOWN, stops_for
from controllers.auth_controller import AuthController
from controllers.protocol_controller import ProtocolController
from controllers.connection_manager import ConnectionManager

# Suppress Qt warnings. Rule values must be lowercase true/false — Qt silently
# rejects capitalized "False" as a malformed rule, so the suppression is a no-op.
# QT_X11_NO_MITSHM disables X shared-memory image blits, which fail with
# BadMatch (ShmPutImage) over VNC/remote X and can leave video frames black.
os.environ["QT_X11_NO_MITSHM"] = "1"
os.environ["QT_LOGGING_RULES"] = "*.debug=false;qt.qpa.xcb.warning=false"

# Map a Setup jog action to the legacy (speed_factor, direction) pair used by
# move_actuator ("20" = fast, "04" = slow; +1 forward, -1 reverse).
_JOG_SPEED = {
    "rev_fast": ("20", -1),
    "rev": ("04", -1),
    "fwd": ("04", 1),
    "fwd_fast": ("20", 1),
}


class _CloudBridge(QObject):
    """Carries cloud API results from worker threads back to the UI."""
    lookup_done = pyqtSignal(int, object)
    status_changed = pyqtSignal(str)
    upload_failed = pyqtSignal(str, bool)


# Main Python class
class KneeSpa(DeviceStateAttributes, MotionAttributes, QMainWindow):
    """Main application class for KneeSpa."""

    support_email_result = pyqtSignal(bool, str)

    def set_to_distance(self, inches, actuator):
        """Send an axial (or other A-channel) target: see MotionController."""
        return self.motion.set_to_distance(inches, actuator)

    def set_to_c_distance(self, degrees):
        """Send a lateral target in degrees: see MotionController."""
        return self.motion.set_to_c_distance(degrees)

    ### App Initialization ####
    def __init__(self, debug_mode=False, config_path=None):
        super().__init__()

        self.logger = setup_logger(component="KneeSpa")
        self.logger.info(
            "Initializing KneeSpa class in %s mode", "debug" if debug_mode else "production"
        )
        # The order is load-bearing: controllers need the shell; the patient
        # and machine-sign-in controllers need cloud_client and the login
        # modal; _connect_shell runs before setup_timers; GPIO is set up
        # before the deferred Arduino start.
        self._init_state(config_path)
        self._init_window(debug_mode)
        self._init_controllers()
        self._init_users()
        self._init_cloud()
        self._init_runtime()

    def _init_state(self, config_path) -> None:
        """Protocol/UI state, the configuration and the hardware flags."""
        # --- protocol / UI state (mirrors the legacy controller) ---
        self.protocol_value = "1"          # selected protocol (Treatment picker)
        self.protocol_running = False
        self._closing = False
        self.restart_requested = False
        self._system_power_action = None
        self._device_maintenance_active = False
        self._no_automatic_recovery = False
        self._measurement = MeasurementState()
        self._measurement_fault = None
        self.protocol_start_time = None
        self.protocol_duration = 0
        self._paused_at = None             # wall-clock pause anchor for the UI timer
        self.last_measured_pressure = None  # latest load-cell reading (status_emit)
        self._prev_settings = {}           # for mid-protocol slider rollback
        self.current_use_pulse_setting = True
        self.current_pulse_rate = None     # pulses/sec from the Settings slider
        self.actuator_a = ACTUATORS["AXIAL"]["ID"]
        self.actuator_b = ACTUATORS["HORIZONTAL"]["ID"]
        self.actuator_c = ACTUATORS["LATERAL"]["ID"]

        # Backend initialization
        # QObject already exposes a thread() method. Keep the owned Arduino
        # QThread under a distinct name so first-time connection setup cannot
        # mistake that inherited method for a live worker thread.
        self.arduino = None
        self.arduino_thread = None
        self.I2Cstatus_event = threading.Event()  # Thread-safe event for synchronization
        # Setup movement and its commanded positions (checklist A3). The
        # window's position and timer attributes delegate to it.
        self.motion = MotionController(
            lambda: self.arduino, lambda: self.config, self.device_state,
            WindowSetupView(self), logger=self.logger,
            leg=lambda: getattr(self, "leg", None),
            done_event=self.I2Cstatus_event,
            protocol_running=lambda: self.protocol_running,
            release_leg_gpio=self._release_leg_gpio,
            timer_parent=self,
        )
        self.config = Configuration(config_path=config_path)
        self.config.get_config()
        self.logger.info(
            "Device number: %s; configuration: %s",
            self.config.device_number, self.config.configFile,
        )
        if not self.config.calibrated:
            # Surface after the window is up; a corrupt config used to
            # degrade silently to generated default geometry
            QTimer.singleShot(1500, self._warn_uncalibrated)
        self.initial_setup_complete = False
        self.reset_in_progress = False  # Flag to prevent overlapping resets
        self.actuator_command_in_progress = False  # Prevents simultaneous actuator commands
        self.mid_protocol_warning_shown = False
        self.protocol_stop_requested = False
        self._physical_stop_active = False
        # time.monotonic() of the device's stop button press while the
        # firmware's release may still run (see StopController); else None.
        self._firmware_release_since = None
        self.worker = None

    def _init_window(self, debug_mode) -> None:
        """The shell, kiosk window flags, spinner and safety banner."""
        # --- build the modern view ---
        self.setWindowTitle(WINDOW_TITLE)
        self.shell = AppShell()
        self.setCentralWidget(self.shell)
        self.centralWidget().setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        if not debug_mode:
            # Flags MUST be set before showing: changing window flags on an
            # already-shown window recreates the native handle and dropped
            # the window out of fullscreen (and could leave it hidden).
            # Keep Qt.Window so it stays a top-level kiosk window.
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
            # Kiosk guard: Qt derives a top-level window's minimum size from
            # its layout, and showFullScreen() will NOT shrink below it — if
            # font metrics ever push the layout minimum past the panel
            # (1360x768), the window hangs off the bottom of the screen.
            # An explicit minimum overrides the layout-derived one, so
            # fullscreen always matches the display exactly.
            self.setMinimumSize(1, 1)
            self.showFullScreen()
            self.logger.info("Production mode: Set to full screen without frame")
        else:
            self.logger.info("Debug mode: Running in windowed mode")

        self.loading_spinner = LoadingSpinner(
            parent=self,
            size=300,        # up to you
            speed_pct=100    # 2.5× normal
        )

        # Top-of-window safety banner. It is withheld while a protocol is
        # active (starting/running/stopping) and while the device sits in
        # the fault state that follows one: the Protocols page (navigation
        # is locked there during a run) shows phase/pressure/time inline
        # with its own STOP, and safety events raise the acknowledged
        # _show_safety_alert dialog. Outside a run (idle Setup-page jogs)
        # device warnings still overlay the top of the shell.
        self.treatment_panel = TreatmentStatusPanel(
            parent=self, suppress_when=self._banner_suppressed
        )
        self.treatment_panel.stop_requested.connect(self.panel_stop_requested)

    def _init_controllers(self) -> None:
        """Behavior controllers that operate on the window and its shell."""
        self.safety = SafetyMonitor(self)
        self.auth = AuthController(self)
        self.protocol = ProtocolController(self)
        self.connection = ConnectionManager(self)
        self.leg = LegLengthController(self)
        self.hardware_service = HardwareServiceController(self)
        self.device_controller = DeviceController(self)
        self._calibration_active = False
        # Protocol lifecycle state: idle / starting / running / stopping / fault
        self.protocol_state = "idle"

    def _init_users(self) -> None:
        """Local login users; nobody is signed in at start."""
        # Initialize the CSV helper
        self.csv = CSVHelper()
        try:
            self.csv.initialize_data()
            self.users = self.csv.users
            self.logger.info("%s", SUCCESS_MESSAGES["DATA_LOADED"])
        except Exception as e:
            self.users = {}
            self.logger.exception("Error loading CSV data")
            self._show_timed_error(f"Failed to load CSV data: {str(e)}")
        self.current_user = None

    def _init_cloud(self) -> None:
        """The cloud client, linked-patient state and cloud-backed controllers."""
        self.cloud_patient = None
        self._patient_lookup_id = 0
        self._patient_lookup_pending = False
        self._cloud_bridge = _CloudBridge()
        self._cloud_bridge.lookup_done.connect(self._on_cloud_lookup_done)
        self._cloud_bridge.status_changed.connect(self._on_cloud_status)
        self._cloud_bridge.upload_failed.connect(self._show_upload_error)
        self._upload_error_dialog = None
        self._last_upload_error = None
        self.cloud_client = CloudClient(
            on_status=self._cloud_bridge.status_changed.emit,
            on_upload_error=self._cloud_bridge.upload_failed.emit,
        )
        self.patients = PatientController(self)
        self.machine_sign_in = MachineSignInController(self)
        self._cloud_retry_timer = QTimer(self)
        self._cloud_retry_timer.timeout.connect(self._retry_pending_uploads)

    def _init_runtime(self) -> None:
        """Wire the view, start timers and GPIO, then defer hardware and cloud start."""
        # Controls locked while the MCU is busy (jog/Go/Stop/Reset-Arduino) —
        # the same gating group the legacy `actuator_controls` list provided.
        self.actuator_controls = self.shell.setup.control_buttons()

        # Treatment Settings sliders start from the persisted defaults (§15.4).
        self.shell.treatment.set_settings(self.config.protocol_defaults())

        self.threadpool = QtCore.QThreadPool()
        self.logger.info(
            "Multithreading with maximum %s threads", self.threadpool.maxThreadCount()
        )

        # Wire the view's signals/setters to the backend, then start hardware.
        self._connect_shell()
        self.setup_timers()
        from helpers.release_installer import firmware_recovery
        from config.paths import DEVICE_STATE_DIR
        from pathlib import Path
        self._firmware_update_recovery = firmware_recovery(Path(DEVICE_STATE_DIR))
        if self._firmware_update_recovery:
            self._no_automatic_recovery = True
            self.set_protocol_state("fault")

        # Ensure a persisted per-device id exists for support tickets (§15.5).
        try:
            configured_device_id = self.config.ensure_device_id()
        except Exception:
            configured_device_id = ""
            self.logger.exception("Could not ensure device id")
        cloud_device_id = getattr(self.cloud_client, "device_id", "")
        self.shell.device.set_device_id(
            (cloud_device_id if isinstance(cloud_device_id, str) else "") or configured_device_id
        )

        self.shell.navigate("home")
        self._set_badge(False)  # offline until the Arduino connects
        # Leaving the Treatment screen during an active protocol requires an
        # explicit caution acknowledgement; the protocol keeps running.
        self.shell.set_nav_confirmation(self._confirm_leave_treatment)
        self.shell.set_overlay_guard(self._block_nonessential_overlay_during_treatment)

        # Initialize GPIO setup
        self.setup_gpio()
        # Let the first event-loop turn paint the window before serial probing
        # or reset work begins. In debug/windowed mode the final ``show()`` is
        # called by main() after construction; a synchronous connection wait
        # here allowed firmware notices to appear before the app itself.
        QTimer.singleShot(100, self.setup_arduino)
        if self.cloud_client.enabled:
            self.shell.treatment.set_cloud_status("Connecting to cloud…")
            self.cloud_client.ping_async()
            self._cloud_retry_timer.start(5000)

    # ----- view ↔ backend wiring -----
    def _connect_shell(self):
        """Connect every screen/modal signal to its backend slot."""
        s = self.shell

        # Auth (the shell surfaces these; gating lives in the shell).
        s.login_attempted.connect(self._on_login_attempt)
        s.logout_requested.connect(self._on_logout)
        s.exit_requested.connect(self._on_exit_app)
        s.profile.restart_requested.connect(lambda: self.device_controller.action("restart_app"))
        s.device.calibration_requested.connect(self.hardware_service.open)
        s.device.hardware_tests_requested.connect(self.hardware_service.open_tests)

        # Setup screen.
        s.setup.jog_requested.connect(self._on_setup_jog)
        s.setup.go_requested.connect(self._on_setup_go)
        s.setup.stop_requested.connect(self._on_setup_stop)
        s.setup.mark_default_requested.connect(self._on_mark_default)
        s.setup.reset_arduino_requested.connect(self._on_setup_reset_arduino)
        s.setup.emergency_stop_requested.connect(self._on_estop)

        # Treatment screen.
        s.treatment.patient_change_requested.connect(self._show_patient_modal)
        s.treatment.patient_edit_requested.connect(self._edit_patient)
        s.treatment.cloud_error_requested.connect(self._reopen_upload_error)
        s.treatment.next_treatment_requested.connect(self._prepare_next_treatment)
        s.patient_modal.submitted.connect(self._on_patient_pin)
        s.patient_modal.add_requested.connect(self._add_patient)
        s.patient_modal.closed.connect(self._on_patient_cancel)
        s.treatment.protocol_selected.connect(self._on_protocol_selected)
        s.treatment.start_requested.connect(self.start_or_stop_protocol)
        s.treatment.resume_requested.connect(self._on_treatment_resume)
        s.treatment.pause_requested.connect(self._on_treatment_pause)
        s.treatment.estop_requested.connect(self._on_estop)
        s.treatment.setting_changed.connect(self._on_setting_changed)
        self._pressure_state_timer = QTimer(self)
        self._pressure_state_timer.setInterval(250)
        self._pressure_state_timer.timeout.connect(self._refresh_measurement_display)
        self._pressure_state_timer.start()

        # Support screen.
        s.support.submit_ticket_requested.connect(self._on_submit_ticket)
        self.support_email_result.connect(self._on_support_email_result)

        # Video modal (owns the embedded VLC player).
        s.video_modal.play_toggled.connect(self._on_video_toggled)

    def _set_badge(self, connected):
        """Reflect Arduino connectivity on the Setup header badge."""
        present(self.logger, "Setup connection badge",
                lambda: self.shell.setup.set_arduino_connected(connected))
        present(self.logger, "device status", self._refresh_device_presentation)

    def _refresh_device_presentation(self) -> None:
        """Present controller readiness without modifying device operation."""
        state = device_presentation(
            connected=bool(self.arduino and self.arduino.connected),
            protocol_state=self.protocol_state,
            resetting=self.reset_in_progress is True,
            initialized=self.initial_setup_complete is True,
            calibrated=bool(self.config.marks_valid and self.config.scale_calibrated),
            physical_stop=getattr(self, "_physical_stop_active", False) is True,
        )
        self.shell.set_device_status(state.label, state.detail, state.can_start)

    def _reflect_setup(self, key, value):
        """Reflect a commanded target without claiming that a sensor measured it."""
        self.motion.view.show_position(key, value)

    ### UI Methods ###

    def disable_actuator_controls(self):
        """Lock the Setup motion controls: see MotionController."""
        self.motion.disable_actuator_controls()

    def enable_actuator_controls(self):
        """Unlock the Setup motion controls after a 200 ms debounce: see MotionController."""
        self.motion.enable_actuator_controls()

    def reset_setup_readings(self):
        """Reset setup readings to default values (modern Setup rows)."""
        self._reflect_setup("axial", 0)
        self._reflect_setup("lateral", 0)
        self._reflect_setup("pressure", 0)
        self._reflect_setup("horizontal", DEFAULT_HORIZONTAL_POSITION)

    # ----- Treatment: settings / duration -----
    @staticmethod
    def _clamp_minutes(value):
        try:
            v = round(float(value))
        except (TypeError, ValueError):
            v = DEFAULT_PROTOCOL_MINUTES
        return int(max(PROTOCOL_MINUTES_MIN, min(PROTOCOL_MINUTES_MAX, v)))

    def _duration_minutes(self):
        """Treatment duration (minutes) from the Settings slider, clamped to the
        safe range; falls back to the default if the control is unavailable."""
        try:
            v = self.shell.treatment.settings_values().get(
                "duration", DEFAULT_PROTOCOL_MINUTES
            )
        except Exception:
            self.logger.exception("Could not read the treatment duration; using %d min",
                                  DEFAULT_PROTOCOL_MINUTES)
            v = DEFAULT_PROTOCOL_MINUTES
        return self._clamp_minutes(v)

    def _on_protocol_selected(self, n):
        self.protocol_value = str(n)

    def _on_patient_pin(self, pin: str) -> None:
        if self.protocol_running or not self.current_user:
            return
        if not authorize(self, "patients.view", lambda: self._on_patient_pin(pin)):
            return
        self._patient_lookup_id += 1
        request_id = self._patient_lookup_id
        self.cloud_patient = None
        self.shell.treatment.clear_patient()
        if not self.cloud_client.enabled:
            self._on_cloud_lookup_done(request_id, {"error": "disabled"})
            return
        self._patient_lookup_pending = True
        self.shell.treatment.set_patient_pending(True)
        self.shell.patient_modal.set_pending(True)
        bridge = self._cloud_bridge

        def _lookup() -> None:
            result = self.cloud_client.lookup_pin(pin)
            bridge.lookup_done.emit(request_id, result)

        try:
            threading.Thread(target=_lookup, daemon=True).start()
        except RuntimeError as exc:
            # Without a worker nothing would ever clear the pending state.
            self.logger.error("Could not start patient lookup: %s", exc)
            self._on_cloud_lookup_done(request_id, {"error": "unavailable"})

    def _on_cloud_lookup_done(self, request_id: int, result: object) -> None:
        if getattr(self, "_closing", False) or request_id != self._patient_lookup_id:
            return
        if self.protocol_running:
            # This guard includes errors: a failed lookup must not detach the
            # patient from an active treatment or alter its displayed plan.
            self.logger.warning("Ignoring patient lookup that resolved during a treatment")
            return
        self._patient_lookup_pending = False
        self.shell.treatment.set_patient_pending(False)
        self.shell.patient_modal.set_pending(False)
        self.cloud_patient = None
        if not isinstance(result, dict) or "error" in result:
            message = cloud_error_message(result)
            self.shell.treatment.set_patient_error(message + " — no patient linked")
            self.shell.patient_modal.show_error(message)
            return
        try:
            patient, values, protocol = validate_patient(result)
        except ValueError:
            message = "Patient settings or identity need correction in the cloud dashboard"
            self.shell.treatment.set_patient_error(message + " — no patient linked")
            self.shell.patient_modal.show_error(message)
            return
        # Validation is atomic: no values reach clamping/rounding widgets until
        # the identity and the entire plan have passed the contract.
        link_patient(self, patient, values, protocol)
        self.shell.patient_modal.hide()  # Success must not emit the cancellation signal.

    def _on_patient_edit(self) -> None:
        """Detach the previous identity as soon as replacement entry starts."""
        if self.protocol_running:
            return
        unlink_patient(self)

    def _add_patient(self) -> None:
        self.patients.add()

    def _edit_patient(self) -> None:
        self.patients.edit()

    def _show_patient_modal(self) -> None:
        if self.protocol_running or not self.current_user:
            return
        if self.current_user.get("machine_sign_in"):
            if self.current_user.get("status") == "patient":
                self._on_logout()
                self.shell.show_login()
                return
            if not authorize(self, "patients.view", self._show_patient_modal):
                return
        self._on_patient_edit()
        self.shell.patient_modal.open_over(self.shell)

    def _on_patient_cancel(self) -> None:
        if self.protocol_running:
            return
        self._on_patient_edit()

    def _retry_pending_uploads(self):
        if not getattr(self, "_closing", False):
            self.cloud_client.retry_pending_async(DATA_PATHS["PENDING_UPLOADS"])

    def _retry_blocked_uploads(self) -> None:
        self.cloud_client.retry_pending_async(DATA_PATHS["PENDING_UPLOADS"], retry_blocked=True)

    def _on_cloud_status(self, message: str) -> None:
        if self._closing:
            return
        self.shell.treatment.set_cloud_status(message)
        if message == "Treatments synced":
            self._last_upload_error = None
            if self._upload_error_dialog is not None:
                self._upload_error_dialog.close()

    def _show_upload_error(self, message: str, can_retry: bool = False) -> None:
        """Show a persistent, nonblocking upload alert on the GUI thread."""
        if self._closing:
            return
        self._last_upload_error = (message, can_retry)
        self.shell.treatment.set_upload_error()
        dialog = self._upload_error_dialog
        if dialog is None:
            dialog = UploadErrorDialog(self)
            dialog.retry_requested.connect(self._retry_blocked_uploads)
            self._upload_error_dialog = dialog
        dialog.set_message(message, can_retry)
        dialog.show()
        dialog.raise_()

    def _reopen_upload_error(self) -> None:
        if self._last_upload_error is not None:
            self._show_upload_error(*self._last_upload_error)

    def _prepare_next_treatment(self) -> None:
        """Require an explicit patient choice after recovery has completed."""
        if self.protocol_state != "idle" or self.reset_in_progress or self._physical_stop_active:
            return
        self.shell.treatment.clear_outcome()
        self.shell.treatment.set_progress(0, self._duration_minutes() * 60)
        self.shell.treatment.set_phase("idle")
        if not self.current_user:
            self.shell.show_login()
        else:
            self._show_patient_modal()

    def _on_setting_changed(self, key, value):
        """A Treatment Settings slider moved. Mid-protocol changes are gated by a
        one-time safety confirmation; on cancel the slider rolls back."""
        if (self.current_user or {}).get("machine_sign_in"):
            def apply_setting():
                self.shell.treatment.set_settings({key: value})
                self._on_setting_changed(key, value)

            if not authorize(self, "settings", apply_setting):
                self.shell.treatment.set_settings({key: self._prev_settings.get(key, value)})
                return
        if ((self.current_user or {}).get("status") == "patient"
                or not self._confirm_mid_protocol_change()):
            self.shell.treatment.set_settings({key: self._prev_settings.get(key, value)})
            return
        self._prev_settings[key] = value
        if key == "duration" and not self.protocol_running:
            self.shell.treatment.set_progress(0, float(value) * 60)
        if key == "pulse_rate":
            self.current_use_pulse_setting = value > 0
            self.current_pulse_rate = value if value > 0 else None
        if not self.worker:
            return
        if key == "max_pressure":
            self.worker.request_live_pressure(value)
        elif key == "max_left":
            self.worker.request_live_angle("left", value)
        elif key == "max_right":
            self.worker.request_live_angle("right", value)
        elif key == "pulse_rate":
            self.worker.request_live_pulse_rate(value)
        # "duration" is a pre-run parameter — the Treatment screen locks its
        # slider during an active run, so it is deliberately NOT adjusted live
        # here (a mid-run shorten could silently end the treatment).
        self.logger.info("Mid-protocol: worker %s updated to %s", key, value)

    def _seed_modern_run_inputs(self):
        """Snapshot the modern Settings sliders for the controllers and the
        mid-protocol rollback seam before a start/stop toggle."""
        # A fresh run never starts paused. The anchor used to survive a
        # banner EMERGENCY STOP taken while paused (that path bypasses
        # _on_estop), after which PAUSE was permanently inert.
        self._paused_at = None
        try:
            vals = self.shell.treatment.settings_values()
        except Exception:
            # The run keeps the previous settings snapshot.
            self.logger.exception("Could not read the Treatment settings")
            return
        self._prev_settings = dict(vals)
        try:
            self.protocol_value = str(self.shell.treatment.selected_protocol())
        except Exception:
            self.logger.exception("Could not read the selected protocol; keeping %s",
                                  self.protocol_value)
        rate = vals.get("pulse_rate", 0) or 0
        self.current_pulse_rate = rate if rate > 0 else None
        self.current_use_pulse_setting = rate > 0

    # ----- Treatment: run-state handlers -----
    def start_or_stop_protocol(self):
        """Start/Stop button (see controllers.protocol_controller)."""
        if not self.current_user and not self.protocol_running:
            self.shell.show_login()
            return
        self._seed_modern_run_inputs()
        self.protocol.start_or_stop()

    def _on_treatment_pause(self):
        self.protocol.pause()

    def _on_treatment_resume(self):
        self.protocol.resume()

    def _on_estop(self):
        """Emergency stop from the modern Setup/Treatment screens."""
        self.protocol.stop_from_view()

    def _warn_uncalibrated(self):
        reasons = "\n".join(
            self.config.calibration_errors[:4]
        ) or "calibration data invalid"
        self._show_safety_alert(
            "DEVICE UNCALIBRATED - treatments are disabled.\n\n"
            f"{reasons}\n\n"
            "Recalibrate and restart before treating patients."
        )

    # ----- Setup: jog / go / stop / reset -----
    def _on_setup_reset_arduino(self) -> None:
        """Authorize user-requested resets without gating automatic recovery."""
        if authorize(self, "setup", self._on_setup_reset_arduino):
            self.reset_arduino()

    def _on_setup_jog(self, key, action):
        """A Setup jog button was tapped. move_actuator stays the authoritative,
        safety-clamped path; the row's local pre-move is corrected by reflecting
        the true commanded position back onto the slider."""
        if not authorize(self, "setup", lambda: self._on_setup_jog(key, action)):
            return
        if action == "reset":
            self.motion.setup_reset(key)
            return
        if key == "leg_length":
            self._leg_jog(action)
            return
        if key == "pressure":
            # Pressure arrows edit the target. Only Go sends a pressure command.
            return

        speed, direction = _JOG_SPEED.get(action, ("04", 1))
        actuator = {
            "axial": self.actuator_a,
            "lateral": self.actuator_c,
            "horizontal": self.actuator_b,
        }.get(key)
        if actuator is not None:
            self.move_actuator(actuator, speed, direction)

    def _leg_jog(self, action):
        handler = {
            "rev_fast": self.reverse_fast_button_clicked,
            "rev": self.reverse_button_clicked,
            "fwd": self.forward_button_clicked,
            "fwd_fast": self.forward_fast_button_clicked,
        }.get(action)
        if handler:
            handler()

    def _on_setup_go(self, key):
        """Setup Go, once the operator is authorized: see MotionController.setup_go."""
        if not authorize(self, "setup", lambda: self._on_setup_go(key)):
            return False
        return self.motion.setup_go(key)

    def _on_setup_stop(self, key):
        """A Setup row's Stop: see MotionController.setup_stop."""
        self.motion.setup_stop(key)

    def _on_mark_default(self):
        """Mark As Default: persist the current Treatment Settings as protocol
        defaults (§15.4), clamped to constants."""
        if not authorize(self, "setup", lambda: self._on_mark_default()):
            return
        vals = self.shell.treatment.settings_values()
        mp = max(0, min(PRESSURE_MAX, vals.get("max_pressure", 40)))
        ml = max(0, min(abs(LATERAL_MAX_DEGREES), abs(vals.get("max_left", 10))))
        mr = max(0, min(abs(LATERAL_MAX_DEGREES), abs(vals.get("max_right", 10))))
        pr = max(0, min(5, vals.get("pulse_rate", 1)))
        dur = self._clamp_minutes(vals.get("duration", DEFAULT_PROTOCOL_MINUTES))
        try:
            self.config.save_protocol_defaults(mp, ml, mr, pr, dur, motor_speeds=vals)
            self.shell.treatment.set_settings(
                {"max_pressure": mp, "max_left": ml, "max_right": mr,
                 "pulse_rate": pr, "duration": dur}
            )
            self._show_timed_error(
                f"Saved treatment defaults: {dur} min · {mp:g} lbs · "
                f"left {ml:g}° / right {mr:g}° · pulse {pr:g}/sec.\n"
                f"Motor speed: {vals['motor_speed']:g}%."
            )
        except Exception:
            self.logger.exception("Failed to save defaults")
            self._show_timed_error("Could not save defaults.")

    # ----- auth -----
    def _on_login_attempt(self, pin):
        """Modern login modal submits the whole PIN; the salted-hash verify and
        lockout live in controllers.auth_controller."""
        if self.protocol_running:
            return
        self.machine_sign_in.clear()
        self.auth.handle_login(pin)
        if self.current_user is None:
            # Specifics (lockout countdown, etc.) arrive via the timed error
            # box; the modal shows the inline generic failure.
            present(self.logger, "login failure message",
                    lambda: self.shell.login_failed("Invalid PIN. Please try again."))

    def _on_logout(self):
        if self._block_active_treatment_exit():
            return
        self.logger.info("Handling logout")
        self.machine_sign_in.clear()
        self.patients.clear_session()
        self.current_user = None
        try:
            unlink_patient(self)
        except Exception:
            # Logout continues, but a patient left linked must be visible.
            self.logger.exception("Could not unlink the patient at logout")
        self.shell.logout()

    def _on_exit_app(self):
        """Exit App from the Profile screen — full cleanup via closeEvent."""
        if self._block_active_treatment_exit():
            return
        self.logger.info("Handling app exit")
        self.close()

    def _on_restart_app(self) -> None:
        if self._closing or self.restart_requested or self._block_active_treatment_exit():
            return
        self.restart_requested = True
        self.logger.info("Application restart requested")
        self.close()

    def _is_admin(self):
        return bool(self.current_user) and self.current_user.get("status") == "admin"

    def update_ui_after_login(self):
        """Update user interface with user details after login (modern shell:
        close the modal, set the user chip, and go to the Treatment screen)."""
        self.logger.info("Updating UI after login")
        self.machine_sign_in.clear()
        self.shell.set_access_role(None)
        self.patients.clear_session()
        is_admin = self._is_admin()
        title = "Administrator" if is_admin else "Clinician"
        self.shell.login_succeeded(
            self.current_user["username"], title=title,
            is_admin=is_admin,
        )
        self.shell.support.set_contact(
            self.current_user.get("username", ""), self.current_user.get("email", ""),
        )
        if self.shell._current == "protocols":
            # Start with a clean patient selection; entry is an explicit operator action.
            self._on_patient_edit()

    # ----- Support -----
    def _on_submit_ticket(self, payload: dict) -> None:
        """Validate contact details and send a retryable request with device context."""
        if getattr(self, "_support_mail_busy", False) is True:
            return
        try:
            payload = validate_ticket(payload)
        except ValueError as exc:
            self.shell.support.set_delivery_state("invalid", str(exc))
            return
        pending = getattr(self, "_pending_support_ticket", None)
        if pending is None or pending[0] != payload:
            try:
                device_id = self.config.ensure_device_id()
            except Exception:
                self.logger.exception("Could not read support device identity")
                device_id = "Unavailable"
            cloud_id = getattr(getattr(self, "cloud_client", None), "device_id", "")
            if isinstance(cloud_id, str) and cloud_id:
                device_id = cloud_id
            arduino = getattr(self, "arduino", None)
            connected = bool(arduino and arduino.connected)
            user = self.current_user or {}
            ticket = create_ticket(payload, {
                "Device ID": device_id,
                "Software version": APP_VERSION,
                "Firmware version": (getattr(arduino, "firmware_version", None) or "Not reported")
                    if connected else "Controller disconnected",
                "Controller connection": "Connected" if connected else "Disconnected",
                "Device state": getattr(self, "protocol_state", "Unknown"),
                "Operator": user.get("username", "Not signed in"),
            })
            self._pending_support_ticket = (dict(payload), ticket)
        else:
            ticket = pending[1]
        self._send_support_email(
            subject=ticket["subject"], body=ticket["body"],
            receiver_email=EMAIL_CONFIG["TICKET_EMAIL"], reply_to=ticket["reply_to"],
            success_message=f"Ticket sent. Request reference: {ticket['reference']}.",
            failure_prefix="Failed to send ticket",
        )

    def _on_video_toggled(self, playing):
        # The VideoModal owns the embedded VLC player; this is just telemetry.
        self.logger.info("Video play toggled: %s", playing)

    def _send_support_email(
        self, *, subject: str, body: str, receiver_email: str,
        success_message: str, failure_prefix: str, reply_to: str = "",
    ) -> None:
        """Build MIME headers and send on a daemon thread, logging SMTP failures."""
        if getattr(self, "_support_mail_busy", False) is True:
            return
        self._support_mail_busy = True
        signal = getattr(self, "support_email_result", None)
        shell = getattr(self, "shell", None)
        if shell is not None:
            shell.support.set_delivery_state("sending", "Sending request…")
        sender_email = EMAIL_CONFIG["SENDER_EMAIL"]
        sender_password = EMAIL_CONFIG["SENDER_PASSWORD"]
        smtp_server = EMAIL_CONFIG["SMTP_SERVER"]
        smtp_port = EMAIL_CONFIG["SMTP_PORT"]

        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email
        if reply_to:
            message["Reply-To"] = reply_to

        def _send() -> None:
            try:
                if not sender_email or not sender_password or not receiver_email:
                    raise RuntimeError("SMTP credentials are not configured")
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, receiver_email, message.as_string())
                self.logger.info("%s", success_message)
                if signal is not None:
                    signal.emit(True, success_message)
            # A worker thread: every failure must reach the Support screen,
            # or it would stay on "Sending" for good.
            except Exception as e:
                self.logger.exception(f"{failure_prefix}: {e}")
                if signal is not None:
                    signal.emit(False, "Request not sent. Check the connection or contact your administrator.")

        try:
            threading.Thread(target=_send, daemon=True).start()
        except RuntimeError as exc:
            self._support_mail_busy = False
            self.logger.error("Could not start support delivery: %s", exc)
            if shell is not None:
                shell.support.set_delivery_state("failed", "Request not sent. Please retry.")

    def _on_support_email_result(self, success: bool, message: str) -> None:
        """Receive worker results on the GUI thread, with a persistent retryable result."""
        self._support_mail_busy = False
        if success:
            self._pending_support_ticket = None
        if not getattr(self, "_closing", False):
            self.shell.support.set_delivery_state("sent" if success else "failed", message)

    # ----- protocol state / navigation gating -----
    def set_protocol_state(self, state):
        """Protocol lifecycle (see controllers.protocol_controller)."""
        self.protocol.set_state(state)
        controller = getattr(self, "device_controller", None)
        if controller is not None and state != "idle":
            controller.wake()

    def _confirm_leave_treatment(self, source_page: str, destination_page: str) -> bool:
        return self.protocol.confirm_leave_treatment(source_page, destination_page)

    def _block_active_treatment_exit(self) -> bool:
        if not self.device_state.can_exit():
            self._show_timed_error("Finish movement, reset or device service before leaving.")
            return True
        return self.protocol.block_active_treatment_exit()

    def _block_nonessential_overlay_during_treatment(self) -> bool:
        return self.protocol.block_nonessential_overlay()

    def panel_stop_requested(self):
        self.protocol.panel_stop_requested()

    def _banner_suppressed(self):
        """True whenever the protocol state machine is not idle."""
        return getattr(self, "protocol_state", "idle") != "idle"

    def _show_safety_alert(self, message: str, warning: bool = False) -> None:
        """Persistent, acknowledged alert for safety events.

        Safety stops used to auto-dismiss after 5 seconds, so an operator
        who looked away never knew an emergency stop fired.

        Device-originated safety notices are warnings rather than emergency
        stops, so they use the orange warning icon and title.
        """
        self.logger.error(f"Safety alert: {message}")
        # Coalesce: a fault cascade (protocol abort -> firmware ERROR from
        # the same event) used to stack a second modal on top of the first;
        # fold follow-on messages into the box the operator already sees
        existing = getattr(self, "_active_safety_alert", None)
        if existing is not None and existing.isVisible():
            # Never let a later emergency inherit an existing warning's less
            # urgent presentation. A warning added to a critical alert stays
            # critical as well.
            if not warning and existing.property("safetyWarning"):
                existing.setIcon(QMessageBox.Critical)
                existing.setWindowTitle("SAFETY STOP")
                existing.setProperty("safetyWarning", False)
            if message not in existing.text():
                existing.setText(existing.text() + "\n\n" + message)
            return
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning if warning else QMessageBox.Critical)
        msg_box.setWindowTitle("DEVICE SAFETY WARNING" if warning else "SAFETY STOP")
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
        msg_box.setProperty("safetyWarning", warning)
        # Release the box when it is dismissed, as _show_timed_error does:
        # every dismissed alert used to stay alive, owned by the window, for
        # the kiosk's uptime. Drop the reference as the box is deleted, so
        # the next alert never calls isVisible() on a deleted box (V10).
        msg_box.setAttribute(Qt.WA_DeleteOnClose, True)

        def forget(*_args, box=msg_box):
            if getattr(self, "_active_safety_alert", None) is box:
                self._active_safety_alert = None

        msg_box.destroyed.connect(forget)
        msg_box.show()  # non-modal so STOP controls stay reachable
        # Keep a reference so it is not garbage-collected
        self._active_safety_alert = msg_box

    ### Backend Methods ###

    def handle_connection_failed(self, message):
        self._set_badge(False)
        self.connection.handle_connection_failed(message)

    def cleanup(self) -> bool:
        """Begin shutdown once and poll resource completion without blocking Qt."""
        if not getattr(self, "_cleanup_started", False):
            self._cleanup_started = True
            self._closing = True
            self.machine_sign_in.clear()
            self.machine_sign_in.timer.stop()
            self.patients.clear_session()
            self._shutdown_began = time.monotonic()
            # The shutdown stop: see StopController (kind "shutdown").
            stops_for(self).stop(SHUTDOWN)
            # Outbox flushing may wait on bounded network I/O; keep Qt responsive.
            self._cloud_close_thread = threading.Thread(
                target=lambda: self.cloud_client.close(wait=True), name="cloud-shutdown",
            )
            self._cloud_close_thread.start()
            self.shell.setEnabled(False)

        arduino = self.arduino
        if arduino is not None:
            drained = arduino.wait_for_drain(0)
            if not drained and time.monotonic() - self._shutdown_began < 2.0:
                return False
            arduino._running = False
            io_thread = arduino._io_thread
            if io_thread is not None and io_thread.is_alive():
                return False
        if self.arduino_thread is not None:
            self.arduino_thread.quit()
            if self.arduino_thread.isRunning():
                return False
        device_controller = getattr(self, "device_controller", None)
        if device_controller is not None and not device_controller.shutdown_ready():
            return False
        if self.threadpool.activeThreadCount() or self._cloud_close_thread.is_alive():
            return False
        if arduino is not None:
            self.connection.teardown_arduino()
        if not getattr(self, "_cleanup_complete", False):
            self.shell.video_modal.cleanup()
            GPIO.cleanup()
            self._cleanup_complete = True
        return True

    def closeEvent(self, event) -> None:
        if self.cleanup():
            event.accept()
        else:
            event.ignore()
            QTimer.singleShot(50, self.close)

    def move_actuator(self, actuator, speed_factor, direction):
        """Jog an actuator one step: see MotionController."""
        return self.motion.move_actuator(actuator, speed_factor, direction)

    def stop_actuators(self):
        """Emergency stop for all actuators."""
        self.logger.warning("Emergency stop triggered")
        self.connection.cancel_reset()
        if getattr(self, "_physical_stop_active", False) is True:
            # The device's stop button has already stopped every motor, and
            # the firmware is backing the load off by itself. An X ends that
            # release and the firmware does not start another, so a Stop
            # tapped after the button used to leave the load on until Reset.
            self.logger.warning("Stop not sent: the device's stop button owns the release")
            return
        try:
            if not self.arduino.send("X"):  # Stop all movement
                # A stop that could not even be queued is an alarm, not a
                # log line: the link is down and the physical E-stop is the
                # only independent stop path.
                self.logger.error("Emergency stop could not be sent - link down")
                self._show_timed_error(
                    "STOP NOT DELIVERED - connection down. "
                    "Press the physical emergency stop immediately."
                )
        except Exception as e:
            self.logger.exception("Error in emergency stop")
            self._show_timed_error(f"Emergency stop failed: {str(e)}")

    # ----- leg-length (FIT) jog handlers (open-loop F-commands + GPIO) -----
    def _move_leg(self, command):
        """Delegate timing and estimate updates to the FIT command owner."""
        if getattr(self, "_service_leg_position_unknown", False) is True:
            self._show_timed_error("Use the leg-length Return control to establish zero.")
            return False
        return self.leg.move(command)

    def forward_button_clicked(self):
        """Handle forward button press - normal speed."""
        return KneeSpa._move_leg(self, "F+")

    def reverse_button_clicked(self):
        """Handle reverse button press - normal speed."""
        return KneeSpa._move_leg(self, "F-")

    def forward_fast_button_clicked(self):
        """Handle forward button press - fast speed."""
        return KneeSpa._move_leg(self, "FF")

    def reverse_fast_button_clicked(self):
        """Handle reverse button press - fast speed."""
        return KneeSpa._move_leg(self, "FR")

    def _release_leg_gpio(self):
        """Drop the Pi-side leg-motor direction pins to a safe state."""
        if getattr(self, "leg", None) is not None:
            self.leg.cancel()
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

    def _start_service_leg_gpio(self, forward: bool) -> None:
        """Exercise the production Pi leg drive for one bounded service jog."""
        if not self._calibration_active or self._physical_stop_active or self._closing:
            raise RuntimeError("Service movement is no longer permitted")
        GPIO.output(EXTRAFORWARD, GPIO.HIGH if forward else GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW if forward else GPIO.HIGH)
        QTimer.singleShot(600, self._release_leg_gpio)

    def reset_extra_button_clicked(self):
        """Home the open-loop FIT axis, updating zero only after completion."""
        return self.leg.home()

    def ensure_arduino_connection(self):
        return self.connection.ensure_arduino_connection()

    def update_protocol_time(self):
        """Protocol countdown (see controllers.protocol_controller), plus the
        Treatment screen's inline progress ring."""
        if self.protocol_start_time:
            elapsed = int(time.time() - self.protocol_start_time)
            present(self.logger, "treatment progress",
                    lambda: self.shell.treatment.set_progress(elapsed, self.protocol_duration))
        self.protocol.update_protocol_time()

    def _confirm_mid_protocol_change(self) -> bool:
        """
        Show the “be careful” dialog once per protocol run.
        Returns True if the action may proceed.
        """
        if self.protocol_running and not self.mid_protocol_warning_shown:
            res = QtWidgets.QMessageBox.warning(
                self,
                "Caution",
                ("Changing pressure, angle or pulse while the treatment is active "
                 "may pose a safety risk.\n\nDo you want to continue?"),
                QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel
            )
            if res != QtWidgets.QMessageBox.Ok:
                self.disable_actuator_controls()
                return False           # user backed out
            self.mid_protocol_warning_shown = True  # don’t ask again
            self.enable_actuator_controls()
        return True

    def status_emit(self, position_a, position_b, steps, pressure):
        """Device status -> safety supervision (see controllers.safety_monitor),
        plus the Treatment screen's live pressure/angle readouts."""
        try:
            self._status_received_at = time.monotonic()
            # Latest MEASURED load; the stop sequence waits on this before
            # running the recovery reset (see ProtocolController).
            self.last_measured_pressure = float(pressure)
        except (TypeError, ValueError):
            pass
        def update_live_view() -> None:
            self.shell.treatment.set_pressure(pressure)
            connected = bool(self.arduino and self.arduino.connected)
            calibrated = connected and self.config.marks_valid
            lateral_angle = (calibrated_reading(steps, self.config.CMarks)
                             if calibrated else None)
            self.shell.treatment.set_angle(lateral_angle)
            # Measured feedback must never overwrite an unsubmitted Setup target.
            caption = self._measurement.caption(connected)
            self.shell.setup.set_measured_position(
                "pressure", pressure if caption == "Pressure live" else None, caption,
            )
            for key, raw, marks in (
                ("axial", position_a, self.config.AMarks),
                ("horizontal", position_b, self.config.BMarks),
                ("lateral", steps, self.config.CMarks),
            ):
                reading = calibrated_reading(raw, marks) if calibrated else None
                # Older devices use the existing distance factor for axial travel.
                if (key == "axial" and calibrated
                        and not self.config.axial_service_calibrated):
                    factor = float(self.config.a_factor)
                    reading = float(raw) * 6 / factor if factor > 0 else None
                self.shell.setup.set_measured_position(
                    key, round(reading, 1) if reading is not None else None,
                    "From calibration" if reading is not None else "Check calibration",
                )

        # Runs for every status frame: present() logs one traceback per failure
        # episode, and the safety checks below always run.
        present(self.logger, "live status", update_live_view)
        return self.safety.on_status(position_a, position_b, steps, pressure)

    def on_sensor_diagnostics(self, diagnostics: dict) -> None:
        self._measurement.receive(diagnostics)
        self._refresh_pressure_state()

    def on_calibration_result(self, result: dict) -> None:
        if result.get("operation") == "tare":
            self.on_baseline_changed(False)

    def on_baseline_changed(self, valid: bool) -> None:
        if valid and (self._closing or self._no_automatic_recovery or self._physical_stop_active):
            return
        self._measurement.baseline_valid = valid
        self._refresh_pressure_state()

    def _refresh_pressure_state(self) -> None:
        self._measurement.fault = self._measurement_fault
        self._measurement.protocol_running = bool(getattr(self, "protocol_running", False))
        connected = self.arduino is not None and self.arduino.connected
        caption = self._measurement.caption(connected)
        received = getattr(self, "_status_received_at", None)
        if caption == "Pressure live":
            if received is None:
                caption = "Waiting for pressure"
            elif time.monotonic() - received > diagnostics_max_age_s(self._measurement.protocol_running):
                caption = "Pressure stale"
        self.shell.treatment.set_pressure_state(caption)
        if caption != "Pressure live":
            self.shell.setup.set_measured_position("pressure", None, caption)

    def _refresh_measurement_display(self) -> None:
        """Age displayed readings independently of new serial events or motion logic."""
        if getattr(self, "_closing", False):
            return
        self._refresh_pressure_state()
        self._refresh_device_presentation()
        received = getattr(self, "_status_received_at", None)
        if (not (self.arduino and self.arduino.connected) or received is None
                or time.monotonic() - received
                > diagnostics_max_age_s(getattr(self, "protocol_running", False))):
            self.shell.setup.invalidate_measurements("Waiting" if received is None else "Stale")
            self.shell.treatment.set_angle(None)

    def on_pressure_progress_notice(self, notice: dict) -> None:
        """Advisory only: dismissing has no effect; Stop cannot schedule homing."""
        if self._closing:
            return
        existing = getattr(self, "_pressure_notice", None)
        if existing is not None and existing.isVisible():
            return
        box = PressureNotice(notice, self)
        box.stop_requested.connect(
            lambda: self.protocol.stop_without_recovery("Pressure-progress Stop")
        )
        box.show()
        self._pressure_notice = box
        box.destroyed.connect(lambda: setattr(self, "_pressure_notice", None))

    def _show_rehome_prompt(self, load_cleared: bool = True) -> None:
        """Ask before homing after an on-screen STOP; nothing moves on a timer."""
        if self._closing:
            return
        existing = getattr(self, "_rehome_prompt", None)
        if existing is not None and existing.isVisible():
            return
        box = RehomePrompt(load_cleared, self)
        box.rehome_requested.connect(self._on_rehome_requested)
        box.show()
        self._rehome_prompt = box
        box.destroyed.connect(lambda: setattr(self, "_rehome_prompt", None))

    def _on_rehome_requested(self) -> None:
        """Run the reset that used to start on its own after a STOP.

        It replaces automatic recovery, so it needs no Setup sign-in. A fault
        or physical stop since the prompt opened hands recovery to Setup.
        """
        if (getattr(self, "_no_automatic_recovery", False) is True
                or getattr(self, "_physical_stop_active", False) is True):
            self._show_timed_error(
                "A safety stop is active. Check the device, then use Reset in Setup."
            )
            return
        self.reset_arduino()

    def _close_rehome_prompt(self) -> None:
        box = getattr(self, "_rehome_prompt", None)
        if box is not None:
            box.close()

    def _show_timed_error(self, message):
        """Show error message that automatically closes after a timeout."""
        self.logger.warning("Status emit error: %s", message)

        # Create the error dialog
        msg_box = QMessageBox(self)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        # Release the box when it closes: a hidden QMessageBox (plus its
        # timer) per error used to accumulate for the kiosk's uptime.
        msg_box.setAttribute(Qt.WA_DeleteOnClose, True)

        # Auto-close after 5 s. Parenting the timer to the box means it dies
        # with the box if the operator dismisses it first.
        timer = QTimer(msg_box)
        timer.setSingleShot(True)
        timer.timeout.connect(msg_box.close)
        timer.start(5000)

        # Show the dialog without blocking
        msg_box.show()

    @QtCore.pyqtSlot(str)
    def handle_firmware_error(self, message):
        self.safety.on_firmware_error(message)

    @QtCore.pyqtSlot(str)
    def handle_firmware_warning(self, message):
        self.safety.on_firmware_warning(message)

    @QtCore.pyqtSlot()
    def handle_pressure_released(self):
        # Release completion is not a new numeric measurement or target edit.
        self.enable_actuator_controls()
        self.loading_spinner.hide()
        self.safety.on_pressure_released()

    @QtCore.pyqtSlot(int, int)
    def handle_zeros_echo(self, a_zero, b_zero):
        self.safety.on_zeros_echo(a_zero, b_zero)

    @QtCore.pyqtSlot()
    def handle_connection_lost(self):
        self._set_badge(False)
        self.safety.on_connection_lost()

    def setup_timers(self):
        """Setup timers for protocol events."""
        self.logger.info("Setting up timers for protocol events")
        self.protocol_timer = QTimer(self)
        # QTimer defaults to 0 ms. The controller's start() relied on a
        # dialog-gated start(1000) that never ran on the modern UI, so the
        # countdown fired on every event-loop pass for the whole treatment,
        # pegging the GUI thread on the Pi.
        self.protocol_timer.setInterval(1000)
        self.protocol_timer.timeout.connect(self.update_protocol_time)

    def setup_arduino(self, auto_reset=True):
        """Arduino lifecycle (see controllers.connection_manager)."""
        connected = self.connection.setup_arduino(auto_reset=auto_reset)
        self._set_badge(bool(connected))
        return connected

    def reset_arduino(self, event=None):
        # Reset from Setup also answers a pending re-home prompt.
        self._close_rehome_prompt()
        self.connection.reset_arduino(event)

    def setup_gpio(self):
        """Setup GPIO pins with proper error handling."""
        self.logger.info("Initializing GPIO setup process")
        try:
            # Initialize GPIO helper
            self.logger.debug("Setting GPIO mode to BCM")
            GPIO.setmode(GPIO.BCM)

            self.logger.debug("Disabling GPIO warnings")
            GPIO.setwarnings(False)

            self.logger.debug(
                "Setting up GPIO pins for EMERGENCYSTOP, EXTRAFORWARD, EXTRABACKWARD, and EXTRAENABLE"
            )
            GPIO.setup(EMERGENCYSTOP, GPIO.OUT)
            GPIO.setup(EXTRAFORWARD, GPIO.OUT)
            GPIO.setup(EXTRABACKWARD, GPIO.OUT)
            GPIO.setup(EXTRAENABLE, GPIO.OUT)

            self.logger.debug("Configuring default GPIO states")
            GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
            GPIO.output(EXTRAENABLE, GPIO.HIGH)

            self.logger.info("GPIO setup completed successfully")
        except Exception as e:
            self.logger.error("GPIO setup failed with error: %s", e)
            raise


def _print_recent_logs(lines: int = 200) -> None:
    """Print recent application logs for debug runs."""
    log_setup = LoggerSetup()
    for path in (log_setup.main_log_file, log_setup.serial_log_file):
        if not os.path.exists(path):
            continue
        print(f"\n--- {path} ---")
        try:
            content = read_recent_log_lines(path, lines)
            print("".join(content))
        except (OSError, ValueError) as e:  # unreadable or undecodable log file
            print(f"Could not print {path}: {e}")


def _sync_logs(destination):
    """Copy application logs to a destination directory."""
    if not destination:
        return
    log_dir = LoggerSetup().log_dir
    os.makedirs(destination, exist_ok=True)
    if not os.path.isdir(log_dir):
        print(f"Log directory does not exist: {log_dir}")
        return
    for name in os.listdir(log_dir):
        source = os.path.join(log_dir, name)
        target = os.path.join(destination, name)
        if os.path.isfile(source) and os.path.abspath(source) != os.path.abspath(target):
            shutil.copy2(source, target)
    print(f"Logs synced to {destination}")


def _install_excepthook():
    """Log unhandled Python exceptions instead of letting PyQt5 abort.

    PyQt5 >= 5.5 calls ``qFatal()`` when an exception escapes a slot, so one
    stray ``KeyError`` in a button handler would kill the kiosk UI (and the
    operator's on-screen STOP) mid-treatment. Record the full traceback to the
    log files + stderr and keep the event loop alive instead. Only logging
    happens here: the hook can fire on a worker thread, where touching widgets
    is unsafe.
    """
    unhandled_log = setup_logger(component="Unhandled")

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        print(f"UNHANDLED EXCEPTION (app kept running):\n{text}", file=sys.stderr)
        try:
            unhandled_log.error("Unhandled exception:\n%s", text)
        except Exception:  # noqa: BLE001, S110
            pass  # Logging itself failed; stderr above already has the traceback.

    sys.excepthook = _hook


# Main function without direct access to Arduino
def main():
    """Main function to start the application."""
    import argparse

    _install_excepthook()

    parser = argparse.ArgumentParser(description="KneeSpa Application")
    parser.add_argument(
        "--debug", action="store_true", help="Run in debug mode (windowed)"
    )
    parser.add_argument("--config", help="Path to a custom kneespa.cfg file")
    parser.add_argument(
        "--sync-logs",
        metavar="DIR",
        help="Copy application logs to DIR after the app exits",
    )
    parser.add_argument(
        "--print-logs",
        action="store_true",
        help="Print recent application logs after the app exits",
    )
    args = parser.parse_args()
    log_setup = LoggerSetup()
    log_setup.start_console_capture()
    try:
        log_setup.logger.info("Application started at %s", datetime.now())
        log_setup.logger.info("Debug mode: %s", "enabled" if args.debug else "disabled")

        app = QApplication(sys.argv)
        app.setStyle("Fusion")

        # A theme/stylesheet problem must never stop the device launching.
        try:
            from ui.theme import apply_theme
            theme_info = apply_theme(app)
            log_setup.logger.info("Theme applied: %s", theme_info)
        except Exception:
            log_setup.logger.exception("Theme not applied, continuing with default style")

        window = KneeSpa(debug_mode=args.debug, config_path=args.config)
        window._release_install_enabled = True
        window.show()

        # Under systemd with WatchdogSec set, a frozen GUI thread stops these
        # pings and the service is restarted. A no-op everywhere else.
        watchdog = start_watchdog(app)
        app.exec_()
        extend_watchdog_for_shutdown(watchdog)
        log_setup.logger.info("Application exited")
    except Exception:
        log_setup.logger.exception("Application failed")
        raise
    finally:
        log_setup.stop_console_capture()

    if args.print_logs:
        _print_recent_logs()
    if args.sync_logs:
        _sync_logs(args.sync_logs)

    from ui.modals.release_install import finish_release_install
    finish_release_install(window)
    logging.shutdown()
    if getattr(window, "_system_power_action", None):
        try:
            DeviceSystem.power(window._system_power_action)
        except (RuntimeError, ValueError) as exc:
            QMessageBox.critical(None, "Power action failed", str(exc) + "\nPlease reopen KneeSpa.")
    elif window.restart_requested:
        try:
            restart_app(__file__)
        except OSError as exc:
            QMessageBox.critical(None, "Restart failed",
                                 f"Could not restart the app. Please reopen it.\n{exc}")


def run_as_script():
    """Device entry point: a failed run must exit non-zero.

    kneespa.service restarts the app with Restart=on-failure, which ignores a
    clean exit. Swallowing the exception here used to leave a blank kiosk
    after a startup crash instead of letting systemd bring the app back.
    """
    try:
        main()
    except Exception as e:  # noqa: BLE001 - top level: print the traceback and exit 1
        print(f"Exception occurred: {str(e)}")
        print("Full traceback:")
        traceback.print_exc()
        sys.exit(1)
    finally:
        GPIO.cleanup()


if __name__ == "__main__":
    run_as_script()
