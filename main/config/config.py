import configparser
import os
from config.constants import CONFIG_PATH


class Configuration:
    def __init__(self):
        print("Configuration: Initializing configuration object")
        self.flexion_position = 0
        self.c_factor = 1900

    def get_config(self):
        print(f"Configuration: Loading config from {CONFIG_PATH}")
        self.config = configparser.ConfigParser(allow_no_value=True)
        self.configFile = CONFIG_PATH
        # Load configuration

        if not os.path.exists(self.configFile):
            print(f"Configuration: Config file not found, creating new one at {self.configFile}")
            self.config["Options"] = {"flexion_position": self.flexion_position}
            # Fix file handle leak - use context manager
            with open(self.configFile, "w") as config_file:
                self.config.write(config_file)
            print("Configuration: New config file created successfully")
        else:
            print(f"Configuration: Reading existing config file from {self.configFile}")
            try:
                self.config.read(self.configFile)

                allSections = {
                    s: dict(self.config.items(s)) for s in self.config.sections()
                }

                # Safely convert marks values to integers with error handling
                self.CMarks = {}
                self.AMarks = {}
                self.BMarks = {}

                # Handle CMarks section
                if "CMarks" in allSections:
                    try:
                        self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
                        print(f"Configuration: Loaded {len(self.CMarks)} CMarks calibration points")
                    except (ValueError, TypeError) as e:
                        print(f"Configuration: Error parsing CMarks: {e}")
                        self.CMarks = self._get_default_marks("C")
                        print("Configuration: Using default CMarks values")
                else:
                    print("Configuration: CMarks section missing, using defaults")
                    self.CMarks = self._get_default_marks("C")

                # Handle AMarks section
                if "AMarks" in allSections:
                    try:
                        self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
                        print(f"Configuration: Loaded {len(self.AMarks)} AMarks calibration points")
                    except (ValueError, TypeError) as e:
                        print(f"Configuration: Error parsing AMarks: {e}")
                        self.AMarks = self._get_default_marks("A")
                        print("Configuration: Using default AMarks values")
                else:
                    print("Configuration: AMarks section missing, using defaults")
                    self.AMarks = self._get_default_marks("A")

                # Handle BMarks section
                if "BMarks" in allSections:
                    try:
                        self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}
                        print(f"Configuration: Loaded {len(self.BMarks)} BMarks calibration points")
                    except (ValueError, TypeError) as e:
                        print(f"Configuration: Error parsing BMarks: {e}")
                        self.BMarks = self._get_default_marks("B")
                        print("Configuration: Using default BMarks values")
                else:
                    print("Configuration: BMarks section missing, using defaults")
                    self.BMarks = self._get_default_marks("B")

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
                        print(f"Configuration: Set default value for {option_name} = {option_settings['default']}")
                    else:
                        # Option exists, read it with proper type conversion
                        value = self.config[section][option_name]
                        if option_settings["type"] != str:
                            value = option_settings["type"](value)
                        setattr(self, option_name, value)
                        print(f"Configuration: Loaded {option_name} = {value}")

            except Exception as e:
                print(f"Configuration: Fatal error loading config - {str(e)}")
                print(f'Configuration: Could not load config file from "{self.configFile}"')

    def _get_default_marks(self, actuator_type):
        """Return default calibration marks for a given actuator type."""
        print(f"Configuration: Generating default marks for actuator {actuator_type}")
        if actuator_type == "A":
            # Default marks for Axial actuator (inches to position)
            return {
                "0": 0,
                "1": 475,
                "2": 950,
                "3": 1425,
                "4": 1900
            }
        elif actuator_type == "B":
            # Default marks for Horizontal actuator (degrees to position)
            return {
                "-25": 0,
                "-20": 380,
                "-15": 760,
                "-10": 1140,
                "-5": 1520,
                "0": 1900,
                "5": 2280
            }
        elif actuator_type == "C":
            # Default marks for Lateral actuator (degrees to position)
            return {
                "-20": 0,
                "-15": 475,
                "-10": 950,
                "-5": 1425,
                "0": 1900,
                "5": 2375,
                "10": 2850,
                "15": 3325,
                "20": 3800
            }
        return {}

    def update_config(self):
        """Update the configuration file with current values."""
        print("Configuration: Updating config file with current values")
        section = "Options"

        # List of configuration options to update
        config_options = [
            "flexion_position", "a_factor", "b_factor", "c_factor",
            "unlock", "calibration"
        ]

        # Set each option in the config
        updated_count = 0
        for option in config_options:
            if hasattr(self, option):
                value = getattr(self, option)
                self.config.set(section, option, str(value))
                print(f"Configuration: Updating {option} = {value}")
                updated_count += 1

        print(f"Configuration: Updated {updated_count} config options")
        try:
            # Fix file handle leak - use context manager
            with open(self.configFile, "w") as config_file:
                self.config.write(config_file)
            print(f"Configuration: Successfully wrote config to {self.configFile}")
        except Exception as e:
            print(f"Configuration: Error writing config - {str(e)}")
            print(f'Configuration: Fatal error, could not write config file to "{self.configFile}"')
