# KneeSpa main window — modern AppShell view layer on the FAILSAFE controller base.
#
# Union of the two development lines (Phase B replay):
#   * Backend/controllers (improvement-plan): the Arduino QThread, controllers/
#     (auth, connection, protocol, safety), frozen calibration math
#     (set_to_distance / set_to_c_distance / move_actuator / read_position),
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
    QThread,
    QObject,
    QTime,
    pyqtSignal,
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
)

# Resolve main.* imports from this release even while the legacy main/ tree
# remains beside runtime/ for rollback.
_SOFTWARE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SOFTWARE_ROOT not in sys.path:
    sys.path.insert(0, _SOFTWARE_ROOT)

if __name__ == "__main__":
    from config.migrate_state import migrate_default_state

    migrate_default_state()

from config.constants import (
    WINDOW_TITLE,
    DEGREES,
    ACTUATORS,
    SUCCESS_MESSAGES,
    EMERGENCYSTOP,
    EXTRAFORWARD,
    EXTRABACKWARD,
    EXTRAENABLE,
    EMAIL_CONFIG,
    PRESSURE_MAX,
    AXIAL_MAX_INCHES,
    AXIAL_MIN_INCHES,
    LATERAL_MIN_DEGREES,
    LATERAL_MAX_DEGREES,
    HORIZONTAL_MIN_DEGREES,
    HORIZONTAL_MAX_DEGREES,
    LEG_LENGTH_SPEED_NORMAL,
    LEG_LENGTH_SPEED_FAST,
    LEG_LENGTH_MIN,
    LEG_LENGTH_MAX,
    DEFAULT_PRESSURE,
    DEFAULT_LEG_LENGTH_POSITION,
    DEFAULT_HORIZONTAL_POSITION,
    MIN_PRESSURE,
    DEFAULT_PROTOCOL_MINUTES,
    PROTOCOL_MINUTES_MIN,
    PROTOCOL_MINUTES_MAX,
    DATA_PATHS,
)

from ui.modals.pressure_notice import PressureNotice
from ui.modals.upload_error import UploadErrorDialog
from config.config import Configuration
from helpers.arduino import Arduino
from helpers.csv import CSVHelper
from helpers.secure_auth import SecureAuthHelper
from helpers import protocols
from helpers.reset_worker import ResetWorker, ResetWorkerSignals
from helpers.measurement_state import DIAGNOSTICS_MAX_AGE_S, MeasurementState
from helpers.app_restart import restart_app
from helpers.device_system import DeviceSystem
from helpers.conversions import (
    lateral_degrees_to_position,
    horizontal_degrees_to_position,
)
from helpers.cloud_client import CloudClient
from helpers.cloud_contract import cloud_error_message, validate_patient
from controllers.hardware_service_controller import HardwareServiceController
from controllers.device_controller import DeviceController
from controllers.patient_controller import PatientController
from controllers.machine_sign_in_controller import MachineSignInController, authorize
from helpers.support_ticket import create_ticket, validate_ticket
from main.config.constants import APP_VERSION
from controllers.leg_length_controller import LegLengthController
from helpers.hardware_service import axial_position

from helpers.logging import LoggerSetup, read_recent_log_lines, setup_logger

# Modern view layer — the composition root for chrome + screens + modals.
from ui.app_shell import AppShell
from ui.measurements import calibrated_reading
from ui.presentation import device_presentation
from ui.widgets.loading_spinner import LoadingSpinner
from ui.widgets.treatment_status_panel import TreatmentStatusPanel

from controllers.safety_monitor import SafetyMonitor
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
class KneeSpa(QMainWindow):
    """Main application class for KneeSpa."""

    support_email_result = pyqtSignal(bool, str)

    def set_to_distance(self, inches, actuator, factor):
        command = "A{}{:.1f}".format(actuator, inches)
        config = getattr(self, "config", None)
        if str(actuator) == "12" and getattr(config, "axial_service_calibrated", False) is True:
            try:
                command = f"I12{axial_position(config.AMarks, inches)}"
            except (ValueError, TypeError, KeyError) as exc:
                self._show_timed_error(f"Axial calibration is invalid: {exc}")
                return False
        self.I2Cstatus_event.clear()
        if not KneeSpa._send_motion_command(self, command, "axial movement"):
            return False
        print("Sent cmd {}".format(command.strip()))
        print("End set to distance")
        return True

    def set_to_c_distance(self, degrees):
        """
        Set the C actuator position based on degrees with proper type handling.

        Args:
            degrees (float): Target angle in degrees
        """
        self.loading_spinner.show()
        self.disable_actuator_controls()
        try:
            position, degrees = lateral_degrees_to_position(
                self.config.CMarks, degrees
            )

            print(f" positioned to {degrees} degrees pos {position}")
            command = f"K{position}"
            self.I2Cstatus_event.clear()
            if not KneeSpa._send_motion_command(self, command, "lateral movement"):
                return False
            print(f"cmd {command}")

            print("End set to c.")
            self.loading_spinner.hide()
            return True

        except Exception as e:
            self.loading_spinner.hide()
            print(f"Error in set_to_c_distance: {str(e)}")
            print(f"Degrees: {degrees}, Type: {type(degrees)}")
            print(f"CMarks: {self.config.CMarks}")
            return False

    ### App Initialization ####
    def __init__(self, debug_mode=False, config_path=None):
        super().__init__()

        self.logger = setup_logger(component="KneeSpa")
        print(
            f"Initializing KneeSpa class in {'debug' if debug_mode else 'production'} mode"
        )

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
        self._selected_issue = None        # last-opened Support troubleshooting item
        self.current_use_pulse_setting = True
        self.current_pulse_rate = None     # pulses/sec from the Settings slider
        self.axial_flexion_pressure = 0
        self.actuator_a = ACTUATORS["AXIAL"]["ID"]
        self.actuator_b = ACTUATORS["HORIZONTAL"]["ID"]
        self.actuator_c = ACTUATORS["LATERAL"]["ID"]

        # Actuator position tracking (legacy setup_actuator_controls defaults).
        self.axial_flexion_position = 0
        self.horizontal_flexion_position = DEFAULT_HORIZONTAL_POSITION
        self.lateral_flexion_position = 0
        self.leg_length = DEFAULT_LEG_LENGTH_POSITION
        self.current_pressure = DEFAULT_PRESSURE
        self.LEG_LENGTH_MIN = LEG_LENGTH_MIN
        self.LEG_LENGTH_MAX = LEG_LENGTH_MAX
        self.LEG_LENGTH_SPEED_NORMAL = LEG_LENGTH_SPEED_NORMAL
        self.LEG_LENGTH_SPEED_FAST = LEG_LENGTH_SPEED_FAST

        # Backend initialization
        # QObject already exposes a thread() method. Keep the owned Arduino
        # QThread under a distinct name so first-time connection setup cannot
        # mistake that inherited method for a live worker thread.
        self.arduino = None
        self.arduino_thread = None
        self.I2Cstatus = 0  # Keep for compatibility
        self.I2Cstatus_event = threading.Event()  # Thread-safe event for synchronization
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
        self.reset_done_event = threading.Event()
        self.initial_setup_complete = False
        self.reset_in_progress = False  # Flag to prevent overlapping resets
        self.actuator_command_in_progress = False  # Prevents simultaneous actuator commands
        self.controls_enable_timer = None  # Single pending-enable timer for all controls
        self.mid_protocol_warning_shown = False
        self.protocol_stop_requested = False
        self._physical_stop_active = False
        self.worker = None

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
            print("Production mode: Set to full screen without frame")
        else:
            print("Debug mode: Running in windowed mode")

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
        self.safety = SafetyMonitor(self)
        self.auth = AuthController(self)
        self.protocol = ProtocolController(self)
        self.connection = ConnectionManager(self)
        self.leg = LegLengthController(self)
        self.calibration_controller = HardwareServiceController(self)
        self.device_controller = DeviceController(self)
        self._calibration_active = False
        # Protocol lifecycle state: idle / starting / running / stopping / fault
        self.protocol_state = "idle"

        self.login_pin = ""

        # Initialize the CSV helper
        self.csv = CSVHelper()
        try:
            self.csv.initialize_data()
            self.users = self.csv.users
            print(SUCCESS_MESSAGES["DATA_LOADED"])
        except Exception as e:
            self.users = {}
            print(f"Error loading CSV data: {str(e)}")
            self._show_timed_error(f"Failed to load CSV data: {str(e)}")

        self.current_user = None
        self.cloud_patient = None
        self._treatment_patient = None
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
        self._patient_editor = self.patients.editor
        self._cloud_retry_timer = QTimer(self)
        self._cloud_retry_timer.timeout.connect(self._retry_pending_uploads)

        # Controls locked while the MCU is busy (jog/Go/Stop/Reset-Arduino) —
        # the same gating group the legacy `actuator_controls` list provided.
        self.actuator_controls = self.shell.setup.control_buttons()

        # Treatment Settings sliders start from the persisted defaults (§15.4).
        self.shell.treatment.set_settings(self.config.protocol_defaults())

        self.threadpool = QtCore.QThreadPool()
        print(f"Multithreading with maximum {self.threadpool.maxThreadCount()} threads")

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
        except Exception as e:
            configured_device_id = ""
            self.logger.error("Could not ensure device id: %s", e)
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
        s.device.calibration_requested.connect(self.calibration_controller.open)
        s.device.hardware_tests_requested.connect(self.calibration_controller.open_tests)

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
        s.support.issue_activated.connect(self._on_issue_activated)
        self.support_email_result.connect(self._on_support_email_result)

        # Video modal (owns the embedded VLC player).
        s.video_modal.play_toggled.connect(self._on_video_toggled)

    def _set_badge(self, connected):
        """Reflect Arduino connectivity on the Setup header badge."""
        try:
            self.shell.setup.set_arduino_connected(connected)
            self._refresh_device_presentation()
        except Exception:
            pass

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
        try:
            self.shell.setup.set_position(key, value)
        except Exception:
            pass

    def _send_motion_command(self, command, context):
        """Queue a Setup motion without fabricating success in the UI."""
        if getattr(self, "_closing", False) is True:
            return False
        if (getattr(self, "_calibration_active", False) is True
                or getattr(self, "_device_maintenance_active", False) is True):
            self._show_timed_error("Finish device service before normal movement.")
            return False
        try:
            queued = bool(self.arduino and self.arduino.send(command))
        except Exception as exc:
            queued = False
            self.logger.error("Could not queue %s command %s: %s", context, command, exc)
        if queued:
            return True

        self.logger.error("Could not queue %s command %s", context, command)
        self._set_badge(False)
        self._show_timed_error(
            f"{context.capitalize()} was not sent. Check the Arduino connection."
        )
        self.enable_actuator_controls()
        self.loading_spinner.hide()
        return False

    ### UI Methods ###

    def disable_actuator_controls(self):
        # Cancel any pending enable so it cannot fire mid-command and
        # re-enable controls while the MCU is still busy
        if self.controls_enable_timer is not None:
            self.controls_enable_timer.stop()
            self.controls_enable_timer = None
        self.actuator_command_in_progress = True
        for w in self.actuator_controls:
            w.setEnabled(False)

    def enable_actuator_controls(self):
        if getattr(getattr(self, "leg", None), "active", False) is True:
            return
        if (getattr(self, "_calibration_active", False) is True
                or getattr(self, "_device_maintenance_active", False) is True):
            return
        if (
            self.reset_in_progress
            or not self.initial_setup_complete
            or self.protocol_state == "fault"
        ):
            return
        self.actuator_command_in_progress = False
        if self.protocol_running == False:
            print("Scheduling controls to enable with delay...") # Add for debugging
            # Single timer instance shared by all controls: a new enable
            # request supersedes any pending one instead of stacking
            # per-widget timers that can interleave with a later disable
            if self.controls_enable_timer is not None:
                self.controls_enable_timer.stop()
            self.controls_enable_timer = QTimer()
            self.controls_enable_timer.setSingleShot(True)
            self.controls_enable_timer.timeout.connect(
                self._apply_enable_actuator_controls
            )
            self.controls_enable_timer.start(200)

    def _apply_enable_actuator_controls(self):
        self.controls_enable_timer = None
        if getattr(getattr(self, "leg", None), "active", False) is True:
            return
        if (getattr(self, "_calibration_active", False) is True
                or getattr(self, "_device_maintenance_active", False) is True):
            return
        # The state may have changed during the 200 ms debounce window.
        if (
            self.reset_in_progress
            or not self.initial_setup_complete
            or self.protocol_running
            or self.protocol_state == "fault"
        ):
            return
        for w in self.actuator_controls:
            w.setEnabled(True)

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

        threading.Thread(target=_lookup, daemon=True).start()

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
        self.shell.treatment.set_settings(values)
        self.shell.treatment.select_protocol(protocol)
        self.cloud_patient = patient
        self.shell.treatment.set_patient(
            patient.get("display_name") or patient.get("external_ref") or patient["patient_id"]
        )
        self.shell.patient_modal.hide()  # Success must not emit the cancellation signal.

    def _on_patient_edit(self) -> None:
        """Detach the previous identity as soon as replacement entry starts."""
        if self.protocol_running:
            return
        self._patient_lookup_id += 1
        self.cloud_patient = None
        self._patient_lookup_pending = False
        self.shell.treatment.set_patient_pending(False)
        self.shell.treatment.clear_patient()

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
        print(f"Mid-protocol: worker {key} updated to {value}")

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
            return
        self._prev_settings = dict(vals)
        try:
            self.protocol_value = str(self.shell.treatment.selected_protocol())
        except Exception:
            pass
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

    def emergency_stop_clicked(self, event):
        self.protocol.emergency_stop_clicked(event)

    def _update_status_label(self, text):
        self.protocol.update_status_label(text)

    def _warn_uncalibrated(self):
        reasons = "\n".join(
            self.config.calibration_errors[:4]
        ) or "calibration data invalid"
        self._show_safety_alert(
            "DEVICE UNCALIBRATED - treatments are disabled.\n\n"
            f"{reasons}\n\n"
            "Recalibrate and restart before treating patients."
        )

    def _confirm_protocol_start(self):
        return self.protocol.confirm_start()

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
            self._setup_reset(key)
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
            self.move_actuator(actuator, None, speed, direction)

    def _leg_jog(self, action):
        handler = {
            "rev_fast": self.reverse_fast_button_clicked,
            "rev": self.reverse_button_clicked,
            "fwd": self.forward_button_clicked,
            "fwd_fast": self.forward_fast_button_clicked,
        }.get(action)
        if handler:
            handler()

    def _setup_reset(self, key):
        if key == "axial":
            self.reset_flexion_button_clicked(self.actuator_a)
        elif key == "lateral":
            self.reset_flexion_button_clicked(self.actuator_c)
        elif key == "horizontal":
            self.reset_flexion_button_clicked(self.actuator_b)
        elif key == "leg_length":
            self.reset_extra_button_clicked()
        elif key == "pressure":
            self.loading_spinner.show()
            self.disable_actuator_controls()
            # DONE re-enables the controls via set_done. The treatment banner
            # is reserved for protocol stops: set_stopping() here had no
            # matching set_idle(), so "STOPPING - RELEASING TRACTION" stayed
            # over the top bar until the next treatment or Arduino reset.
            KneeSpa._send_motion_command(self, "P0", "pressure release")
            self.loading_spinner.hide()

    def _on_setup_go(self, key):
        """Move an actuator to its row's current slider value (the legacy Go
        path), preserving the per-actuator unit conversions and clamps."""
        if not authorize(self, "setup", lambda: self._on_setup_go(key)):
            return False
        if key in ("axial", "horizontal", "lateral") and not self.config.marks_valid:
            self._warn_uncalibrated()
            return False
        if key == "pressure" and not self.config.scale_calibrated:
            self._warn_uncalibrated()
            return False
        if key == "leg_length":
            return self.leg.move_to(self.shell.setup.row_value("leg_length"))

        self.loading_spinner.show()
        self.disable_actuator_controls()
        try:
            if key == "axial":
                inches = self.shell.setup.row_value("axial")
                inches = max(AXIAL_MIN_INCHES, min(AXIAL_MAX_INCHES, inches))
                if not self.set_to_distance(inches, self.actuator_a, self.config.a_factor):
                    return False
                self.axial_flexion_position = inches
                self._reflect_setup("axial", inches)
            elif key == "horizontal":
                degrees = self.shell.setup.row_value("horizontal")
                degrees = max(HORIZONTAL_MIN_DEGREES, min(HORIZONTAL_MAX_DEGREES, degrees))
                position = horizontal_degrees_to_position(self.config.BMarks, degrees)
                if not KneeSpa._send_motion_command(
                    self, f"I13{position}", "horizontal movement"
                ):
                    return False
                self.horizontal_flexion_position = degrees
                self._reflect_setup("horizontal", degrees)
            elif key == "lateral":
                degrees = self.shell.setup.row_value("lateral")
                degrees = max(LATERAL_MIN_DEGREES, min(LATERAL_MAX_DEGREES, degrees))
                if not self.set_to_c_distance(degrees):
                    return False
                self.lateral_flexion_position = degrees
                self._reflect_setup("lateral", degrees)
            elif key == "pressure":
                return self._apply_setup_pressure()
            return True
        except Exception as e:
            print(f"Error in Setup Go: {str(e)}")
            self._show_timed_error(f"Error moving actuator: {str(e)}")
        finally:
            self.loading_spinner.hide()

    def _apply_setup_pressure(self):
        """Setup pressure Go: clamp to [MIN_PRESSURE, PRESSURE_MAX] and send P."""
        if not self.config.scale_calibrated:
            self._warn_uncalibrated()
            return False
        pressure = self.shell.setup.row_value("pressure")
        if pressure > PRESSURE_MAX:
            pressure = PRESSURE_MAX
            self.logger.warning(f"Pressure request exceeds max {PRESSURE_MAX}, clamping")
            self._show_timed_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
        elif pressure < MIN_PRESSURE:
            pressure = MIN_PRESSURE
            self.logger.warning(f"Pressure request below minimum, setting to {MIN_PRESSURE}")
        pressure = int(pressure)
        if not KneeSpa._send_motion_command(
            self, "P{}".format(pressure), "pressure movement"
        ):
            return False
        print("Pressure cmd sent P{}".format(pressure))
        # This is a target, not measured pressure. The live readout is updated
        # only by status_emit feedback.
        self.current_pressure = pressure
        self._reflect_setup("pressure", pressure)
        return True

    def _on_setup_stop(self, key):
        """Per-row Stop. The firmware's 'X' stops all actuators regardless of
        suffix; route through the base stop paths so a link-down failure is
        alarmed, not just logged."""
        if key == "leg_length":
            self.stop_leg_movement()
            return
        actuator = {
            "axial": self.actuator_a,
            "horizontal": self.actuator_b,
            "lateral": self.actuator_c,
            "pressure": self.actuator_a,  # pressure rides the axial channel
        }.get(key)
        if actuator is not None:
            self.stop_position_flexion_button(actuator)

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
        except Exception as e:
            print(f"Failed to save defaults: {e}")
            self.logger.error("Failed to save defaults: %s", e)
            self._show_timed_error("Could not save defaults.")

    # ----- auth -----
    def _on_login_attempt(self, pin):
        """Modern login modal submits the whole PIN; the salted-hash verify and
        lockout live in controllers.auth_controller."""
        if self.protocol_running:
            return
        self.machine_sign_in.clear()
        self.login_pin = pin
        self.auth.handle_login()
        if self.current_user is None:
            # Specifics (lockout countdown, etc.) arrive via the timed error
            # box; the modal shows the inline generic failure.
            try:
                self.shell.login_failed("Invalid PIN. Please try again.")
            except Exception:
                pass

    def _on_logout(self):
        if self._block_active_treatment_exit():
            return
        print("Handling logout")
        self.machine_sign_in.clear()
        self.patients.clear_session()
        self._patient_lookup_id += 1
        self.current_user = None
        self.cloud_patient = None
        self._patient_lookup_pending = False
        try:
            self.shell.treatment.clear_patient()
        except Exception:
            pass
        self.shell.logout()

    def _on_exit_app(self):
        """Exit App from the Profile screen — full cleanup via closeEvent."""
        if self._block_active_treatment_exit():
            return
        print("Handling app exit")
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
        print("Updating UI after login")
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
    def _on_issue_activated(self, question):
        # Remember the last-opened troubleshooting item as ticket context.
        self._selected_issue = question

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
        print(f"Video play toggled: {playing}")

    def handle_assistance_request(self):
        """Request assistance — emails the admin using the logged-in user's
        identity (read from current_user, not stale label text)."""
        print(f"Handle assistance method called")
        if self.current_user:
            self.username = self.current_user.get("username", "")
            self.user_email = self.current_user.get("email", "")
            self.user_status = self.current_user.get("status", "")
        else:
            self.username = self.user_email = self.user_status = ""
        self.email_admin()

    def email_admin(self) -> None:
        """Send the assistance-request email from a worker thread.

        Blocking SMTP-over-SSL used to run on the UI thread, freezing the
        kiosk up to the TCP timeout whenever the network was down -- and
        the operator never learned whether help was actually summoned.
        """
        receiver_email = EMAIL_CONFIG["RECEIVER_EMAIL"]

        subject = "Assistance Request"
        body = (
            f"User {self.username} with email {self.user_email} and status "
            f"{self.user_status} is requesting assistance."
        )
        print(body)

        self._send_support_email(
            subject=subject,
            body=body,
            receiver_email=receiver_email,
            success_message="Assistance request email sent successfully.",
            failure_prefix="Failed to send assistance email",
        )

    def submit_ticket(self, issue_text: str) -> None:
        """Submit a support ticket (§15.5) — SMTP to the TICKET_EMAIL, tagged
        with the persisted per-device id. Sent from a worker thread like
        email_admin (blocking SMTP froze the kiosk on a down network)."""
        receiver_email = EMAIL_CONFIG["TICKET_EMAIL"]

        try:
            device_id = self.config.ensure_device_id()
        except Exception:
            device_id = "unknown"

        user = self.current_user.get("username", "unknown") if self.current_user else "unknown"
        status = self.current_user.get("status", "") if self.current_user else ""

        subject = f"[KneeSpa {device_id}] Support ticket"
        body = (
            f"Device: {device_id}\n"
            f"User: {user} ({status})\n\n"
            f"Issue:\n{issue_text}"
        )
        self._send_support_email(
            subject=subject,
            body=body,
            receiver_email=receiver_email,
            success_message="Support ticket sent successfully.",
            failure_prefix="Failed to send ticket",
        )
        self._show_timed_error("Support ticket is being sent.")

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
                print(success_message)
                if signal is not None:
                    signal.emit(True, success_message)
            except Exception as e:
                print(f"{failure_prefix}: {e}")
                self.logger.error(f"{failure_prefix}: {e}")
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
        if any(getattr(self, name, False) is True for name in (
            "_device_maintenance_active", "_calibration_active", "reset_in_progress",
            "actuator_command_in_progress",
        )):
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
        print(f"SAFETY ALERT: {message}")
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
            self._no_automatic_recovery = True
            self._shutdown_began = time.monotonic()
            self.protocol.latch_session_outcome("fault")
            self.connection.cancel_reset()
            if self.worker:
                self.worker.cancel(firmware_stopped=self._physical_stop_active)
            if getattr(self, "_calibration_active", False) is True:
                self.calibration_controller.shutdown()
            for name in ("protocol_timer", "controls_enable_timer", "_cloud_retry_timer",
                         "_pressure_state_timer"):
                timer = getattr(self, name, None)
                if timer is not None:
                    timer.stop()
            arduino = self.arduino
            if arduino is not None:
                arduino._connect_cancel.set()
                if self._physical_stop_active:
                    arduino.cancel_pending_commands()
                else:
                    for command in ("X", "P0", "HF0"):
                        arduino.send(command)
            self._release_leg_gpio()
            self.protocol.finalize_session()
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

    def move_actuator(self, actuator, step, speed_factor, direction):
        """
        Move an actuator in the specified direction.

        The position math, clamps, and emitted serial commands are FROZEN (unit
        tested). Only the UI feedback is rerouted to the modern Setup screen.
        """
        if self.actuator_command_in_progress:
            print("Actuator command already in progress - ignoring input")
            return
        if not self.config.marks_valid:
            # Generated default marks are fabricated geometry; jogging on
            # them moves the mechanism to unintended positions
            self._warn_uncalibrated()
            return
        print(f"Speed factor: {speed_factor}")
        if actuator == self.actuator_b:  # Horizontal Flexion
            step = 10 if int(speed_factor) > 4 else 5
            new_position = self.horizontal_flexion_position + (step * direction)

            # Check position limits
            if direction >= 0 and new_position > HORIZONTAL_MAX_DEGREES:
                return
            if direction < 0 and new_position < HORIZONTAL_MIN_DEGREES:
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            position = horizontal_degrees_to_position(
                self.config.BMarks, new_position
            )
            command = f"I13{position}"
            if not KneeSpa._send_motion_command(
                self, command, "horizontal movement"
            ):
                return False

            self.horizontal_flexion_position = new_position
            print(f"B position: {self.horizontal_flexion_position}")

            self._reflect_setup("horizontal", self.horizontal_flexion_position)
            self.loading_spinner.hide()

        elif actuator == self.actuator_a:  # Axial Flexion
            step = 1 if int(speed_factor) > 4 else 0.5
            new_position = self.axial_flexion_position + (step * direction)

            if direction > 0 and new_position > AXIAL_MAX_INCHES:
                self._show_timed_error(
                    f"Axial position limited to {AXIAL_MAX_INCHES} inches (max)"
                )
                return
            if direction < 0 and new_position < AXIAL_MIN_INCHES:
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            # Send command to Arduino
            # Arduino expects: A[2-digit device][float value starting at position 3]
            # Format position with at least 1 decimal place to ensure proper parsing
            command = f"A12{new_position:.1f}"
            if getattr(self.config, "axial_service_calibrated", False) is True:
                try:
                    command = f"I12{axial_position(self.config.AMarks, new_position)}"
                except (ValueError, TypeError, KeyError) as exc:
                    self._show_timed_error(f"Axial calibration is invalid: {exc}")
                    self.loading_spinner.hide()
                    self.enable_actuator_controls()
                    return False
            print(f"Sending axial command: {command}")
            if not KneeSpa._send_motion_command(self, command, "axial movement"):
                return False
            self.axial_flexion_position = new_position
            print(f"A position: {self.axial_flexion_position}")
            print(f"Axial flexion position: {self.axial_flexion_position} in")

            # Removed problematic L5 command that was sent without proper parameters
            # This was causing malformed commands after forward axial movement

            self._reflect_setup("axial", self.axial_flexion_position)
            self.loading_spinner.hide()

        elif actuator == self.actuator_c:  # Lateral Flexion
            step = 5 if int(speed_factor) > 4 else 2.5  # Use 2.5 degree increments
            new_position = self.lateral_flexion_position + (step * direction)

            # Round to nearest 2.5 degree increment
            new_position = round(new_position / 2.5) * 2.5

            # Check position limits using constants
            if direction > 0 and new_position > LATERAL_MAX_DEGREES:
                self._show_timed_error(
                    f"Lateral position limited to {LATERAL_MAX_DEGREES}{DEGREES} (max)"
                )
                return
            if direction < 0 and new_position < LATERAL_MIN_DEGREES:
                self._show_timed_error(
                    f"Lateral position limited to {LATERAL_MIN_DEGREES}{DEGREES} (min)"
                )
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            # Interpolate between marks; an exact-key-only lookup used to
            # silently no-op the button press when a 2.5-degree mark was
            # missing from the table
            try:
                position, new_position = lateral_degrees_to_position(
                    self.config.CMarks, new_position
                )
            except ValueError as e:
                print(f"Invalid lateral position: {e}")
                self.enable_actuator_controls()
                self.loading_spinner.hide()
                return

            print(
                f" positioned to {new_position} degrees pos {position}"
            )

            # Send command to Arduino
            command = f"K{position}"
            if not KneeSpa._send_motion_command(self, command, "lateral movement"):
                return False

            self.lateral_flexion_position = new_position

            self._reflect_setup("lateral", self.lateral_flexion_position)
            self.loading_spinner.hide()

        return True

    def reset_flexion_button_clicked(self, actuator):
        self.loading_spinner.show()
        self.disable_actuator_controls()
        print(actuator)
        if actuator == self.actuator_c:
            # Tolerant lookup (same as the horizontal branch): a hand-edited
            # CMarks without an exact "0.0" key raised KeyError out of this
            # slot, which PyQt5 turns into a process abort.
            try:
                position, _ = lateral_degrees_to_position(self.config.CMarks, 0)
            except ValueError as e:
                print(f"Invalid lateral position: {e}")
                self.enable_actuator_controls()
                self.loading_spinner.hide()
                return
            print(f" positioned to 0 degrees pos {position}")
            command = f"I14{position}"
            if not KneeSpa._send_motion_command(self, command, "lateral reset"):
                return False
            self.lateral_flexion_position = 0
            self._reflect_setup("lateral", 0)
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_b:
            # Home the horizontal actuator to the calibrated
            # DEFAULT_HORIZONTAL_POSITION via its BMarks position, the same way
            # the lateral branch above homes from CMarks. The old 'A132' inches
            # path ignored BMarks and under-shot the true angle.
            try:
                position = horizontal_degrees_to_position(
                    self.config.BMarks, DEFAULT_HORIZONTAL_POSITION
                )
            except ValueError as e:
                print(f"Invalid horizontal position: {e}")
                self.enable_actuator_controls()
                self.loading_spinner.hide()
                return
            command = f"I13{position}"
            if not KneeSpa._send_motion_command(self, command, "horizontal reset"):
                return False
            self.horizontal_flexion_position = DEFAULT_HORIZONTAL_POSITION
            self._reflect_setup("horizontal", DEFAULT_HORIZONTAL_POSITION)
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_a:
            # 'R12' was never a firmware command (parsed as Unknown); the
            # UI then showed 0 in / 0 lb while nothing moved. Home the
            # axial actuator for real, the way the reset sequence does.
            command = "I120"
            if not KneeSpa._send_motion_command(self, command, "axial reset"):
                return False
            self.axial_flexion_position = 0
            self._reflect_setup("axial", 0)
            # Automatic reset/protocol workflows own pressure zeroing.
            self.loading_spinner.hide()

            return

    def stop_actuators(self):
        """Emergency stop for all actuators."""
        print("Emergency stop triggered")
        self.connection.cancel_reset()
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
            print(f"Error in emergency stop: {str(e)}")
            self._show_timed_error(f"Emergency stop failed: {str(e)}")

    def stop_position_flexion_button(self, actuator):
        # Firmware 'X' stops all actuators regardless of suffix. Guarded like
        # stop_actuators: a torn-down transport (arduino is None) must still
        # produce the STOP NOT DELIVERED alarm rather than an AttributeError.
        try:
            sent = bool(self.arduino and self.arduino.send("X"))
        except Exception as exc:
            self.logger.error("Actuator stop raised: %s", exc)
            sent = False
        if not sent:
            self.logger.error("Actuator stop could not be sent - link down")
            self._show_timed_error(
                "STOP NOT DELIVERED - connection down. "
                "Press the physical emergency stop immediately."
            )

    # ----- leg-length (FIT) jog handlers (open-loop F-commands + GPIO) -----
    def _move_leg(self, command, delta, duration_ms, forward):
        """Delegate timing and estimate updates to the FIT command owner."""
        if getattr(self, "_service_leg_position_unknown", False) is True:
            self._show_timed_error("Use the leg-length Return control to establish zero.")
            return False
        return self.leg.move(command)

    def forward_button_clicked(self):
        """Handle forward button press - normal speed."""
        return KneeSpa._move_leg(self, "F+", 0.25, 600, True)

    def reverse_button_clicked(self):
        """Handle reverse button press - normal speed."""
        return KneeSpa._move_leg(self, "F-", -0.25, 600, False)

    def forward_fast_button_clicked(self):
        """Handle forward button press - fast speed."""
        return KneeSpa._move_leg(self, "FF", 3.0, 6100, True)

    def reverse_fast_button_clicked(self):
        """Handle reverse button press - fast speed."""
        return KneeSpa._move_leg(self, "FR", -3.0, 6100, False)

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

    def stop_leg_movement(self):
        """Stop leg length actuator movement."""
        self.leg.cancel()
        self.loading_spinner.show()
        if not KneeSpa._send_motion_command(self, "F0", "leg-length stop"):
            # Local GPIO stop remains mandatory even when serial is down.
            self._release_leg_gpio()
            return False
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        # GPIO.output(EXTRAENABLE, GPIO.LOW)
        self.loading_spinner.hide()
        return True

    @QtCore.pyqtSlot()
    def set_done(self):
        self.connection.set_done()

    def ready_to_go(self):
        self.connection.ready_to_go()

    def read_position(self, position, steps, actuator):
        """Read position data from the Arduino with safety checks."""
        print(
            f"Reading position: position={position}, steps={steps}, actuator={actuator}"
        )

        # Safety check calibration factors to prevent division by zero
        if not hasattr(self.config, 'a_factor') or not hasattr(self.config, 'b_factor') or not hasattr(self.config, 'c_factor'):
            self.logger.error("Missing calibration factors in config")
            self._show_timed_error("Calibration error - please recalibrate system")
            return

        if self.config.a_factor == 0 or self.config.b_factor == 0 or self.config.c_factor == 0:
            self.logger.error(f"Invalid calibration factors: a={self.config.a_factor}, b={self.config.b_factor}, c={self.config.c_factor}")
            self._show_timed_error("Calibration error - factors cannot be zero. Please recalibrate.")
            return

        try:
            if hasattr(self, "actuator_b") and actuator == self.actuator_b:
                inches = (position * 6) / self.config.b_factor
                inches = round(inches * 2.0) / 2.0
                print(f"Inches (actuator B): {inches}")
                degrees = int(-(25 - (inches / 5) * 25)) if inches != 0 else -25
                print(f"Degrees (actuator B): {degrees}")
            elif hasattr(self, "actuator_a") and actuator == self.actuator_a:
                inches = (position * 6) / self.config.a_factor
                inches = round(inches * 2.0) / 2.0
                print(f"Inches (actuator A): {inches}")
            elif hasattr(self, "actuator_c") and actuator == self.actuator_c:
                inches = steps / (self.config.c_factor / 6)
                inches = round(inches * 2.0) / 2.0
                print(f"Inches (actuator C): {inches}")
                degrees = int((inches * 20) - 20)
                print(f"Degrees (actuator C): {degrees}")
        except (ZeroDivisionError, ValueError) as e:
            self.logger.error(f"Position calculation error: {e}")
            self._show_timed_error(f"Error calculating position: {str(e)}")

    def ensure_arduino_connection(self):
        return self.connection.ensure_arduino_connection()

    def start_protocol(self):
        return self.protocol.start_protocol()

    def update_protocol_time(self):
        """Protocol countdown (see controllers.protocol_controller), plus the
        Treatment screen's inline progress ring."""
        if self.protocol_start_time:
            elapsed = int(time.time() - self.protocol_start_time)
            try:
                self.shell.treatment.set_progress(elapsed, self.protocol_duration)
            except Exception:
                pass
        self.protocol.update_protocol_time()

    def protocol_completed(self, success=True):
        self.protocol.protocol_completed(success)

    def stop_protocol(self):
        self.protocol.stop_protocol()

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
        try:
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
        except Exception as e:
            print(f"Error updating live status: {e}")
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
        connected = self.arduino is not None and self.arduino.connected
        caption = self._measurement.caption(connected)
        received = getattr(self, "_status_received_at", None)
        if caption == "Pressure live":
            if received is None:
                caption = "Waiting for pressure"
            elif time.monotonic() - received > DIAGNOSTICS_MAX_AGE_S:
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
                or time.monotonic() - received > DIAGNOSTICS_MAX_AGE_S):
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

    def _trigger_safety_stop(self, reason):
        self.safety.trigger_safety_stop(reason)

    def _show_timed_error(self, message):
        """Show error message that automatically closes after a timeout."""
        print(f"Status emit error: {message}")

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

    def handle_buffer_warning(self, warning):
        print(f"Buffer warning: {warning}")

    @QtCore.pyqtSlot(str)
    def handle_firmware_error(self, message):
        self.safety.on_firmware_error(message)

    @QtCore.pyqtSlot(str)
    def handle_firmware_warning(self, message):
        self.safety.on_firmware_warning(message)

    @QtCore.pyqtSlot()
    def handle_pressure_released(self):
        self.current_pressure = 0
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
        print("Setting up timers for protocol events")
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
        self.connection.reset_arduino(event)

    def send_zero_mark(self):
        self.connection.send_zero_mark()

    def send_calibration(self):
        self.connection.send_calibration()

    def setup_gpio(self):
        """Setup GPIO pins with proper error handling."""
        print("Initializing GPIO setup process")
        try:
            # Initialize GPIO helper
            print("Setting GPIO mode to BCM")
            GPIO.setmode(GPIO.BCM)

            print("Disabling GPIO warnings")
            GPIO.setwarnings(False)

            print(
                "Setting up GPIO pins for EMERGENCYSTOP, EXTRAFORWARD, EXTRABACKWARD, and EXTRAENABLE"
            )
            GPIO.setup(EMERGENCYSTOP, GPIO.OUT)
            GPIO.setup(EXTRAFORWARD, GPIO.OUT)
            GPIO.setup(EXTRABACKWARD, GPIO.OUT)
            GPIO.setup(EXTRAENABLE, GPIO.OUT)

            print("Configuring default GPIO states")
            GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
            GPIO.output(EXTRAENABLE, GPIO.HIGH)

            print("GPIO setup completed successfully")
        except Exception as e:
            print(f"GPIO setup failed with error: {str(e)}")
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
        except Exception as e:
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
        except Exception:
            pass

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
        print(f"Application started at {datetime.now()}")
        print(f"Debug mode: {'enabled' if args.debug else 'disabled'}")

        app = QApplication(sys.argv)
        app.setStyle("Fusion")

        # A theme/stylesheet problem must never stop the device launching.
        try:
            from ui.theme import apply_theme
            theme_info = apply_theme(app)
            print(f"Theme applied: {theme_info}")
        except Exception as theme_err:
            print(f"Theme not applied, continuing with default style: {theme_err}")

        window = KneeSpa(debug_mode=args.debug, config_path=args.config)
        window._release_install_enabled = True
        window.show()

        app.exec_()
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


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        print("Full traceback:")
        traceback.print_exc()
    finally:
        GPIO.cleanup()
