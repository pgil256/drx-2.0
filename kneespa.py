import sys
import csv
import os
from PyQt5 import QtWidgets, QtCore, uic
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QPixmap
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QDesktopWidget,
    QMessageBox,
    QDialog,
    QVBoxLayout,
)


class VideoPlayerDialog(QDialog):
    def __init__(self, parent=None):
        super(VideoPlayerDialog, self).__init__(parent)
        uic.loadUi("video-player.ui", self)

        # Create QVideoWidget and add it to the video_container
        self.video_player_widget = QVideoWidget()
        video_container = self.findChild(QWidget, "video_container")
        layout = QVBoxLayout(video_container)
        layout.addWidget(self.video_player_widget)
        video_container.setLayout(layout)

        self.play_button = self.findChild(QtWidgets.QPushButton, "play_button")
        self.pause_button = self.findChild(QtWidgets.QPushButton, "pause_button")
        self.seekSlider = self.findChild(QtWidgets.QSlider, "seekSlider")

        self.forward_button_video = self.findChild(
            QtWidgets.QLabel, "forward_button_video"
        )
        self.backward_button_video = self.findChild(
            QtWidgets.QLabel, "backward_button_video"
        )

        self.mediaPlayer = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.mediaPlayer.setVideoOutput(self.video_player_widget)

        self.play_button.clicked.connect(self.play_video)
        self.pause_button.clicked.connect(self.pause_video)
        self.seekSlider.sliderMoved.connect(self.set_position)

        self.mediaPlayer.positionChanged.connect(self.position_changed)
        self.mediaPlayer.durationChanged.connect(self.duration_changed)

        self.mediaPlayer.error.connect(self.handle_error)

        # Connect video navigation buttons
        self.forward_button_video.mousePressEvent = self.show_next_video
        self.backward_button_video.mousePressEvent = self.show_previous_video

        # Initialize video list and current video index
        self.video_list = ["1.mp4", "2.mp4"]
        self.current_video_index = 0

    def play_video(self):
        if self.mediaPlayer.state() != QMediaPlayer.PlayingState:
            self.mediaPlayer.play()

    def pause_video(self):
        if self.mediaPlayer.state() == QMediaPlayer.PlayingState:
            self.mediaPlayer.pause()

    def set_position(self, position):
        self.mediaPlayer.setPosition(position)

    def position_changed(self, position):
        self.seekSlider.setValue(position)

    def duration_changed(self, duration):
        self.seekSlider.setRange(0, duration)

    def set_media(self, file_path):
        if os.path.exists(file_path):
            if os.access(file_path, os.R_OK):
                self.mediaPlayer.setMedia(QMediaContent(QUrl.fromLocalFile(file_path)))
            else:
                QMessageBox.critical(
                    self, "Error", f"Permission denied: Cannot read {file_path}"
                )
        else:
            QMessageBox.critical(self, "Error", f"Video file not found: {file_path}")

    def handle_error(self):
        error_msg = self.mediaPlayer.errorString()
        QMessageBox.critical(self, "Media Error", f"Error: {error_msg}")

    def show_next_video(self, event):
        self.current_video_index = (self.current_video_index + 1) % len(self.video_list)
        self.load_current_video()

    def show_previous_video(self, event):
        self.current_video_index = (self.current_video_index - 1) % len(self.video_list)
        self.load_current_video()

    def load_current_video(self):
        video_path = os.path.abspath(
            f"videos/{self.video_list[self.current_video_index]}"
        )
        self.set_media(video_path)
        self.play_video()


class KneeSpaApp(QtWidgets.QMainWindow):
    def __init__(self):
        super(KneeSpaApp, self).__init__()
        try:
            uic.loadUi("kneespa.ui", self)
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", "UI file 'kneespa.ui' not found.")
            sys.exit(1)

        # Set window to fullscreen
        self.showFullScreen()

        self.setWindowFlags(Qt.FramelessWindowHint)

        # Ensure the central widget takes up all available space
        self.centralWidget().setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )

        self.login_pin = ""
        self.patient_pin = ""

        # Initialize table widget
        self.table_widget = self.findChild(
            QtWidgets.QTableWidget, "patient_table_widget"
        )
        if self.table_widget:
            self.table_widget.verticalHeader().setVisible(True)

        # Initialize user and patient data
        self.users = self.load_csv("users/user_pins.csv")
        self.patients = self.load_csv("patients/patient_pins.csv")
        self.current_user = None

        # Stacked widget pages
        self.home_page = 0
        self.main_page = 1
        self.help_page = 2
        self.profile_page = 3

        # Buttons
        self.protocols_button = self.findChild(
            QtWidgets.QPushButton, "protocols_button"
        )
        self.help_button = self.findChild(QtWidgets.QPushButton, "help_button")
        self.login_button = self.findChild(QtWidgets.QPushButton, "login_button")
        self.start_button = self.findChild(QtWidgets.QPushButton, "push_button_start")
        self.enter_patient_button = self.findChild(
            QtWidgets.QPushButton, "enter_patient_pin_button"
        )

        # Labels acting as buttons
        self.profile_button = self.findChild(QtWidgets.QLabel, "profile_button")
        self.video_player_button = self.findChild(
            QtWidgets.QLabel, "video_player_button"
        )
        self.brand_label = self.findChild(QtWidgets.QLabel, "top_nav_brand_label")
        self.brand_logo = self.findChild(QtWidgets.QLabel, "top_nav_logo")

        # User information labels
        self.username_nav = self.findChild(QtWidgets.QLabel, "username_nav")
        self.username_profile = self.findChild(QtWidgets.QLabel, "username_field")
        self.email_profile = self.findChild(QtWidgets.QLabel, "email_field")
        self.status_profile = self.findChild(QtWidgets.QLabel, "status_field")

        # Protocol image controls
        self.label_protocol_image = self.findChild(
            QtWidgets.QLabel, "label_protocol_image"
        )
        self.protocol_image_number = self.findChild(
            QtWidgets.QLineEdit, "protocol_number_field"
        )
        self.forward_button_protocol_image = self.findChild(
            QtWidgets.QLabel, "forward_button_protocol_image"
        )
        self.backward_button_protocol_image = self.findChild(
            QtWidgets.QLabel, "backward_button_protocol_image"
        )

        # Initialize protocol image
        self.current_image_number = 1
        self.update_protocol_image()

        # Connect protocol image navigation buttons
        self.forward_button_protocol_image.mousePressEvent = (
            self.show_next_protocol_image
        )
        self.backward_button_protocol_image.mousePressEvent = (
            self.show_previous_protocol_image
        )

        # Pressure field controls
        self.pressure_field = self.findChild(QtWidgets.QLineEdit, "pressure_field")
        self.plus_label_pressure = self.findChild(
            QtWidgets.QLabel, "plus_label_pressure"
        )
        self.minus_label_pressure = self.findChild(
            QtWidgets.QLabel, "minus_label_pressure"
        )

        # Initialize pressure field
        self.current_pressure = 40
        self.update_pressure_field()

        # Connect pressure field navigation buttons
        self.plus_label_pressure.mousePressEvent = self.increase_pressure
        self.minus_label_pressure.mousePressEvent = self.decrease_pressure

        # Leg length field controls
        self.leg_length_field = self.findChild(QtWidgets.QLineEdit, "leg_length_field")
        self.plus_label_leg_length = self.findChild(
            QtWidgets.QLabel, "plus_label_leg_length"
        )
        self.minus_label_leg_length = self.findChild(
            QtWidgets.QLabel, "minus_label_leg_length"
        )

        # Initialize leg length field
        self.current_leg_length = 6.0
        self.update_leg_length_field()

        # Connect leg length field navigation buttons
        self.plus_label_leg_length.mousePressEvent = self.increase_leg_length
        self.minus_label_leg_length.mousePressEvent = self.decrease_leg_length

        # Connect buttons to functions if they are found
        if self.protocols_button:
            self.protocols_button.clicked.connect(self.show_main_page)
        else:
            print("Error: 'protocols_button' not found")

        if self.help_button:
            self.help_button.clicked.connect(self.show_help_page)
        else:
            print("Error: 'help_button' not found")

        if self.login_button:
            self.login_button.clicked.connect(self.show_login_dialog)
        else:
            print("Error: 'login_button' not found")

        if self.start_button:
            self.start_button.clicked.connect(self.start_or_stop_protocol)
        else:
            print("Error: 'start_button' not found")

        if self.enter_patient_button:
            self.enter_patient_button.clicked.connect(self.show_enter_patient_dialog)
        else:
            print("Error: 'enter_patient_pin_button' not found")

        # Connect edit and clear patient data buttons
        self.edit_patient_button.clicked.connect(self.edit_patient_data)
        self.clear_patient_button.clicked.connect(self.clear_patient_data)

        if self.profile_button:
            self.profile_button.mousePressEvent = self.show_profile_page
        else:
            print("Error: 'profile_button' not found")

        if self.video_player_button:
            self.video_player_button.mousePressEvent = self.show_video_player_dialog
        else:
            print("Error: 'video_player_button' not found")

        if self.brand_label:
            self.brand_label.mousePressEvent = self.return_to_home_page
        else:
            print("Error: 'brand_label' not found")

        if self.brand_logo:
            self.brand_logo.mousePressEvent = self.return_to_home_page
        else:
            print("Error: 'brand_logo' not found")

        # Set the initial page to home_page
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

        # Initialize the dialogs
        self.login_dialog = None
        self.init_login_dialog()
        self.enter_patient_dialog = None
        self.init_enter_patient_dialog()
        self.video_player_dialog = None

    def update_protocol_image(self):
        image_path = (
            f"images/graphics/protocol-graphics/{self.current_image_number}.png"
        )
        self.label_protocol_image.setPixmap(QPixmap(image_path))
        self.protocol_image_number.setText(str(self.current_image_number))

    def show_next_protocol_image(self, event):
        if self.current_image_number < 18:
            self.current_image_number += 1
            self.update_protocol_image()

    def show_previous_protocol_image(self, event):
        if self.current_image_number > 1:
            self.current_image_number -= 1
            self.update_protocol_image()

    def update_pressure_field(self):
        self.pressure_field.setText(f"{self.current_pressure} lbs")

    def increase_pressure(self, event):
        if self.current_pressure < 100:
            self.current_pressure += 5
            self.update_pressure_field()

    def decrease_pressure(self, event):
        if self.current_pressure > 0:
            self.current_pressure -= 5
            self.update_pressure_field()

    def update_leg_length_field(self):
        self.leg_length_field.setText(f"{self.current_leg_length:.1f} in")

    def increase_leg_length(self, event):
        if self.current_leg_length < 18:
            self.current_leg_length += 0.5
            self.update_leg_length_field()

    def decrease_leg_length(self, event):
        if self.current_leg_length > 0:
            self.current_leg_length -= 0.5
            self.update_leg_length_field()

    def start_or_stop_protocol(self):
        if self.start_button.text() == "Start":
            self.start_button.setText("Stop")
            self.start_button.setStyleSheet(
                "background-color: rgb(200, 0, 0);"
                "color: white;"
                "border: none;"
                "text-decoration: bold;"
                "margin: 0px 15px;"
                "font-size: 32px;"
                "font-weight: bold;"
                "border-radius: 12px;"
            )
        else:
            self.start_button.setText("Start")
            self.start_button.setStyleSheet(
                "background-color: rgb(0, 200, 0);"
                "color: white;"
                "border: none;"
                "text-decoration: bold;"
                "margin: 0px 15px;"
                "font-size: 32px;"
                "font-weight: bold;"
                "border-radius: 12px;"
            )

    def load_csv(self, filename):
        data = {}
        try:
            with open(filename, "r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data[row["pin"]] = row
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", f"CSV file not found: {filename}")
        except csv.Error as e:
            QMessageBox.critical(self, "Error", f"CSV file error in {filename}: {e}")
        return data

    def save_patient_data(self):
        if self.current_user and self.current_user["status"] == "admin":
            current_pin = (
                self.patient_pin
            )  # Assuming you store the current patient's PIN
            if current_pin in self.patients:
                for row in range(self.table_widget.rowCount()):
                    key = (
                        self.table_widget.item(row, 0).text().lower().replace(" ", "_")
                    )
                    value = self.table_widget.item(row, 1).text()
                    self.patients[current_pin][key] = value

                # Update CSV file
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
            else:
                QMessageBox.warning(self, "Error", "No patient data to save.")
        else:
            QMessageBox.warning(
                self, "Access Denied", "Only admins can save patient data."
            )

    def show_login_dialog(self):
        self.login_pin = ""
        self.login_line_edit.clear()
        self.login_dialog.exec_()

    def init_login_dialog(self):
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
        self.login_line_edit.setText(self.login_line_edit.text() + "*")
        self.login_pin = self.login_pin + value

    def append_patient_star(self, value):
        self.patient_pin_input.setText(self.patient_pin_input.text() + "*")
        self.patient_pin += value

    def clear_login_line_edit(self):
        self.login_line_edit.clear()
        self.login_pin = ""

    def show_login_help_dialog(self):
        help_dialog = QtWidgets.QDialog(self)
        uic.loadUi("login-help.ui", help_dialog)
        help_dialog.exec_()

    def show_enter_patient_help_dialog(self):
        help_dialog = QtWidgets.QDialog(self)
        uic.loadUi("enter-patient-help.ui", help_dialog)
        help_dialog.exec_()

    def handle_login(self):
        if self.login_pin in self.users:
            self.current_user = self.users[self.login_pin]
            self.login_line_edit.clear()
            self.login_pin = ""
            self.update_ui_after_login()
            self.login_dialog.accept()
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid PIN. Please try again.")

    def update_ui_after_login(self):
        self.username_nav.setText(self.current_user["username"])
        self.username_profile.setText(self.current_user["username"])
        self.email_profile.setText(self.current_user["email"])
        self.status_profile.setText(self.current_user["status"])
        self.login_button.setText("Logout")
        self.login_button.clicked.disconnect()
        self.login_button.clicked.connect(self.handle_logout)

    def handle_logout(self):
        self.username_nav.setText("")
        self.username_profile.setText("")
        self.email_profile.setText("")
        self.status_profile.setText("")
        self.login_button.setText("Login")
        self.login_button.clicked.disconnect()
        self.login_button.clicked.connect(self.show_login_dialog)
        self.clear_patient_data()

        # Reset the page to home_page
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def handle_patient_pin(self):
        if self.patient_pin in self.patients:
            self.update_patient_table(self.patients[self.patient_pin])
            self.enter_patient_dialog.accept()
        else:
            QMessageBox.warning(
                self, "Invalid PIN", "Patient not found. Please try again."
            )
        self.patient_pin = ""  # Clear the PIN after handling

    def update_patient_table(self, patient_data):
        for row, (key, value) in enumerate(patient_data.items()):
            if key != "pin":
                self.table_widget.setItem(
                    row - 1,
                    0,
                    QtWidgets.QTableWidgetItem(key.replace("_", " ").title()),
                )
                self.table_widget.setItem(row - 1, 1, QtWidgets.QTableWidgetItem(value))
        QMessageBox.information(self, "Success", "Patient data loaded successfully.")

    def init_enter_patient_dialog(self):
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
        self.patient_pin = ""
        self.patient_pin_input.clear()
        self.enter_patient_dialog.exec_()

    def edit_patient_data(self):
        if not self.current_user:
            QMessageBox.warning(self, "Access Denied", "Please log in first.")
            return

        if self.current_user["status"] != "admin":
            QMessageBox.warning(
                self, "Access Denied", "Only admins can edit patient data."
            )
            return

        # Enable editing for the second column
        for row in range(self.table_widget.rowCount()):
            item = self.table_widget.item(row, 1)
            if item:
                item.setFlags(item.flags() | Qt.ItemIsEditable)

        # Connect itemChanged signal to save_patient_data method
        self.table_widget.itemChanged.connect(self.save_patient_data)

        QMessageBox.information(
            self,
            "Edit Mode",
            "You can now edit patient data. Changes will be saved automatically.",
        )

    def clear_patient_data(self):
        for row in range(self.table_widget.rowCount()):
            self.table_widget.setItem(row, 1, QtWidgets.QTableWidgetItem(""))
        QMessageBox.information(self, "Success", "Patient data cleared successfully.")

    def clear_patient_line_edit(self):
        self.patient_pin_input.clear()
        self.patient_pin = ""

    def show_home_page(self):
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def return_to_home_page(self, event):
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.home_page
        )

    def show_main_page(self):
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.main_page
        )
        if self.findChild(QtWidgets.QTabWidget, "DRx_tabs"):
            self.findChild(QtWidgets.QTabWidget, "DRx_tabs").setCurrentIndex(0)

    def show_help_page(self):
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.help_page
        )

    def show_profile_page(self, event):
        self.findChild(QtWidgets.QStackedWidget, "stackedWidget").setCurrentIndex(
            self.profile_page
        )

    def show_video_player_dialog(self, event):
        if not self.video_player_dialog:
            self.video_player_dialog = VideoPlayerDialog(self)
            self.video_player_dialog.load_current_video()
        self.video_player_dialog.show()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = KneeSpaApp()
    window.show()
    sys.exit(app.exec_())
