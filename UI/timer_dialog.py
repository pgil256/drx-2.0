from PyQt5 import QtCore, QtGui, QtWidgets, uic, QDialog, QVBoxLayout, QLabel
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, Qt

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
