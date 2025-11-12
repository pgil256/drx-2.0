from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt


class PressureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        print("PressureDialog: Initializing pressure dialog")
        self.setWindowTitle("Current Pressure")
        self.setFixedSize(325, 150)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        
        self.setStyleSheet("""
            QDialog {
                background-color: white;
                border: 2px solid #3498db;
                border-radius: 12px;
            }
            QLabel {
                color: #27ae60;
                font-family: 'Segoe UI', Arial;
                font-size: 22px;
                font-weight: bold;
                padding: 10px;
                qproperty-alignment: AlignCenter;
            }
        """)

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # Pressure Label
        self.pressure_label = QLabel("Pressure: 0 lbs")
        layout.addWidget(self.pressure_label)

        self.setLayout(layout)

        # Store the last shown pressure to avoid unnecessary updates
        self.last_pressure = 0
        print("PressureDialog: Initialization complete")

    def update_pressure(self, pressure):
        """Update the pressure display with the current pressure value."""
        # Ensure pressure is a float and not None
        try:
            if pressure is None:
                pressure = 0.0
            pressure = float(pressure)
            
            # Only update if pressure has changed significantly (> 0.5 lbs)
            if abs(pressure - self.last_pressure) > 0.5:
                self.last_pressure = pressure

                # Color coding based on pressure
                if pressure >= 70:
                    color = "#e74c3c"  # Red
                    level = "HIGH"
                elif pressure >= 50:
                    color = "#f39c12"  # Orange
                    level = "MEDIUM"
                else:
                    color = "#27ae60"  # Green
                    level = "NORMAL"

                print(f"PressureDialog: Pressure update {pressure:.1f} lbs [{level}]")
                    
                self.pressure_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
                self.pressure_label.setText(f"Pressure: {pressure:.1f} lbs")
                
                # Force update of the UI
                QApplication.processEvents()

        except Exception as e:
            print(f"PressureDialog: ERROR - Failed to update pressure: {e}")