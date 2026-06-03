from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget
)
from PyQt5.QtCore import Qt
import time

class TimerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("TimerDialog: Initializing timer dialog")
        self.setWindowTitle("Protocol Timer")
        self.setFixedSize(325, 150)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #3498db;
                border-radius: 12px;
            }
            QLabel {
                color: #2c3e50;
                font-family: 'Segoe UI', Arial;
                font-size: 22px;
                font-weight: bold;
                padding: 15px;
                qproperty-alignment: AlignCenter;
            }
        """)

        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Time Label
        self.time_label = QLabel("Time Remaining: 00:00")
        layout.addWidget(self.time_label)
        
        self.setLayout(layout)

        # Store protocol state
        self.protocol_start_time = None
        self.protocol_duration = None
        print("TimerDialog: Initialization complete")

    def initialize_protocol_time(self, start_time, duration):
        print(f"TimerDialog: Initializing protocol timer - Duration: {duration}s ({duration//60}m {duration%60}s)")
        self.protocol_start_time = start_time
        self.protocol_duration = duration
        self.update_time()
        
    def update_time(self, remaining_seconds=None):
        if remaining_seconds is None and self.protocol_start_time and self.protocol_duration:
            elapsed = time.time() - self.protocol_start_time
            remaining_seconds = max(0, self.protocol_duration - int(elapsed))
        elif remaining_seconds is None:
            remaining_seconds = 0

        # Ensure we're working with integers
        remaining_seconds = int(remaining_seconds)
        minutes = int(remaining_seconds // 60)
        seconds = int(remaining_seconds % 60)

        # Color coding for remaining time
        if remaining_seconds <= 30:
            self.time_label.setStyleSheet("color: #e74c3c;")  # Red
            level = "CRITICAL"
        elif remaining_seconds <= 60:
            self.time_label.setStyleSheet("color: #f39c12;")  # Orange
            level = "LOW"
        else:
            self.time_label.setStyleSheet("color: #2c3e50;")  # Default blue-gray
            level = "NORMAL"

        # Only print every 10 seconds to avoid spam
        if remaining_seconds % 10 == 0 or remaining_seconds <= 30:
            print(f"TimerDialog: Time remaining {minutes:02d}:{seconds:02d} [{level}]")

        self.time_label.setText(f"Time Remaining: {minutes:02d}:{seconds:02d}")
        
    def showEvent(self, event):
        print("TimerDialog: Dialog shown")
        parent = self.parent()
        if parent and hasattr(parent, 'protocol_start_time') and hasattr(parent, 'protocol_duration'):
            if parent.protocol_start_time and parent.protocol_duration:
                self.initialize_protocol_time(parent.protocol_start_time, parent.protocol_duration)
        super().showEvent(event)