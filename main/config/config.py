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
            self.config.write(open(self.configFile, "w"))
        else:

            try:
                self.config.read(self.configFile)

                allSections = {
                    s: dict(self.config.items(s)) for s in self.config.sections()
                }
                # Convert CMarks values to integers
                self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
                self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
                self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}

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
            self.config.write(open(self.configFile, "w"))
        except Exception as e:
            print(str(e))
            print(f'Fatal error, could not write config file to "{self.configFile}"')
