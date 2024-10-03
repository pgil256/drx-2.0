from PyQt5 import QtCore, QtGui, QtWidgets, uic, QDialog, QVBoxLayout, QLabel
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, Qt

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
