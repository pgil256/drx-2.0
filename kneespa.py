import sys
import os
import csv
import config
import RPi.GPIO as GPIO
from time import sleep
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
)
from Arduino import comm
from video.video_player import VideoPlayerDialog
from Protocols import preconfigured_protocols


# Constants
DEGREES0 = 0
DEGREES5 = 5
DEGREES10 = 10

EMERGENCYSTOP = 16
EXTRAFORWARD = 27
EXTRABACKWARD = 22
EXTRAENABLE = 17

AC_PROTOCOL_MAPPING = {
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

# Define worker signals
class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""

    finished = QtCore.pyqtSignal()
    stopped = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(tuple)
    result = QtCore.pyqtSignal(object)
    progress = QtCore.pyqtSignal(str)
    APressure = QtCore.pyqtSignal(str)
    statusEmit = QtCore.pyqtSignal(int, int, int, float)
    AstatusEmit = QtCore.pyqtSignal(int, int, int, float)

# Optional Dialog Boxes
class TimerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("Initializing TimerDialog")
        self.setWindowTitle("Protocol Timer")
        self.layout = QVBoxLayout()
        self.timer_label = QLabel("Estimated time remaining: ")
        self.layout.addWidget(self.timer_label)
        self.setLayout(self.layout)

    def update_time(self, time_remaining):
        print(f"Updating time in TimerDialog: {time_remaining}")
        self.timer_label.setText(f"Estimated time remaining: {time_remaining}")

class PressureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("Initializing PressureDialog")
        self.setWindowTitle("Current Pressure")
        self.layout = QVBoxLayout()
        self.pressure_label = QLabel("Current pressure: ")
        self.layout.addWidget(self.pressure_label)
        self.setLayout(self.layout)

    def update_pressure(self, pressure):
        print(f"Updating pressure in PressureDialog: {pressure}")
        self.pressure_label.setText(f"Current pressure: {pressure} lbs")

# Main Python class
class KneeSpaApp(QMainWindow):
    """Main application class for KneeSpa."""

    def __init__(self):
        super().__init__()
        print("Initializing KneeSpaApp")
        try:
            self.ui = uic.loadUi("UI/kneespa.ui", self)
        except FileNotFoundError:
            print("UI file 'kneespa.ui' not found.")
            QMessageBox.critical(self, "Error", "UI file 'kneespa.ui' not found.")
            sys.exit(1)

        self.newC = True
        self.ui.showFullScreen()
        self.setWindowFlags(Qt.FramelessWindowHint)

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

        self.timer_dialog = TimerDialog(self)
        self.pressure_dialog = PressureDialog(self)

        self.threadpool = QtCore.QThreadPool()
        print(f"Multithreading with maximum {self.threadpool.maxThreadCount()} threads")
        self.worker = None
        self.setup_arduino()
        self.setup_timers()

        self.config = config.Configuration()
        self.config.getConfig()

        self.CMarks = {}
        for i in range(16):
            u = (i * 220) + 98
            angle = (i * 2.5) - 20
            print(f"Mark {i}: angle {angle}, value {u}")
            self.CMarks[angle] = u

        QTimer.singleShot(2000, self.sendCalibration)
        QTimer.singleShot(5000, self.sendZeroMark)

        QTimer.singleShot(1000, self.show_arduino_info_dialog)

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

    # Arduino methods
    def setup_arduino(self):
        """Setup Arduino interface."""
        print("Setting up Arduino interface")
        self.arduino = comm.Arduino()
        self.thread = QThread()

        print("Connecting Arduino signals to KneeSpaApp slots")
        self.arduino.doneEmit.connect(self.setDone)
        self.arduino.moveToThread(self.thread)
        self.arduino.finished.connect(self.thread.quit)
        self.arduino.AstatusEmit.connect(self.statusEmit)
        self.arduino.readyToGoEmit.connect(self.readyToGo)
        self.thread.started.connect(self.arduino.run)

        self.arduino.positionEmit.connect(self.readPosition)
        self.arduino.statusEmit.connect(self.status)
        self.arduino.pressureEmit.connect(self.readPressure)
        self.update_leg_length_field

        self.thread.start()

        self.setupGPIO()

    def setupGPIO(self):
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

    ### UI Methods ###

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
            self.video_player_dialog = VideoPlayerDialog(self)
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

    def logProtocol(self, protocol, cycles, pressure):
        print(f"Logging protocol: {protocol}, cycles: {cycles}, pressure: {pressure}")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp},{self.current_user['username']},{protocol},{cycles},{pressure}\n"

        with open("protocol_log.csv", "a") as log_file:
            log_file.write(log_entry)
        print("Protocol logged successfully")

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

    @QtCore.pyqtSlot()
    def setDone(self):
        """Set the I2C status to done."""
        print("Setting I2C status to done")
        self.I2Cstatus = True
        if self.worker:
            self.worker.I2CStatus()

    def readyToGo(self):
        """Set the I2C status to ready."""
        print("Setting I2C status to ready")
        self.I2Cstatus = True

    def readPosition(self, position, steps, actuator):
        """Read position data from the Arduino."""
        print(
            f"Reading position: position={position}, steps={steps}, actuator={actuator}"
        )
        if hasattr(self, "actuatorB") and actuator == self.actuatorB:
            inches = (position * 6) / self.config.BFactor
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator B): {inches}")
            degrees = int(-(25 - (inches / 5) * 25))
            print(f"Degrees (actuator B): {degrees}")
        elif hasattr(self, "actuatorA") and actuator == self.actuatorA:
            inches = (position * 6) / self.config.AFactor
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator A): {inches}")
        elif hasattr(self, "actuatorC") and actuator == self.actuatorC:
            inches = steps / (self.config.CFactor / 6)
            inches = round(inches * 2.0) / 2.0
            print(f"Inches (actuator C): {inches}")
            degrees = int((inches * 20) - 20)
            print(f"Degrees (actuator C): {degrees}")

    def readPressure(self, pressure):
        """Read pressure data from the Arduino."""
        print(f"Reading pressure: {pressure}")

    def start_protocol(self):
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

        self.logProtocol(protocol, cycles, pressure)
        self.execute_protocol(protocol, pressure, cycles)

    def stop_protocol(self):
        print("Stopping protocol")
        self.arduino.send("X")
        self.ui.start_button.setText("Start")
        if self.worker:
            self.worker.stop()

    def execute_protocol(self, protocol, pressure, cycles):
        print(f"Executing protocol: {protocol}, pressure: {pressure}, cycles: {cycles}")
        if protocol.isdigit() and 1 <= int(protocol) <= 9:
            protocol_number = AC_PROTOCOL_MAPPING[int(protocol)]
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
        print("Updating protocol time")
        elapsed_time = datetime.now() - self.protocol_start_time
        remaining_time = self.protocol_total_time - elapsed_time
        if remaining_time.total_seconds() <= 0:
            self.protocol_timer.stop()
            remaining_time = timedelta(0)
        self.timer_dialog.update_time(str(remaining_time).split(".")[0])
        print(f"Time remaining: {remaining_time}")

    def statusEmit(self, s1, s2, s3, s4):
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

    def sendZeroMark(self):
        """Send zero mark to Arduino."""
        print("Sending zero mark to Arduino")
        self.arduino.send(
            "L5{:3} {:3}".format(self.config.AMarks["0.0"], self.config.BMarks["0.0"])
        )

    def sendCalibration(self):
        """Send calibration data to Arduino."""
        print("Sending calibration data to Arduino")
        self.arduino.send("L0{}".format(self.config.calibration))

    def measureWeightBtnClicked(self):
        """Measure weight."""
        print("Measuring weight")
        self.arduino.send("L4")

    def measureLocationBtnClicked(self):
        """Measure location."""
        print("Measuring location")
        self.arduino.send("L6")

    def readyToGo(self):
        """Set I2C status to ready."""
        print("Setting I2C status to ready")
        self.I2Cstatus = True

    def status(self, positionA, positionB, steps, pressure):
        """Log the status data received from the Arduino."""
        print(
            f"Status received: A {positionA}, B {positionB}, C {steps}, Pressure {pressure}"
        )
        if self.worker:
            self.worker.status(positionA, positionB, steps, pressure)

    def closeEvent(self, event):
        """Handle window close event."""
        print("Closing application")
        GPIO.cleanup()
        self.arduino.disconnect()
        event.accept()

        if self.worker:
            self.worker.stop()

    def forwardFlexionBtn(self, actuator, step, speedFactor):
        """Handle forward flexion button press."""
        print(
            f"Forward flexion button pressed: actuator={actuator}, step={step}, speedFactor={speedFactor}"
        )

        if actuator == self.actuatorB:
            if int(speedFactor) <= 4:
                step = 5
            else:
                step = 10
            print(f"Actuator B current position: {self.horizontalFlexionPosition}")
            if (self.horizontalFlexionPosition + step) > -5:
                return
            self.horizontalFlexionPosition += step
            print(f"New Actuator B position: {self.horizontalFlexionPosition}")

            command = "E{}+{}".format(actuator, speedFactor)

            self.arduino.send(command)
            return

        if actuator == self.actuatorA:
            print(f"Actuator A current position: {self.axialFlexionPosition}")
            if int(speedFactor) <= 4:
                step = 0.5
            else:
                step = 1

            self.axialFlexionPosition += step

            command = "E{}+{}".format(actuator, speedFactor)
            command = "A12{}".format(self.axialFlexionPosition)

            self.arduino.send(command)
            print(f"Actuator A new position: {self.axialFlexionPosition}")

            sleep(0.3)
            self.arduino.send("L5")
            return

        if actuator == self.actuatorC:
            if int(speedFactor) <= 4:
                step = 5
            else:
                step = 10
            if (self.lateralFlexionPosition + step) > 20:
                return
            self.lateralFlexionPosition += step
            position = self.config.CMarks["{:.1f}".format(self.lateralFlexionPosition)]
            print(
                f"Actuator C positioned to {self.lateralFlexionPosition} degrees pos {position}"
            )
            command = "K{}".format(position)

            self.arduino.send(command)

    def reverseFlexionBtn(self, actuator, step, speedFactor):
        """Handle reverse flexion button press."""
        print(
            f"Reverse flexion button pressed: actuator={actuator}, step={step}, speedFactor={speedFactor}"
        )
        print(f"Actuator A current position: {self.axialFlexionPosition}")

        if actuator == self.actuatorA:
            if int(speedFactor) <= 4:
                step = 0.5
            else:
                step = 1
            if (self.axialFlexionPosition - step) < -5:
                return

            self.axialFlexionPosition -= step
            command = "A12{}".format(self.axialFlexionPosition)

            self.arduino.send(command)
            print(f"Actuator A new position: {self.axialFlexionPosition}")

        if actuator == self.actuatorB:
            if int(speedFactor) <= 4:
                step = 5
            else:
                step = 10
            print(f"Actuator B current position: {self.horizontalFlexionPosition}")
            if (self.horizontalFlexionPosition - step) < -25:
                return
            self.horizontalFlexionPosition -= step
            print(f"New Actuator B position: {self.horizontalFlexionPosition}")

            command = "E{}-{}".format(actuator, speedFactor)

            self.arduino.send(command)

        if actuator == self.actuatorC:
            print(f"Actuator C current position: {self.lateralFlexionPosition}")
            if int(speedFactor) <= 4:
                step = 5
            else:
                step = 10
            if (self.lateralFlexionPosition - step) < -20:
                return
            self.lateralFlexionPosition -= step

            position = self.config.CMarks["{:.1f}".format(self.lateralFlexionPosition)]
            print(
                f"Actuator C positioned to {self.lateralFlexionPosition} degrees pos {position}"
            )
            command = "K{}".format(position)

            self.arduino.send(command)

    def resetFlexionBtn(self, actuator):
        """Reset flexion for the given actuator."""
        print(f"Resetting flexion for actuator: {actuator}")
        if actuator == self.actuatorB:
            command = "A{}2".format(actuator)

            self.arduino.send(command)
            self.horizontalFlexionPosition = -15
            return

        if actuator == self.actuatorA:
            command = "R{}".format(actuator)

            self.arduino.send(command)
            self.axialFlexionPosition = 0
            sleep(5)
            self.arduino.send("L0{}".format(self.config.calibration))
            return

        if actuator == self.actuatorC:
            position = self.config.CMarks["{:.1f}".format(0)]
            print(f"Actuator C positioned to {0} degrees pos {position}")
            command = "I14{}".format(position)
            self.arduino.send(command)
            self.lateralFlexionPosition = 0
            return


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
