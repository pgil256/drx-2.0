# test
import logging
import traceback
import sys
import os
import csv
import RPi.GPIO as GPIO
import time
import smtplib
import threading 
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtCore import (
    Qt,
    QTimer,
    QThread,
    QObject,
    QTime
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QCheckBox,
)

from config.constants import (
    APP_BASE_DIR,
    PAGES,
    UI_PATHS,
    DATA_PATHS,
    DEGREES,
    ACTUATORS,
    BUTTON_STYLES,
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    ARDUINO_SETTINGS,
    PROTOCOL_MAPPING,
    EMERGENCYSTOP,
    EXTRAFORWARD,
    EXTRABACKWARD,
    EXTRAENABLE,
    EMAIL_CONFIG,
    PRESSURE_MAX,
    AXIAL_MAX,
    LATERAL_MIN,
    LATERAL_MAX,
    HORIZONTAL_MIN,
    HORIZONTAL_MAX,
    LEG_LENGTH_SPEED_NORMAL,
    LEG_LENGTH_SPEED_FAST,
    LEG_LENGTH_MIN,
    LEG_LENGTH_MAX,
    DEFAULT_AXIAL_POSITION,
    DEFAULT_LATERAL_POSITION,
    DEFAULT_HORIZONTAL_POSITION,
    DEFAULT_PRESSURE,
    DEFAULT_LEG_LENGTH_POSITION
)

from config.config import Configuration
from helpers.arduino import Arduino
from helpers.csv import CSVHelper
from helpers import protocols
from helpers.reset_worker import ResetWorker, ResetWorkerSignals 

from helpers.logging import setup_logger

# Import UI components
from ui.dialogs import TimerDialog, PressureDialog, VideoPlayer
from ui.widgets.loading_spinner import LoadingSpinner

# Suppress Qt warnings
os.environ["QT_LOGGING_RULES"] = "*.debug=False;qt.qpa.xcb=False"

# Main Python class
class KneeSpa(QMainWindow):
    """Main application class for KneeSpa."""

    ### Static methods ###
    def exit_app(self):
        GPIO.cleanup()  # clean up GPIO on normal exit
        self.cleanup()
        os._exit(1)

    def set_to_distance(self, inches, actuator, factor):
        position = int(inches * (factor / 8.0))
        print("Setting to {} in {} pos {} act".format(inches, position, actuator))
        command = "A{}{}".format(actuator, inches)
        self.arduino.send(command)
        print("Sent cmd {}".format(command.strip()))
        self.I2CStatus = 0
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
            # Ensure degrees is float
            degrees = float(degrees)

            # Round to nearest 2.5 degrees
            degrees = round(degrees * 2) / 2

            # Ensure degrees is within bounds
            degrees = max(-20.0, min(20.0, degrees))

            # Format for dictionary lookup
            degree_key = "{:.1f}".format(degrees)

            # If exact value exists, use it
            if degree_key in self.config.CMarks:
                position = int(self.config.CMarks[degree_key])
            else:
                # Convert dictionary items to float keys and integer values
                marks = sorted(
                    [(float(k), int(v)) for k, v in self.config.CMarks.items()]
                )

                # Find the two closest points for interpolation
                for i in range(len(marks) - 1):
                    if marks[i][0] <= degrees <= marks[i + 1][0]:
                        deg1, pos1 = marks[i]
                        deg2, pos2 = marks[i + 1]

                        # Linear interpolation with explicit float conversion
                        ratio = (float(degrees) - deg1) / (deg2 - deg1)
                        position = pos1 + int((pos2 - pos1) * ratio)
                        break
                else:
                    raise ValueError(f"Degree value {degrees} outside valid range")

            print(f" positioned to {degrees} degrees pos {position}")
            command = f"K{position}"
            self.arduino.send(command)
            print(f"cmd {command}")

            self.I2CStatus = 0
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
    def __init__(self, debug_mode=False):
        super().__init__()

        self.logger = setup_logger(component="KneeSpa")
        print(
            f"Initializing KneeSpa class in {'debug' if debug_mode else 'production'} mode"
        )

        self.protocol_value = ""
        self.protocol_running = False
        self.mid_protocol_warning_shown = False # <-- Add this
        self.button_value = 0
        self.protocol_start_time = None  # Initialize as None
        self.current_use_pulse_setting = True
        self.axial_flexion_pressure = 0
        self.left_lat_angle = 0
        self.right_lat_angle = 0
        self.actuator_a = ACTUATORS["AXIAL"]["ID"]
        self.actuator_b = ACTUATORS["HORIZONTAL"]["ID"]
        self.actuator_c = ACTUATORS["LATERAL"]["ID"]
        self.protocol_timer = QTimer()
        self.elapsed_timer = QTimer()
        self.complete_timer = QTimer()
        self.stop_timer = QTimer()
        self.go_timer = QTimer()
        self.reset_timer = QTimer()

        # Backend initialization
        self.newC = True
        self.I2Cstatus = 0
        self.I2Cstatus_event = threading.Event()  # Thread-safe event for I2C synchronization
        self.config = Configuration()
        self.config.get_config()
        self.reset_done_event = threading.Event()
        self.initial_setup_complete = False
        self.reset_in_progress = False  # Flag to prevent overlapping resets
        self.mid_protocol_warning_shown = False 
        self._prev_pressure = None                   #  for rollback
        self._prev_left   = None
        self._prev_right  = None

        try:
            print("Loading main UI file")
            self.ui = uic.loadUi(UI_PATHS["MAIN_UI"], self)
        except FileNotFoundError:
            print(ERROR_MESSAGES["UI_NOT_FOUND"])
            self._show_timed_error("UI file not found.")
            sys.exit(1)

        if not debug_mode:
            self.ui.showFullScreen()
            self.setWindowFlags(Qt.FramelessWindowHint)
            print("Production mode: Set to full screen without frame")
        else:
            print("Debug mode: Running in windowed mode")

        # Finding and assigning central widget
        print("Finding central widget 'central_widget'")
        central_widget = self.ui.findChild(QtWidgets.QWidget, "central_widget")
        if central_widget:
            self.setCentralWidget(central_widget)
        else:
            raise ValueError("Central widget 'main_content' not found in the UI file.")

        self.centralWidget().setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        self.loading_spinner = LoadingSpinner(
            parent=self,
            size=300,        # up to you
            speed_pct=100    # 2.5× normal
        )

        self.login_pin = ""

        # Initialize the CSV helper
        self.csv = CSVHelper()
        try:
            self.csv.initialize_data()
            self.users = self.csv.users
            print(SUCCESS_MESSAGES["DATA_LOADED"])
        except Exception as e:
            print(f"Error loading CSV data: {str(e)}")
            self._show_timed_error(f"Failed to load CSV data: {str(e)}")

        self.current_user = None

        self.home_page = PAGES["HOME"]
        self.setup_page = PAGES["SETUP"]
        self.main_page = PAGES["MAIN"]
        self.help_page = PAGES["HELP"]
        self.profile_page = PAGES["PROFILE"]

        self.setup_buttons_and_labels()
        self.connect_buttons_and_labels()
        self.setup_protocol_controls()
        self.setup_dialogs()
        self.show_home_page()
        self.reset_setup_readings()

        self.threadpool = QtCore.QThreadPool()
        print(f"Multithreading with maximum {self.threadpool.maxThreadCount()} threads")
        self.worker = None

        self.timer_dialog = TimerDialog(self)
        self.pressure_dialog = PressureDialog(self)

        self.setup_timers()

        self.CMarks = {}
        for i in range(16):
            u = (i * 220) + 98
            angle = (i * 2.5) - 20
            self.CMarks[angle] = u

        # Initialize GPIO setup
        self.setup_gpio()
        # Initialize the Arduino instance afterward
        self.setup_arduino()

        ### UI Methods ###

    def setup_buttons_and_labels(self):
        """Setup and store references to all UI buttons and labels."""
        print("Setting up UI buttons and labels")

        try:
            # Navigation buttons
            self.ui.setup_button = self.ui.findChild(
                QtWidgets.QPushButton, "setup_button"
            )
            self.ui.protocols_button = self.ui.findChild(
                QtWidgets.QPushButton, "protocols_button"
            )
            self.ui.help_button = self.ui.findChild(
                QtWidgets.QPushButton, "help_button"
            )
            self.ui.login_button = self.ui.findChild(
                QtWidgets.QPushButton, "login_button"
            )

            # Protocol controls
            self.ui.start_button = self.ui.findChild(
                QtWidgets.QPushButton, "push_button_start"
            )
            self.ui.start_button.setStyleSheet(BUTTON_STYLES["START"])

            # Profile and navigation labels
            self.ui.profile_button = self.ui.findChild(
                QtWidgets.QLabel, "profile_button"
            )
            self.ui.video_player_button = self.ui.findChild(
                QtWidgets.QLabel, "video_player_button"
            )
            self.ui.brand_label = self.ui.findChild(
                QtWidgets.QLabel, "top_nav_brand_label"
            )
            self.ui.brand_logo = self.ui.findChild(QtWidgets.QLabel, "top_nav_logo")
            self.ui.exit_app_button = self.ui.findChild(
                QtWidgets.QPushButton, "exit_app_button"
            )
            self.ui.request_assistance_button = self.ui.findChild(
                QtWidgets.QPushButton, "request_assistance_button"
            )

            # User information labels
            self.ui.username_nav = self.ui.findChild(QtWidgets.QLabel, "username_nav")
            self.ui.username_profile = self.ui.findChild(
                QtWidgets.QLabel, "username_field"
            )
            self.ui.email_profile = self.ui.findChild(QtWidgets.QLabel, "email_field")
            self.ui.status_profile = self.ui.findChild(QtWidgets.QLabel, "status_field")

            # System control buttons
            self.ui.set_up_tolerance_button = self.ui.findChild(
                QtWidgets.QLabel, "set_up_tolerance_button"
            )
            self.ui.reset_arduino_main_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_arduino_main_button"
            )
            self.ui.reset_arduino_setup_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_arduino_setup_button"
            )

            # Checkbox controls
            self.ui.show_timer_button = self.ui.findChild(
                QtWidgets.QCheckBox, "checkbox_show_timer"
            )
            self.ui.show_pressure_button = self.ui.findChild(
                QtWidgets.QCheckBox, "checkbox_show_pressure"
            )
            self.ui.use_pulse_button = self.ui.findChild(
                QtWidgets.QCheckBox, "checkbox_use_pulse"
            )

            # Protocol image controls
            self.ui.label_protocol_image = self.ui.findChild(
                QtWidgets.QLabel, "label_protocol_image"
            )
            self.ui.protocol_image_number = self.ui.findChild(
                QtWidgets.QLineEdit, "protocol_number_field"
            )
            self.ui.forward_button_protocol_image = self.ui.findChild(
                QtWidgets.QLabel, "forward_button_protocol_image"
            )
            self.ui.backward_button_protocol_image = self.ui.findChild(
                QtWidgets.QLabel, "backward_button_protocol_image"
            )

            # Emergency controls
            self.ui.emergency_stop_setup_label = self.ui.findChild(
                QtWidgets.QLabel, "emergency_stop_setup_label"
            )

            # Actuator position labels
            self.ui.axial_flexion_position_label = self.ui.findChild(
                QtWidgets.QLabel, "axial_flexion_position_label"
            )
            self.ui.axial_flexion_position_label_2 = self.ui.findChild(
                QtWidgets.QLabel, "axial_flexion_position_label_2"
            )
            self.ui.lateral_flexion_position_label = self.ui.findChild(
                QtWidgets.QLabel, "lateral_flexion_position_label"
            )
            self.ui.horizontal_flexion_position_label = self.ui.findChild(
                QtWidgets.QLabel, "horizontal_flexion_position_label"
            )

            # Actuator pressure labels
            self.ui.axial_flexion_pressure_label = self.ui.findChild(
                QtWidgets.QLabel, "axial_flexion_pressure_label"
            )

            # Actuator control buttons
            self.ui.forward_extra_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_extra_button"
            )
            self.ui.reverse_extra_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_extra_button"
            )
            self.ui.forward_fast_extra_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_fast_extra_button"
            )
            self.ui.reverse_fast_extra_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_fast_extra_button"
            )
            self.ui.reset_extra_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_extra_button"
            )
            self.ui.forward_axial_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_axial_flexion_button"
            )
            self.ui.reverse_axial_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_axial_flexion_button"
            )
            self.ui.forward_fast_axial_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_fast_axial_flexion_button"
            )
            self.ui.reverse_fast_axial_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_fast_axial_flexion_button"
            )
            self.ui.reset_axial_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_axial_flexion_button"
            )

            # Actuator stop and go controls
            self.ui.axial_flexion_position_go_button = self.ui.findChild(
                QtWidgets.QPushButton, "axial_flexion_position_go_button"
            )
            self.ui.axial_flexion_position_stop_button = self.ui.findChild(
                QtWidgets.QPushButton, "axial_flexion_position_stop_button"
            )
            self.ui.axial_flexion_pressure_go_button = self.ui.findChild(
                QtWidgets.QPushButton, "axial_flexion_pressure_go_button"
            )
            self.ui.axial_flexion_pressure_stop_button = self.ui.findChild(
                QtWidgets.QPushButton, "axial_flexion_pressure_stop_button"
            )
            self.ui.lateral_flexion_position_go_button = self.ui.findChild(
                QtWidgets.QPushButton, "lateral_flexion_position_go_button"
            )
            self.ui.lateral_flexion_position_stop_button = self.ui.findChild(
                QtWidgets.QPushButton, "lateral_flexion_position_stop_button"
            )
            self.ui.horizontal_flexion_position_go_button = self.ui.findChild(
                QtWidgets.QPushButton, "horizontal_flexion_position_go_button"
            )
            self.ui.horizontal_flexion_position_stop_button = self.ui.findChild(
                QtWidgets.QPushButton, "horizontal_flexion_position_stop_button"
            )

            # Lateral and horizontal flexion control buttons
            self.ui.forward_lateral_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_lateral_flexion_button"
            )
            self.ui.reverse_lateral_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_lateral_flexion_button"
            )
            self.ui.forward_fast_lateral_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_fast_lateral_flexion_button"
            )
            self.ui.reverse_fast_lateral_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_fast_lateral_flexion_button"
            )
            self.ui.reset_lateral_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_lateral_flexion_button"
            )

            self.ui.forward_horizontal_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_horizontal_flexion_button"
            )
            self.ui.reverse_horizontal_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_horizontal_flexion_button"
            )
            self.ui.forward_fast_horizontal_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "forward_fast_horizontal_flexion_button"
            )
            self.ui.reverse_fast_horizontal_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reverse_fast_horizontal_flexion_button"
            )
            self.ui.reset_horizontal_flexion_button = self.ui.findChild(
                QtWidgets.QPushButton, "reset_horizontal_flexion_button"
            )

            # Actuator position sliders
            self.ui.axial_flexion_position_slider = self.ui.findChild(
                QtWidgets.QSlider, "axial_flexion_position_slider"
            )
            self.ui.lateral_flexion_position_slider = self.ui.findChild(
                QtWidgets.QSlider, "lateral_flexion_position_slider"
            )
            self.ui.horizontal_flexion_position_slider = self.ui.findChild(
                QtWidgets.QSlider, "horizontal_flexion_position_slider"
            )
            self.ui.axial_flexion_pressure_slider = self.ui.findChild(
                QtWidgets.QSlider, "axial_flexion_pressure_slider"
            )

            # Group all widgets that should be locked while the MCU is busy
            self.actuator_controls = [
                # leg-length
                self.ui.forward_extra_button, self.ui.reverse_extra_button,
                self.ui.forward_fast_extra_button, self.ui.reverse_fast_extra_button,
                self.ui.reset_extra_button,
                # axial
                self.ui.forward_axial_flexion_button, self.ui.reverse_axial_flexion_button,
                self.ui.forward_fast_axial_flexion_button, self.ui.reverse_fast_axial_flexion_button,
                self.ui.reset_axial_flexion_button,
                self.ui.axial_flexion_position_go_button,
                self.ui.axial_flexion_pressure_go_button,
                # lateral
                self.ui.forward_lateral_flexion_button, self.ui.reverse_lateral_flexion_button,
                self.ui.forward_fast_lateral_flexion_button, self.ui.reverse_fast_lateral_flexion_button,
                self.ui.reset_lateral_flexion_button, self.ui.lateral_flexion_position_go_button,
                
                # horizontal
                self.ui.forward_horizontal_flexion_button, self.ui.reverse_horizontal_flexion_button,
                self.ui.forward_fast_horizontal_flexion_button, self.ui.reverse_fast_horizontal_flexion_button,
                self.ui.reset_horizontal_flexion_button, self.ui.horizontal_flexion_position_go_button,
                
                self.ui.reset_arduino_main_button, self.ui.reset_arduino_setup_button,
            ]

            # Initialize actuator controls and connect signals
            self.setup_actuator_controls()
            print("UI elements setup completed successfully")

        except Exception as e:
            print(f"UI setup failed: {str(e)}")
            raise

    def disable_actuator_controls(self):
        for w in self.actuator_controls:
            w.setEnabled(False)

    def enable_actuator_controls(self):
        if self.protocol_running == False:
            print("Scheduling controls to enable with delay...") # Add for debugging
            for w in self.actuator_controls:
                # Use a default argument to capture the current value of 'w'
                QTimer.singleShot(200, lambda widget=w: widget.setEnabled(True))

    def connect_buttons_and_labels(self):
        """Connect signals and slots for all UI elements."""
        print("Connecting UI element signals")
        try:
            # Navigation connections
            if self.ui.setup_button:
                self.ui.setup_button.clicked.connect(self.show_setup_page)
            if self.ui.protocols_button:
                self.ui.protocols_button.clicked.connect(self.show_main_page)
            if self.ui.help_button:
                self.ui.help_button.clicked.connect(self.show_help_page)
            if self.ui.login_button:
                self.ui.login_button.clicked.connect(self.show_login_dialog)

            # Protocol control connections
            if self.ui.start_button:
                self.ui.start_button.clicked.connect(self.start_or_stop_protocol)

            # Profile and navigation connections
            if self.ui.profile_button:
                self.ui.profile_button.mousePressEvent = self.show_profile_page
            if self.ui.video_player_button:
                self.ui.video_player_button.mousePressEvent = (
                    self.show_video_player_dialog
                )
            if self.ui.brand_label:
                self.ui.brand_label.mousePressEvent = self.return_to_home_page
            if self.ui.brand_logo:
                self.ui.brand_logo.mousePressEvent = self.return_to_home_page
            if self.ui.exit_app_button:
                self.ui.exit_app_button.mousePressEvent = lambda event: self.exit_app()
            if self.ui.request_assistance_button:
                self.ui.request_assistance_button.mousePressEvent = (
                    lambda event: self.handle_assistance_request()
                )

            # System control connections
            if self.ui.set_up_tolerance_button:
                self.ui.set_up_tolerance_button.clicked.connect(
                    self.show_tolerance_dialog
                )
            if self.ui.show_timer_button:
                self.ui.show_timer_button.stateChanged.connect(self.show_timer_dialog)
            if self.ui.show_pressure_button:
                print("Connecting show_pressure_button")
                self.ui.show_pressure_button.stateChanged.connect(
                    self.show_pressure_dialog
                )
            if self.ui.reset_arduino_main_button:
                self.ui.reset_arduino_main_button.clicked.connect(self.reset_arduino)
            if self.ui.reset_arduino_setup_button:
                self.ui.reset_arduino_setup_button.clicked.connect(self.reset_arduino)

            # Protocol image navigation
            self.current_image_number = 1
            self.update_protocol_image()
            if self.forward_button_protocol_image:
                self.forward_button_protocol_image.mousePressEvent = (
                    self.show_next_protocol_image
                )
            if self.backward_button_protocol_image:
                self.backward_button_protocol_image.mousePressEvent = (
                    self.show_previous_protocol_image
                )

            print("Signal connections completed successfully")
            print("UI element signals connected")

        except Exception as e:
            print(f"Error connecting signals: {str(e)}")
            print(f"Signal connection failed: {str(e)}")
            raise

    def reset_setup_readings(self):
        """Reset setup readings to default values."""
        self.ui.axial_flexion_position_label.setText("0 in")
        self.ui.axial_flexion_position_label_2.setText("0 in")
        self.ui.lateral_flexion_position_label.setText("0°")
        self.ui.axial_flexion_pressure_label.setText("0 lbs")
        self.ui.horizontal_flexion_position_label.setText("-10°")

    def setup_protocol_controls(self):
        """Initialize protocol control GUI elements with preset values."""
        try:
            # Pulse control checkbox - single checkbox now
            self.ui.use_pulse_button = self.findChild(QtWidgets.QCheckBox, "checkbox_use_pulse")
            if self.ui.use_pulse_button:
                self.ui.use_pulse_button.setChecked(True)  # Default to use pulse
                self.ui.use_pulse_button.stateChanged.connect(self._on_pulse_toggled)
            # Slider controls
            self.max_pressure_edit = self.findChild(QtWidgets.QSlider, "max_pressure_edit")
            self.max_left_edit = self.findChild(QtWidgets.QSlider, "max_left_edit")
            self.max_right_edit = self.findChild(QtWidgets.QSlider, "max_right_edit")

            # Initialize sliders with default values
            if self.max_pressure_edit:
                self.max_pressure_edit.setRange(0, 80)
                self.max_pressure_edit.setSingleStep(5)
                self.max_pressure_edit.setValue(40)  # Default 40 lbs
                self.max_pressure_edit.valueChanged.connect(self.on_pressure_changed)

            if self.max_left_edit:
                self.max_left_edit.setRange(0, 20)
                self.max_left_edit.setSingleStep(5)
                self.max_left_edit.setValue(10)  # Default 10 degrees
                self.max_left_edit.valueChanged.connect(self.on_left_angle_changed)

            if self.max_right_edit:
                self.max_right_edit.setRange(0, 20)
                self.max_right_edit.setSingleStep(5)
                self.max_right_edit.setValue(10)  # Default 10 degrees
                self.max_right_edit.valueChanged.connect(self.on_right_angle_changed)

            # Time display (LCD)
            self.time_edit = self.findChild(QtWidgets.QLCDNumber, "time_edit")
            if self.time_edit:
                self.time_edit.display(12)  # Default 12 minutes

            self.decrease_time = self.findChild(QtWidgets.QLabel, "decrease_time")
            self.increase_time = self.findChild(QtWidgets.QLabel, "increase_time")

            if self.decrease_time and self.increase_time:
                self.decrease_time.mousePressEvent = self.decrease_time_value
                self.increase_time.mousePressEvent = self.increase_time_value

            print("Protocol controls setup completed successfully")

        except Exception as e:
            print(f"Failed to setup protocol controls: {str(e)}")
            self._show_timed_error(
             f"Failed to initialize protocol controls: {str(e)}"
            )

    def on_pressure_changed(self, value):
        """Handle pressure slider value changes."""
        if not self._confirm_mid_protocol_change():
            self.max_pressure_edit.blockSignals(True)
            self.max_pressure_edit.setValue(self._prev_pressure)
            self.max_pressure_edit.blockSignals(False)
            return
        self._prev_pressure = value          
        self.max_pressure = value
        if self.worker:
            self.worker.max_pressure = value
            print(f"Mid-protocol: Worker max_pressure updated to {value}")

    def on_left_angle_changed(self, value):
        """Handle left angle slider value changes."""
        if not self._confirm_mid_protocol_change():
            self.max_left_edit.blockSignals(True)
            self.max_left_edit.setValue(self._prev_left)
            self.max_left_edit.blockSignals(False)
            return
        self._prev_left = value         
        self.max_left_angle = value
        if self.worker:
            actual_left = -abs(value) # Ensure negative
            self.worker.max_left = actual_left
            print(f"Mid-protocol: Worker max_left_angle updated to {value}")

    def on_right_angle_changed(self, value):
        """Handle right angle slider value changes."""
        if not self._confirm_mid_protocol_change():
            self.max_right_edit.blockSignals(True)
            self.max_right_edit.setValue(self._prev_right)
            self.max_right_edit.blockSignals(False)
            return
        self._prev_right = value         
        self.max_right_angle = value
        if self.worker:
            actual_right = abs(value) # Ensure positive
            self.worker.max_right = actual_right
            print(f"Mid-protocol: Worker max_right_angle updated to {value}")

    def _on_pulse_toggled(self, state):
        if not self._confirm_mid_protocol_change():
            self.ui.use_pulse_button.blockSignals(True)
            self.ui.use_pulse_button.setChecked(not bool(state))
            self.ui.use_pulse_button.blockSignals(False)
            return
        current_state = bool(state)
        if self.current_use_pulse_setting:
            self.current_use_pulse_setting = (
                current_state  # Update KneeSpa's state tracker
            )
        if self.worker:
            self.worker.use_pulse = current_state # Update worker with correct attribute name and value
            print(f"Mid-protocol: Worker use_pulse updated to {current_state}")

    def decrease_time_value(self, event):
        """Decrease protocol time."""
        current_value = int(self.time_edit.value())
        if current_value > 1:
            self.time_edit.display(current_value - 1)

    def increase_time_value(self, event):
        """Increase protocol time."""
        current_value = int(self.time_edit.value())
        if current_value < 60:
            self.time_edit.display(current_value + 1)

    def setup_dialogs(self):
        """Initialize dialogs."""
        print("Setting up dialogs")
        self.ui.login_dialog = None
        self.init_login_dialog()
        self.ui.video_player_dialog = None

    def setup_timers(self):
        """Setup timers for protocol event"""
        print("Setting up timers for protocol events")
        self.protocol_timer = QTimer(self)
        self.protocol_timer.timeout.connect(self.update_protocol_time)

    def show_timer_dialog(self, state):
        """Show/hide timer dialog during protocol execution."""
        if state == Qt.Checked:
            if not self.timer_dialog.isVisible():
                # Position dialog in the top-right corner of the main window
                dialog_x = self.x() + self.width() - self.timer_dialog.width() - 20
                dialog_y = self.y() + 100
                self.timer_dialog.move(dialog_x, dialog_y)

                # Initialize timer if protocol is running
                if self.protocol_start_time and self.protocol_duration:
                    self.timer_dialog.initialize_protocol_time(
                        self.protocol_start_time, self.protocol_duration
                    )

                self.timer_dialog.show()

                # Start timer if protocol is running
                if self.protocol_start_time:
                    self.protocol_timer.start(1000)

        else:
            self.timer_dialog.hide()
            if self.protocol_timer.isActive():
                self.protocol_timer.stop()

    def emergency_stop_clicked(self, event):
        """Handle emergency stop button press."""
        print("Emergency stop triggered")
        self.stop_actuators()
        time.sleep(1)
        if self.worker:
            self.worker.stop()
        time.sleep(1)
        self.reset_arduino()

    def start_or_stop_protocol(self):
        """Start or stop the protocol with debouncing to prevent multiple rapid clicks."""
        print("Toggling protocol start/stop")

        # Prevent rapid clicking by disabling the button during operation
        self.start_button.setEnabled(False)

        try:
            if self.start_button.text() == "Start":
                self.start_button.setText("Stop")
                self.start_button.setStyleSheet(BUTTON_STYLES["STOP"])
                self.ensure_arduino_connection()
                self.start_protocol()
            else:
                self.start_button.setText("Stop")
                self.start_button.setStyleSheet(BUTTON_STYLES["STOP"])
                self.stop_protocol()
        except Exception as e:
            print(f"Error during protocol operation: {e}")
            # Reset the button state in case of error
            self.start_button.setText("Start")
            self.start_button.setStyleSheet(BUTTON_STYLES["START"])

    def show_login_dialog(self):
        """Show the login dialog."""
        print("Showing login dialog")
        self.login_pin = ""
        self.login_dialog.exec_()

    def init_login_dialog(self):
        """Initialize the login dialog."""
        print("Initializing login dialog")
        self.login_dialog = QtWidgets.QDialog(self)
        uic.loadUi(UI_PATHS["LOGIN_UI"], self.login_dialog)
        self.login_dialog.adjustSize()

        # Find key UI elements
        self.login_line_edit = self.login_dialog.findChild(
            QtWidgets.QLineEdit, "login_line_edit"
        )
        self.login_help_button = self.login_dialog.findChild(
            QtWidgets.QPushButton, "login_help_button"
        )
        self.login_enter_button = self.login_dialog.findChild(
            QtWidgets.QPushButton, "enter_password_button"
        )
        self.clear_login_pin_button = self.login_dialog.findChild(
            QtWidgets.QPushButton, "clear_login_pin_button"
        )

        # Connect action buttons
        self.login_enter_button.clicked.connect(self.handle_login)
        self.login_help_button.clicked.connect(self.show_login_help_dialog)
        self.clear_login_pin_button.clicked.connect(self.clear_login_line_edit)

        # Connect numeric keypad buttons (0-9)
        self.login_pin = ""  # Initialize PIN storage
        for i in range(10):
            button_name = f"pushButton_{i}"
            button = self.login_dialog.findChild(QtWidgets.QPushButton, button_name)
            if button:
                # Use lambda with default argument to capture current value of i
                button.clicked.connect(
                    lambda checked, num=str(i): self.append_login_star(num)
                )

    def append_login_star(self, value):
        """Append star to login input field."""
        print(f"Appending value {value} to login input")
        if self.login_line_edit:
            current_text = self.login_line_edit.text()
            self.login_line_edit.setText(current_text + "*")
            self.login_pin += value

    def clear_login_line_edit(self):
        """Clear the login input field."""
        print("Clearing login input field")
        self.login_line_edit.clear()
        self.login_pin = ""

    def show_login_help_dialog(self):
        """Show login help dialog."""
        print("Showing login help dialog")
        help_dialog = QtWidgets.QDialog(self)
        uic.loadUi(UI_PATHS["LOGIN_HELP_UI"], help_dialog)
        help_dialog.exec_()

    def handle_assistance_request(self):
        """Handle request assistance button click and email admin"""
        print(f"Handle assistance method called")
        self.username = self.ui.username_profile.text()
        self.user_email = self.ui.email_profile.text()
        self.user_status = self.ui.status_profile.text()

        # Call the function from email.py
        self.email_admin()

    def email_admin(self):
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

        try:
            with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                server.login(sender_email, sender_password)
                server.sendmail(sender_email, receiver_email, message.as_string())
            print("Assistance request email sent successfully.")
        except Exception as e:
            print(f"Failed to send assistance email: {e}")

    def handle_login(self):
        """Sequence events to handle login event"""
        print("Handling login")
        if self.login_pin in self.users:
            print(f"Login successful for PIN: {self.login_pin}")
            self.current_user = self.users[self.login_pin]
            self.login_pin = ""
            self.update_ui_after_login()
            self.login_dialog.accept()
            self.clear_login_line_edit()
        else:
            print("Login failed: Invalid PIN")
            self._show_timed_error("Invalid PIN. Please try again.")
            self.clear_login_line_edit()

    def update_ui_after_login(self):
        """Update user interface with user details after login"""
        print("Updating UI after login")
        # self.ui.username_nav.setText(self.current_user["username"])
        self.ui.username_profile.setText(self.current_user["username"])
        self.ui.email_profile.setText(self.current_user["email"])
        self.ui.status_profile.setText(self.current_user["status"])
        self.ui.login_button.setText("Logout")
        self.ui.login_button.clicked.disconnect()
        self.ui.login_button.clicked.connect(self.handle_logout)

        if self.current_user["status"] == "admin":
            print("Admin user logged in: Enabling admin features")
            self.ui.protocols_button.setEnabled(True)
        elif self.current_user["status"] == "user":
            print("Standard user logged in: Disabling admin features")
            self.ui.protocols_button.setEnabled(True)
        else:
            print("Unknown user status: Disabling protocol and edit features")
            self.ui.protocols_button.setEnabled(False)

    def handle_logout(self):
        """Handle user logout"""
        print("Handling logout")
        self.current_user = None
        self.ui.username_nav.setText("")
        self.ui.username_profile.setText("")
        self.ui.email_profile.setText("")
        self.ui.status_profile.setText("")
        self.ui.login_button.setText("Login")
        self.ui.login_button.clicked.disconnect()
        self.ui.login_button.clicked.connect(self.show_login_dialog)

        self.ui.protocols_button.setEnabled(False)

        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def show_home_page(self):
        """Show the home page."""
        print("Showing home page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def return_to_home_page(self, event):
        """Return to the home page."""
        print("Returning to home page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def show_setup_page(self):
        """Show the setup page."""

        if not self.current_user:
            print("Access denied: User not logged in")
            self._show_timed_error("Please log in to proceed.")
            return

        print("Showing setup page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.setup_page
        )
        if self.ui.findChild(QtWidgets.QTabWidget, "setup_tabs"):
            self.ui.findChild(QtWidgets.QTabWidget, "setup_tabs").setCurrentIndex(0)

    def show_main_page(self):
        """Show the main page."""

        if not self.current_user:
            print("Access denied: User not logged in")
            self._show_timed_error(
                "Please log in to start a protocol."
            )
            return

        print("Showing main page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.main_page
        )
        if self.ui.findChild(QtWidgets.QTabWidget, "DRx_tabs"):
            self.ui.findChild(QtWidgets.QTabWidget, "DRx_tabs").setCurrentIndex(0)

    def show_help_page(self):
        """Show the help page."""
        print("Showing help page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.help_page
        )

    def show_profile_page(self, event):
        """Show the profile page."""
        print("Showing profile page")
        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.profile_page
        )

    def show_video_player_dialog(self, event):
        """Show the video player dialog."""
        print("Showing video player dialog")
        # Always create a new instance
        if self.video_player_dialog:
            self.video_player_dialog.deleteLater()
        self.video_player_dialog = VideoPlayer(self)
        self.video_player_dialog.show()

    def update_protocol_image(self):
        """Update the displayed protocol image."""
        print(f"Updating protocol image to number {self.current_image_number}")
        image_path = f"{UI_PATHS['PROTOCOL_IMAGES']}/{self.current_image_number}.png"
        self.label_protocol_image.setPixmap(QPixmap(image_path))
        self.protocol_image_number.setText(str(self.current_image_number))

    def show_next_protocol_image(self, event):
        """Show the next protocol image."""
        print("Showing next protocol image")
        if self.current_image_number < 4:
            self.current_image_number += 1
            self.update_protocol_image()

    def show_previous_protocol_image(self, event):
        """Show the previous protocol image."""
        print("Showing previous protocol image")
        if self.current_image_number > 1:
            self.current_image_number -= 1
            self.update_protocol_image()

    ### Backend Methods ###

    def setup_actuator_controls(self):
        """Initialize actuator control buttons and sliders."""

        print("Setting up actuator controls...")
        # Initialize actuator positions
        self.axial_position = DEFAULT_AXIAL_POSITION  # inches
        self.lateral_position = DEFAULT_LATERAL_POSITION  # degrees
        self.horizontal_position = DEFAULT_HORIZONTAL_POSITION  # degrees
        self.current_pressure = DEFAULT_PRESSURE  # pounds
        self.leg_length = DEFAULT_LEG_LENGTH_POSITION
        self.LEG_LENGTH_MIN = LEG_LENGTH_MIN
        self.LEG_LENGTH_MAX = LEG_LENGTH_MAX
        self.LEG_LENGTH_SPEED_NORMAL = LEG_LENGTH_SPEED_NORMAL
        self.LEG_LENGTH_SPEED_FAST = LEG_LENGTH_SPEED_FAST

        # Connect axial flexion controls
        self.ui.forward_extra_button.clicked.connect(self.forward_button_clicked)
        self.ui.reverse_extra_button.clicked.connect(self.reverse_button_clicked)
        self.ui.forward_fast_extra_button.clicked.connect(
            self.forward_fast_button_clicked
        )
        self.ui.reverse_fast_extra_button.clicked.connect(
            self.reverse_fast_button_clicked
        )
        self.ui.reset_extra_button.clicked.connect(self.reset_extra_button_clicked)
        self.axial_flexion_position = 0
        self.horizontal_flexion_position = -10
        self.lateral_flexion_position = 0
        self.ui.axial_flexion_position_slider.setSingleStep(
            5
        )  # 5 represents 2.5 degrees
        self.ui.axial_flexion_position_slider.setPageStep(10)
        self.ui.lateral_flexion_position_slider.setSingleStep(
            5
        )  # 5 represents 2.5 degrees
        self.ui.lateral_flexion_position_slider.setPageStep(10)
        self.ui.horizontal_flexion_position_slider.setSingleStep(
            5
        )  # 5 represents 2.5 degrees
        self.ui.horizontal_flexion_position_slider.setPageStep(10)

        self.ui.forward_axial_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_a, 0.065, "04", 1)
        )
        self.ui.reverse_axial_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_a, 0.065, "04", -1)
        )
        self.ui.forward_fast_axial_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_a, 0.065, "20", 1)
        )
        self.ui.reverse_fast_axial_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_a, 0.065, "20", -1)
        )
        self.ui.reset_axial_flexion_button.clicked.connect(
            lambda: self.reset_flexion_button_clicked(self.actuator_a)
        )
        self.ui.reset_lateral_flexion_button.clicked.connect(
            lambda: self.reset_flexion_button_clicked(self.actuator_c)
        )
        self.ui.reset_horizontal_flexion_button.clicked.connect(
            lambda: self.reset_flexion_button_clicked(self.actuator_b)
        )

        # Connection axial controls
        self.ui.axial_flexion_position_go_button.clicked.connect(
            lambda: self.move_position_flexion_button(self.actuator_a)
        )
        self.ui.axial_flexion_position_stop_button.clicked.connect(
            lambda: self.stop_position_flexion_button(self.actuator_a)
        )
        self.ui.axial_flexion_pressure_go_button.clicked.connect(
            self.axial_flexion_pressure_go_button_clicked
        )
        self.ui.axial_flexion_pressure_stop_button.clicked.connect(
            lambda: self.stop_position_flexion_button(self.actuator_a)
        )
        self.ui.lateral_flexion_position_go_button.clicked.connect(
            lambda: self.move_position_flexion_button(self.actuator_c)
        )
        self.ui.lateral_flexion_position_stop_button.clicked.connect(
            lambda: self.stop_position_flexion_button(self.actuator_a)
        )
        self.ui.horizontal_flexion_position_go_button.clicked.connect(
            lambda: self.move_position_flexion_button(self.actuator_b)
        )
        self.ui.horizontal_flexion_position_stop_button.clicked.connect(
            lambda: self.stop_position_flexion_button(self.actuator_b)
        )

        # Connect lateral flexion controls
        self.ui.forward_lateral_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_c, 5, "04", 1)  # slow speed
        )
        self.ui.reverse_lateral_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_c, 5, "04", -1)  # slow speed
        )
        self.ui.forward_fast_lateral_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_c, 10, "20", 1)  # fast speed
        )
        self.ui.reverse_fast_lateral_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_c, 10, "20", -1)  # fast speed
        )

        # Connect horizontal flexion controls
        self.ui.forward_horizontal_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_b, 5, "04", 1)  # slow speed
        )
        self.ui.reverse_horizontal_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_b, 5, "04", -1)  # slow speed
        )
        self.ui.forward_fast_horizontal_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_b, 10, "20", 1)  # fast speed
        )
        self.ui.reverse_fast_horizontal_flexion_button.clicked.connect(
            lambda: self.move_actuator(self.actuator_b, 10, "20", -1)  # fast speed
        )

        # Connect position sliders
        self.ui.axial_flexion_position_slider.valueChanged.connect(
            self.axial_flexion_position_changed
        )
        self.ui.lateral_flexion_position_slider.valueChanged.connect(
            self.lateral_flexion_position_changed
        )
        self.ui.horizontal_flexion_position_slider.valueChanged.connect(
            self.horizontal_flexion_position_changed
        )
        self.ui.axial_flexion_pressure_slider.valueChanged.connect(
            self.axial_flexion_pressure_changed
        )

        # Update pressure display from slider
        self.ui.axial_flexion_pressure_slider.valueChanged.connect(
            self.update_pressure_display
        )

        # Emergency stop
        self.ui.emergency_stop_setup_label.mousePressEvent = self.emergency_stop_clicked

        print("Actuator controls setup complete")

    def handle_connection_failed(self, message):
        """Handle failure to connect to Arduino."""
        print(message)
        self._show_timed_error(message)

    def cleanup(self):
        """Clean up resources, including VideoPlayer and GPIO."""
        print("Cleaning up resources.")

        if self.worker:
            self.worker.stop()

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
        Move an actuator in the specified direction
        """
        print(f"Speed factor: {speed_factor}")
        if actuator == self.actuator_b:  # Horizontal Flexion
            step = 10 if int(speed_factor) > 4 else 5
            new_position = self.horizontal_flexion_position + (step * direction)

            # Check position limits
            if direction >= 0 and new_position > -5:
                return
            if direction < 0 and new_position < -25:
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            self.horizontal_flexion_position = new_position
            print(f"B position: {self.horizontal_flexion_position}")

            # Update UI
            self.ui.horizontal_flexion_position_slider.setValue(
                self.horizontal_flexion_position
            )
            self.ui.horizontal_flexion_position_label.setText(
                f"{self.horizontal_flexion_position}{DEGREES}"
            )

            # Convert degrees to inches like the slider does
            inches = abs((self.horizontal_flexion_position + 25) / 5)

            # Use the same command format as the slider/go button
            command = f"A{actuator}{inches}"
            self.arduino.send(command)

            self.loading_spinner.hide()

        elif actuator == self.actuator_a:  # Axial Flexion
            from config.constants import ACTUATORS

            axial_max = ACTUATORS["AXIAL"]["LIMITS"][1]  # Should be 4 inches
            axial_min = ACTUATORS["AXIAL"]["LIMITS"][0]  # Should be 0 inches

            step = 1 if int(speed_factor) > 4 else 0.5
            new_position = self.axial_flexion_position + (step * direction)

            # Check position limits - Use correct safety limits
            if direction > 0 and new_position > axial_max:
                self.logger.warning(f"Axial position {new_position} exceeds max {axial_max} inches")
                self._show_timed_error(f"Axial position limited to {axial_max} inches for safety")
                return
            if direction < 0 and new_position < axial_min:
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            self.axial_flexion_position = new_position
            print(f"A position: {self.axial_flexion_position}")

            # Update UI
            self.ui.axial_flexion_position_slider.setValue(
                self.axial_flexion_position * 2
            )
            self.ui.axial_flexion_position_label.setText(
                f"{self.axial_flexion_position} in"
            )

            # Send command to Arduino
            command = f"A12{self.axial_flexion_position}"
            self.arduino.send(command)
            print("Axial flexion position", self.axial_flexion_position)

            if direction > 0:  # Only for forward movement
                time.sleep(0.3)
                self.arduino.send("L5")

            self.loading_spinner.hide()

        elif actuator == self.actuator_c:  # Lateral Flexion
            step = 5 if int(speed_factor) > 4 else 2.5  # Use 2.5 degree increments
            new_position = self.lateral_flexion_position + (step * direction)

            # Round to nearest 2.5 degree increment
            new_position = round(new_position / 2.5) * 2.5

            # Check position limits using constants for safety
            from config.constants import ACTUATORS

            lateral_max = ACTUATORS["LATERAL"]["LIMITS"][1]  # Should be 20
            lateral_min = ACTUATORS["LATERAL"]["LIMITS"][0]  # Should be -20

            if direction > 0 and new_position > lateral_max:
                self.logger.warning(f"Lateral position {new_position} exceeds max {lateral_max}")
                self._show_timed_error(f"Lateral position limited to {lateral_max}° for safety")
                return
            if direction < 0 and new_position < lateral_min:
                self.logger.warning(f"Lateral position {new_position} below min {lateral_min}")
                self._show_timed_error(f"Lateral position limited to {lateral_min}° for safety")
                return

            self.loading_spinner.show()
            self.disable_actuator_controls()

            # Ensure the position exists in CMarks
            position_key = f"{new_position:.1f}"
            if position_key not in self.config.CMarks:
                print(f"Invalid position {position_key}, skipping movement")
                return

            self.lateral_flexion_position = new_position

            position = self.config.CMarks[position_key]

            print(
                f" positioned to {self.lateral_flexion_position} degrees pos {position}"
            )

            # Update UI
            left_right = (
                "R"
                if self.lateral_flexion_position > 0
                else "L" if self.lateral_flexion_position < 0 else ""
            )
            self.ui.lateral_flexion_position_slider.setValue(
                self.lateral_flexion_position
            )
            self.ui.lateral_flexion_position_label.setText(
                f"{abs(self.lateral_flexion_position)}{left_right}{DEGREES}"
            )

            # Send command to Arduino
            command = f"K{position}"
            self.arduino.send(command)

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
            self.ui.lateral_flexion_position_label.setText(
                str(round(self.lateral_flexion_position, 2))
            )
            self.ui.lateral_flexion_position_slider.setValue(0)
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_b:
            command = f"A{actuator}2"
            self.arduino.send(command)  # transmit data serially
            self.horizontal_flexion_position = -10
            self.ui.horizontal_flexion_position_label.setText(
                str(round(self.horizontal_flexion_position, 2))
            )
            self.ui.horizontal_flexion_position_slider.setValue(
                self.horizontal_flexion_position
            )
            self.loading_spinner.hide()

            return

        if actuator == self.actuator_a:
            command = f"R{actuator}"
            self.arduino.send(command)  # transmit data serially
            self.axial_flexion_position = 0
            self.ui.axial_flexion_position_label.setText(
                str(round(self.axial_flexion_position, 2))
            )
            self.ui.axial_flexion_position_slider.setValue(0)
            self.ui.axial_flexion_pressure_slider.setValue(0)
            self.ui.axial_flexion_pressure_label.setText("0 lb")
            time.sleep(5)
            self.send_calibration()
            self.loading_spinner.hide()

            return

    def move_position_flexion_button(self, actuator):
        """Handle movement based on slider position for different actuators."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        try:
            if actuator == self.actuator_b:  # Horizontal
                horizontal_degrees = self.ui.horizontal_flexion_position_slider.value()
                inches = abs((horizontal_degrees + 25) / 5)
                self.set_to_distance(inches, actuator, self.config.b_factor)
                self.horizontal_flexion_position = horizontal_degrees
                self.loading_spinner.hide()

            elif actuator == self.actuator_a:  # Axial
                inches = self.ui.axial_flexion_position_slider.value() / 2.0
                self.set_to_distance(inches, actuator, self.config.a_factor)
                self.axial_flexion_position = inches
                self.loading_spinner.hide()

            elif actuator == self.actuator_c:  # Lateral
                degrees = self.ui.lateral_flexion_position_slider.value()
                # Ensure degrees are within valid range
                degrees = max(-20.0, min(20.0, degrees))
                self.set_to_c_distance(degrees)
                self.lateral_flexion_position = degrees
                self.loading_spinner.hide()

        except Exception as e:
            print(f"Error in move_position_flexion_button: {str(e)}")
            self._show_timed_error(
                 f"Error moving actuator: {str(e)}"
            )
            self.loading_spinner.hide()

    def adjust_pressure(self, target_pressure):
        """Adjust axial pressure to target value with safety validation."""
        from config.constants import PRESSURE_MAX, PROTOCOL_DEFAULT_SETTINGS

        print(f"Adjusting pressure to {target_pressure} lbs")
        self.loading_spinner.show()
        self.disable_actuator_controls()

        # CRITICAL SAFETY VALIDATION
        min_pressure = PROTOCOL_DEFAULT_SETTINGS.get("MIN_PRESSURE", 0)
        original_target = target_pressure

        if target_pressure > PRESSURE_MAX:
            self.logger.warning(f"Pressure {target_pressure} exceeds max {PRESSURE_MAX}, clamping")
            target_pressure = PRESSURE_MAX
            self._show_timed_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
        elif target_pressure < 0:
            self.logger.warning(f"Negative pressure {target_pressure} requested, setting to 0")
            target_pressure = 0

        try:
            self.ui.axial_flexion_pressure_label.setText(f"{target_pressure} lb")
            self.ui.axial_flexion_pressure_slider.setValue(target_pressure)  # Update slider too
            self.arduino.send(f"P{target_pressure}")
            self.current_pressure = target_pressure

            if original_target != target_pressure:
                print(f"Pressure adjusted from {original_target} to {target_pressure} lbs (safety limited)")
            else:
                print(f"Pressure adjusted to {target_pressure} lbs")

            self.loading_spinner.hide()

        except Exception as e:
            print(f"Error adjusting pressure: {str(e)}")
            self.logger.error(f"Pressure adjustment failed: {str(e)}")
            self.stop_pressure_adjustment()
            self.loading_spinner.hide()

    def update_pressure_display(self, value):
        """Update pressure display when slider moves."""
        self.ui.axial_flexion_pressure_label.setText(f"{value} lb")

    def stop_actuators(self):
        """Emergency stop for all actuators."""
        print("Emergency stop triggered")
        try:
            self.arduino.send("X")  # Stop all movement
        except Exception as e:
            print(f"Error in emergency stop: {str(e)}")
            print(f"Emergency stop failed: {str(e)}")

    def stop_pressure_adjustment(self):
        """Stop pressure adjustment."""
        print("Stopping pressure adjustment")
        try:
            time.sleep(0.1)
            self.arduino.send("X")  # Stop pressure adjustment
            print("Pressure adjustment stopped")
        except Exception as e:
            print(f"Error stopping pressure adjustment: {str(e)}")
            print(f"Pressure stop failed: {str(e)}")

    def stop_position_flexion_button(self, actuator):
        self.arduino.send("X{}".format(actuator))

    def update_leg_position(self, direction, fast=False):
        """
        Update leg length position tracking.

        Args:
            direction: 1 for forward, -1 for reverse
            fast: True for fast movement speed
        """
        try:
            speed = 1 if fast else 0.5  # inches per second
            delta = direction * (speed * 0.1)  # 0.1 seconds per update
            new_position = self.leg_length + delta

            # Enforce limits (0 to 6 inches)
            if 0 <= new_position <= 6:
                self.leg_length = new_position
                self.ui.axial_flexion_position_label_2.setText(
                    f"{self.leg_length:.1f} in"
                )
            else:
                # Stop movement if limit reached
                self.stop_leg_movement()
                print(f"Leg length limit reached: {new_position}")
        except Exception as e:
            print(f"Error updating leg position: {str(e)}")
            self.stop_leg_movement()

    def forward_button_clicked(self):
        """Handle forward button press - normal speed."""

        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F+")
        GPIO.output(EXTRAFORWARD, GPIO.HIGH)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

        if self.leg_length >= self.LEG_LENGTH_MAX:
            return  # Already at max
        # Update display
        self.leg_length += 0.25  # Move 0.5 inches per press
        self.leg_length = min(self.leg_length, self.LEG_LENGTH_MAX)  # Don't exceed max
        self.ui.axial_flexion_position_label_2.setText(f"{self.leg_length:.1f} in")
        self.loading_spinner.hide()

    def reverse_button_clicked(self):
        """Handle reverse button press - normal speed."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F-")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH)

        if self.leg_length <= 0:
            return  # Already at min

        # Update display
        self.leg_length -= 0.25  # Move 0.5 inches per press
        self.leg_length = max(0, self.leg_length)  # Don't go below 0
        self.ui.axial_flexion_position_label_2.setText(f"{self.leg_length:.1f} in")
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

        # Update display
        self.leg_length += 3.0  # Move 1.0 inches per press
        self.leg_length = min(self.leg_length, self.LEG_LENGTH_MAX)  # Don't exceed max
        self.ui.axial_flexion_position_label_2.setText(f"{self.leg_length:.1f} in")
        self.loading_spinner.hide()

    def reverse_fast_button_clicked(self):
        """Handle reverse button press - fast speed."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("FR")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.HIGH)

        if self.leg_length >= 3:
            # Update displays
            self.leg_length = 0
            self.ui.axial_flexion_position_label_2.setText(f"{self.leg_length:.1f} in")
        else:
            self.leg_length -= 3.0  # Move 1.0 inches per press
            self.leg_length = max(0, self.leg_length)  # Don't go below 0

        self.loading_spinner.hide()

    def reset_extra_button_clicked(self):
        """Reset leg length position."""
        self.loading_spinner.show()
        self.disable_actuator_controls()
        self.arduino.send("F0")
        GPIO.output(EXTRAFORWARD, GPIO.LOW)
        GPIO.output(EXTRABACKWARD, GPIO.LOW)

        QTimer.singleShot(3000, self.reverse_fast_button_clicked)

        self.leg_length = 0.0
        self.ui.axial_flexion_position_label_2.setText("0.0 in")
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

    def axial_flexion_position_changed(self):
        inches = self.ui.axial_flexion_position_slider.value() / 2.0
        self.ui.axial_flexion_position_label.setText(str(inches) + " in")

    def axial_flexion_pressure_changed(self):
        pounds = self.ui.axial_flexion_pressure_slider.value()
        self.ui.axial_flexion_pressure_label.setText(str(pounds) + " lb")

    def axial_flexion_pressure_go_button_clicked(self):
        from config.constants import PRESSURE_MAX, PROTOCOL_DEFAULT_SETTINGS

        print("axial_flexion_pressure_go_button_clicked")
        self.loading_spinner.show()
        self.disable_actuator_controls()
        pressure = self.ui.axial_flexion_pressure_slider.value()
        print(f"Requested pressure: {pressure} lbs")

        # CRITICAL SAFETY CHECK - Prevent dangerous pressure levels
        min_pressure = PROTOCOL_DEFAULT_SETTINGS.get("MIN_PRESSURE", 0)
        if pressure > PRESSURE_MAX:
            original_pressure = pressure
            pressure = PRESSURE_MAX
            self.logger.warning(f"Pressure request {original_pressure} exceeds max {PRESSURE_MAX}, clamping")
            self._show_timed_error(f"Pressure limited to maximum {PRESSURE_MAX} lbs for safety")
            self.ui.axial_flexion_pressure_slider.setValue(pressure)  # Update UI to show clamped value
        elif pressure < min_pressure:
            pressure = min_pressure
            self.logger.warning(f"Pressure below minimum {min_pressure}, adjusting")
            self.ui.axial_flexion_pressure_slider.setValue(pressure)

        command = "P{}".format(pressure)
        self.arduino.send(command)
        print("Pressure cmd sent {}".format(command.strip()))
        self.loading_spinner.hide()

    def horizontal_flexion_position_changed(self):
        self.minus_horizontal_degrees = (
            self.ui.horizontal_flexion_position_slider.value()
        )
        if (self.minus_horizontal_degrees % 5) != 0:
            return
        self.ui.horizontal_flexion_position_label.setText(
            str(self.minus_horizontal_degrees) + "°"
        )

    def lateral_flexion_position_changed(self):
        self.minus_horizontal_degrees = self.ui.lateral_flexion_position_slider.value()
        if (self.minus_horizontal_degrees % 5) != 0:
            return
        self.ui.lateral_flexion_position_label.setText(
            str(self.minus_horizontal_degrees) + "°"
        )

    @QtCore.pyqtSlot()
    def set_done(self):
        """Set the I2C status to done."""
        print("Setting I2C status to done - signal received from Arduino")
        self.I2Cstatus = 1
        self.I2Cstatus_event.set()  # Signal the thread-safe event
        self.enable_actuator_controls()

    def ready_to_go(self):
        """Set the I2C status to ready."""
        print("Setting I2C status to ready")
        self.I2Cstatus = 1
        self.I2Cstatus_event.set()  # Signal the thread-safe event  

    def read_position(self, position, steps, actuator):
        """Read position data from the Arduino."""
        print(
            f"Reading position: position={position}, steps={steps}, actuator={actuator}"
        )

        # Safety check for calibration factors to prevent division by zero
        if hasattr(self, "actuator_b") and actuator == self.actuator_b:
            if self.config.b_factor == 0:
                self.logger.error("b_factor is 0, cannot calculate position")
                self._show_timed_error("Calibration error for actuator B - please recalibrate")
                return
            inches = (position * 6) / self.config.b_factor
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator B): {inches}")
            degrees = int(-(25 - (inches / 5) * 25))
            print(f"Degrees (actuator B): {degrees}")
        elif hasattr(self, "actuator_a") and actuator == self.actuator_a:
            if self.config.a_factor == 0:
                self.logger.error("a_factor is 0, cannot calculate position")
                self._show_timed_error("Calibration error for actuator A - please recalibrate")
                return
            inches = (position * 6) / self.config.a_factor
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator A): {inches}")
        elif hasattr(self, "actuator_c") and actuator == self.actuator_c:
            if self.config.c_factor == 0:
                self.logger.error("c_factor is 0, cannot calculate position")
                self._show_timed_error("Calibration error for actuator C - please recalibrate")
                return
            inches = steps / (self.config.c_factor / 6)
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator C): {inches}")
            degrees = int((inches * 20) - 20)
            print(f"Degrees (actuator C): {degrees}")

    def ensure_arduino_connection(self):
        """
        Ensure Arduino connection is reliable before starting a protocol.
        Performs thorough reset and reconnection if needed.
        
        Returns:
            bool: True if connection is established or restored, False otherwise
        """
        print("Verifying Arduino connection before protocol start...")

        # Check if Arduino is responsive
        if self.arduino and self.arduino.connected:
            # Send a test command to verify responsiveness
            if self.arduino.verify_connection():
                print("Arduino connection verified.")
                return True

        # If we reach here, connection needs reset
        print("Arduino connection needs reset, attempting reconnection...")

        # Forcefully disconnect current connection
        if hasattr(self, 'arduino') and self.arduino:
            self.arduino.disconnect()
            time.sleep(2)  # Allow time for port to release

        # Reset GPIO pins to safe state
        self.setup_gpio()

        time.sleep(5) 

        # Reinitialize Arduino connection
        connection_success = self.setup_arduino()

        if connection_success:
            print("Arduino successfully reset and reconnected.")

            # Send calibration commands after reconnection
            self.send_zero_mark()
            time.sleep(1)
            self.send_calibration()

            return True
        else:
            print("Failed to restore Arduino connection.")
            QtWidgets.self._show_timed_error(
                "Unable to establish reliable connection to Arduino. Please check connections and try again."
            )
            return False

    def start_protocol(self):
        """Start protocol execution."""
        if not self.current_user:
            print("Access denied: User not logged in")
            self._show_timed_error("Please login to proceed")
            return

        try:
            # Validate protocol number
            protocol = self.protocol_number_field.text()
            if protocol not in ["1", "2", "3", "4"]:
                raise ValueError(f"Invalid protocol number: {protocol}")

            # Get duration in minutes from time_edit
            duration = 12  # Default to 12 minutes
            if hasattr(self, "time_edit") and self.time_edit is not None:
                try:
                    duration = int(self.time_edit.value())
                except Exception as e:
                    print(f"Error getting time value: {e}, using default 5 minutes")

            if duration == 0:
                duration = 12  # Ensure we have a valid duration

            print(f"Protocol duration: {duration} minutes")
            self.protocol_duration = duration * 60  # Convert to seconds
            self.protocol_start_time = time.time()

            # Update timer dialog if visible
            if hasattr(self, "timer_dialog") and self.timer_dialog and self.timer_dialog.isVisible():
                self.timer_dialog.initialize_protocol_time(
                    self.protocol_start_time, self.protocol_duration
                )
                self.protocol_timer.start(1000)  # Update every second

            max_pressure = int(self.max_pressure_edit.value()) if self.max_pressure_edit else 50
            max_left_from_slider = int(self.max_left_edit.value()) if self.max_left_edit else 10
            max_right_from_slider = int(self.max_right_edit.value()) if self.max_right_edit else 10

            # The worker expects max_left to be negative
            max_left_for_worker = -abs(max_left_from_slider)
            max_right_for_worker = abs(max_right_from_slider)

            use_pulse = self.current_use_pulse_setting # Use the tracked state

            if self.ui.forward_button_protocol_image:
                self.ui.forward_button_protocol_image.setEnabled(False)
            else:
                print("Warning: Could not find forward_button_protocol_image to disable it.")

            if self.ui.backward_button_protocol_image:
                self.ui.backward_button_protocol_image.setEnabled(False)
            else:
                print("Warning: Could not find backward_button_protocol_image to disable it.")

            self.ui.reset_arduino_main_button.setEnabled(False)
            self.increase_time.setEnabled(False)
            self.decrease_time.setEnabled(False)

            self.mid_protocol_change_warning_shown = False
            # Update previous values before starting
            if self.max_pressure_edit: self.max_pressure_edit_previous_value = self.max_pressure_edit.value()
            if self.max_left_edit: self.max_left_edit_previous_value = self.max_left_edit.value()
            if self.max_right_edit: self.max_right_edit_previous_value = self.max_right_edit.value()
            # self.current_use_pulse_setting is already up-to-date via its handler

            # Update UI
            self.ui.start_button.setText("Stop")
            self.ui.start_button.setStyleSheet(BUTTON_STYLES["STOP"])

            self.set_to_c_distance(0)
            time.sleep(0.5)

            # Create and start protocol
            self.worker = protocols.Protocols(
                self.config.a_factor,
                protocol,
                max_pressure,
                max_left_for_worker,
                max_right_for_worker,
                duration,
                use_pulse,  # Just the boolean flag
                ser=self.arduino,
                config=self.config,
            )

            # Connect signals
            self.worker.signals.finished.connect(self.protocol_completed)

            # Connect pressure dialog regardless of visibility
            # We'll connect it now so it's ready when the checkbox is checked
            if hasattr(self, "pressure_dialog") and self.pressure_dialog:
                # Disconnect any existing connections to avoid duplicate signals
                try:
                    self.worker.signals.pressure_emit.disconnect(self.pressure_dialog.update_pressure)
                except Exception:
                    pass  # Ignore if not previously connected

                # Connect the pressure signal to the dialog's update method
                self.worker.signals.pressure_emit.connect(self.pressure_dialog.update_pressure)
                print("MAIN APP: Connected worker.signals.pressure_emit to pressure_dialog.update_pressure")

                # Also connect the Arduino's status directly as a backup connection
                if hasattr(self, "arduino") and self.arduino and hasattr(self.arduino, "status_emit"):
                    try:
                        self.arduino.status_emit.disconnect(self.pressure_dialog.update_pressure)
                    except Exception:
                        pass  # Ignore if not previously connected

                    # Create a direct connection from Arduino to pressure dialog
                    self.arduino.status_emit.connect(
                        lambda pos_a, pos_b, pos_c, pressure: self.pressure_dialog.update_pressure(pressure)
                    )
                    print("MAIN APP: Connected arduino.status_emit directly to pressure_dialog.update_pressure")

            self.protocol_running = True
            self.mid_protocol_warning_shown = False    

            time.sleep(0.5)
            self.start_button.setEnabled(True)

            # Start protocol execution
            self.threadpool.start(self.worker)

            # Start timers
            self.protocol_timer.start()
            QApplication.processEvents()
            self.elapsed_timer.start(1000)

            # Update status
            self.ui.status_label.setText("Protocol Started")

        except ValueError as e:
            print(f"Invalid parameter: {str(e)}")
            self._show_timed_error(f"Invalid Parameters: {str(e)}")
            return
        except Exception as e:
            print(f"Failed to start protocol: {str(e)}")
            import traceback
            traceback.print_exc()  # Print full stack trace
            self._show_timed_error(f"Protocol Error: {str(e)}")
            return

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

    def update_protocol_time(self):
        """Update the protocol timer display."""
        if not self.protocol_start_time:
            return

        elapsed_time = int(time.time() - self.protocol_start_time)
        remaining_time = max(0, self.protocol_duration - elapsed_time)

        if self.timer_dialog.isVisible():
            self.timer_dialog.update_time(remaining_time)

        if remaining_time == 0:
            self.protocol_timer.stop()
            self.protocol_start_time = None

    def protocol_completed(self):
        """Handle protocol completion."""
        print("Protocol completed")
        self.protocol_timer.stop()

        if self.worker:
            self.worker.stop()

        # Update UI
        self.ui.show_timer_button.setChecked(False)
        self.ui.show_pressure_button.setChecked(False)
        # self.ui.use_pulse_button.setChecked(False)
        self.ui.use_pulse_button.setEnabled(True)
        self.ui.forward_button_protocol_image.setEnabled(True)
        self.ui.backward_button_protocol_image.setEnabled(True)
        self.ui.reset_arduino_main_button.setEnabled(True)
        self.increase_time.setEnabled(True)
        self.decrease_time.setEnabled(True)

        # (optional) be sure the dialogs disappear
        self.timer_dialog.hide()
        self.pressure_dialog.hide()
        self.ui.start_button.setText("Start")
        self.ui.start_button.setStyleSheet(BUTTON_STYLES["START"])
        self.protocol_running = False
        self.mid_protocol_warning_shown = False

    def stop_protocol(self):
        """Stop protocol sequence."""
        print("Stopping protocol")
        self.stop_actuators()
        time.sleep(0.5)
        self.protocol_running = False # Ensure flag is set here too
        self.mid_protocol_warning_shown = False # <-- Add this line
        if self.worker:
            self.worker.stop()
        time.sleep(0.5)
        self.start_button.setEnabled(True)
        self.reset_arduino()

    def show_pressure_dialog(self, state):
        """Show/hide pressure dialog during protocol execution."""
        if state == Qt.Checked:
            if not self.pressure_dialog.isVisible():
                print("Showing PressureDialog")  # Debug print
                # Position dialog below timer dialog if visible
                dialog_x = self.x() + self.width() - self.pressure_dialog.width() - 20
                dialog_y = self.y() + (300)
                self.pressure_dialog.move(dialog_x, dialog_y)

                # Initialize with current pressure if available
                if hasattr(self, 'worker') and self.worker and hasattr(self.worker, 'current_pressure'):
                    self.pressure_dialog.update_pressure(self.worker.current_pressure)

                # Check if we're running a protocol and need to connect signals
                if self.protocol_running and hasattr(self, 'worker') and self.worker:
                    # Make sure signal is connected
                    try:
                        self.worker.signals.pressure_emit.disconnect(self.pressure_dialog.update_pressure)
                    except Exception:
                        pass  # Ignore if not previously connected

                    self.worker.signals.pressure_emit.connect(self.pressure_dialog.update_pressure)
                    print("Connected pressure signal to dialog on show")

                # Show the dialog
                self.pressure_dialog.show()
        else:
            self.pressure_dialog.hide()

    def status_emit(self, position_a, position_b, steps, pressure):
        """Handle status updates from Arduino with safety checks."""

        success = True  # Track if processing was successful
        print(f"A {position_a} B {position_b} C {steps} Pressure {pressure}")
        if self.initial_setup_complete:
            try:
                # Check various safety conditions
                if position_a > AXIAL_MAX or (self.initial_setup_complete and pressure > PRESSURE_MAX):
                    self._show_timed_error("Emergency stop triggered: Axial limit exceeded")
                    if self.worker is not None:
                        self.worker.stop()
                    success = False
                    self.initial_setup_complete = False
                    self.reset_arduino()

                # Check horizontal position (B actuator)
                if position_b < HORIZONTAL_MIN or position_b > HORIZONTAL_MAX:
                    self._show_timed_error("Emergency stop triggered: Horizontal position limit exceeded")
                    if self.worker is not None:
                        self.worker.stop()
                    success = False
                    self.initial_setup_complete = False
                    self.reset_arduino()

                # Check lateral position (C actuator)
                if steps < LATERAL_MIN or steps > LATERAL_MAX:
                    self._show_timed_error("Emergency stop triggered: Lateral position limit exceeded")
                    if self.worker is not None:
                        self.worker.stop()
                    success = False
                    self.initial_setup_complete = False
                    self.reset_arduino()

            except Exception as e:
                print(f"Error in status monitoring: {str(e)}")
                self.stop_actuators()
                time.sleep(1)
                self.initial_setup_complete = False
                self.reset_arduino()
                self._show_timed_error(f"Emergency stop: Error monitoring system status\n{str(e)}")
                success = False

        return success

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

    def setup_arduino(self):
        """Setup Arduino interface."""
        try:
            print("Showing loading spinner")
            self.loading_spinner.show()
            self.disable_actuator_controls()

            print("Setting up Arduino interface")
            # 1 - create Worker and Thread inside the Form
            self.arduino = Arduino()  # no parent!
            print("Arduino instance created")

            self.thread = QThread()  # no parent!
            print("Thread instance created for Arduino")

            # 2 - Connect Worker's Signals to Form method slots to post data
            print("Connecting Arduino signals to corresponding slots")
            self.arduino.done_emit.connect(self.set_done)

            # 3 - Move the Worker object to the Thread object
            print("Moving Arduino object to thread")
            self.arduino.moveToThread(self.thread)

            # 4 - Connect Worker Signals to the Thread slots
            print("Connecting Arduino finished signal to thread quit")
            self.arduino.finished.connect(self.thread.quit)
            self.arduino.ready_to_go_emit.connect(self.ready_to_go)
            self.arduino.buffer_warning.connect(self.handle_buffer_warning)

            # 5 - Connect Thread started signal to Worker operational slot method
            print("Connecting thread started signal to Arduino run method")
            self.thread.started.connect(self.arduino.run)

            # Additional Arduino signal connections
            print("Connecting Arduino position, status, and pressure signals")
            self.arduino.position_emit.connect(self.read_position)
            self.arduino.status_emit.connect(self.status_emit)
            self.arduino.connection_lost.connect(self.reset_arduino)
            self.arduino.connection_failed.connect(self.handle_connection_failed)

            # 6 - Start the thread
            print("Starting Arduino thread")
            self.thread.start()
            print("Thread started for Arduino")

            # Wait for "Ready to Go" signal with timeout
            print("Waiting for Arduino connection readiness")
            connection_ready = False
            start_time = time.time()
            while time.time() - start_time < 5:  # 5 second timeout
                if self.arduino.connection_ready:
                    connection_ready = True
                    break
                QApplication.processEvents()
                time.sleep(0.1)

            if connection_ready:
                print("Arduino initialized successfully")

                # Setup connection signal handlers for initialization tasks
                print("Setting up initialization tasks to run on successful connection")

                # Connect the signal once to reset Arduino
                self.arduino.connection_ready.connect(self.reset_arduino)

                # Emit signal to trigger connected handlers if already connected
            else:
                self.loading_spinner.hide()

                print("Arduino initialization timed out")

            return connection_ready  # Indicate success or failure

        except Exception as e:
            self.loading_spinner.hide()

            print(f"An error occurred while setting up Arduino: {e}")
            raise

    def reset_arduino(self, event=None):
        """Reset Arduino and reinitialize actuators using ResetWorker."""
        print("Reset Arduino requested...")

        # Check if reset is already in progress to avoid multiple overlapping resets
        if self.reset_in_progress:
            print("Reset already in progress, ignoring duplicate request")
            return

        self.reset_in_progress = True  # Set flag to prevent overlapping resets
        self.initial_setup_complete = False

        if not hasattr(self, 'arduino') or self.arduino is None:
            print("Arduino object not ready for reset.")
            self._show_timed_error(self, "Error", "Arduino connection not initialized.")
            self.reset_in_progress = False  # Reset flag
            return

        # Show the spinner
        print("Showing loading spinner for reset")
        self.loading_spinner.show()
        self.disable_actuator_controls()
        # Disable start button during reset to prevent crashes
        self.start_button.setEnabled(False)
        QApplication.processEvents() # Ensure spinner is visible

        # Create and configure the worker, passing 'self'
        reset_worker = ResetWorker(self.arduino, self.config, self)

        # Connect signals from the worker to slots in this main class
        reset_worker.signals.finished.connect(self._on_reset_finished)
        reset_worker.signals.error.connect(self._on_reset_error)

        # Run the worker in the thread pool
        print("Starting ResetWorker in threadpool")
        self.threadpool.start(reset_worker)
        self.reset_setup_readings()

    @QtCore.pyqtSlot(bool)
    def _on_reset_finished(self, success):
        """Slot called when ResetWorker finishes."""
        print(f"Reset sequence finished signal received. Success: {success}")

        # Clear the reset in progress flag
        self.reset_in_progress = False

        if success:
            if self.initial_setup_complete == False:
                self.reset_extra_button_clicked()
            self.loading_spinner.hide() # Hide spinner when done
            self.start_button.setText("Start")
            self.start_button.setStyleSheet(BUTTON_STYLES["START"])
            self.start_button.setEnabled(True)  # Re-enable start button
            time.sleep(0.1)
            self._show_timed_error(
                "Arduino reset and actuators reinitialized."
            )
            self.initial_setup_complete = True
            print("Reset sequence completed successfully via worker.")
        else:
            self.start_button.setEnabled(True)  # Re-enable start button even on failure
            self._show_timed_error(
             "Reset sequence failed. Check logs and Arduino connection."
             )

    @QtCore.pyqtSlot(str)
    def _on_reset_error(self, error_message):
        """Slot called if ResetWorker emits an error signal."""
        print(f"Reset error signal received: {error_message}")
        # Ensure spinner hides even if finished signal doesn't fire (though finally should handle it)
        self.loading_spinner.hide()
        # Make sure to clear the reset_in_progress flag in case of error too
        self.reset_in_progress = False
        self.start_button.setEnabled(True)  # Re-enable start button on error
        self._show_timed_error(
         f"Could not complete reset sequence:\n{error_message}"
        )

    def send_zero_mark(self):
        print("send_zero_mark")
        self.arduino.send(
            "L5{:3} {:3}".format(self.config.AMarks["0.0"], self.config.BMarks["0.0"])
        )

    def send_calibration(self):
        print("send_calibration")
        self.arduino.send("L0{}".format(self.config.calibration))

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


# Main function without direct access to Arduino
def main():
    """Main function to start the application."""
    import argparse

    parser = argparse.ArgumentParser(description="KneeSpa Application")
    parser.add_argument(
        "--debug", action="store_true", help="Run in debug mode (windowed)"
    )
    args = parser.parse_args()

    print(f"Application started at {datetime.now()}")
    print(f"Debug mode: {'enabled' if args.debug else 'disabled'}")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = KneeSpa(debug_mode=args.debug)
    window.show()

    app.exec_()

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
