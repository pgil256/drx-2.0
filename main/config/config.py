import configparser
import os
from typing import Optional

from config.constants import CONFIG_PATH, LATERAL_MIN, LATERAL_MAX


class Configuration:
    def get_list(option, sep=",", chars=None):
        return [chunk.strip(chars) for chunk in option.split(sep)]

    def __init__(self, config_path: Optional[str] = None):
        self.flexion_position = 0
        self.a_factor = 1900
        self.b_factor = 1900
        self.c_factor = 1900
        self.unlock = "false"
        self.calibration = 1.0
        self.configFile = config_path or CONFIG_PATH
        self.config = configparser.ConfigParser(allow_no_value=True)
        self.CMarks = {}
        self.AMarks = {}
        self.BMarks = {}

    def get_config(self, config_path: Optional[str] = None):

        self.config = configparser.ConfigParser(allow_no_value=True)
        if config_path:
            self.configFile = config_path
        # Load configuration

        if not os.path.exists(self.configFile):
            self._set_default_c_marks()
            self._set_default_a_marks()
            self._set_default_b_marks()
            self._write_default_config()
            return

        try:
            self.config.read(self.configFile)

            allSections = {
                s: dict(self.config.items(s)) for s in self.config.sections()
            }

            self._load_marks(allSections)
            self._load_options()
            self._ensure_config_sections()

        except Exception as e:
            print(str(e))
            print(
                'Fatal error, could not load config file from "%s"'
                % self.configFile
            )
            self._set_default_c_marks()
            self._set_default_a_marks()
            self._set_default_b_marks()

    def _load_marks(self, allSections):
        """Load actuator marks, falling back to safe defaults on malformed data."""
        if "CMarks" in allSections:
            try:
                self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
            except (ValueError, TypeError) as e:
                print(f"Error parsing CMarks: {e}, using defaults")
                self._set_default_c_marks()
        else:
            print("CMarks section missing, using defaults")
            self._set_default_c_marks()

        if "AMarks" in allSections:
            try:
                self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
            except (ValueError, TypeError) as e:
                print(f"Error parsing AMarks: {e}, using defaults")
                self._set_default_a_marks()
        else:
            print("AMarks section missing, using defaults")
            self._set_default_a_marks()

        if "BMarks" in allSections:
            try:
                self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}
            except (ValueError, TypeError) as e:
                print(f"Error parsing BMarks: {e}, using defaults")
                self._set_default_b_marks()
        else:
            print("BMarks section missing, using defaults")
            self._set_default_b_marks()

    def _load_options(self):
        """Load scalar options with type-aware fallback defaults."""
        section = "Options"
        if not self.config.has_section(section):
            self.config.add_section(section)

        config_options = {
            "flexion_position": {"default": self.flexion_position, "type": int},
            "a_factor": {"default": self.a_factor, "type": int},
            "b_factor": {"default": self.b_factor, "type": int},
            "c_factor": {"default": self.c_factor, "type": int},
            "unlock": {"default": self.unlock, "type": str},
            "calibration": {"default": self.calibration, "type": float},
        }

        for option_name, option_settings in config_options.items():
            if not self.config.has_option(section, option_name):
                value = option_settings["default"]
                self.config.set(section, option_name, str(value))
                setattr(self, option_name, value)
                continue

            raw_value = self.config[section][option_name]
            try:
                value = raw_value
                if option_settings["type"] != str:
                    value = option_settings["type"](raw_value)
            except (ValueError, TypeError) as e:
                print(f"Error parsing {option_name}: {e}, using default")
                value = option_settings["default"]
                self.config.set(section, option_name, str(value))
            setattr(self, option_name, value)

    def _ensure_config_sections(self):
        """Ensure defaults are persisted for sections missing from the file."""
        if not self.config.has_section("Options"):
            self.config.add_section("Options")
        for section_name, marks in {
            "CMarks": self.CMarks,
            "AMarks": self.AMarks,
            "BMarks": self.BMarks,
        }.items():
            if not self.config.has_section(section_name):
                self.config.add_section(section_name)
            for key, value in marks.items():
                if not self.config.has_option(section_name, key):
                    self.config.set(section_name, key, str(value))

    def _write_default_config(self):
        """Write a complete default config, including calibration mark sections."""
        self.config["Options"] = {
            "flexion_position": str(self.flexion_position),
            "a_factor": str(self.a_factor),
            "b_factor": str(self.b_factor),
            "c_factor": str(self.c_factor),
            "unlock": str(self.unlock),
            "calibration": str(self.calibration),
        }
        self.config["AMarks"] = {k: str(v) for k, v in self.AMarks.items()}
        self.config["BMarks"] = {k: str(v) for k, v in self.BMarks.items()}
        self.config["CMarks"] = {k: str(v) for k, v in self.CMarks.items()}
        directory = os.path.dirname(os.path.abspath(self.configFile))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self.configFile, "w", encoding="utf-8") as config_file:
            self.config.write(config_file)

    def update_config(self):
        """Update the configuration file with current values."""
        section = "Options"
        if not self.config.has_section(section):
            self.config.add_section(section)
        
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
            self._ensure_config_sections()
            with open(self.configFile, "w", encoding="utf-8") as config_file:
                self.config.write(config_file)
        except Exception as e:
            print(str(e))
            print(f'Fatal error, could not write config file to "{self.configFile}"')

    def _set_default_c_marks(self):
        """Set default CMarks values for lateral actuator."""
        self.CMarks = {}
        for i in range(17):
            angle = (i * 2.5) - 20
            ratio = i / 16
            position = int(round(LATERAL_MIN + ((LATERAL_MAX - LATERAL_MIN) * ratio)))
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
