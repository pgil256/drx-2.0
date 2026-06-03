from PyQt5.QtWidgets import QDialog, QVBoxLayout, QLabel, QApplication
from PyQt5.QtCore import Qt
from helpers.logging import debug, debug_state_change, debug_error


class PressureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        debug("Initializing pressure dialog", component="PressureDialog", level="INFO")
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
        self.update_count = 0  # Track total updates
        self.filtered_count = 0  # Track filtered updates
        debug("PressureDialog initialization complete", component="PressureDialog")

    def update_pressure(self, pressure):
        """Update the pressure display with the current pressure value."""
        self.update_count += 1

        # Ensure pressure is a float and not None
        try:
            if pressure is None:
                debug("Received None pressure - defaulting to 0.0", component="PressureDialog", level="WARNING")
                pressure = 0.0
            pressure = float(pressure)

            # Calculate the change from last pressure
            pressure_change = abs(pressure - self.last_pressure)

            # Only update if pressure has changed significantly (> 0.5 lbs)
            if pressure_change > 0.5:
                # Track the state change
                old_pressure = self.last_pressure
                self.last_pressure = pressure

                # Color coding based on pressure thresholds
                if pressure >= 70:
                    color = "#e74c3c"  # Red
                    level = "HIGH"
                    log_level = "WARNING"
                elif pressure >= 50:
                    color = "#f39c12"  # Orange
                    level = "MEDIUM"
                    log_level = "INFO"
                else:
                    color = "#27ae60"  # Green
                    level = "NORMAL"
                    log_level = "DEBUG"

                debug_state_change("PressureDialog.pressure", old_pressure, pressure,
                                 f"Level: {level}, Change: {pressure_change:.1f} lbs")

                # Update the UI
                self.pressure_label.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: bold;")
                self.pressure_label.setText(f"Pressure: {pressure:.1f} lbs")

                # Force update of the UI
                QApplication.processEvents()

                # Log update statistics periodically (every 10 updates)
                if self.update_count % 10 == 0:
                    debug(f"Update statistics", component="PressureDialog",
                         total_updates=self.update_count,
                         filtered_updates=self.filtered_count,
                         current_pressure=pressure)
            else:
                # Update was filtered out
                self.filtered_count += 1
                if self.filtered_count % 20 == 0:  # Log every 20 filtered updates
                    debug(f"Filtered minor pressure change", component="PressureDialog",
                         level="DEBUG", change=pressure_change, current=pressure)

        except Exception as e:
            debug_error("Failed to update pressure display", exception=e,
                       component="PressureDialog", pressure_value=pressure)