import configparser
import os
import uuid
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

        # Treatment Settings defaults persisted by Setup's "Mark As Default"
        # (Phase 3.5 §15.4). Fallbacks match the legacy 50/10/10 + a 2/sec pulse.
        self.default_max_pressure = 50.0
        self.default_max_left = 10.0
        self.default_max_right = 10.0
        self.default_pulse_rate = 2.0

        # Per-device id for support tickets (Phase 3.5 §15.5); generated once.
        self.device_id = ""

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
            self._load_protocol_defaults()
            self._load_device()
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

    def _load_protocol_defaults(self):
        """Load persisted Treatment Settings defaults, keeping __init__ fallbacks
        for any malformed/absent value."""
        section = "ProtocolDefaults"
        if not self.config.has_section(section):
            return
        specs = {
            "max_pressure": "default_max_pressure",
            "max_left": "default_max_left",
            "max_right": "default_max_right",
            "pulse_rate": "default_pulse_rate",
        }
        for key, attr in specs.items():
            if self.config.has_option(section, key):
                try:
                    setattr(self, attr, float(self.config[section][key]))
                except (ValueError, TypeError) as e:
                    print(f"Error parsing ProtocolDefaults.{key}: {e}, using default")

    def _load_device(self):
        """Load the persisted per-device id, if present."""
        if self.config.has_section("Device") and self.config.has_option("Device", "id"):
            self.device_id = self.config["Device"]["id"]

    def _set_section(self, section, mapping):
        """Write a flat string-valued section, creating it if missing."""
        if not self.config.has_section(section):
            self.config.add_section(section)
        for key, value in mapping.items():
            self.config.set(section, key, str(value))

    def protocol_defaults(self):
        """Return the persisted Treatment Settings defaults as a dict."""
        return {
            "max_pressure": self.default_max_pressure,
            "max_left": self.default_max_left,
            "max_right": self.default_max_right,
            "pulse_rate": self.default_pulse_rate,
        }

    def save_protocol_defaults(self, max_pressure, max_left, max_right, pulse_rate):
        """Persist new Treatment Settings defaults (values should be pre-clamped)."""
        self.default_max_pressure = float(max_pressure)
        self.default_max_left = float(max_left)
        self.default_max_right = float(max_right)
        self.default_pulse_rate = float(pulse_rate)
        self.update_config()

    def ensure_device_id(self):
        """Return the persisted per-device id, generating + saving one if absent."""
        if not self.device_id:
            self.device_id = uuid.uuid4().hex
            self.update_config()
        return self.device_id

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
        
        # Persist the Phase-3.5 sections alongside the legacy Options.
        self._set_section("ProtocolDefaults", {
            "max_pressure": self.default_max_pressure,
            "max_left": self.default_max_left,
            "max_right": self.default_max_right,
            "pulse_rate": self.default_pulse_rate,
        })
        self._set_section("Device", {"id": self.device_id})

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
