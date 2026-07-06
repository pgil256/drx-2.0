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
# The controllers still address the window through the legacy attribute contract
# (window.ui.start_button, window.time_edit, window.timer_dialog, ...). That
# contract is satisfied here by explicit adapters onto the modern widgets, and
# by documented no-ops where the modern UI deliberately dropped a feature
# (floating timer/pressure dialogs, protocol-image pager, show-timer/pressure
# checkboxes). Controller logic itself is unchanged.
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
    QTime
)
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
)

from config.constants import (
    APP_BASE_DIR,
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
    MIN_PRESSURE,
    DEFAULT_PROTOCOL_MINUTES,
    PROTOCOL_MINUTES_MIN,
    PROTOCOL_MINUTES_MAX,
)

from config.config import Configuration
from helpers.arduino import Arduino
from helpers.csv import CSVHelper
from helpers.secure_auth import SecureAuthHelper
from helpers import protocols
from helpers.reset_worker import ResetWorker, ResetWorkerSignals
from helpers.conversions import lateral_degrees_to_position
from helpers.angles import pos_c_to_angle

from helpers.logging import setup_logger

# Modern view layer — the composition root for chrome + screens + modals.
from ui.app_shell import AppShell
from ui.widgets.loading_spinner import LoadingSpinner
from ui.widgets.treatment_status_panel import TreatmentStatusPanel

from controllers.safety_monitor import SafetyMonitor
from controllers.auth_controller import AuthController
from controllers.protocol_controller import ProtocolController
from controllers.connection_manager import ConnectionManager

# Suppress Qt warnings
os.environ["QT_LOGGING_RULES"] = "*.debug=False;qt.qpa.xcb=False"

# Map a Setup jog action to the legacy (speed_factor, direction) pair used by
# move_actuator ("20" = fast, "04" = slow; +1 forward, -1 reverse).
_JOG_SPEED = {
    "rev_fast": ("20", -1),
    "rev": ("04", -1),
    "fwd": ("04", 1),
    "fwd_fast": ("20", 1),
}


# ---------------------------------------------------------------------------
# Legacy-contract adapters
#
# The controllers (controllers/*) were extracted against the legacy .ui-file
# window and drive it through attributes like window.ui.start_button and
# window.time_edit. These adapters satisfy that contract against the modern
# AppShell so the controllers stay byte-identical.
# ---------------------------------------------------------------------------
class _NullWidget:
    """Stand-in for legacy widgets the modern UI deliberately dropped.

    Accepts every call the controllers make and does nothing:
    - timer_dialog / pressure_dialog (countdown + live pressure now render
      inline on the Treatment screen and the status banner),
    - forward/backward protocol-image pager, show-timer / show-pressure /
      use-pulse checkboxes, increase/decrease time labels (replaced by the
      Settings sliders), and the legacy login dialog/PIN field (the modern
      modal manages its own display and submits the whole PIN at once).
    """

    def setEnabled(self, *_): pass
    def setChecked(self, *_): pass
    def setText(self, *_): pass
    def setStyleSheet(self, *_): pass
    def setValue(self, *_): pass
    def setEchoMode(self, *_): pass
    def blockSignals(self, *_): pass
    def isVisible(self): return False
    def hide(self): pass
    def show(self): pass
    def clear(self): pass
    def text(self): return ""
    def value(self): return 0
    def accept(self): pass
    def initialize_protocol_time(self, *_): pass
    def update_time(self, *_): pass
    def update_pressure(self, *_): pass


class _ValueProxy:
    """Adapts the controllers' legacy ``.value()`` / ``.text()`` reads onto a
    live getter (the modern Settings sliders / protocol picker)."""

    def __init__(self, getter):
        self._getter = getter

    def value(self):
        return self._getter()

    def text(self):
        return str(self._getter())

    def setEnabled(self, *_): pass
    def setValue(self, *_): pass
    def blockSignals(self, *_): pass


class _StartButtonAdapter:
    """Maps the controllers' legacy Start/Stop-button drive onto the Treatment
    screen's run-state API: setText("Stop"/"Start") -> running/idle visuals,
    setEnabled -> busy lock. Styling belongs to the DS theme, so setStyleSheet
    is a no-op."""

    def __init__(self, window):
        self._window = window

    def setText(self, text):
        running = str(text).strip().lower() == "stop"
        try:
            self._window.shell.treatment.set_run_state(running=running, paused=False)
        except Exception:
            pass

    def setStyleSheet(self, *_):
        pass

    def setEnabled(self, enabled):
        try:
            self._window.shell.treatment.set_busy(not enabled)
        except Exception:
            pass


class _PhaseLabelAdapter:
    """Maps the controllers' free-text status-label writes onto the Treatment
    screen's phase badge/stepper (the status banner still gets the full text
    via treatment_panel.set_phase inside the controller)."""

    def __init__(self, window):
        self._window = window

    def setText(self, text):
        t = str(text).lower()
        if "pulsing" in t:
            phase = "pulsing"
        elif "oscillat" in t:
            phase = "oscillating"
        elif "moving to" in t:
            phase = "positioning"
        elif "complete" in t:
            phase = "complete"
        elif "stopped" in t:
            phase = "stopped"
        elif "started" in t or "pressure" in t:
            phase = "ramping"
        else:
            return  # untranslatable free text — leave the phase unchanged
        try:
            self._window.shell.treatment.set_phase(phase)
        except Exception:
            pass


class _LegacyUi:
    """Namespace for the ``window.ui.<name>`` attributes the controllers use."""

    def __init__(self, window):
        self.start_button = _StartButtonAdapter(window)
        self.status_label = _PhaseLabelAdapter(window)
        null = _NullWidget()
        # Dropped in the modern UI (see _NullWidget docstring). The reset-
        # arduino button's protocol-run lockout is covered by the Treatment
        # screen's set_busy + the actuator_controls group gating.
        self.forward_button_protocol_image = null
        self.backward_button_protocol_image = null
        self.show_timer_button = null
        self.show_pressure_button = null
        self.use_pulse_button = null
        self.reset_arduino_main_button = null


# Main Python class
class KneeSpa(QMainWindow):
    """Main application class for KneeSpa."""

    ### Static methods ###
    def exit_app(self):
        GPIO.cleanup()  # clean up GPIO on normal exit
        self.cleanup()
        # Exit 0: a nonzero code here made systemd (Restart=always /
        # on-failure) treat the operator's deliberate "Exit" as a crash
        # and immediately relaunch the app
        os._exit(0)

    def set_to_distance(self, inches, actuator, factor):
        position = int(inches * (factor / 8.0))
        print("Setting to {} in {} pos {} act".format(inches, position, actuator))
        # Format inches with at least 1 decimal place for proper Arduino parsing
        command = "A{}{:.1f}".format(actuator, inches)
        self.arduino.send(command)
        print("Sent cmd {}".format(command.strip()))
        self.I2Cstatus_event.clear()  # Clear the thread-safe event
        print("End set to distance")
        self.enable_actuator_controls()

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
            self.arduino.send(command)
            print(f"cmd {command}")

            self.I2Cstatus_event.clear()  # Clear the thread-safe event
            print("End set to c.")
            self.enable_actuator_controls()
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
        self.protocol_start_time = None
        self.protocol_duration = 0
        self._paused_at = None             # wall-clock pause anchor for the UI timer
        self._prev_settings = {}           # for mid-protocol slider rollback
        self._selected_issue = None        # last-opened Support troubleshooting item
        self.current_use_pulse_setting = True
        self.current_pulse_rate = None     # pulses/sec from the Settings slider
        self.axial_flexion_pressure = 0
        self.actuator_a = ACTUATORS["AXIAL"]["ID"]
        self.actuator_b = ACTUATORS["HORIZONTAL"]["ID"]
        self.actuator_c = ACTUATORS["LATERAL"]["ID"]
        self.protocol_timer = QTimer()

        # Actuator position tracking (legacy setup_actuator_controls defaults).
        self.axial_flexion_position = 0
        self.horizontal_flexion_position = -10
        self.lateral_flexion_position = 0
        self.leg_length = DEFAULT_LEG_LENGTH_POSITION
        self.current_pressure = DEFAULT_PRESSURE
        self.LEG_LENGTH_MIN = LEG_LENGTH_MIN
        self.LEG_LENGTH_MAX = LEG_LENGTH_MAX
        self.LEG_LENGTH_SPEED_NORMAL = LEG_LENGTH_SPEED_NORMAL
        self.LEG_LENGTH_SPEED_FAST = LEG_LENGTH_SPEED_FAST

        # Backend initialization
        self.I2Cstatus = 0  # Keep for compatibility
        self.I2Cstatus_event = threading.Event()  # Thread-safe event for synchronization
        self.config = Configuration(config_path=config_path)
        self.config.get_config()
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
        self._prev_pressure = None                   #  for rollback
        self._prev_left   = None
        self._prev_right  = None
        self.worker = None

        # --- build the modern view ---
        self.setWindowTitle(WINDOW_TITLE)
        self.shell = AppShell()
        self.setCentralWidget(self.shell)
        self.centralWidget().setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        if not debug_mode:
            self.showFullScreen()
            self.setWindowFlags(Qt.FramelessWindowHint)
            print("Production mode: Set to full screen without frame")
        else:
            print("Debug mode: Running in windowed mode")

        self.loading_spinner = LoadingSpinner(
            parent=self,
            size=300,        # up to you
            speed_pct=100    # 2.5× normal
        )

        # Always-visible treatment banner: live pressure, time remaining,
        # and a permanent STOP control on every page while a protocol runs.
        # Deliberately kept on top of the modern shell: the SafetyMonitor's
        # fault banner must stay visible regardless of the active screen.
        self.treatment_panel = TreatmentStatusPanel(parent=self)
        self.treatment_panel.stop_requested.connect(self.panel_stop_requested)
        self.safety = SafetyMonitor(self)
        self.auth = AuthController(self)
        self.protocol = ProtocolController(self)
        self.connection = ConnectionManager(self)
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

        # --- legacy attribute contract for the controllers ---
        self.ui = _LegacyUi(self)
        self.start_button = self.ui.start_button
        # Dropped floating dialogs / legacy time controls (see _NullWidget).
        self.timer_dialog = _NullWidget()
        self.pressure_dialog = _NullWidget()
        self.increase_time = _NullWidget()
        self.decrease_time = _NullWidget()
        self.login_line_edit = _NullWidget()
        self.login_dialog = _NullWidget()
        # Live reads the controllers make when starting/confirming a protocol.
        self.protocol_number_field = _ValueProxy(lambda: self.protocol_value)
        self.time_edit = _ValueProxy(self._duration_minutes)
        self.max_pressure_edit = _ValueProxy(
            lambda: self.shell.treatment.settings_values().get("max_pressure", 50)
        )
        self.max_left_edit = _ValueProxy(
            lambda: self.shell.treatment.settings_values().get("max_left", 10)
        )
        self.max_right_edit = _ValueProxy(
            lambda: self.shell.treatment.settings_values().get("max_right", 10)
        )

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

        # Ensure a persisted per-device id exists for support tickets (§15.5).
        try:
            self.config.ensure_device_id()
        except Exception as e:
            print(f"Could not ensure device id: {e}")

        self.shell.navigate("home")
        self._set_badge(False)  # offline until the Arduino connects
        # Navigation away from the Treatment screen is blocked while a
        # protocol is active (see controllers.protocol_controller.block_nav).
        self.shell.set_nav_guard(self._block_nav_during_treatment)

        # Initialize GPIO setup
        self.setup_gpio()
        # Initialize the Arduino instance afterward
        self.setup_arduino()

    # ----- view ↔ backend wiring -----
    def _connect_shell(self):
        """Connect every screen/modal signal to its backend slot."""
        s = self.shell

        # Auth (the shell surfaces these; gating lives in the shell).
        s.login_attempted.connect(self._on_login_attempt)
        s.logout_requested.connect(self._on_logout)

        # Setup screen.
        s.setup.jog_requested.connect(self._on_setup_jog)
        s.setup.go_requested.connect(self._on_setup_go)
        s.setup.stop_requested.connect(self._on_setup_stop)
        s.setup.mark_default_requested.connect(self._on_mark_default)
        s.setup.reset_arduino_requested.connect(self.reset_arduino)
        s.setup.emergency_stop_requested.connect(self._on_estop)

        # Treatment screen.
        s.treatment.protocol_selected.connect(self._on_protocol_selected)
        s.treatment.start_requested.connect(self.start_or_stop_protocol)
        s.treatment.resume_requested.connect(self._on_treatment_resume)
        s.treatment.pause_requested.connect(self._on_treatment_pause)
        s.treatment.estop_requested.connect(self._on_estop)
        s.treatment.setting_changed.connect(self._on_setting_changed)

        # Support screen.
        s.support.request_assistance.connect(self.handle_assistance_request)
        s.support.submit_ticket_requested.connect(self._on_submit_ticket)
        s.support.issue_activated.connect(self._on_issue_activated)

        # Video modal (owns the embedded VLC player).
        s.video_modal.play_toggled.connect(self._on_video_toggled)

    def _set_badge(self, connected):
        """Reflect Arduino connectivity on the Setup header badge."""
        try:
            self.shell.setup.set_arduino_connected(connected)
        except Exception:
            pass

    def _reflect_setup(self, key, value):
        """Push a controller-commanded position back onto the Setup row + Live
        Position readout (tolerant of a mocked shell in unit tests)."""
        try:
            self.shell.setup.set_position(key, value)
        except Exception:
            pass

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
        for w in self.actuator_controls:
            w.setEnabled(True)

    def reset_setup_readings(self):
        """Reset setup readings to default values (modern Setup rows)."""
        self._reflect_setup("axial", 0)
        self._reflect_setup("leg_length", 0.0)
        self._reflect_setup("lateral", 0)
        self._reflect_setup("pressure", 0)
        self._reflect_setup("horizontal", -10)

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

    def _on_setting_changed(self, key, value):
        """A Treatment Settings slider moved. Mid-protocol changes are gated by a
        one-time safety confirmation; on cancel the slider rolls back."""
        if not self._confirm_mid_protocol_change():
            self.shell.treatment.set_settings({key: self._prev_settings.get(key, value)})
            return
        self._prev_settings[key] = value
        if key == "pulse_rate":
            self.current_use_pulse_setting = value > 0
            self.current_pulse_rate = value if value > 0 else None
        if not self.worker:
            return
        if key == "max_pressure":
            self.worker.max_pressure = value
        elif key == "max_left":
            self.worker.max_left = -abs(value)
        elif key == "max_right":
            self.worker.max_right = abs(value)
        elif key == "pulse_rate":
            self.worker.pulse_rate = value
            self.worker.use_pulse = value > 0
        # "duration" is a pre-run parameter — the Treatment screen locks its
        # slider during an active run, so it is deliberately NOT adjusted live
        # here (a mid-run shorten could silently end the treatment).
        print(f"Mid-protocol: worker {key} updated to {value}")

    def _seed_modern_run_inputs(self):
        """Snapshot the modern Settings sliders for the controllers and the
        mid-protocol rollback seam before a start/stop toggle."""
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
        self._seed_modern_run_inputs()
        self.protocol.start_or_stop()
        if self.protocol_state == "running":
            try:
                self.shell.treatment.set_phase("ramping")
            except Exception:
                pass

    def _on_treatment_pause(self):
        if self.worker and self.protocol_running and not self._paused_at:
            self.worker.pause()
            self._paused_at = time.time()
            if self.protocol_timer.isActive():
                self.protocol_timer.stop()
            try:
                self.shell.treatment.set_run_state(running=True, paused=True)
                self.shell.treatment.set_phase("paused")
            except Exception:
                pass

    def _on_treatment_resume(self):
        if self.worker and self.protocol_running and self._paused_at:
            self.worker.resume()
            # Shift the UI clock past the paused span so the countdown is correct.
            if self.protocol_start_time is not None:
                self.protocol_start_time += (time.time() - self._paused_at)
            self._paused_at = None
            self.protocol_timer.start(1000)
            try:
                self.shell.treatment.set_run_state(running=True, paused=False)
                self.shell.treatment.set_phase(
                    "pulsing" if self.current_use_pulse_setting else "holding"
                )
            except Exception:
                pass

    def _on_estop(self):
        """Emergency stop from the modern Setup/Treatment screens. Runs the
        controllers' e-stop chain (X → worker stop → reset), then forces the
        Treatment UI back to a stopped state; the protocol state machine
        closes via the worker's finished(False) signal."""
        self.emergency_stop_clicked(None)
        self._paused_at = None
        if self.protocol_timer.isActive():
            self.protocol_timer.stop()
        try:
            self.shell.treatment.set_run_state(running=False, paused=False)
            self.shell.treatment.set_phase("stopped")
        except Exception:
            pass

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
    def _on_setup_jog(self, key, action):
        """A Setup jog button was tapped. move_actuator stays the authoritative,
        safety-clamped path; the row's local pre-move is corrected by reflecting
        the true commanded position back onto the slider."""
        if action == "reset":
            self._setup_reset(key)
            return
        if key == "leg_length":
            self._leg_jog(action)
            return
        if key == "pressure":
            # Pressure has no jog-command in the legacy device; the row already
            # nudged its slider — just refresh the Live Position readout.
            self._reflect_setup("pressure", self.shell.setup.row_value("pressure"))
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
            # No firmware pressure reset; just zero the display.
            self._reflect_setup("pressure", 0)

    def _on_setup_go(self, key):
        """Move an actuator to its row's current slider value (the legacy Go
        path), preserving the per-actuator unit conversions and clamps."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        try:
            if key == "axial":
                inches = self.shell.setup.row_value("axial")
                inches = max(AXIAL_MIN_INCHES, min(AXIAL_MAX_INCHES, inches))
                self.set_to_distance(inches, self.actuator_a, self.config.a_factor)
                self.axial_flexion_position = inches
                self._reflect_setup("axial", inches)
            elif key == "horizontal":
                degrees = self.shell.setup.row_value("horizontal")
                degrees = max(HORIZONTAL_MIN_DEGREES, min(HORIZONTAL_MAX_DEGREES, degrees))
                inches = abs((degrees + 25) / 5)
                self.set_to_distance(inches, self.actuator_b, self.config.b_factor)
                self.horizontal_flexion_position = degrees
                self._reflect_setup("horizontal", degrees)
            elif key == "lateral":
                degrees = self.shell.setup.row_value("lateral")
                degrees = max(LATERAL_MIN_DEGREES, min(LATERAL_MAX_DEGREES, degrees))
                self.set_to_c_distance(degrees)
                self.lateral_flexion_position = degrees
                self._reflect_setup("lateral", degrees)
            elif key == "pressure":
                self._apply_setup_pressure()
            elif key == "leg_length":
                # Open-loop FIT actuator — no absolute position command.
                pass
        except Exception as e:
            print(f"Error in Setup Go: {str(e)}")
            self._show_timed_error(f"Error moving actuator: {str(e)}")
        finally:
            self.loading_spinner.hide()

    def _apply_setup_pressure(self):
        """Setup pressure Go: clamp to [MIN_PRESSURE, PRESSURE_MAX] and send P."""
        pressure = self.shell.setup.row_value("pressure")
        if pressure > PRESSURE_MAX:
            pressure = PRESSURE_MAX
            self.logger.warning(f"Pressure request exceeds max {PRESSURE_MAX}, clamping")
            self._show_timed_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
        elif pressure < MIN_PRESSURE:
            pressure = MIN_PRESSURE
            self.logger.warning(f"Pressure request below minimum, setting to {MIN_PRESSURE}")
        pressure = int(pressure)
        self.arduino.send("P{}".format(pressure))
        print("Pressure cmd sent P{}".format(pressure))
        self.current_pressure = pressure
        self._reflect_setup("pressure", pressure)

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
        vals = self.shell.treatment.settings_values()
        mp = max(0, min(PRESSURE_MAX, vals.get("max_pressure", 50)))
        ml = max(0, min(abs(LATERAL_MAX_DEGREES), abs(vals.get("max_left", 10))))
        mr = max(0, min(abs(LATERAL_MAX_DEGREES), abs(vals.get("max_right", 10))))
        pr = max(0, min(5, vals.get("pulse_rate", 2)))
        dur = self._clamp_minutes(vals.get("duration", DEFAULT_PROTOCOL_MINUTES))
        try:
            self.config.save_protocol_defaults(mp, ml, mr, pr, dur)
            self.shell.treatment.set_settings(
                {"max_pressure": mp, "max_left": ml, "max_right": mr,
                 "pulse_rate": pr, "duration": dur}
            )
            self._show_timed_error("Saved current settings as the default.")
        except Exception as e:
            print(f"Failed to save defaults: {e}")
            self._show_timed_error("Could not save defaults.")

    # ----- auth -----
    def _on_login_attempt(self, pin):
        """Modern login modal submits the whole PIN; the salted-hash verify and
        lockout live in controllers.auth_controller."""
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
        if self._block_nav_during_treatment():
            return
        print("Handling logout")
        self.current_user = None
        self.shell.logout()

    def update_ui_after_login(self):
        """Update user interface with user details after login (modern shell:
        close the modal, set the user chip, and go to the Treatment screen)."""
        print("Updating UI after login")
        self.shell.login_succeeded(self.current_user["username"], goto="protocols")

    # ----- Support -----
    def _on_issue_activated(self, question):
        # Remember the last-opened troubleshooting item as ticket context.
        self._selected_issue = question

    def _on_submit_ticket(self):
        self.submit_ticket(self._selected_issue or "General support request")

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

    def email_admin(self):
        """Send the assistance-request email from a worker thread.

        Blocking SMTP-over-SSL used to run on the UI thread, freezing the
        kiosk up to the TCP timeout whenever the network was down -- and
        the operator never learned whether help was actually summoned.
        """
        sender_email = EMAIL_CONFIG["SENDER_EMAIL"]
        sender_password = EMAIL_CONFIG["SENDER_PASSWORD"]
        receiver_email = EMAIL_CONFIG["RECEIVER_EMAIL"]
        smtp_server = EMAIL_CONFIG["SMTP_SERVER"]
        smtp_port = EMAIL_CONFIG["SMTP_PORT"]

        subject = "Assistance Request"
        body = f"User {self.username} with email {self.user_email} and status {self.user_status} is requesting assistance."
        print(body)

        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email

        def _send():
            try:
                if not sender_email or not sender_password or not receiver_email:
                    raise RuntimeError("SMTP credentials are not configured")
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, receiver_email, message.as_string())
                print("Assistance request email sent successfully.")
            except Exception as e:
                print(f"Failed to send assistance email: {e}")
                self.logger.error(f"Failed to send assistance email: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def submit_ticket(self, issue_text):
        """Submit a support ticket (§15.5) — SMTP to the TICKET_EMAIL, tagged
        with the persisted per-device id. Sent from a worker thread like
        email_admin (blocking SMTP froze the kiosk on a down network)."""
        sender_email = EMAIL_CONFIG["SENDER_EMAIL"]
        sender_password = EMAIL_CONFIG["SENDER_PASSWORD"]
        receiver_email = EMAIL_CONFIG["TICKET_EMAIL"]
        smtp_server = EMAIL_CONFIG["SMTP_SERVER"]
        smtp_port = EMAIL_CONFIG["SMTP_PORT"]

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
        message = MIMEText(body)
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = receiver_email

        def _send():
            try:
                if not sender_email or not sender_password or not receiver_email:
                    raise RuntimeError("SMTP credentials are not configured")
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15) as server:
                    server.login(sender_email, sender_password)
                    server.sendmail(sender_email, receiver_email, message.as_string())
                print("Support ticket sent successfully.")
            except Exception as e:
                print(f"Failed to send ticket: {e}")
                self.logger.error(f"Failed to send ticket: {e}")

        threading.Thread(target=_send, daemon=True).start()
        self._show_timed_error("Support ticket is being sent.")

    # ----- protocol state / navigation gating -----
    def set_protocol_state(self, state):
        """Protocol lifecycle (see controllers.protocol_controller)."""
        self.protocol.set_state(state)

    def _block_nav_during_treatment(self):
        return self.protocol.block_nav()

    def panel_stop_requested(self):
        self.protocol.panel_stop_requested()

    def _show_safety_alert(self, message):
        """Persistent, acknowledged alert for safety events.

        Safety stops used to auto-dismiss after 5 seconds, so an operator
        who looked away never knew an emergency stop fired.
        """
        print(f"SAFETY ALERT: {message}")
        self.logger.error(f"Safety alert: {message}")
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("SAFETY STOP")
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.setWindowFlags(msg_box.windowFlags() | Qt.WindowStaysOnTopHint)
        msg_box.show()  # non-modal so STOP controls stay reachable
        # Keep a reference so it is not garbage-collected
        self._active_safety_alert = msg_box

    ### Backend Methods ###

    def handle_connection_failed(self, message):
        self._set_badge(False)
        self.connection.handle_connection_failed(message)

    def cleanup(self):
        """Clean up resources, including the video player and GPIO."""
        print("Cleaning up resources.")

        if self.worker:
            self.worker.stop()

        # Release the embedded VLC player, if any.
        if hasattr(self, "shell"):
            self.shell.video_modal.cleanup()

        # Force Arduino disconnect
        if hasattr(self, "arduino"):
            self.arduino.disconnect()

        GPIO.cleanup()

    def closeEvent(self, event):
        """Handle the close event to ensure cleanup."""
        self.cleanup()
        event.accept()

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

            self.horizontal_flexion_position = new_position
            print(f"B position: {self.horizontal_flexion_position}")

            # Convert degrees to inches like the slider does
            inches = abs((self.horizontal_flexion_position + 25) / 5)

            # Use the same command format as the slider/go button
            command = f"A{actuator}{inches}"
            self.arduino.send(command)

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

            self.axial_flexion_position = new_position
            print(f"A position: {self.axial_flexion_position}")

            # Send command to Arduino
            # Arduino expects: A[2-digit device][float value starting at position 3]
            # Format position with at least 1 decimal place to ensure proper parsing
            command = f"A12{self.axial_flexion_position:.1f}"
            print(f"Sending axial command: {command}")
            self.arduino.send(command)
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

            self.lateral_flexion_position = new_position

            print(
                f" positioned to {self.lateral_flexion_position} degrees pos {position}"
            )

            # Send command to Arduino
            command = f"K{position}"
            self.arduino.send(command)

            self._reflect_setup("lateral", self.lateral_flexion_position)
            self.loading_spinner.hide()

    def reset_flexion_button_clicked(self, actuator):
        self.loading_spinner.show()
        self.disable_actuator_controls()
        print(actuator)
        if actuator == self.actuator_c:
            position = self.config.CMarks["{:.1f}".format(0)]
            print(f" positioned to 0 degrees pos {position}")
            command = f"I14{position}"
            self.arduino.send(command)
            self.lateral_flexion_position = 0
            self._reflect_setup("lateral", 0)
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_b:
            command = f"A{actuator}2"
            self.arduino.send(command)  # transmit data serially
            self.horizontal_flexion_position = -10
            self._reflect_setup("horizontal", -10)
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_a:
            # 'R12' was never a firmware command (parsed as Unknown); the
            # UI then showed 0 in / 0 lb while nothing moved. Home the
            # axial actuator for real, the way the reset sequence does.
            command = "I120"
            self.arduino.send(command)  # firmware floors this to AZERO
            self.axial_flexion_position = 0
            self._reflect_setup("axial", 0)
            self._reflect_setup("pressure", 0)
            # Re-send the scale factor once the move has had time to
            # finish, without freezing the UI thread for 5 seconds.
            # NOTE: the firmware tares on L0, so this must only happen
            # in a no-load state -- which a completed axial home is.
            QTimer.singleShot(5000, self.send_calibration)
            self.loading_spinner.hide()

            return

    def stop_actuators(self):
        """Emergency stop for all actuators."""
        print("Emergency stop triggered")
        try:
            if not self.arduino.send("X"):  # Stop all movement
                # A stop that could not even be queued is an alarm, not a
                # log line: the link is down. The firmware's heartbeat
                # timeout stops motion on its side within ~3 seconds.
                self.logger.error("Emergency stop could not be sent - link down")
                self._show_timed_error(
                    "STOP NOT DELIVERED - connection down. "
                    "Device stops itself within 3 seconds."
                )
        except Exception as e:
            print(f"Error in emergency stop: {str(e)}")
            self._show_timed_error(f"Emergency stop failed: {str(e)}")

    def stop_position_flexion_button(self, actuator):
        # Firmware 'X' stops all actuators regardless of suffix
        if not self.arduino.send("X"):
            self.logger.error("Actuator stop could not be sent - link down")
            self._show_timed_error(
                "STOP NOT DELIVERED - connection down. "
                "Device stops itself within 3 seconds."
            )

    # ----- leg-length (FIT) jog handlers (open-loop F-commands + GPIO) -----
    def forward_button_clicked(self):
        """Handle forward button press - normal speed."""

        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F+")
        GPIO.output(EXTRAFORWARD, GPIO.HIGH)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        # Firmware auto-stops its FIT pins after FIT_SLOW_DELAY (0.5s);
        # mirror that on the Pi pins, which used to latch HIGH until the
        # next button press
        QTimer.singleShot(600, self._release_leg_gpio)

        if self.leg_length >= self.LEG_LENGTH_MAX:
            return  # Already at max
        # Update display (0.5s slow run ~= 0.25 in of travel)
        self.leg_length += 0.25
        self.leg_length = min(self.leg_length, self.LEG_LENGTH_MAX)  # Don't exceed max
        self._reflect_setup("leg_length", self.leg_length)
        self.loading_spinner.hide()

    def reverse_button_clicked(self):
        """Handle reverse button press - normal speed."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F-")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH)
        QTimer.singleShot(600, self._release_leg_gpio)

        if self.leg_length <= 0:
            return  # Already at min

        # Update display (0.5s slow run ~= 0.25 in of travel)
        self.leg_length -= 0.25
        self.leg_length = max(0, self.leg_length)  # Don't go below 0
        self._reflect_setup("leg_length", self.leg_length)
        self.loading_spinner.hide()

    def forward_fast_button_clicked(self):
        """Handle forward button press - fast speed."""
        self.loading_spinner.show()
        print("forward_fast_button_clicked")
        self.disable_actuator_controls()
        if self.leg_length >= self.LEG_LENGTH_MAX:
            return  # Already at max

        self.arduino.send("FF")
        GPIO.output(EXTRAFORWARD, GPIO.HIGH)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        # Firmware fast run is FIT_FAST_DELAY (6s)
        QTimer.singleShot(6100, self._release_leg_gpio)

        # Update display (6s fast run ~= 3.0 in of travel)
        self.leg_length += 3.0
        self.leg_length = min(self.leg_length, self.LEG_LENGTH_MAX)  # Don't exceed max
        self._reflect_setup("leg_length", self.leg_length)
        self.loading_spinner.hide()

    def reverse_fast_button_clicked(self):
        """Handle reverse button press - fast speed."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("FR")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH)
        QTimer.singleShot(6100, self._release_leg_gpio)

        if self.leg_length >= 3:
            # Update displays
            self.leg_length = 0
            self._reflect_setup("leg_length", self.leg_length)
        else:
            self.leg_length -= 3.0  # 6s fast run ~= 3.0 in of travel
            self.leg_length = max(0, self.leg_length)  # Don't go below 0
            self._reflect_setup("leg_length", self.leg_length)

        self.loading_spinner.hide()

    def _release_leg_gpio(self):
        """Drop the Pi-side leg-motor direction pins to a safe state."""
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

    def reset_extra_button_clicked(self):
        """Reset leg length position."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F0")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

        QTimer.singleShot(3000, self.reverse_fast_button_clicked)

        self.leg_length = 0.0
        self._reflect_setup("leg_length", 0.0)
        self.loading_spinner.hide()

    def stop_leg_movement(self):
        """Stop leg length actuator movement."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F0")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)
        # GPIO.output(EXTRAENABLE, GPIO.LOW)
        self.loading_spinner.hide()

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
            self.shell.treatment.set_pressure(pressure)
            self.shell.treatment.set_angle(pos_c_to_angle(steps, self.config.CMarks))
        except Exception as e:
            print(f"Error updating live status: {e}")
        return self.safety.on_status(position_a, position_b, steps, pressure)

    def _trigger_safety_stop(self, reason):
        self.safety.trigger_safety_stop(reason)

    def _show_timed_error(self, message):
        """Show error message that automatically closes after a timeout."""
        print(f"Status emit error: {message}")

        # Create the error dialog
        msg_box = QMessageBox(self)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)

        # Create a QTimer to close the dialog after 10 seconds
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(msg_box.close)
        timer.start(5000)  # 5 seconds in milliseconds

        # Show the dialog without blocking
        msg_box.show()

    def handle_buffer_warning(self, warning):
        print(f"Buffer warning: {warning}")

    @QtCore.pyqtSlot(str)
    def handle_firmware_error(self, message):
        self.safety.on_firmware_error(message)

    @QtCore.pyqtSlot()
    def handle_pressure_released(self):
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


def _print_recent_logs(lines=200):
    """Print recent application logs for debug runs."""
    log_dir = os.path.join(APP_BASE_DIR, "logs")
    for filename in ("kneespa.log", "error.log", "debug.log"):
        path = os.path.join(log_dir, filename)
        if not os.path.exists(path):
            continue
        print(f"\n--- {path} ---")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as log_file:
                content = log_file.readlines()[-lines:]
            print("".join(content))
        except Exception as e:
            print(f"Could not print {path}: {e}")


def _sync_logs(destination):
    """Copy application logs to a destination directory."""
    if not destination:
        return
    log_dir = os.path.join(APP_BASE_DIR, "logs")
    os.makedirs(destination, exist_ok=True)
    if not os.path.isdir(log_dir):
        print(f"Log directory does not exist: {log_dir}")
        return
    for name in os.listdir(log_dir):
        source = os.path.join(log_dir, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(destination, name))
    print(f"Logs synced to {destination}")


# Main function without direct access to Arduino
def main():
    """Main function to start the application."""
    import argparse

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

    print(f"Application started at {datetime.now()}")
    print(f"Debug mode: {'enabled' if args.debug else 'disabled'}")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Apply the modern theme foundation (bundled fonts + global QSS).
    # Guarded so a theme/stylesheet problem can never stop the device launching.
    try:
        from ui.theme import apply_theme
        theme_info = apply_theme(app)
        print(f"Theme applied: {theme_info}")
    except Exception as theme_err:
        print(f"Theme not applied, continuing with default style: {theme_err}")

    window = KneeSpa(debug_mode=args.debug, config_path=args.config)
    window.show()

    app.exec_()

    if args.print_logs:
        _print_recent_logs()
    if args.sync_logs:
        _sync_logs(args.sync_logs)

    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        print("Full traceback:")
        traceback.print_exc()
    finally:
        GPIO.cleanup()
