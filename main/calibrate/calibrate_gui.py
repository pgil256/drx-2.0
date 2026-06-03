#!/usr/bin/env python3
"""
KneeSpa Actuator Calibration GUI Tool
=====================================
Interactive GUI for calibrating actuator parameters with direct Arduino control.
Allows real-time adjustment of:
- Arduino motor.ino constants (AFULLINCH, BFULLINCH, CFULLINCH)
- Config file factors (a_factor, b_factor, c_factor)
- Position marks/angle mappings

Author: Calibration Tool
Date: 2025
"""

import sys
import os
import re
import time
import json
import serial
import configparser
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
import shutil

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QTextEdit,
    QTabWidget,
    QMessageBox,
    QFileDialog,
    QComboBox,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QProgressBar,
    QScrollBar,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtGui import QFont, QPalette, QColor


class ArduinoController(QThread):
    """Thread for Arduino serial communication"""

    status_update = pyqtSignal(str)
    position_update = pyqtSignal(str, int)  # actuator, position
    connection_status = pyqtSignal(bool)

    def __init__(self, port=None, baudrate=115200):
        super().__init__()
        # Try to detect the correct port
        if port is None:
            # Check for common Arduino ports
            if os.path.exists("/dev/serial0"):
                self.port = "/dev/serial0"
            elif os.path.exists("/dev/ttyACM0"):
                self.port = "/dev/ttyACM0"
            elif os.path.exists("/dev/ttyUSB0"):
                self.port = "/dev/ttyUSB0"
            elif os.path.exists("COM3"):
                self.port = "COM3"
            else:
                # Windows fallback
                self.port = "COM3"
        else:
            self.port = port

        self.baudrate = baudrate
        self.serial_conn = None
        self.connected = False
        self.running = True
        self.command_queue = []
        self._lock = threading.Lock()

    def connect_arduino(self):
        """Establish connection to Arduino"""
        try:
            self.status_update.emit(f"Attempting connection on port: {self.port}")

            if self.serial_conn:
                self.serial_conn.close()
                time.sleep(0.5)

            self.serial_conn = serial.Serial(
                port=self.port, baudrate=self.baudrate, timeout=2
            )
            time.sleep(3)  # Wait for Arduino reset

            # Clear any existing data
            self.serial_conn.reset_input_buffer()

            # Test connection - Arduino expects 'T' command
            self.serial_conn.write(b"T\n")
            self.serial_conn.flush()
            time.sleep(0.5)

            # Read response
            response = ""
            if self.serial_conn.in_waiting:
                response = self.serial_conn.readline().decode().strip()
                self.status_update.emit(f"Response: {response}")

            # The Arduino should respond with status including "OK"
            if response and ("OK" in response or "A:" in response):
                self.connected = True
                self.connection_status.emit(True)
                self.status_update.emit(f"✓ Arduino connected on {self.port}")
                return True
            else:
                self.connected = False
                self.connection_status.emit(False)
                self.status_update.emit(f"✗ Arduino not responding (got: '{response}')")
                return False

        except serial.SerialException as e:
            self.connected = False
            self.connection_status.emit(False)
            self.status_update.emit(f"✗ Serial error on {self.port}: {e}")
            return False
        except Exception as e:
            self.connected = False
            self.connection_status.emit(False)
            self.status_update.emit(f"✗ Connection error: {e}")
            return False

    def send_command(self, command: str):
        """Queue a command to send to Arduino"""
        with self._lock:
            self.command_queue.append(command)

    def move_actuator(self, actuator: str, inches: float):
        """Send movement command to specific actuator"""
        # Use the same format as kneespa.py: A{actuator}{inches}
        # The Arduino expects integer values for movement
        command = f"A{actuator}{int(inches)}"
        self.send_command(command)

    def stop_all(self):
        """Emergency stop all actuators"""
        # Use 'X' command like in kneespa.py for emergency stop
        self.send_command("X")

    def get_status(self):
        """Request status from Arduino"""
        self.send_command("T")

    def run(self):
        """Main thread loop for Arduino communication"""
        while self.running:
            if self.connected and self.serial_conn:
                try:
                    # Process command queue
                    with self._lock:
                        if self.command_queue:
                            cmd = self.command_queue.pop(0)
                            # Clear buffer before sending
                            self.serial_conn.reset_input_buffer()
                            # Send command with newline
                            full_command = f"{cmd}\n"
                            self.serial_conn.write(full_command.encode())
                            self.serial_conn.flush()
                            self.status_update.emit(f"→ Sent: {cmd}")
                            # Small delay after sending
                            time.sleep(0.1)

                    # Read responses
                    if self.serial_conn.in_waiting:
                        try:
                            response = self.serial_conn.readline().decode().strip()
                            if response:
                                self.process_response(response)
                        except UnicodeDecodeError:
                            # Handle non-UTF8 responses
                            pass

                except serial.SerialException as e:
                    self.status_update.emit(f"✗ Serial error: {e}")
                    self.connected = False
                    self.connection_status.emit(False)
                except Exception as e:
                    self.status_update.emit(f"✗ Communication error: {e}")

            time.sleep(0.05)  # 50ms loop delay

    def process_response(self, response: str):
        """Parse Arduino responses"""
        self.status_update.emit(f"← Recv: {response}")

        # Parse position updates (format: "A:1234 B:5678 C:9012")
        if ":" in response:
            parts = response.split()
            for part in parts:
                if ":" in part:
                    actuator, pos = part.split(":")
                    try:
                        self.position_update.emit(actuator, int(pos))
                    except ValueError:
                        pass

    def stop(self):
        """Stop the thread"""
        self.running = False
        if self.serial_conn:
            self.serial_conn.close()


class CalibrationGUI(QMainWindow):
    """Main GUI window for actuator calibration"""

    def __init__(self):
        super().__init__()
        self.base_path = Path("/home/pi/drx-2.3/")
        self.config_path = self.base_path / "main" / "config" / "kneespa.cfg"
        self.motor_ino_path = self.base_path / "main" / "motor" / "motor.ino"

        # Current values storage
        self.arduino_values = {}
        self.config_values = {}
        self.current_positions = {"A": 0, "B": 0, "C": 0}

        # Arduino controller
        self.arduino = ArduinoController()
        self.arduino.status_update.connect(self.log_message)
        self.arduino.position_update.connect(self.update_position)
        self.arduino.connection_status.connect(self.update_connection_status)

        self.init_ui()
        self.load_current_values()
        self.arduino.start()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("KneeSpa Actuator Calibration Tool")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top toolbar
        toolbar_layout = QHBoxLayout()

        # Connection status
        self.conn_status = QLabel("⚫ Disconnected")
        self.conn_status.setStyleSheet("font-weight: bold; font-size: 12pt;")
        toolbar_layout.addWidget(self.conn_status)

        # Connect button
        self.connect_btn = QPushButton("Connect Arduino")
        self.connect_btn.clicked.connect(self.connect_arduino)
        toolbar_layout.addWidget(self.connect_btn)

        # Emergency stop
        self.stop_btn = QPushButton("🛑 STOP ALL")
        self.stop_btn.setStyleSheet(
            "background-color: red; color: white; font-weight: bold;"
        )
        self.stop_btn.clicked.connect(self.emergency_stop)
        toolbar_layout.addWidget(self.stop_btn)

        toolbar_layout.addStretch()

        # Save/Load buttons
        self.save_btn = QPushButton("💾 Save Config")
        self.save_btn.clicked.connect(self.save_all_values)
        toolbar_layout.addWidget(self.save_btn)

        self.load_btn = QPushButton("📂 Reload")
        self.load_btn.clicked.connect(self.load_current_values)
        toolbar_layout.addWidget(self.load_btn)

        main_layout.addLayout(toolbar_layout)

        # Main content area with tabs
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # Tab 1: Motor Control
        self.motor_tab = self.create_motor_control_tab()
        self.tabs.addTab(self.motor_tab, "Motor Control")

        # Tab 2: Calibration Values
        self.calib_tab = self.create_calibration_tab()
        self.tabs.addTab(self.calib_tab, "Calibration Values")

        # Tab 3: Position Marks
        self.marks_tab = self.create_marks_tab()
        self.tabs.addTab(self.marks_tab, "Position Marks")

        # Tab 4: Auto Calibration
        self.auto_tab = self.create_auto_calibration_tab()
        self.tabs.addTab(self.auto_tab, "Auto Calibration")

        # Manual command input
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("Manual Command:"))
        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText("Enter command (e.g., A11, T, X)")
        manual_layout.addWidget(self.manual_input)

        send_manual_btn = QPushButton("Send")
        send_manual_btn.clicked.connect(self.send_manual_command)
        manual_layout.addWidget(send_manual_btn)

        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self.test_connection)
        manual_layout.addWidget(test_btn)

        main_layout.addLayout(manual_layout)

        # Bottom log area
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(150)
        main_layout.addWidget(QLabel("Log:"))
        main_layout.addWidget(self.log_area)

    def create_motor_control_tab(self):
        """Create the motor control tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Create control for each actuator
        for actuator in ["A", "B", "C"]:
            group = QGroupBox(f"Actuator {actuator}")
            group_layout = QGridLayout()

            # Position display
            pos_label = QLabel("Position:")
            self.__dict__[f"pos_{actuator}_label"] = QLabel("0")
            self.__dict__[f"pos_{actuator}_label"].setStyleSheet("font-weight: bold;")
            group_layout.addWidget(pos_label, 0, 0)
            group_layout.addWidget(self.__dict__[f"pos_{actuator}_label"], 0, 1)

            # Inch movement controls
            group_layout.addWidget(QLabel("Move (inches):"), 1, 0)

            inch_input = QDoubleSpinBox()
            inch_input.setRange(-10.0, 10.0)
            inch_input.setSingleStep(0.1)
            inch_input.setDecimals(2)
            self.__dict__[f"inch_{actuator}_input"] = inch_input
            group_layout.addWidget(inch_input, 1, 1)

            # Movement buttons
            move_btn = QPushButton(f"Move {actuator}")
            move_btn.clicked.connect(lambda checked, a=actuator: self.move_actuator(a))
            group_layout.addWidget(move_btn, 1, 2)

            # Fine adjustment slider
            group_layout.addWidget(QLabel("Fine adjust:"), 2, 0)

            slider = QSlider(Qt.Horizontal)
            slider.setRange(-100, 100)
            slider.setValue(0)
            slider.setTickPosition(QSlider.TicksBelow)
            slider.setTickInterval(10)
            slider.valueChanged.connect(lambda v, a=actuator: self.fine_adjust(a, v))
            self.__dict__[f"slider_{actuator}"] = slider
            group_layout.addWidget(slider, 2, 1, 1, 2)

            # Home button
            home_btn = QPushButton(f"Home {actuator}")
            home_btn.clicked.connect(lambda checked, a=actuator: self.home_actuator(a))
            group_layout.addWidget(home_btn, 3, 0)

            # Record position button
            record_btn = QPushButton(f"Record Position")
            record_btn.clicked.connect(
                lambda checked, a=actuator: self.record_position(a)
            )
            group_layout.addWidget(record_btn, 3, 1)

            group.setLayout(group_layout)
            layout.addWidget(group)

        layout.addStretch()
        return widget

    def create_calibration_tab(self):
        """Create the calibration values tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Arduino FULLINCH values
        arduino_group = QGroupBox("Arduino Constants (motor.ino)")
        arduino_layout = QGridLayout()

        arduino_layout.addWidget(
            QLabel("Encoder counts per inch of travel:"), 0, 0, 1, 3
        )

        self.fullinch_inputs = {}
        for i, actuator in enumerate(["A", "B", "C"]):
            label = QLabel(f"{actuator}FULLINCH:")
            input_box = QSpinBox()
            input_box.setRange(1, 10000)
            input_box.setSuffix(" counts/inch")
            self.fullinch_inputs[actuator] = input_box

            arduino_layout.addWidget(label, i + 1, 0)
            arduino_layout.addWidget(input_box, i + 1, 1)

            # Calculate button for each
            calc_btn = QPushButton(f"Calculate {actuator}")
            calc_btn.clicked.connect(
                lambda checked, a=actuator: self.calculate_fullinch(a)
            )
            arduino_layout.addWidget(calc_btn, i + 1, 2)

        arduino_group.setLayout(arduino_layout)
        layout.addWidget(arduino_group)

        # Config factors
        config_group = QGroupBox("Configuration Factors (kneespa.cfg)")
        config_layout = QGridLayout()

        self.factor_inputs = {}
        factors = [
            "a_factor",
            "b_factor",
            "c_factor",
            "xc_factor",
            "flexion_position",
            "calibration",
            "x_calibration",
        ]

        for i, factor in enumerate(factors):
            label = QLabel(f"{factor}:")
            input_box = QLineEdit()
            self.factor_inputs[factor] = input_box

            row = i // 2
            col = (i % 2) * 2
            config_layout.addWidget(label, row, col)
            config_layout.addWidget(input_box, row, col + 1)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Update buttons
        button_layout = QHBoxLayout()

        update_arduino_btn = QPushButton("Update Arduino Values")
        update_arduino_btn.clicked.connect(self.update_arduino_values)
        button_layout.addWidget(update_arduino_btn)

        update_config_btn = QPushButton("Update Config Values")
        update_config_btn.clicked.connect(self.update_config_values)
        button_layout.addWidget(update_config_btn)

        layout.addLayout(button_layout)
        layout.addStretch()

        return widget

    def create_marks_tab(self):
        """Create the position marks tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Selection combo
        select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("Select Actuator:"))

        self.marks_combo = QComboBox()
        self.marks_combo.addItems(["AMarks", "BMarks", "CMarks"])
        self.marks_combo.currentTextChanged.connect(self.load_marks_table)
        select_layout.addWidget(self.marks_combo)

        select_layout.addStretch()
        layout.addLayout(select_layout)

        # Marks table
        self.marks_table = QTableWidget()
        self.marks_table.setColumnCount(3)
        self.marks_table.setHorizontalHeaderLabels(["Angle (°)", "Position", "Actions"])
        self.marks_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.marks_table)

        # Add new mark controls
        add_group = QGroupBox("Add New Mark")
        add_layout = QHBoxLayout()

        add_layout.addWidget(QLabel("Angle:"))
        self.new_angle_input = QDoubleSpinBox()
        self.new_angle_input.setRange(-180, 180)
        self.new_angle_input.setDecimals(1)
        add_layout.addWidget(self.new_angle_input)

        add_layout.addWidget(QLabel("Position:"))
        self.new_position_input = QSpinBox()
        self.new_position_input.setRange(-10000, 10000)
        add_layout.addWidget(self.new_position_input)

        add_btn = QPushButton("Add Mark")
        add_btn.clicked.connect(self.add_mark)
        add_layout.addWidget(add_btn)

        capture_btn = QPushButton("Capture Current")
        capture_btn.clicked.connect(self.capture_current_position)
        add_layout.addWidget(capture_btn)

        add_group.setLayout(add_layout)
        layout.addWidget(add_group)

        return widget

    def create_auto_calibration_tab(self):
        """Create the auto calibration tab"""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Instructions
        instructions = QTextEdit()
        instructions.setReadOnly(True)
        instructions.setMaximumHeight(100)
        instructions.setPlainText(
            "Automated Calibration Procedure:\n"
            "1. Select actuator to calibrate\n"
            "2. Define movement range and steps\n"
            "3. System will automatically move and record positions\n"
            "4. Review and save calibration data"
        )
        layout.addWidget(instructions)

        # Calibration settings
        settings_group = QGroupBox("Calibration Settings")
        settings_layout = QGridLayout()

        # Actuator selection
        settings_layout.addWidget(QLabel("Actuator:"), 0, 0)
        self.auto_actuator = QComboBox()
        self.auto_actuator.addItems(["A", "B", "C"])
        settings_layout.addWidget(self.auto_actuator, 0, 1)

        # Range settings
        settings_layout.addWidget(QLabel("Start (inches):"), 1, 0)
        self.auto_start = QDoubleSpinBox()
        self.auto_start.setRange(-10, 10)
        self.auto_start.setValue(-2)
        settings_layout.addWidget(self.auto_start, 1, 1)

        settings_layout.addWidget(QLabel("End (inches):"), 2, 0)
        self.auto_end = QDoubleSpinBox()
        self.auto_end.setRange(-10, 10)
        self.auto_end.setValue(2)
        settings_layout.addWidget(self.auto_end, 2, 1)

        settings_layout.addWidget(QLabel("Steps:"), 3, 0)
        self.auto_steps = QSpinBox()
        self.auto_steps.setRange(2, 50)
        self.auto_steps.setValue(10)
        settings_layout.addWidget(self.auto_steps, 3, 1)

        settings_layout.addWidget(QLabel("Delay (s):"), 4, 0)
        self.auto_delay = QDoubleSpinBox()
        self.auto_delay.setRange(0.5, 10)
        self.auto_delay.setValue(2)
        settings_layout.addWidget(self.auto_delay, 4, 1)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        # Control buttons
        control_layout = QHBoxLayout()

        self.start_auto_btn = QPushButton("Start Auto Calibration")
        self.start_auto_btn.clicked.connect(self.start_auto_calibration)
        control_layout.addWidget(self.start_auto_btn)

        self.stop_auto_btn = QPushButton("Stop")
        self.stop_auto_btn.setEnabled(False)
        self.stop_auto_btn.clicked.connect(self.stop_auto_calibration)
        control_layout.addWidget(self.stop_auto_btn)

        layout.addLayout(control_layout)

        # Progress bar
        self.auto_progress = QProgressBar()
        layout.addWidget(self.auto_progress)

        # Results area
        self.auto_results = QTextEdit()
        self.auto_results.setReadOnly(True)
        layout.addWidget(QLabel("Results:"))
        layout.addWidget(self.auto_results)

        return widget

    def load_current_values(self):
        """Load current values from config files"""
        try:
            # Load Arduino values
            with open(self.motor_ino_path, "r") as f:
                content = f.read()

            for actuator in ["A", "B", "C"]:
                pattern = f"#define {actuator}FULLINCH\\s+(\\d+)"
                match = re.search(pattern, content)
                if match:
                    value = int(match.group(1))
                    self.arduino_values[f"{actuator}FULLINCH"] = value
                    self.fullinch_inputs[actuator].setValue(value)

            # Load config values
            config = configparser.ConfigParser()
            config.read(self.config_path)

            if "Options" in config:
                for key, value in config["Options"].items():
                    self.config_values[key] = value
                    if key in self.factor_inputs:
                        self.factor_inputs[key].setText(value)

            self.log_message("✓ Loaded current configuration values")

        except Exception as e:
            self.log_message(f"✗ Error loading values: {e}")

    def save_all_values(self):
        """Save all current values to files"""
        reply = QMessageBox.question(
            self,
            "Save Configuration",
            "Save all changes to configuration files?",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # Create backup
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_dir = (
                    self.base_path / "calibration_backups" / f"backup_{timestamp}"
                )
                backup_dir.mkdir(parents=True, exist_ok=True)

                shutil.copy2(self.motor_ino_path, backup_dir / "motor.ino.bak")
                shutil.copy2(self.config_path, backup_dir / "kneespa.cfg.bak")

                # Save Arduino values
                self.update_arduino_values()

                # Save config values
                self.update_config_values()

                self.log_message(f"✓ Configuration saved. Backup: {backup_dir}")
                QMessageBox.information(
                    self, "Success", "Configuration saved successfully!"
                )

            except Exception as e:
                self.log_message(f"✗ Error saving: {e}")
                QMessageBox.critical(
                    self, "Error", f"Failed to save configuration: {e}"
                )

    def update_arduino_values(self):
        """Update Arduino FULLINCH values in motor.ino"""
        try:
            with open(self.motor_ino_path, "r") as f:
                content = f.read()

            for actuator in ["A", "B", "C"]:
                new_value = self.fullinch_inputs[actuator].value()
                pattern = f"(#define {actuator}FULLINCH\\s+)\\d+"
                replacement = f"\\g<1>{new_value}"
                content = re.sub(pattern, replacement, content)

            with open(self.motor_ino_path, "w") as f:
                f.write(content)

            self.log_message("✓ Updated Arduino values in motor.ino")
            QMessageBox.warning(
                self,
                "Reminder",
                "Remember to recompile and upload motor.ino to Arduino!",
            )

        except Exception as e:
            self.log_message(f"✗ Error updating Arduino values: {e}")

    def update_config_values(self):
        """Update configuration values in kneespa.cfg"""
        try:
            config = configparser.ConfigParser()
            config.read(self.config_path)

            if "Options" not in config:
                config.add_section("Options")

            for key, input_box in self.factor_inputs.items():
                value = input_box.text()
                if value:
                    config.set("Options", key, value)

            with open(self.config_path, "w") as f:
                config.write(f)

            self.log_message("✓ Updated configuration values in kneespa.cfg")

        except Exception as e:
            self.log_message(f"✗ Error updating config: {e}")

    def connect_arduino(self):
        """Connect to Arduino"""
        self.log_message("Attempting to connect to Arduino...")
        if self.arduino.connect_arduino():
            self.log_message("✓ Arduino connected successfully")
        else:
            self.log_message("✗ Failed to connect to Arduino")

    def update_connection_status(self, connected):
        """Update connection status display"""
        if connected:
            self.conn_status.setText("🟢 Connected")
            self.conn_status.setStyleSheet(
                "color: green; font-weight: bold; font-size: 12pt;"
            )
        else:
            self.conn_status.setText("🔴 Disconnected")
            self.conn_status.setStyleSheet(
                "color: red; font-weight: bold; font-size: 12pt;"
            )

    def update_position(self, actuator, position):
        """Update position display for actuator"""
        self.current_positions[actuator] = position
        if f"pos_{actuator}_label" in self.__dict__:
            self.__dict__[f"pos_{actuator}_label"].setText(str(position))

    def move_actuator(self, actuator):
        """Move specific actuator"""
        inches = self.__dict__[f"inch_{actuator}_input"].value()
        self.arduino.move_actuator(actuator, inches)
        self.log_message(f"Moving actuator {actuator} by {inches} inches")

    def fine_adjust(self, actuator, value):
        """Fine adjustment using slider"""
        if value != 0:
            inches = value / 100.0  # Convert slider value to inches
            self.arduino.move_actuator(actuator, inches)
            # Reset slider to center after movement
            QTimer.singleShot(
                500, lambda: self.__dict__[f"slider_{actuator}"].setValue(0)
            )

    def home_actuator(self, actuator):
        """Home specific actuator"""
        self.arduino.send_command(f"H{actuator}")
        self.log_message(f"Homing actuator {actuator}")

    def record_position(self, actuator):
        """Record current position for actuator"""
        position = self.current_positions.get(actuator, 0)
        angle = self.new_angle_input.value()

        # Add to marks table
        self.marks_combo.setCurrentText(f"{actuator}Marks")
        self.new_position_input.setValue(position)
        self.add_mark()

        self.log_message(f"Recorded position for {actuator}: {angle}° = {position}")

    def emergency_stop(self):
        """Emergency stop all actuators"""
        self.arduino.stop_all()
        self.log_message("⚠️ EMERGENCY STOP - All actuators stopped")

    def calculate_fullinch(self, actuator):
        """Interactive calculation of FULLINCH value"""
        # Get current position
        start_pos = self.current_positions.get(actuator, 0)

        reply = QMessageBox.information(
            self,
            f"Calculate {actuator}FULLINCH",
            f"Current position: {start_pos}\n\n"
            f"Click OK, then manually move actuator {actuator} exactly 1 inch.\n"
            f"Click the Calculate button again when done.",
            QMessageBox.Ok,
        )

        # Store start position for next click
        self.__dict__[f"calib_start_{actuator}"] = start_pos

        # Check if this is the second click
        if f"calib_start_{actuator}" in self.__dict__:
            end_pos = self.current_positions.get(actuator, 0)
            counts_per_inch = abs(end_pos - self.__dict__[f"calib_start_{actuator}"])

            if counts_per_inch > 0:
                self.fullinch_inputs[actuator].setValue(counts_per_inch)
                self.log_message(
                    f"Calculated {actuator}FULLINCH: {counts_per_inch} counts/inch"
                )
                del self.__dict__[f"calib_start_{actuator}"]

    def load_marks_table(self):
        """Load marks into table for selected actuator"""
        marks_type = self.marks_combo.currentText()

        config = configparser.ConfigParser()
        config.read(self.config_path)

        self.marks_table.setRowCount(0)

        if marks_type in config:
            marks = config[marks_type]
            for angle, position in sorted(marks.items(), key=lambda x: float(x[0])):
                row = self.marks_table.rowCount()
                self.marks_table.insertRow(row)

                self.marks_table.setItem(row, 0, QTableWidgetItem(angle))
                self.marks_table.setItem(row, 1, QTableWidgetItem(position))

                # Delete button
                delete_btn = QPushButton("Delete")
                delete_btn.clicked.connect(lambda checked, a=angle: self.delete_mark(a))
                self.marks_table.setCellWidget(row, 2, delete_btn)

    def add_mark(self):
        """Add new position mark"""
        marks_type = self.marks_combo.currentText()
        angle = str(self.new_angle_input.value())
        position = str(self.new_position_input.value())

        config = configparser.ConfigParser()
        config.read(self.config_path)

        if marks_type not in config:
            config.add_section(marks_type)

        config.set(marks_type, angle, position)

        with open(self.config_path, "w") as f:
            config.write(f)

        self.load_marks_table()
        self.log_message(f"Added mark: {marks_type} {angle}° = {position}")

    def delete_mark(self, angle):
        """Delete a position mark"""
        marks_type = self.marks_combo.currentText()

        config = configparser.ConfigParser()
        config.read(self.config_path)

        if marks_type in config and angle in config[marks_type]:
            config.remove_option(marks_type, angle)

            with open(self.config_path, "w") as f:
                config.write(f)

            self.load_marks_table()
            self.log_message(f"Deleted mark: {marks_type} {angle}°")

    def capture_current_position(self):
        """Capture current position for selected actuator"""
        actuator = self.marks_combo.currentText()[0]  # Get A, B, or C
        position = self.current_positions.get(actuator, 0)
        self.new_position_input.setValue(position)
        self.log_message(f"Captured position: {position}")

    def start_auto_calibration(self):
        """Start automatic calibration procedure"""
        actuator = self.auto_actuator.currentText()
        start = self.auto_start.value()
        end = self.auto_end.value()
        steps = self.auto_steps.value()
        delay = self.auto_delay.value()

        self.auto_results.clear()
        self.auto_results.append(f"Starting auto calibration for actuator {actuator}")
        self.auto_results.append(f"Range: {start} to {end} inches in {steps} steps")

        self.start_auto_btn.setEnabled(False)
        self.stop_auto_btn.setEnabled(True)

        # Create calibration thread
        self.auto_thread = threading.Thread(
            target=self.run_auto_calibration, args=(actuator, start, end, steps, delay)
        )
        self.auto_thread.daemon = True
        self.auto_thread.start()

    def run_auto_calibration(self, actuator, start, end, steps, delay):
        """Run automatic calibration sequence"""
        step_size = (end - start) / (steps - 1)
        results = []

        for i in range(steps):
            if not self.stop_auto_btn.isEnabled():
                break

            target = start + (i * step_size)
            self.arduino.move_actuator(actuator, target)

            # Wait for movement
            time.sleep(delay)

            # Record position
            position = self.current_positions.get(actuator, 0)
            results.append((target, position))

            # Update UI
            self.auto_progress.setValue(int((i + 1) / steps * 100))
            self.auto_results.append(
                f"Step {i+1}: {target:.2f} inches → {position} counts"
            )

        # Calculate average counts per inch
        if len(results) > 1:
            total_counts = abs(results[-1][1] - results[0][1])
            total_inches = abs(results[-1][0] - results[0][0])
            if total_inches > 0:
                counts_per_inch = total_counts / total_inches
                self.auto_results.append(
                    f"\nCalculated: {counts_per_inch:.1f} counts/inch"
                )
                self.fullinch_inputs[actuator].setValue(int(counts_per_inch))

        self.start_auto_btn.setEnabled(True)
        self.stop_auto_btn.setEnabled(False)
        self.auto_progress.setValue(0)

    def stop_auto_calibration(self):
        """Stop automatic calibration"""
        self.stop_auto_btn.setEnabled(False)
        self.arduino.stop_all()
        self.log_message("Auto calibration stopped")

    def send_manual_command(self):
        """Send manual command to Arduino"""
        command = self.manual_input.text().strip()
        if command:
            self.arduino.send_command(command)
            self.manual_input.clear()
            self.log_message(f"Manual command sent: {command}")

    def test_connection(self):
        """Test Arduino connection with status command"""
        self.arduino.send_command("T")
        self.log_message("Sent test command 'T' - check response in log")

    def log_message(self, message):
        """Add message to log area"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.append(f"[{timestamp}] {message}")
        # Auto-scroll to bottom
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    def closeEvent(self, event):
        """Handle window close event"""
        self.arduino.stop()
        self.arduino.wait()
        event.accept()


def main():
    """Main entry point"""
    app = QApplication(sys.argv)

    # Set dark theme
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    window = CalibrationGUI()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
