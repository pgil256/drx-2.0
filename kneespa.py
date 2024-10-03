import sys
import os
import csv
import RPi.GPIO as GPIO
import time
from datetime import datetime, timedelta
from PyQt5 import QtWidgets, uic, QtCore
from PyQt5.QtCore import Qt, QTimer, QThread, QObject
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QCheckBox,
    QDateTime,
    QTime,
    QElapsedTimer,
)
from Arduino import comm, config
from UI.video_player import VideoPlayer
from UI.timer_dialog import TimerDialog
from UI.pressure_dialog import PressureDialog
from Protocols import (
    AProtocols,
    BProtocols,
    CProtocols,
    DProtocols,
    ABProtocols,
    ACProtocols,
    ADProtocols,
)


# Constants
DEGREES0 = 0
DEGREES5 = 5
DEGREES10 = 10

EMERGENCYSTOP = 16
EXTRAFORWARD = 27
EXTRABACKWARD = 22
EXTRAENABLE = 17

degreeList = {0: 5, -5: 4, -10: 3, -15: 2, -20: 1, -25: 0, -30: 0}
CdegreeList = {-20: 0, -10: 0.5, 0: 1, 10: 1.5, 20: 2}
BDegreeList = {0: 5, 5: 4, 10: 3, 15: 2, 20: 1, 25: 0, 30: 0}

PROTOCOL_MAPPING = {
    1: "AC1",
    2: "AC2",
    3: "AC3",
    4: "AC4",
    5: "AC5",
    6: "AC6",
    7: "AC7",
    8: "AC8",
    9: "AC9",
}

# Change the working directory
print("Changing working directory to /home/pi/kneespa")
os.chdir("/home/pi/kneespa")

DEGREES = "\u00b0"


# Main Python class
class KneeSpaApp(QMainWindow):
    """Main application class for KneeSpa."""

    ### Static methods ###

    def shutdown_app(self):
        GPIO.cleanup()  # clean up GPIO on normal exit
        os.system("sudo shutdown -h now")
        os._exit(1)

    def exit_app(self):
        GPIO.cleanup()  # clean up GPIO on normal exit
        os._exit(1)

    def set_to_distance(self, inches, actuator, factor):
        position = int(inches * (factor / 8.0))
        print(" positioned to {} in. {} pos {}".format(inches, position, actuator))
        if self.newC:
            command = "A{}{}".format(actuator, inches)
        else:
            if actuator == self.actuatorC:
                command = "K{}".format(position)
            else:
                command = "A{}{}".format(actuator, inches)
        self.arduino.send(command)
        print("cmd {}".format(command.strip()))
        self.I2C_status = False
        print("end")

    def set_to_distance(self, degrees):

        position = self.config.CMarks["{:.1f}".format(degrees)]

        print(" positioned to {} degrees pos {}".format(degrees, position))
        command = "K{}".format(position)
        self.arduino.send(command)
        print("cmd {}".format(command.strip()))

        self.I2C_status = False
        print("end")

    ### App Initialization ####

    def __init__(self):
        super().__init__()
        print("Initializing KneeSpaApp")

        # Backend initialization
        self.newC = True
        self.task = None
        self.I2C_status = 0
        self.config = config.Configuration()
        self.config.getConfig()

        # Monitor setup
        try:
            self.ui = uic.loadUi("UI/kneespa.ui", self)
        except FileNotFoundError:
            print("UI file 'kneespa.ui' not found.")
            QMessageBox.critical(self, "Error", "UI file 'kneespa.ui' not found.")
            sys.exit(1)

        self.ui.showFullScreen()
        self.setWindowFlags(Qt.FramelessWindowHint)

        # Timer setup
        def setup_timer(self):
            self.elapsed_timer = QTimer(self)
            self.elapsed_timer.timeout.connect(self.update_time)

            self.hour_format = "24"
            self.ui.time_mm_lbl.setText("")
            self.ui.time_colon_lbl.setText("")
            self.ui.time_ss_lbl.setText("")

            self.protocol_timer = QElapsedTimer()
            self.protocol_timer.clockType = QElapsedTimer.SystemTime

            self.ui.time_group.hide()

            self.complete_timer = QTimer(self)
            self.complete_timer.timeout.connect(self.blink_complete)
            self.blinking_complete = False
            self.blinking_complete_count = 0

            self.go_timer = QTimer(self)
            self.go_timer.timeout.connect(self.blink_go)
            self.blinking_go = True

            self.stop_timer = QTimer(self)
            self.stop_timer.timeout.connect(self.blink_stop)
            self.blinking_stop = True

            self.reset_timer = QTimer(self)
            self.reset_timer.timeout.connect(self.blink_reset)
            self.blinking_reset = False

            self.logger = False

            self.slider_go_btn = None
            self.slider_timer = QTimer(self)
            self.slider_timer.timeout.connect(
                lambda: self.blink_slider(self.slider_go_btn)
            )
            self.slider_go = True

            self.status_timer = QTimer(self)
            self.status_timer.timeout.connect(self.clear_status)

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

        self.login_pin = ""
        self.patient_pin = ""

        self.table_widget = self.findChild(
            QtWidgets.QTableWidget, "patient_table_widget"
        )
        if self.table_widget:
            self.table_widget.verticalHeader().setVisible(True)

        self.users = self.load_csv("users/user_pins.csv")
        self.patients = self.load_csv("patients/patient_pins.csv")
        self.current_user = None

        self.home_page = 0
        self.main_page = 1
        self.help_page = 2
        self.profile_page = 3

        self.setup_buttons_and_labels()
        self.setup_protocol_image()
        self.setup_pressure_controls()
        self.setup_leg_length_controls()
        self.setup_dialogs()
        self.connect_slider_signals()

        self.timer_dialog = TimerDialog(self)
        self.pressure_dialog = PressureDialog(self)

        self.threadpool = QtCore.QThreadPool()
        print(f"Multithreading with maximum {self.threadpool.maxThreadCount()} threads")
        self.worker = None

        self.setup_arduino()
        self.setup_timers()

        self.CMarks = {}
        for i in range(16):
            u = (i * 220) + 98
            angle = (i * 2.5) - 20
            print(f"Mark {i}: angle {angle}, value {u}")
            self.CMarks[angle] = u

        print(self.config.AMarks)
        print(self.config.BMarks)
        print(self.config.CMarks)

        QTimer.singleShot(2000, self.send_calibration)
        QTimer.singleShot(5000, self.send_zero_ark)

        QTimer.singleShot(1000, self.show_arduino_info_dialog)

        ### UI Methods ###

    def connect_slider_signals(self):
        self.ui.axial_pressure_slider.valueChanged.connect(self.axial_pressure_changed)
        self.ui.minus_horizontal_flexion_slider.valueChanged.connect(
            self.minus_horizontal_flexion_changed
        )
        self.ui.plus_horizontal_flexion_slider.valueChanged.connect(
            self.plus_horizontal_flexion_changed
        )
        self.ui.left_lat_flexion_slider.valueChanged.connect(
            self.left_lat_flexion_changed
        )
        self.ui.right_lat_flexion_slider.valueChanged.connect(
            self.right_lat_flexion_changed
        )
        self.ui.cycles_slider.valueChanged.connect(self.cycles_changed)
        self.ui.ab_axial_pressure_slider.valueChanged.connect(
            self.ab_axial_pressure_changed
        )
        self.ui.minus_ab_horizontal_flexion_slider.valueChanged.connect(
            self.minus_ab_horizontal_flexion_changed
        )
        self.ui.plus_ab_horizontal_flexion_slider.valueChanged.connect(
            self.plus_ab_horizontal_flexion_changed
        )
        self.ui.acd_axial_pressure_slider.valueChanged.connect(
            self.acd_axial_pressure_changed
        )
        self.ui.acd_left_lat_flexion_slider.valueChanged.connect(
            self.acd_left_lat_flexion_changed
        )
        self.ui.acd_right_lat_flexion_slider.valueChanged.connect(
            self.acd_right_lat_flexion_changed
        )
        self.ui.forward_axial_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_a, 0.065, "04")
        )
        self.ui.reverse_axial_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_a, 0.065, "04")
        )
        self.ui.forward_fast_axial_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_a, 0.065, "20")
        )
        self.ui.reverse_fast_axial_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_a, 0.065, "20")
        )
        self.ui.reset_axial_flexion_btn.clicked.connect(
            lambda: self.reset_flexion_btn(self.actuator_a)
        )
        self.axial_flexion_position = 0
        self.ui.axial_flexion_position_slider.valueChanged.connect(
            self.axial_flexion_position_changed
        )
        self.ui.axial_flexion_position_lbl.setText("0 in")
        self.ui.axial_flexion_position_btn.clicked.connect(
            lambda: self.move_position_flexion_btn(self.actuator_a)
        )
        self.ui.axial_flexion_position_stop_btn.clicked.connect(
            lambda: self.stop_position_flexion_btn(self.actuator_a)
        )
        self.ui.axial_flexion_pressure_slider.valueChanged.connect(
            self.axial_flexion_pressure_changed
        )
        self.ui.axial_flexion_pressure_lbl.setText("0 lb")
        self.ui.axial_flexion_pressure_btn.clicked.connect(
            self.axial_flexion_pressure_btn
        )
        self.ui.axial_flexion_pressure_stop_btn.clicked.connect(
            lambda: self.stop_position_flexion_btn(self.actuator_a)
        )
        self.ui.axial_pressure_up_lbl.mousePressEvent = self.axial_pressure_up
        self.ui.axial_pressure_down_lbl.mousePressEvent = self.axial_pressure_down
        self.ui.ab_axial_pressure_up_lbl.mousePressEvent = self.ab_axial_pressure_up
        self.ui.ab_axial_pressure_down_lbl.mousePressEvent = self.ab_axial_pressure_down
        self.ui.minus_ab_horizontal_flexion_up_lbl.mousePressEvent = (
            self.minus_ab_horizontal_flexion_up
        )
        self.ui.minus_ab_horizontal_flexion_down_lbl.mousePressEvent = (
            self.minus_ab_horizontal_flexion_down
        )
        self.ui.plus_ab_horizontal_flexion_up_lbl.mousePressEvent = (
            self.plus_ab_horizontal_flexion_up
        )
        self.ui.plus_ab_horizontal_flexion_down_lbl.mousePressEvent = (
            self.plus_ab_horizontal_flexion_down
        )
        self.ui.minus_horizontal_up_lbl.mousePressEvent = self.minus_horizontal_up
        self.ui.minus_horizontal_down_lbl.mousePressEvent = self.minus_horizontal_down
        self.ui.plus_horizontal_up_lbl.mousePressEvent = self.plus_horizontal_up
        self.ui.plus_horizontal_down_lbl.mousePressEvent = self.plus_horizontal_down
        self.ui.left_lat_up_lbl.mousePressEvent = self.left_lat_up
        self.ui.left_lat_down_lbl.mousePressEvent = self.left_lat_down
        self.ui.right_lat_up_lbl.mousePressEvent = self.right_lat_up
        self.ui.right_lat_down_lbl.mousePressEvent = self.right_lat_down
        self.ui.acd_axial_pressure_up_lbl.mousePressEvent = self.acd_axial_pressure_up
        self.ui.acd_axial_pressure_down_lbl.mousePressEvent = (
            self.acd_axial_pressure_down
        )
        self.ui.acd_left_lat_up_lbl.mousePressEvent = self.acd_left_lat_up
        self.ui.acd_left_lat_down_lbl.mousePressEvent = self.acd_left_lat_down
        self.ui.acd_right_lat_up_lbl.mousePressEvent = self.acd_right_lat_up
        self.ui.acd_right_lat_down_lbl.mousePressEvent = self.acd_right_lat_down
        self.ui.forward_horizontal_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_b, 0.065, "04")
        )
        self.ui.reverse_horizontal_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_b, 0.065, "04")
        )
        self.ui.forward_fast_horizontal_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_b, 0.065, "20")
        )
        self.ui.reverse_fast_horizontal_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_b, 0.065, "20")
        )
        self.ui.reset_horizontal_flexion_btn.clicked.connect(
            lambda: self.reset_flexion_btn(self.actuator_b)
        )
        self.horizontal_flexion_position = -15
        self.ui.horizontal_position_flexion_slider.valueChanged.connect(
            self.horizontal_position_flexion_changed
        )
        self.ui.horizontal_position_flexion_lbl.setText("-15" + DEGREES)
        self.ui.horizontal_position_flexion_btn.clicked.connect(
            lambda: self.move_position_flexion_btn(self.actuator_b)
        )
        self.ui.horizontal_position_flexion_stop_btn.clicked.connect(
            lambda: self.stop_position_flexion_btn(self.actuator_b)
        )
        self.ui.forward_lateral_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_c, 0.0328, "04")
        )
        self.ui.reverse_lateral_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_c, 0.0328, "04")
        )
        self.ui.forward_fast_lateral_flexion_btn.clicked.connect(
            lambda: self.forward_flexion_btn(self.actuator_c, 0.0328, "20")
        )
        self.ui.reverse_fast_lateral_flexion_btn.clicked.connect(
            lambda: self.reverse_flexion_btn(self.actuator_c, 0.0328, "20")
        )
        self.ui.reset_lateral_flexion_btn.clicked.connect(
            lambda: self.reset_flexion_btn(self.actuator_c)
        )
        self.lateral_flexion_position = 0
        self.ui.lateral_flexion_position_slider.valueChanged.connect(
            self.lateral_flexion_position_changed
        )
        self.ui.lateral_flexion_position_lbl.setText("0" + DEGREES)
        self.ui.lateral_flexion_position_btn.clicked.connect(
            lambda: self.move_position_flexion_btn(self.actuator_c)
        )
        self.ui.lateral_flexion_position_stop_btn.clicked.connect(
            lambda: self.stop_position_flexion_btn(self.actuator_c)
        )
        self.ui.cycles_slider.sliderMoved.connect(self.cycles_slider_moved)
        self.ui.axial_pressure_slider.sliderMoved.connect(
            self.axial_pressure_slider_moved
        )
        self.ui.minus_horizontal_flexion_slider.sliderMoved.connect(
            self.minus_horizontal_flexion_slider_moved
        )
        self.ui.plus_horizontal_flexion_slider.sliderMoved.connect(
            self.plus_horizontal_flexion_slider_moved
        )
        self.ui.left_lat_flexion_slider.sliderMoved.connect(
            self.left_lat_flexion_slider_moved
        )
        self.ui.right_lat_flexion_slider.sliderMoved.connect(
            self.right_lat_flexion_slider_moved
        )
        self.ui.ab_axial_pressure_slider.sliderMoved.connect(
            self.ab_axial_pressure_slider_moved
        )
        self.ui.acd_axial_pressure_slider.sliderMoved.connect(
            self.acd_axial_pressure_slider_moved
        )
        self.ui.minus_ab_horizontal_flexion_slider.sliderMoved.connect(
            self.minus_ab_horizontal_flexion_slider_moved
        )
        self.ui.plus_ab_horizontal_flexion_slider.sliderMoved.connect(
            self.plus_ab_horizontal_flexion_slider_moved
        )
        self.ui.acd_left_lat_flexion_slider.sliderMoved.connect(
            self.acd_left_lat_flexion_slider_moved
        )
        self.ui.acd_right_lat_flexion_slider.sliderMoved.connect(
            self.acd_right_lat_flexion_slider_moved
        )
        self.ui.axial_flexion_pressure_slider.sliderMoved.connect(
            self.axial_flexion_pressure_slider_moved
        )
        self.ui.horizontal_position_flexion_slider.sliderMoved.connect(
            self.horizontal_position_flexion_slider_moved
        )
        self.ui.lateral_flexion_position_slider.sliderMoved.connect(
            self.lateral_flexion_slider_moved
        )
        self.ui.forward_extra_btn.clicked.connect(self.forward_extra_btn_clicked)
        self.ui.reverse_extra_btn.clicked.connect(self.reverse_extra_btn_clicked)
        self.ui.forward_fast_extra_btn.clicked.connect(
            self.forward_fast_extra_btn_clicked
        )
        self.ui.reverse_fast_extra_btn.clicked.connect(
            self.reverse_fast_extra_btn_clicked
        )
        self.ui.reset_extra_btn.clicked.connect(self.reset_extra_btn_clicked)
        # self.ui.measure_weight_btn.clicked.connect(self.measure_weight_btn_clicked)
        # self.ui.measure_location_btn.clicked.connect(self.measure_location_btn_clicked)
        # self.ui.reset_arduino_btn.clicked.connect(self.reset_arduino_btn)
        # self.ui.reset_arduino_2_btn.clicked.connect(self.reset_arduino_btn)
        # self.ui.emergency_stop_lbl.mousePressEvent = self.emergency_stop_lbl
        # self.ui.emergency_stop_2_lbl.mousePressEvent = self.emergency_stop_lbl

    def setup_buttons_and_labels(self):
        """Setup buttons and label elements."""
        print("Setting up buttons and labels")
        self.ui.protocols_button = self.ui.findChild(
            QtWidgets.QPushButton, "protocols_button"
        )
        self.ui.help_button = self.ui.findChild(QtWidgets.QPushButton, "help_button")
        self.ui.login_button = self.ui.findChild(QtWidgets.QPushButton, "login_button")
        self.ui.start_button = self.ui.findChild(
            QtWidgets.QPushButton, "push_button_start"
        )
        self.ui.enter_patient_button = self.ui.findChild(
            QtWidgets.QPushButton, "enter_patient_pin_button"
        )
        self.ui.edit_patient_button = self.ui.findChild(
            QtWidgets.QPushButton, "edit_patient_button"
        )
        self.ui.profile_button = self.ui.findChild(QtWidgets.QLabel, "profile_button")
        self.ui.video_player_button = self.ui.findChild(
            QtWidgets.QLabel, "video_player_button"
        )
        self.ui.brand_label = self.ui.findChild(QtWidgets.QLabel, "top_nav_brand_label")
        self.ui.brand_logo = self.ui.findChild(QtWidgets.QLabel, "top_nav_logo")

        self.ui.username_nav = self.ui.findChild(QtWidgets.QLabel, "username_nav")
        self.ui.username_profile = self.ui.findChild(QtWidgets.QLabel, "username_field")
        self.ui.email_profile = self.ui.findChild(QtWidgets.QLabel, "email_field")
        self.ui.status_profile = self.ui.findChild(QtWidgets.QLabel, "status_field")
        self.ui.reset_arduino_button = self.ui.findChild(
            QtWidgets.QLabel, "reset_arduino_button"
        )
        self.ui.show_timer_button = self.ui.findChild(
            QtWidgets.QCheckBox, "checkbox_show_timer"
        )
        self.ui.show_pressure_button = self.ui.findChild(
            QtWidgets.QCheckBox, "checkbox_show_pressure"
        )

        self.connect_buttons_and_labels()

    def connect_buttons_and_labels(self):
        """Connect buttons and labels to their corresponding functions."""
        print("Connecting buttons and labels to their functions")
        if self.ui.protocols_button:
            self.ui.protocols_button.clicked.connect(self.show_main_page)
        if self.ui.help_button:
            self.ui.help_button.clicked.connect(self.show_help_page)
        if self.ui.login_button:
            self.ui.login_button.clicked.connect(self.show_login_dialog)
        if self.ui.start_button:
            self.ui.start_button.clicked.connect(self.start_or_stop_protocol)
        if self.ui.enter_patient_button:
            self.ui.enter_patient_button.clicked.connect(self.show_enter_patient_dialog)
        if self.ui.edit_patient_button:
            self.ui.edit_patient_button.clicked.connect(self.edit_patient_data)
        if self.ui.profile_button:
            self.ui.profile_button.mousePressEvent = self.show_profile_page
        if self.ui.video_player_button:
            self.ui.video_player_button.mousePressEvent = self.show_video_player_dialog
        if self.ui.brand_label:
            self.ui.brand_label.mousePressEvent = self.return_to_home_page
        if self.ui.brand_logo:
            self.ui.brand_logo.mousePressEvent = self.return_to_home_page
        if self.ui.show_timer_button:
            self.ui.show_timer_button.stateChanged.connect(self.show_timer_dialog)
        if self.ui.show_pressure_button:
            self.ui.show_pressure_button.stateChanged.connect(self.show_pressure_dialog)
        if self.ui.reset_arduino_button:
            self.ui.reset_arduino_button.mousePressEvent = self.reset_arduino

    def setup_protocol_image(self):
        """Initialize and setup protocol image navigation."""
        print("Setting up protocol image navigation")
        self.label_protocol_image = self.ui.findChild(
            QtWidgets.QLabel, "label_protocol_image"
        )
        self.protocol_image_number = self.ui.findChild(
            QtWidgets.QLineEdit, "protocol_number_field"
        )
        self.forward_button_protocol_image = self.ui.findChild(
            QtWidgets.QLabel, "forward_button_protocol_image"
        )
        self.backward_button_protocol_image = self.ui.findChild(
            QtWidgets.QLabel, "backward_button_protocol_image"
        )

        self.current_image_number = 1
        self.update_protocol_image()

        self.forward_button_protocol_image.mousePressEvent = (
            self.show_next_protocol_image
        )
        self.backward_button_protocol_image.mousePressEvent = (
            self.show_previous_protocol_image
        )

    def setup_pressure_controls(self):
        """Initialize and setup pressure controls."""
        print("Setting up pressure controls")
        self.ui.pressure_field = self.ui.findChild(
            QtWidgets.QLineEdit, "pressure_field"
        )
        self.ui.plus_label_pressure = self.ui.findChild(
            QtWidgets.QLabel, "plus_label_pressure"
        )
        self.ui.minus_label_pressure = self.ui.findChild(
            QtWidgets.QLabel, "minus_label_pressure"
        )

        self.current_pressure = 40
        self.update_pressure_field()

        self.ui.plus_label_pressure.mousePressEvent = self.increase_pressure
        self.ui.minus_label_pressure.mousePressEvent = self.decrease_pressure

    def setup_leg_length_controls(self):
        """Initialize and setup leg length controls."""
        print("Setting up leg length controls")
        self.ui.leg_length_field = self.ui.findChild(
            QtWidgets.QLineEdit, "leg_length_field"
        )
        self.ui.plus_label_leg_length = self.ui.findChild(
            QtWidgets.QLabel, "plus_label_leg_length"
        )
        self.ui.minus_label_leg_length = self.ui.findChild(
            QtWidgets.QLabel, "minus_label_leg_length"
        )

        self.current_leg_length = 6.0
        self.update_leg_length_field()

        self.ui.plus_label_leg_length.mousePressEvent = self.increase_leg_length
        self.ui.minus_label_leg_length.mousePressEvent = self.decrease_leg_length

    def setup_dialogs(self):
        """Initialize dialogs."""
        print("Setting up dialogs")
        self.ui.login_dialog = None
        self.init_login_dialog()
        self.ui.enter_patient_dialog = None
        self.init_enter_patient_dialog()
        self.ui.video_player_dialog = None
        self.arduino_info_dialog = None

    def update_time(self):
        if not self.protocol_timer.isValid():
            return
        elapsed = self.protocol_timer.elapsed()
        seconds = (elapsed / 1000) % 60
        seconds = int(seconds)
        minutes = (elapsed / (1000 * 60)) % 60
        minutes = int(minutes)
        dt = QDateTime.currentDateTime()
        time = QTime.currentTime()
        textMM = "{:02d}".format(minutes)
        textSS = "{:02d}".format(seconds)
        text = ":"
        if self.hourFormat == "12":
            textTime = time.toString("h:mm ap").split(" ")[0]
        else:
            textTime = time.toString("h:mm").split(" ")[0]
        textTime = textTime.replace(":", text)

        self.ui.timeMMLbl.setText(textMM)
        self.ui.timeColonLbl.setText(text)
        self.ui.timeSSLbl.setText(textSS)

    def setup_timers(self):
        """Setup timers for protocol event"""
        print("Setting up timers for protocol events")
        self.protocol_timer = QTimer(self)
        self.protocol_timer.timeout.connect(self.update_protocol_time)

    def show_timer_dialog(self, state):
        """Show timer dialog during protocol execution"""
        print(f"Timer checkbox state changed: {state}")
        if self.timer_dialog.isVisible():
            print("Hiding TimerDialog")
            self.timer_dialog.hide()
        else:
            print("Showing TimerDialog")
            self.timer_dialog.show()

    def show_pressure_dialog(self, state):
        """Show the current pressure during protocol execution"""
        print(f"Pressure checkbox state changed: {state}")
        if self.pressure_dialog.isVisible():
            print("Hiding PressureDialog")
            self.pressure_dialog.hide()
        else:
            print("Showing PressureDialog")
            self.pressure_dialog.show()

    def log_protocol(
        self, protocol, cycles, pressure, degrees, start_degrees, left_lat, right_lat
    ):
        return
        time_stamp = datetime.now().strftime("%m/%d/%Y %H:%M")
        file_name = datetime.now().strftime("%m-%d-%Y") + ".csv"
        if exists(file_name):
            self.logger = False
            with open(file_name, "a") as f:
                csv_writer = csv.writer(f)
                # writing the fields
                csv_writer.writerow(
                    [
                        time_stamp,
                        self.unlock_id,
                        protocol,
                        cycles,
                        pressure,
                        degrees,
                        start_degrees,
                        left_lat,
                        right_lat,
                    ]
                )
        else:
            with open(file_name, "w") as f:
                # creating a csv writer object
                csv_writer = csv.writer(f)
                # writing the fields
                csv_writer.writerow(
                    [
                        "TimeStamp",
                        "Id",
                        "Protocol",
                        "Cycles",
                        "Axial Pressure",
                        "Horizontal Degrees",
                        "Start Degrees",
                        "Left Lat Degrees",
                        "Right Lat Degrees",
                    ]
                )
                csv_writer.writerow(
                    [
                        time_stamp,
                        self.unlock_id,
                        protocol,
                        cycles,
                        pressure,
                        degrees,
                        start_degrees,
                        left_lat,
                        right_lat,
                    ]
                )
                self.logger = True

    def start_or_stop_protocol(self):
        """Start or stop the protocol."""
        print("Toggling protocol start/stop")
        if self.start_button.text() == "Start":
            print("Starting protocol")
            self.start_button.setText("Stop")
            self.start_button.setStyleSheet(
                "background-color: rgb(200, 0, 0);"
                "color: white;"
                "border: none;"
                "text-decoration: bold;"
                "font-size: 32px;"
                "font-weight: bold;"
                "border-radius: 12px;"
            )
            self.start_protocol()
        else:
            print("Stopping protocol")
            self.start_button.setText("Start")
            self.start_button.setStyleSheet(
                "background-color: rgb(0, 200, 0);"
                "color: white;"
                "border: none;"
                "text-decoration: bold;"
                "font-size: 32px;"
                "font-weight: bold;"
                "border-radius: 12px;"
            )
            self.stop_protocol()

    def load_csv(self, filename):
        """Load CSV data."""
        print(f"Loading CSV file: {filename}")
        data = {}
        try:
            with open(filename, "r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data[row["pin"]] = row
            print(f"CSV file {filename} loaded successfully")
        except FileNotFoundError:
            print(f"CSV file not found: {filename}")
            QMessageBox.critical(self, "Error", f"CSV file not found: {filename}")
        except csv.Error as e:
            print(f"CSV file error in {filename}: {e}")
            QMessageBox.critical(self, "Error", f"CSV file error in {filename}: {e}")
        return data

    def save_patient_data(self):
        """Save patient data to CSV."""
        print("Saving patient data to CSV")
        if self.current_user and self.current_user["status"] == "admin":
            current_pin = self.patient_pin
            if current_pin in self.patients:
                for row in range(self.ui.table_widget.rowCount()):
                    key = (
                        self.ui.table_widget.item(row, 0)
                        .text()
                        .lower()
                        .replace(" ", "_")
                    )
                    value = self.ui.table_widget.item(row, 1).text()
                    self.patients[current_pin][key] = value

                with open("patients_pins.csv", "w", newline="") as file:
                    writer = csv.DictWriter(
                        file, fieldnames=self.patients[current_pin].keys()
                    )
                    writer.writeheader()
                    for patient in self.patients.values():
                        writer.writerow(patient)

                QMessageBox.information(
                    self, "Success", "Patient data updated successfully."
                )
                print("Patient data saved successfully")
            else:
                QMessageBox.warning(self, "Error", "No patient data to save.")
                print("No patient data to save")
        else:
            QMessageBox.warning(
                self, "Access Denied", "Only admins can save patient data."
            )
            print("Access denied for saving patient data")

    def show_login_dialog(self):
        """Show the login dialog."""
        print("Showing login dialog")
        self.login_pin = ""
        self.login_line_edit.clear()
        self.login_dialog.exec_()

    def init_login_dialog(self):
        """Initialize the login dialog."""
        print("Initializing login dialog")
        self.login_dialog = QtWidgets.QDialog(self)
        uic.loadUi("login.ui", self.login_dialog)
        self.login_dialog.adjustSize()

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

        self.login_enter_button.clicked.connect(self.handle_login)
        self.login_help_button.clicked.connect(self.show_login_help_dialog)
        self.clear_login_pin_button.clicked.connect(self.clear_login_line_edit)

        for i in range(10):
            button = self.login_dialog.findChild(
                QtWidgets.QPushButton, f"pushButton_{i}"
            )
            if button:
                button.clicked.connect(lambda _, x=str(i): self.append_login_star(x))

    def append_login_star(self, value):
        """Append star to login input."""
        print(f"Appending value {value} to login input")
        self.login_line_edit.setText(self.login_line_edit.text() + "*")
        self.login_pin += value

    def append_patient_star(self, value):
        """Append star to patient input."""
        print(f"Appending value {value} to patient input")
        self.patient_pin_input.setText(self.patient_pin_input.text() + "*")
        self.patient_pin += value

    def clear_login_line_edit(self):
        """Clear the login input field."""
        print("Clearing login input field")
        self.login_line_edit.clear()
        self.login_pin = ""

    def show_login_help_dialog(self):
        """Show login help dialog."""
        print("Showing login help dialog")
        help_dialog = QtWidgets.QDialog(self)
        uic.loadUi("login-help.ui", help_dialog)
        help_dialog.exec_()

    def show_enter_patient_help_dialog(self):
        """Show enter patient help dialog."""
        print("Showing enter patient help dialog")
        help_dialog = QtWidgets.QDialog(self)
        uic.loadUi("enter-patient-help.ui", help_dialog)
        help_dialog.exec_()

    def handle_login(self):
        """Sequence events to handle login event"""
        print("Handling login")
        if self.login_pin in self.users:
            print(f"Login successful for PIN: {self.login_pin}")
            self.current_user = self.users[self.login_pin]
            self.login_line_edit.clear()
            self.login_pin = ""
            self.update_ui_after_login()
            self.login_dialog.accept()
        else:
            print("Login failed: Invalid PIN")
            QMessageBox.warning(self, "Login Failed", "Invalid PIN. Please try again.")

    def update_ui_after_login(self):
        """Update user interface with user details after login"""
        print("Updating UI after login")
        self.ui.username_nav.setText(self.current_user["username"])
        self.ui.username_profile.setText(self.current_user["username"])
        self.ui.email_profile.setText(self.current_user["email"])
        self.ui.status_profile.setText(self.current_user["status"])
        self.ui.login_button.setText("Logout")
        self.ui.login_button.clicked.disconnect()
        self.ui.login_button.clicked.connect(self.handle_logout)

        if self.current_user["status"] == "admin":
            print("Admin user logged in: Enabling admin features")
            self.ui.protocols_button.setEnabled(True)
            self.ui.edit_patient_button.setEnabled(True)
        elif self.current_user["status"] == "user":
            print("Standard user logged in: Disabling admin features")
            self.ui.protocols_button.setEnabled(True)
            self.ui.edit_patient_button.setEnabled(False)
        else:
            print("Unknown user status: Disabling protocol and edit features")
            self.ui.protocols_button.setEnabled(False)
            self.ui.edit_patient_button.setEnabled(False)

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
        self.clear_patient_data()

        self.ui.protocols_button.setEnabled(False)
        self.ui.edit_patient_button.setEnabled(False)

        self.ui.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def handle_patient_pin(self):
        """Handle patient PIN input."""
        print(f"Handling patient PIN: {self.patient_pin}")
        if self.patient_pin in self.patients:
            print(f"Valid patient PIN: {self.patient_pin}")
            self.update_patient_table(self.patients[self.patient_pin])
            self.enter_patient_dialog.accept()
        else:
            print("Invalid patient PIN")
            QMessageBox.warning(
                self, "Invalid PIN", "Patient not found. Please try again."
            )
        self.patient_pin = ""  # Clear the PIN after handling

    def update_patient_table(self, patient_data):
        """Update patient table with data."""
        print("Updating patient table with patient data")
        for row, (key, value) in enumerate(patient_data.items()):
            if key != "pin":
                self.ui.table_widget.setItem(
                    row - 1,
                    0,
                    QtWidgets.QTableWidgetItem(key.replace("_", " ").title()),
                )
                self.ui.table_widget.setItem(
                    row - 1, 1, QtWidgets.QTableWidgetItem(value)
                )
        QMessageBox.information(self, "Success", "Patient data loaded successfully.")
        print("Patient data loaded successfully")

    def init_enter_patient_dialog(self):
        """Initialize the enter patient dialog."""
        print("Initializing enter patient dialog")
        self.enter_patient_dialog = QtWidgets.QDialog(self)
        uic.loadUi("enter-patient.ui", self.enter_patient_dialog)
        self.enter_patient_dialog.adjustSize()

        self.patient_pin_input = self.enter_patient_dialog.findChild(
            QtWidgets.QLineEdit, "patient_pin_line_edit"
        )

        self.enter_patient_help_button = self.enter_patient_dialog.findChild(
            QtWidgets.QPushButton, "enter_patient_help_button"
        )

        for i in range(10):
            button = self.enter_patient_dialog.findChild(
                QtWidgets.QPushButton, f"pushButton_{i}"
            )
            if button:
                button.clicked.connect(lambda _, x=str(i): self.append_patient_star(x))

        self.clear_patient_pin_button = self.enter_patient_dialog.findChild(
            QtWidgets.QPushButton, "clear_patient_pin_button"
        )
        if self.clear_patient_pin_button:
            self.clear_patient_pin_button.clicked.connect(self.clear_patient_line_edit)

        self.enter_button = self.enter_patient_dialog.findChild(
            QtWidgets.QPushButton, "enter_patient_pin_button"
        )
        if self.enter_button:
            self.enter_button.clicked.connect(self.handle_patient_pin)

        self.enter_patient_help_button.clicked.connect(
            self.show_enter_patient_help_dialog
        )

    def show_enter_patient_dialog(self):
        """Show enter patient dialog."""
        print("Showing enter patient dialog")
        self.patient_pin = ""
        self.patient_pin_input.clear()
        self.enter_patient_dialog.exec_()

    def edit_patient_data(self):
        """Enable editing of patient data."""
        print("Enabling editing of patient data")
        if not self.current_user:
            print("Access denied: User not logged in")
            QMessageBox.warning(self, "Access Denied", "Please log in first.")
            return

        if self.current_user["status"] != "admin":
            print("Access denied: User is not an admin")
            QMessageBox.warning(
                self, "Access Denied", "Only admins can edit patient data."
            )
            return

        for row in range(self.ui.table_widget.rowCount()):
            item = self.ui.table_widget.item(row, 1)
            if item:
                item.setFlags(item.flags() | Qt.ItemIsEditable)

        QMessageBox.information(
            self,
            "Edit Mode",
            "You can now edit patient data. Click save patient data to confirm changes.",
        )
        print("Patient data edit mode enabled")

    def clear_patient_data(self):
        """Clear patient data from the UI."""
        print("Clearing patient data from UI")
        for row in range(self.ui.table_widget.rowCount()):
            self.ui.table_widget.setItem(row, 1, QtWidgets.QTableWidgetItem(""))
        QMessageBox.information(self, "Success", "Patient data cleared successfully.")
        print("Patient data cleared successfully")

    def clear_patient_line_edit(self):
        """Clear patient input field."""
        print("Clearing patient input field")
        self.patient_pin_input.clear()
        self.patient_pin = ""

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

    def show_main_page(self):
        """Show the main page."""

        if not self.current_user:
            print("Access denied: User not logged in")
            QMessageBox.warning(
                self, "Access Denied", "Please log in to start a protocol."
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
        if not self.video_player_dialog:
            self.video_player_dialog = VideoPlayer(self)
            self.video_player_dialog.load_current_video()
        self.video_player_dialog.show()

    def update_protocol_image(self):
        """Update the displayed protocol image."""
        print(f"Updating protocol image to number {self.current_image_number}")
        image_path = (
            f"images/graphics/protocol-graphics/{self.current_image_number}.png"
        )
        self.label_protocol_image.setPixmap(QPixmap(image_path))
        self.protocol_image_number.setText(str(self.current_image_number))

    def show_next_protocol_image(self, event):
        """Show the next protocol image."""
        print("Showing next protocol image")
        if self.current_image_number < 18:
            self.current_image_number += 1
            self.update_protocol_image()

    def show_previous_protocol_image(self, event):
        """Show the previous protocol image."""
        print("Showing previous protocol image")
        if self.current_image_number > 1:
            self.current_image_number -= 1
            self.update_protocol_image()

    def update_pressure_field(self):
        """Update the pressure field display."""
        print(f"Updating pressure field: {self.current_pressure} lbs")
        self.ui.pressure_field.setText(f"{self.current_pressure} lbs")

    def increase_pressure(self, event):
        """Increase the displayed pressure."""
        print("Increasing pressure")
        if self.current_pressure < 100:
            self.current_pressure += 5
            self.update_pressure_field()
            print(f"Pressure increased to {self.current_pressure} lbs")

    def decrease_pressure(self, event):
        """Decrease the displayed pressure."""
        print("Decreasing pressure")
        if self.current_pressure > 0:
            self.current_pressure -= 5
            self.update_pressure_field()
            print(f"Pressure decreased to {self.current_pressure} lbs")

    def right_lat_up(self, event):
        self.right_lat_angle = self.ui.right_lat_flexion_slider.value()
        self.right_lat_angle += 10
        if self.right_lat_angle > 20:
            self.right_lat_angle = 20
        self.ui.right_lat_flexion_slider.setValue(self.right_lat_angle)
        self.ui.right_lat_flexion_lbl.setText(str(self.right_lat_angle))

    def right_lat_down(self, event):
        self.right_lat_angle = self.ui.right_lat_flexion_slider.value()
        self.right_lat_angle -= 10
        if self.right_lat_angle < 0:
            self.right_lat_angle = 0
        self.ui.right_lat_flexion_slider.setValue(self.right_lat_angle)
        self.ui.right_lat_flexion_lbl.setText(str(self.right_lat_angle))

    def left_lat_up(self, event):
        self.left_lat_angle = self.ui.left_lat_flexion_slider.value()
        self.left_lat_angle += 10
        if self.left_lat_angle > 20:
            self.left_lat_angle = 20
        self.ui.left_lat_flexion_slider.setValue(self.left_lat_angle)
        self.ui.left_lat_flexion_lbl.setText(str(-self.left_lat_angle))

    def left_lat_down(self, event):
        self.left_lat_angle = self.ui.left_lat_flexion_slider.value()
        self.left_lat_angle -= 10
        if self.left_lat_angle < 0:
            self.left_lat_angle = 0
        self.ui.left_lat_flexion_slider.setValue(self.left_lat_angle)
        self.ui.left_lat_flexion_lbl.setText(str(-self.left_lat_angle))

    def acd_axial_pressure_up(self, event):
        self.axial_pressure = self.ui.acd_axial_pressure_slider.value()
        self.axial_pressure += 5
        if self.axial_pressure > 80:
            self.axial_pressure = 80
        self.ui.acd_axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.acd_axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def acd_axial_pressure_down(self, event):
        self.axial_pressure = self.ui.acd_axial_pressure_slider.value()
        self.axial_pressure -= 5
        if self.axial_pressure < 10:
            self.axial_pressure = 10
        self.ui.acd_axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.acd_axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def acd_right_lat_up(self, event):
        self.right_lat_angle = self.ui.acd_right_lat_flexion_slider.value()
        self.right_lat_angle += 5
        if self.right_lat_angle > 20:
            self.right_lat_angle = 20
        self.ui.acd_right_lat_flexion_slider.setValue(self.right_lat_angle)
        self.ui.acd_right_lat_flexion_lbl.setText(str(self.right_lat_angle) + DEGREES)

    def acd_right_lat_down(self, event):
        self.right_lat_angle = self.ui.acd_right_lat_flexion_slider.value()
        self.right_lat_angle -= 5
        if self.right_lat_angle < 0:
            self.right_lat_angle = 0
        self.ui.acd_right_lat_flexion_slider.setValue(self.right_lat_angle)
        self.ui.acd_right_lat_flexion_lbl.setText(str(self.right_lat_angle) + DEGREES)

    def acd_left_lat_up(self, event):
        self.left_lat_angle = self.ui.acd_left_lat_flexion_slider.value()
        self.left_lat_angle += 5
        if self.left_lat_angle > 20:
            self.left_lat_angle = 20
        self.ui.acd_left_lat_flexion_slider.setValue(self.left_lat_angle)
        self.ui.acd_left_lat_flexion_lbl.setText(str(-self.left_lat_angle) + DEGREES)

    def acd_left_lat_down(self, event):
        self.left_lat_angle = self.ui.acd_left_lat_flexion_slider.value()
        self.left_lat_angle -= 5
        if self.left_lat_angle < 0:
            self.left_lat_angle = 0
        self.ui.acd_left_lat_flexion_slider.setValue(self.left_lat_angle)
        self.ui.acd_left_lat_flexion_lbl.setText(str(-self.left_lat_angle) + DEGREES)

    def minus_horizontal_up(self, event):
        self.minus_horizontal_degrees = self.ui.minus_horizontal_flexion_slider.value()
        self.minus_horizontal_degrees -= 5
        if self.minus_horizontal_degrees < 15:
            self.minus_horizontal_degrees = 15
        self.ui.minus_horizontal_flexion_slider.setValue(self.minus_horizontal_degrees)
        self.ui.minus_horizontal_flexion_lbl.setText(
            str(self.minus_horizontal_degrees) + DEGREES
        )

    def minus_horizontal_down(self, event):
        self.minus_horizontal_degrees = self.ui.minus_horizontal_flexion_slider.value()
        self.minus_horizontal_degrees += 5
        if self.minus_horizontal_degrees > 25:
            self.minus_horizontal_degrees = 25
        self.ui.minus_horizontal_flexion_slider.setValue(self.minus_horizontal_degrees)
        self.ui.minus_horizontal_flexion_lbl.setText(
            str(self.minus_horizontal_degrees) + DEGREES
        )

    def plus_horizontal_up(self, event):
        self.plus_horizontal_degrees = self.ui.plus_horizontal_flexion_slider.value()
        self.plus_horizontal_degrees -= 5
        if self.plus_horizontal_degrees <= 5:
            self.plus_horizontal_degrees = 5
        self.ui.plus_horizontal_flexion_slider.setValue(self.plus_horizontal_degrees)
        self.ui.plus_horizontal_flexion_lbl.setText(
            str(self.plus_horizontal_degrees) + DEGREES
        )

    def plus_horizontal_down(self, event):
        self.plus_horizontal_degrees = self.ui.plus_horizontal_flexion_slider.value()
        self.plus_horizontal_degrees += 5
        if self.plus_horizontal_degrees >= 15:
            self.plus_horizontal_degrees = 15
        self.ui.plus_horizontal_flexion_slider.setValue(self.plus_horizontal_degrees)
        self.ui.plus_horizontal_flexion_lbl.setText(
            str(self.plus_horizontal_degrees) + DEGREES
        )

    def minus_ab_horizontal_flexion_up(self, event):
        self.minus_horizontal_degrees = (
            self.ui.minus_ab_horizontal_flexion_slider.value()
        )
        self.minus_horizontal_degrees -= 5
        if self.minus_horizontal_degrees < 15:
            self.minus_horizontal_degrees = 15
        self.ui.minus_ab_horizontal_flexion_slider.setValue(
            self.minus_horizontal_degrees
        )
        self.ui.minus_ab_horizontal_flexion_lbl.setText(
            str(self.minus_horizontal_degrees) + DEGREES
        )

    def minus_ab_horizontal_flexion_down(self, event):
        self.minus_horizontal_degrees = (
            self.ui.minus_ab_horizontal_flexion_slider.value()
        )
        self.minus_horizontal_degrees += 5
        if self.minus_horizontal_degrees > 25:
            self.minus_horizontal_degrees = 25
        self.ui.minus_ab_horizontal_flexion_slider.setValue(
            self.minus_horizontal_degrees
        )
        self.ui.minus_ab_horizontal_flexion_lbl.setText(
            str(self.minus_horizontal_degrees) + DEGREES
        )

    def plus_ab_horizontal_flexion_up(self, event):
        self.plus_horizontal_degrees = self.ui.plus_ab_horizontal_flexion_slider.value()
        self.plus_horizontal_degrees -= 5
        if self.plus_horizontal_degrees < 5:
            self.plus_horizontal_degrees = 5
        self.ui.plus_ab_horizontal_flexion_slider.setValue(self.plus_horizontal_degrees)
        self.ui.plus_ab_horizontal_flexion_lbl.setText(
            str(self.plus_horizontal_degrees) + DEGREES
        )

    def plus_ab_horizontal_flexion_down(self, event):
        self.plus_horizontal_degrees = self.ui.plus_ab_horizontal_flexion_slider.value()
        self.plus_horizontal_degrees += 5
        if self.plus_horizontal_degrees > 15:
            self.plus_horizontal_degrees = 15
        self.ui.plus_ab_horizontal_flexion_slider.setValue(self.plus_horizontal_degrees)
        self.ui.plus_ab_horizontal_flexion_lbl.setText(
            str(self.plus_horizontal_degrees) + DEGREES
        )

    def axial_pressure_up(self, event):
        self.axial_pressure = self.ui.axial_pressure_slider.value()
        self.axial_pressure += 5
        if self.axial_pressure > 80:
            self.axial_pressure = 80
        self.ui.axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def axial_pressure_down(self, event):
        self.axial_pressure = self.ui.axial_pressure_slider.value()
        self.axial_pressure -= 5
        if self.axial_pressure < 10:
            self.axial_pressure = 10
        self.ui.axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def ab_axial_pressure_up(self, event):
        self.axial_pressure = self.ui.ab_axial_pressure_slider.value()
        self.axial_pressure += 5
        if self.axial_pressure > 80:
            self.axial_pressure = 80
        self.ui.ab_axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.ab_axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def ab_axial_pressure_down(self, event):
        self.axial_pressure = self.ui.ab_axial_pressure_slider.value()
        self.axial_pressure -= 5
        if self.axial_pressure < 10:
            self.axial_pressure = 10
        self.ui.ab_axial_pressure_slider.setValue(self.axial_pressure)
        self.ui.ab_axial_pressure_lbl.setText(str(self.axial_pressure) + " lb")

    def update_leg_length_field(self):
        """Update the leg length field display."""
        print(f"Updating leg length field: {self.current_leg_length:.1f} in")
        current_leg_length = self.current_leg_length
        self.ui.leg_length_field.setText(f"{current_leg_length:.1f} in")

    ### Backend Methods ###

    def increase_leg_length(self, event):
        """Increase the displayed leg length."""
        print("Increasing leg length")
        try:
            if self.current_leg_length < 18:
                self.current_leg_length += 0.5
                self.update_leg_length_field()
                self.adjust_leg_length()
                self.arduino.send("F+")
                GPIO.output(EXTRABACKWARD, GPIO.LOW)
                GPIO.output(EXTRAFORWARD, GPIO.HIGH)
                print(f"Leg length increased to {self.current_leg_length}")
            else:
                print("Maximum leg length reached")
        except Exception as e:
            print(f"Error in increase_leg_length: {str(e)}")

    def decrease_leg_length(self, event):
        """Decrease the displayed leg length."""
        print("Decreasing leg length")
        try:
            if self.current_leg_length > 0:
                self.current_leg_length -= 0.5
                self.update_leg_length_field()
                self.adjust_leg_length()
                self.arduino.send("F-")
                GPIO.output(EXTRAFORWARD, GPIO.LOW)
                GPIO.output(EXTRABACKWARD, GPIO.HIGH)
                print(f"Leg length decreased to {self.current_leg_length}")
            else:
                print("Minimum leg length reached")
        except Exception as e:
            print(f"Error in decrease_leg_length: {str(e)}")

    def adjust_leg_length(self):
        """Send the adjusted leg length to the Arduino."""
        print(f"Adjusting leg length to {self.current_leg_length:.1f}")
        try:
            command = f"L{self.current_leg_length:.1f}"
            self.arduino.send(command)
            print(f"Sent command to Arduino: {command}")
        except Exception as e:
            print(f"Error in adjust_leg_length: {str(e)}")

    def debug_status(self, s1, s2, s3, s4):
        """Debug: log status received from the Arduino."""
        print(f"Debug status: {s1}, {s2}, {s3}, {s4}")

    def debug_position(self, position, steps, pressure, actuator):
        """Debug: log position received from the Arduino."""
        print(f"Debug position: {position}, {steps}, {pressure}, {actuator}")

    def debug_pressure(self, pressure):
        """Debug: log pressure received from the Arduino."""
        print(f"Debug pressure: {pressure}")

    def update_status(self, s1, s2, s3, s4):
        """Update the status label with the latest Arduino status."""
        print(f"Updating status: {s1}, {s2}, {s3}, {s4}")
        self.ui.status_label.setText(f"Status: {s1}, {s2}, {s3}, {s4}")

    ### Other UI Control Methods ###
    def axial_pressure_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.axial_pressure_slider.setValue(rounded)
        self.ui.axial_pressure_lbl.setText(str(rounded) + " lb")

    def ab_axial_pressure_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.ab_axial_pressure_slider.setValue(rounded)
        self.ui.ab_axial_pressure_lbl.setText(str(rounded) + " lb")

    def acd_axial_pressure_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.acd_axial_pressure_slider.setValue(rounded)
        self.ui.acd_axial_pressure_lbl.setText(str(rounded) + " lb")

    def axial_flexion_pressure_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.axial_flexion_pressure_slider.setValue(rounded)
        self.ui.axial_flexion_pressure_lbl.setText(str(rounded) + " lb")

    def minus_horizontal_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.minus_horizontal_flexion_slider.setValue(rounded)
        self.ui.minus_horizontal_flexion_lbl.setText(str(rounded) + DEGREES)

    def plus_horizontal_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.plus_horizontal_flexion_slider.setValue(rounded)
        self.ui.plus_horizontal_flexion_lbl.setText(str(rounded) + DEGREES)

    def minus_ab_horizontal_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.minus_ab_horizontal_flexion_slider.setValue(rounded)
        self.ui.minus_ab_horizontal_flexion_lbl.setText(str(rounded) + DEGREES)

    def plus_ab_horizontal_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.plus_ab_horizontal_flexion_slider.setValue(rounded)
        self.ui.plus_ab_horizontal_flexion_lbl.setText(str(rounded) + DEGREES)

    def left_lat_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.left_lat_flexion_slider.setValue(rounded)
        self.ui.left_lat_flexion_lbl.setText(str(-rounded) + DEGREES)

    def right_lat_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.right_lat_flexion_slider.setValue(rounded)
        self.ui.right_lat_flexion_lbl.setText(str(rounded) + DEGREES)

    def acd_left_lat_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.acd_left_lat_flexion_slider.setValue(rounded)
        self.ui.acd_left_lat_flexion_lbl.setText(str(-rounded) + DEGREES)

    def acd_right_lat_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.acd_right_lat_flexion_slider.setValue(rounded)
        self.ui.acd_right_lat_flexion_lbl.setText(str(rounded) + DEGREES)

    def horizontal_position_flexion_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        self.ui.horizontal_position_flexion_slider.setValue(rounded)
        self.ui.horizontal_position_flexion_lbl.setText(str(rounded) + DEGREES)

    def lateral_flexion_slider_moved(self, event):
        rounded = int(round(event / 10) * 10)
        self.ui.lateral_flexion_position_slider.setValue(rounded)
        self.ui.lateral_flexion_position_lbl.setText(str(rounded) + DEGREES)

    @QtCore.pyqtSlot()
    def set_done(self):
        """Set the I2C status to done."""
        print("Setting I2C status to done")
        self.i2c_status = True
        if self.worker:
            self.worker.i2c_status()

    def ready_to_go(self):
        """Set the I2C status to ready."""
        print("Setting I2C status to ready")
        self.i2c_status = True

    def read_position(self, position, steps, actuator):
        """Read position data from the Arduino."""
        print(
            f"Reading position: position={position}, steps={steps}, actuator={actuator}"
        )
        if hasattr(self, "actuator_b") and actuator == self.actuator_b:
            inches = (position * 6) / self.config.b_factor
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator B): {inches}")
            degrees = int(-(25 - (inches / 5) * 25))
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

    def read_pressure(self, pressure):
        """Read pressure data from the Arduino."""
        print(f"Reading pressure: {pressure}")

    def cycles_slider_moved(self, event):
        rounded = int(round(event / 5) * 5)
        if rounded == 0:
            rounded = 1
        self.ui.cycles_slider.setValue(rounded)
        self.ui.cycles_lbl.setText(str(rounded))

    def start_protocol(self):
        """Initiate protocol sequence."""
        print("Starting protocol")
        if not self.current_user:
            print("Access denied: User not logged in")
            QMessageBox.warning(
                self, "Access Denied", "Please log in to start a protocol."
            )
            return

        self.ui.start_button.setText("Stop")
        protocol = self.ui.protocol_image_number.text()
        pressure = int(self.ui.pressure_field.text().split()[0])
        # cycles = int(self.ui.cycles_field.text())

        ### Temp hard code # of cycles ###
        cycles = 10

        self.log_protocol(protocol, cycles, pressure)
        self.execute_protocol(protocol, pressure, cycles)

        self.ui.cyclesSlider.setEnabled(False)

        self.protocolValue += str(self.buttonValue)
        print("protocol {}".format(self.protocolValue))

        self.ui.statusLbl_2.setText("")

        self.ui.statusLbl.setText("Protocol Started")

        self.arduino.send(
            "L5{:3} {:3}".format(self.config.AMarks["0.0"], self.config.BMarks["0.0"])
        )
        self.I2C_status = 0
        time.sleep(1.5)
        print("End")

        self.protocolTimer.start()

        QApplication.processEvents()
        self.elapsedTimer.start(1000)

        #        self.logProtocol(self.protocolValue, self.cycles, self.axialPressure, self.minusHorizontalDegrees, self.plusHorizontalDegrees,self.leftLatAngle, self.rightLatAngle)
        if protocol == "A":
            self.worker = AProtocols.Protocols(
                self.config.AFactor,
                self.protocolValue,
                self.axialPressure,
                self.cycles,
                self.arduino,
            )
            options = "Pressure: " + str(self.axialPressure)

        if protocol == "B":
            inches = self.BDegreeList[
                self.minusHorizontalDegrees
            ]  # set as initial angle
            horizontalPosition = int(inches * self.config.BFactor / 6.0)
            inches = self.BDegreeList[
                self.plusHorizontalDegrees
            ]  # set as initial angle
            horizontalStartPosition = int(inches * self.config.BFactor / 6.0)

            self.worker = BProtocols.Protocols(
                self.config.BFactor,
                self.protocolValue,
                self.minusHorizontalDegrees,
                self.plusHorizontalDegrees,
                self.cycles,
                self.arduino,
            )
            options = (
                "Minus "
                + str(self.minusHorizontalDegrees)
                + DEGREES
                + " Plus "
                + str(self.plusHorizontalDegrees)
                + DEGREES
            )

        if protocol == "C":
            self.worker = CProtocols.Protocols(
                self.config.CFactor,
                self.protocolValue,
                self.leftLatAngle,
                self.rightLatAngle,
                self.cycles,
                self.arduino,
                self.config,
            )
            options = (
                "Left: "
                + str(self.leftLatAngle)
                + DEGREES
                + " Right: "
                + str(self.rightLatAngle)
                + DEGREES
            )

        if protocol == "D":
            self.worker = DProtocols.Protocols(
                self.config.CFactor,
                self.protocolValue,
                self.leftLatAngle,
                self.rightLatAngle,
                self.cycles,
                self.arduino,
                self.config,
            )
            options = (
                "Left: "
                + str(self.leftLatAngle)
                + DEGREES
                + " Right: "
                + str(self.rightLatAngle)
                + DEGREES
            )

        if protocol == "AB":
            self.worker = ABProtocols.Protocols(
                self.config.BFactor,
                self.protocolValue,
                self.axialPressure,
                self.minusHorizontalDegrees,
                self.plusHorizontalDegrees,
                self.cycles,
                self.arduino,
            )
            options = "Pressure: " + str(self.axialPressure)

        if protocol == "AC":
            self.plusHorizontalDegrees = 0
            self.worker = ACProtocols.Protocols(
                self.config.CFactor,
                self.protocolValue,
                self.axialPressure,
                self.leftLatAngle,
                self.rightLatAngle,
                self.plusHorizontalDegrees,
                self.cycles,
                self.arduino,
                self.config,
            )
            options = "Pressure: " + str(self.axialPressure)

        if protocol == "AD":
            self.plusHorizontalDegrees = 0
            self.worker = ADProtocols.Protocols(
                self.config.CFactor,
                self.protocolValue,
                self.axialPressure,
                self.leftLatAngle,
                self.rightLatAngle,
                self.plusHorizontalDegrees,
                self.cycles,
                self.arduino,
                self.config,
            )
            options = "Pressure: " + str(self.axialPressure)

        self.worker.signals.finished.connect(self.protocolCompleted)
        self.worker.signals.progress.connect(self.protocolProgress)
        self.worker.signals.APressure.connect(self.AProtocolPressure)

        self.threadpool.start(self.worker)

        self.goTimer.start(500)

    def stop_protocol(self):
        """Stop protocol sequence."""
        print("Stopping protocol")
        self.arduino.send("X")
        self.ui.start_button.setText("Start")
        if self.worker:
            self.worker.stop()

    def execute_protocol(self, protocol, pressure, cycles):
        """Carry out the protocol after initation."""
        print(f"Executing protocol: {protocol}, pressure: {pressure}, cycles: {cycles}")
        if protocol.isdigit() and 1 <= int(protocol) <= 9:
            protocol_number = PROTOCOL_MAPPING[int(protocol)]
            start_degrees = 0

            self.worker = ACProtocols.Protocols(
                self.config.CFactor,
                f"AC{protocol_number}",
                pressure,
                start_degrees,
                cycles,
                self.arduino,
                self.config,
            )
            self.worker.signals.finished.connect(self.protocol_completed)
            self.worker.signals.progress.connect(self.update_protocol_progress)
            self.threadpool.start(self.worker)

            # Start the protocol timer
            self.protocol_start_time = datetime.now()
            self.protocol_total_time = timedelta(
                seconds=cycles * 60  # Assuming 1 minute per cycle
            )
            self.protocol_timer.start(1000)  # Update every second
        else:
            print("Invalid protocol selected")
            QMessageBox.warning(
                self, "Invalid Protocol", "Please select a valid protocol (1-9)."
            )

    def update_protocol_time(self):
        """Populat the remaining time in a protocol."""
        print("Updating protocol time")
        elapsed_time = datetime.now() - self.protocol_start_time
        remaining_time = self.protocol_total_time - elapsed_time
        if remaining_time.total_seconds() <= 0:
            self.protocol_timer.stop()
            remaining_time = timedelta(0)
        self.timer_dialog.update_time(str(remaining_time).split(".")[0])
        print(f"Time remaining: {remaining_time}")

    def status_emit(self, s1, s2, s3, s4):
        print(f"Status emit: {s1}, {s2}, {s3}, {s4}")
        zero = int(self.config.AMarks["0.0"])
        inches = ((s1 + zero) * 8.0) / self.config.AFactor
        print(f"Positioned to {zero} {s1} {inches} in.")

    def update_protocol_progress(self, progress):
        print(f"Updating protocol progress: {progress}")
        self.ui.protocol_progress_label.setText(f"Progress: {progress}")

    def protocol_completed(self):
        print("Protocol completed")
        self.protocol_timer.stop()
        QMessageBox.information(
            self,
            "Protocol Complete",
            "The protocol has finished executing successfully.",
        )

    def reset_arduino(self, event):
        print("Resetting Arduino")
        self.arduino.send("Y")
        QMessageBox.information(self, "Arduino Reset", "Arduino has been reset.")

    def send_zero_mark(self):
        """Send zero mark to Arduino."""
        print("Sending zero mark to Arduino")
        self.arduino.send(
            "L5{:3} {:3}".format(self.config.AMarks["0.0"], self.config.BMarks["0.0"])
        )

    def send_calibration(self):
        """Send calibration data to Arduino."""
        print("Sending calibration data to Arduino")
        self.arduino.send("L0{}".format(self.config.calibration))

    def measure_weight_btn_clicked(self):
        """Measure weight."""
        print("Measuring weight")
        self.arduino.send("L4")

    def measure_location_btn_clicked(self):
        """Measure location."""
        print("Measuring location")
        self.arduino.send("L6")

    def ready_to_go(self):
        """Set I2C status to ready."""
        print("Setting I2C status to ready")
        self.i2c_status = True

    def status(self, position_a, position_b, steps, pressure):
        """Log the status data received from the Arduino."""
        print(
            f"Status received: A {position_a}, B {position_b}, C {steps}, Pressure {pressure}"
        )
        if self.worker:
            self.worker.status(position_a, position_b, steps, pressure)

    def close_event(self, event):
        """Handle window close event."""
        print("Closing application")
        GPIO.cleanup()
        self.arduino.disconnect()
        event.accept()

        if self.worker:
            self.worker.stop()

    def forward_flexion_btn(self, actuator, step, speed_factor):
        """Handle forward flexion button press."""
        print(
            f"Forward flexion button pressed: actuator={actuator}, step={step}, speed_factor={speed_factor}"
        )

        if actuator == self.actuator_b:
            if int(speed_factor) <= 4:
                step = 5
            else:
                step = 10
            print(f"Actuator B current position: {self.horizontal_flexion_position}")
            if (self.horizontal_flexion_position + step) > -5:
                return
            self.horizontal_flexion_position += step
            print(f"New Actuator B position: {self.horizontal_flexion_position}")

            command = "E{}+{}".format(actuator, speed_factor)

            self.arduino.send(command)
            return

        if actuator == self.actuator_a:
            print(f"Actuator A current position: {self.axial_flexion_position}")
            if int(speed_factor) <= 4:
                step = 0.5
            else:
                step = 1

            self.axial_flexion_position += step

            command = "E{}+{}".format(actuator, speed_factor)
            command = "A12{}".format(self.axial_flexion_position)

            self.arduino.send(command)
            print(f"Actuator A new position: {self.axial_flexion_position}")

            time.sleep(0.3)
            self.arduino.send("L5")
            return

        if actuator == self.actuator_c:
            if int(speed_factor) <= 4:
                step = 5
            else:
                step = 10
            if (self.lateral_flexion_position + step) > 20:
                return
            self.lateral_flexion_position += step
            position = self.config.c_marks[
                "{:.1f}".format(self.lateral_flexion_position)
            ]
            print(
                f"Actuator C positioned to {self.lateral_flexion_position} degrees pos {position}"
            )
            command = "K{}".format(position)

            self.arduino.send(command)

    def reverse_flexion_btn(self, actuator, step, speed_factor):
        """Handle reverse flexion button press."""
        print(
            f"Reverse flexion button pressed: actuator={actuator}, step={step}, speed_factor={speed_factor}"
        )
        print(f"Actuator A current position: {self.axial_flexion_position}")

        if actuator == self.actuator_a:
            if int(speed_factor) <= 4:
                step = 0.5
            else:
                step = 1
            if (self.axial_flexion_position - step) < -5:
                return

            self.axial_flexion_position -= step
            command = "A12{}".format(self.axial_flexion_position)

            self.arduino.send(command)
            print(f"Actuator A new position: {self.axial_flexion_position}")

        if actuator == self.actuator_b:
            if int(speed_factor) <= 4:
                step = 5
            else:
                step = 10
            print(f"Actuator B current position: {self.horizontal_flexion_position}")
            if (self.horizontal_flexion_position - step) < -25:
                return
            self.horizontal_flexion_position -= step
            print(f"New Actuator B position: {self.horizontal_flexion_position}")

            command = "E{}-{}".format(actuator, speed_factor)

            self.arduino.send(command)

        if actuator == self.actuator_c:
            print(f"Actuator C current position: {self.lateral_flexion_position}")
            if int(speed_factor) <= 4:
                step = 5
            else:
                step = 10
            if (self.lateral_flexion_position - step) < -20:
                return
            self.lateral_flexion_position -= step

            position = self.config.c_marks[
                "{:.1f}".format(self.lateral_flexion_position)
            ]
            print(
                f"Actuator C positioned to {self.lateral_flexion_position} degrees pos {position}"
            )
            command = "K{}".format(position)

            self.arduino.send(command)

    def reset_flexion_btn(self, actuator):
        """Reset flexion for the given actuator."""
        print(f"Resetting flexion for actuator: {actuator}")
        if actuator == self.actuator_b:
            command = "A{}2".format(actuator)

            self.arduino.send(command)
            self.horizontal_flexion_position = -15
            return

        if actuator == self.actuator_a:
            command = "R{}".format(actuator)

            self.arduino.send(command)
            self.axial_flexion_position = 0
            time.sleep(5)
            self.arduino.send("L0{}".format(self.config.calibration))
            return

        if actuator == self.actuator_c:
            position = self.config.c_marks["{:.1f}".format(0)]
            print(f"Actuator C positioned to {0} degrees pos {position}")
            command = "I14{}".format(position)
            self.arduino.send(command)
            self.lateral_flexion_position = 0
            return

    def protocol_completed(self, finished):
        self.ui.a_program_lbl.setText(" ")
        self.protocol_timer.invalidate()
        if finished:
            print("protocol_completed")
            self.reset_btns(True)
            self.ui.status_lbl.setText("Protocol Completed")
            self.complete_timer.start(500)
            self.blinking_complete_count = 1
            self.blink_complete()
        else:
            print("protocol_stopped")
            self.ui.status_lbl.setText("Protocol STOPPED")

    def clear_status(self):
        self.ui.status_lbl.setText("")
        self.ui.status_lbl_2.setText("")
        self.ui.program_lbl.setText("")
        self.ui.program_lbl_2.setText("")
        self.ui.a_program_lbl.setText("")

    def blink_complete(self):
        if self.blinking_complete:
            self.ui.keypad_widget.setStyleSheet(
                "border-radius:25px;border:4px solid white;background-color:white;"
            )
        else:
            self.ui.keypad_widget.setStyleSheet(
                "border-radius:25px;border:4px solid white;background-color:blue;"
            )
        self.blinking_complete = not self.blinking_complete
        self.blinking_complete_count += 1
        if self.blinking_complete_count > 5:
            self.complete_timer.stop()
            self.blinking_complete = 0

    def blink_go(self):
        if self.blinking_go:
            self.ui.button_go_btn.setStyleSheet("background-color:#78909C")
        else:
            self.ui.button_go_btn.setStyleSheet("background-color:green;")
        self.blinking_go = not self.blinking_go

    def blink_stop(self):
        if self.blinking_stop:
            self.ui.emergency_stop_lbl.setStyleSheet(
                "border:4px solid black;border-radius:20px;background-color:#78909C;"
            )
            self.ui.emergency_stop_2_lbl.setStyleSheet(
                "border:4px solid black;border-radius:20px;background-color:#78909C;"
            )
        else:
            self.ui.emergency_stop_lbl.setStyleSheet(
                "border:4px solid black;border-radius:20px;background-color:red;"
            )
            self.ui.emergency_stop_2_lbl.setStyleSheet(
                "border:4px solid black;border-radius:20px;background-color:red;"
            )
        self.blinking_stop = not self.blinking_stop

    def protocol_progress(self, status):
        print("Progress: {}".format(status))
        if status[:2] == ">>":
            self.ui.status_lbl_2.setText(str(status))

    def btns_clear(self):
        self.elapsed_timer.stop()
        self.ui.time_group.hide()
        self.protocol_timer.invalidate()

        for i in range(len(self.letter_buttons)):
            self.letter_buttons[i].setEnabled(True)
            self.letter_buttons[i].setStyleSheet("background-color: grey;color:white")

        if not self.unlocked:
            self.unlock_code = ""
            self.ui.unlock_key_lbl.setText("")

            for i in range(len(self.number_buttons)):
                self.number_buttons[i].setStyleSheet(
                    "background-color: blue;color:white"
                )

            return

        for i in range(len(self.letter_buttons)):
            self.letter_buttons[i].setEnabled(True)

        for i in range(len(self.number_buttons)):
            self.number_buttons[i].setEnabled(True)

        self.ui.button_go_btn.setEnabled(True)

        self.reset_btns(True)
        self.first_letter = ""
        self.ui.status_lbl_2.setText("")

        if self.worker is not None:
            self.worker.stop()

        self.ui.setup_btn.show()

        self.ui.status_lbl.setText("Protocol Stopped")
        self.stop_timer.stop()
        self.ui.emergency_stop_lbl.setStyleSheet(
            "border:4px solid black;border-radius:20px;background-color:red;"
        )
        self.ui.emergency_stop_2_lbl.setStyleSheet(
            "border:4px solid black;border-radius:20px;background-color:red;"
        )

    def reset_btns(self, letters):
        self.go_timer.stop()
        if self.task:
            self.task.stop()
            print("task stop")
        return
        self.button_value = 0
        self.protocol = ""
        self.first_letter = ""

        self.axial_pressure = 10
        self.minus_horizontal_degrees = 15
        self.plus_horizontal_degrees = 15
        self.left_lat_angle = 0
        self.right_lat_angle = 0
        self.cycles = 1

        for i in range(len(self.number_buttons)):
            self.number_buttons[i].setEnabled(False)
            self.number_buttons[i].setStyleSheet("background-color: blue;color:white")

        for i in range(len(self.letter_buttons)):
            self.letter_buttons[i].setEnabled(True)
            self.letter_buttons[i].setStyleSheet("background-color: grey;color:white")

        self.sender_number = self.ui.button_0_btn

        self.ui.button_go_btn.setEnabled(False)
        self.ui.button_go_btn.setStyleSheet("background-color: green;")

        self.ui.cycles_slider.setValue(1)
        self.ui.cycles_lbl.setText("1")
        self.ui.cycles_slider.setEnabled(True)

        self.ui.axial_pressure_slider.setValue(10)
        self.ui.axial_pressure_lbl.setText("10 lb")
        self.ui.axial_pressure_slider.setEnabled(True)

        self.ui.minus_horizontal_flexion_slider.setValue(15)
        self.ui.minus_horizontal_flexion_lbl.setText("15" + DEGREES)
        self.ui.minus_horizontal_flexion_slider.setEnabled(True)
        self.ui.plus_horizontal_flexion_slider.setValue(15)
        self.ui.plus_horizontal_flexion_lbl.setText("15" + DEGREES)
        self.ui.plus_horizontal_flexion_slider.setEnabled(True)

        self.ui.ab_axial_pressure_slider.setValue(10)
        self.ui.ab_axial_pressure_lbl.setText("10 lb")
        self.ui.minus_ab_horizontal_flexion_slider.setValue(15)
        self.ui.minus_ab_horizontal_flexion_lbl.setText("15" + DEGREES)
        self.ui.plus_ab_horizontal_flexion_slider.setValue(15)
        self.ui.plus_ab_horizontal_flexion_lbl.setText("15" + DEGREES)

        self.ui.a_group_box.hide()
        self.ui.cd_group_box.hide()
        self.ui.b_group_box.hide()
        self.ui.ab_group_box.hide()
        self.ui.ax_group_box.hide()
        self.ui.acd_group_box.hide()
        self.ui.right_lat_flexion_slider.setValue(0)
        self.ui.right_lat_flexion_lbl.setText("0" + DEGREES)
        self.ui.left_lat_flexion_slider.setValue(0)
        self.ui.left_lat_flexion_lbl.setText("0" + DEGREES)

        self.ui.acd_axial_pressure_slider.setValue(10)
        self.ui.acd_axial_pressure_lbl.setText("10 lb")
        self.ui.acd_right_lat_flexion_slider.setValue(0)
        self.ui.acd_right_lat_flexion_lbl.setText("0" + DEGREES)
        self.ui.acd_left_lat_flexion_slider.setValue(0)
        self.ui.acd_left_lat_flexion_lbl.setText("0" + DEGREES)

        self.ui.status_lbl.setText("")
        self.ui.program_lbl.setText("")
        self.ui.program_lbl_2.setText("")

        self.ui.setup_btn.show()

    ### Shutdown methods ###

    def shutdown(self):
        if os.path.exists("debug.txt"):
            self.exit_app()
        print("shutdown")
        self.shutdown_app()

    ### Arduino methods ###

    def setup_arduino(self):
        """Setup Arduino interface."""
        print("Setting up Arduino interface")
        self.arduino = comm.Arduino()
        self.thread = QThread()

        print("Connecting Arduino signals to KneeSpaApp slots")
        self.arduino.doneEmit.connect(self.setDone)
        self.arduino.moveToThread(self.thread)
        self.arduino.finished.connect(self.thread.quit)
        self.arduino.astatus_emit.connect(self.status_emit)
        self.arduino.readyToGoEmit.connect(self.readyToGo)
        self.thread.started.connect(self.arduino.run)

        self.arduino.positionEmit.connect(self.readPosition)
        self.arduino.status_emit.connect(self.status)
        self.arduino.pressureEmit.connect(self.readPressure)
        self.update_leg_length_field

        self.thread.start()

        self.setup_GPIO()

    def blink_slider(self, go):
        print("self.slider_go", self.slider_go)
        if self.slider_go:
            self.ui.horizontalPositionFlexionBtn.setStyleSheet(
                "background-color:#78909C"
            )  # green;color:78909C")
        else:
            self.ui.horizontalPositionFlexionBtn.setStyleSheet(
                "background-color:green;"
            )
        self.slider_go = not self.slider_go

        self.ui.horizontalPositionFlexionBtn.update()

    def blink_reset(self):
        if self.blinking_reset:
            self.ui.reset_arduino_btn.show()
            self.ui.reset_arduino_2_btn.show()
        else:
            self.ui.reset_arduino_btn.hide()
            self.ui.reset_arduino_2_btn.hide()
        self.blinking_reset = not self.blinking_reset
    
    def reset_arduino_btn(self):
        self.ui.reset_arduino_btn.setEnabled(False)
        self.ui.reset_arduino_2_btn.setEnabled(False)
        self.reset_timer.start(500)
    
        self.i2c_status = 0
        self.arduino.send("Y")
        self.i2c_status = 1
        while self.i2c_status == 0:
            time.sleep(0.5)
            QApplication.processEvents()
            print("time.sleep(0.5)", self.i2c_status)
        self.i2c_status = 0
        print("end Y")
        self.blinking_reset = False
        QApplication.processEvents()
        for i in range(12):
            QApplication.processEvents()
            time.sleep(0.3)
    
        self.i2c_status = 0
        self.i2c_status_mark()
        self.i2c_status = 0
        while self.i2c_status == 0:
            time.sleep(0.5)
            QApplication.processEvents()
            print("time.sleep(0.5)", self.i2c_status)
        self.i2c_status = 0
        print("end L5")
        QApplication.processEvents()
        for i in range(12):
            QApplication.processEvents()
            time.sleep(0.3)
    
        QApplication.processEvents()
        position = 0
        print(" positioned to {}".format(position))
        command = "I12{}".format(position)
        self.arduino.send(command)
        self.i2c_status = 0
        QApplication.processEvents()
        while self.i2c_status == 0:
            QApplication.processEvents()
            time.sleep(0.5)
        self.i2c_status = 0
        print("end I12")
        for i in range(5):
            QApplication.processEvents()
            time.sleep(0.3)
    
        QApplication.processEvents()
        position = 1213
        print(" positioned to {}".format(position))
        command = "A132.0"
        self.arduino.send(command)
        self.i2c_status = 0
        while self.i2c_status == 0:
            QApplication.processEvents()
            time.sleep(0.5)
        self.i2c_status = 0
        print("end I13")
        for i in range(5):
            QApplication.processEvents()
            time.sleep(0.3)
    
        QApplication.processEvents()
        position = self.config.c_marks["{:.1f}".format(0)]
        print(" positioned to {} degrees pos {}".format(0, position))
        command = "I14{}".format(position)
        self.arduino.send(command)
        self.i2c_status = 0
        while self.i2c_status == 0:
            QApplication.processEvents()
            time.sleep(0.5)
        self.i2c_status = 0
        print("end I14")
        for i in range(5):
            QApplication.processEvents()
            time.sleep(0.3)
    
        self.arduino.send("L0{}".format(self.config.calibration))
    
        self.ui.horizontal_position_flexion_slider.setValue(-15)
        self.ui.horizontal_position_flexion_lbl.setText("-15" + DEGREES)
        self.setup_horizontal_degrees = -15
    
        self.ui.axial_flexion_position_slider.setValue(0)
        self.ui.axial_flexion_position_lbl.setText("0 in")
        self.axial_flexion_position = 0
    
        self.ui.lateral_flexion_position_slider.setValue(0)
        self.ui.lateral_flexion_position_lbl.setText("0" + DEGREES)
        self.setup_lateral_degrees = 0
        self.ui.reset_arduino_btn.setEnabled(True)
        self.ui.reset_arduino_2_btn.setEnabled(True)
        self.blinking_reset = True
        self.blink_reset()
        self.reset_timer.stop()


    def setup_GPIO(self):
        """Setup GPIO pins."""
        print("Setting up GPIO pins")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        GPIO.setup(EMERGENCYSTOP, GPIO.OUT)
        GPIO.setup(EXTRAFORWARD, GPIO.OUT)
        GPIO.setup(EXTRABACKWARD, GPIO.OUT)
        GPIO.setup(EXTRAENABLE, GPIO.OUT)

        GPIO.output(EMERGENCYSTOP, GPIO.HIGH)
        GPIO.output(EXTRAENABLE, GPIO.HIGH)

        print("GPIO setup completed")


def main():
    """Main function to start the application."""
    print(f"Application started at {datetime.now()}")

    app = QApplication(sys.argv)
    window = KneeSpaApp()
    window.show()

    app.exec_()

    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        GPIO.cleanup()
