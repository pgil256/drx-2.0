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

                if not self.config.has_option(section, "flexion_position"):
                    self.config.set(
                        "Options", "flexion_position", str(self.flexion_position)
                    )
                else:
                    self.flexion_position = int(
                        self.config["Options"]["flexion_position"]
                    )

                if not self.config.has_option(section, "a_factor"):
                    self.config.set("Options", "a_factor", str(self.a_factor))
                else:
                    self.a_factor = int(self.config["Options"]["a_factor"])

                if not self.config.has_option(section, "b_factor"):
                    self.config.set("Options", "b_factor", str(self.b_factor))
                else:
                    self.b_factor = int(self.config["Options"]["b_factor"])

                if not self.config.has_option(section, "c_factor"):
                    self.config.set("Options", "c_factor", str(self.c_factor))
                else:
                    self.c_factor = int(self.config["Options"]["c_factor"])

                if not self.config.has_option(section, "unlock"):
                    self.config.set("Options", "unlock", str(self.unlock))
                else:
                    self.unlock = self.config["Options"]["unlock"]

                if not self.config.has_option(section, "calibration"):
                    self.config.set("Options", "calibration", str(self.calibration))
                else:
                    self.calibration = float(self.config["Options"]["calibration"])

            except Exception as e:
                print(str(e))
                print(
                    'Fatal error, could not load config file from "%s"'
                    % self.configFile
                )

    def update_config(self):
        section = "Options"
        self.config.set("Options", "flexion_position", str(self.flexion_position))

        self.config.set("Options", "a_factor", str(self.a_factor))
        self.config.set("Options", "b_factor", str(self.b_factor))
        self.config.set("Options", "c_factor", str(self.c_factor))

        self.config.set("Options", "unlock", str(self.unlock))
        self.config.set("Options", "calibration", str(self.calibration))

        print("config written")
        try:
            self.config.write(open(self.configFile, "w"))
        except Exception as e:
            print(str(e))
            print('Fatal error, could not load config file from "%s"' % self.configFile)
