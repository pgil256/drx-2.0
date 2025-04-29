from PyQt5 import QtCore, QtGui, QtWidgets, uic
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtCore import QUrl, Qt
from main.config.constants import DIALOG_STYLES, DIALOG_DIMENSIONS


class PressureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Current Pressure")
        self.setFixedSize(*DIALOG_DIMENSIONS["PRESSURE"])
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        
        self.setStyleSheet(DIALOG_STYLES["PRESSURE"])

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # Pressure Label
        self.pressure_label = QLabel("Pressure: 0 lbs")
        layout.addWidget(self.pressure_label)

        self.setLayout(layout)

    def update_pressure(self, pressure):
        # Color coding based on pressure
        if pressure >= 70:
            color = "#e74c3c"  # Red
        elif pressure >= 50:
            color = "#f39c12"  # Orange
        else:
            color = "#27ae60"  # Green
            
        self.pressure_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
        self.pressure_label.setText(f"Pressure: {pressure:.1f} lbs")