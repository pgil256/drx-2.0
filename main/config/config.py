import configparser
import serial
import time
from datetime import datetime
import os
import sys
from PyQt5.QtWidgets import QApplication, QWidget, QInputDialog, QLineEdit, QFileDialog
from PyQt5 import QtCore, QtGui, QtWidgets
from config.constants import CONFIG_PATH


class Configuration:
    def get_list(option, sep=",", chars=None):
        return [chunk.strip(chars) for chunk in option.split(sep)]

    def __init__(self):

        self.flexion_position = 0
        self.c_factor = 1900

    def get_config(self):

        self.config = configparser.ConfigParser(allow_no_value=True)
        self.configFile = CONFIG_PATH
        # Load configuration

        if not os.path.exists(self.configFile):
            self.config["Options"] = {"flexion_position": self.flexion_position}
            with open(self.configFile, "w") as config_file:
                self.config.write(config_file)
        else:

            try:
                self.config.read(self.configFile)

                allSections = {
                    s: dict(self.config.items(s)) for s in self.config.sections()
                }

                # Safe section access with defaults
                self.CMarks = {}
                self.AMarks = {}
                self.BMarks = {}

                # Convert CMarks values to integers with error handling
                if "CMarks" in allSections:
                    try:
                        self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
                    except (ValueError, TypeError) as e:
                        print(f"Error parsing CMarks: {e}, using defaults")
                        self._set_default_c_marks()
                else:
                    print("CMarks section missing, using defaults")
                    self._set_default_c_marks()

                # Convert AMarks values to integers with error handling
                if "AMarks" in allSections:
                    try:
                        self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
                    except (ValueError, TypeError) as e:
                        print(f"Error parsing AMarks: {e}, using defaults")
                        self._set_default_a_marks()
                else:
                    print("AMarks section missing, using defaults")
                    self._set_default_a_marks()

                # Convert BMarks values to integers with error handling
                if "BMarks" in allSections:
                    try:
                        self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}
                    except (ValueError, TypeError) as e:
                        print(f"Error parsing BMarks: {e}, using defaults")
                        self._set_default_b_marks()
                else:
                    print("BMarks section missing, using defaults")
                    self._set_default_b_marks()

                section = "Options"

                if not self.config.has_section(section):
                    self.config.add_section(section)
                
                # Define config options with their default values and types
                config_options = {
                    "flexion_position": {"default": self.flexion_position, "type": int},
                    "a_factor": {"default": getattr(self, "a_factor", 1900), "type": int},
                    "b_factor": {"default": getattr(self, "b_factor", 1900), "type": int},
                    "c_factor": {"default": self.c_factor, "type": int},
                    "unlock": {"default": getattr(self, "unlock", "false"), "type": str},
                    "calibration": {"default": getattr(self, "calibration", 1.0), "type": float}
                }
                
                # Process all config options with a single pattern
                for option_name, option_settings in config_options.items():
                    if not self.config.has_option(section, option_name):
                        # Option doesn't exist, set default
                        self.config.set(section, option_name, str(option_settings["default"]))
                        setattr(self, option_name, option_settings["default"])
                    else:
                        # Option exists, read it with proper type conversion
                        value = self.config[section][option_name]
                        if option_settings["type"] != str:
                            value = option_settings["type"](value)
                        setattr(self, option_name, value)

            except Exception as e:
                print(str(e))
                print(
                    'Fatal error, could not load config file from "%s"'
                    % self.configFile
                )

    def update_config(self):
        """Update the configuration file with current values."""
        section = "Options"
        
        # List of configuration options to update
        config_options = [
            "flexion_position", "a_factor", "b_factor", "c_factor", 
            "unlock", "calibration"
        ]
        
        # Set each option in the config
        for option in config_options:
            if hasattr(self, option):
                self.config.set(section, option, str(getattr(self, option)))
        
        print("Config updated")
        try:
            with open(self.configFile, "w") as config_file:
                self.config.write(config_file)
        except Exception as e:
            print(str(e))
            print(f'Fatal error, could not write config file to "{self.configFile}"')

    def _set_default_c_marks(self):
        """Set default CMarks values for lateral actuator."""
        self.CMarks = {}
        for i in range(16):
            angle = (i * 2.5) - 20
            position = (i * 220) + 98
            self.CMarks[str(angle)] = position

    def _set_default_a_marks(self):
        """Set default AMarks values for axial actuator."""
        self.AMarks = {
            "0": 0,
            "1": 475,
            "2": 950,
            "3": 1425,
            "4": 1900
        }

    def _set_default_b_marks(self):
        """Set default BMarks values for horizontal actuator."""
        self.BMarks = {
            "-25": 0,
            "-20": 380,
            "-15": 760,
            "-10": 1140,
            "-5": 1520,
            "0": 1900,
            "5": 2280
        }
