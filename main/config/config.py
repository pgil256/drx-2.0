import configparser
import os
import tempfile
import uuid
from typing import Optional

from config.constants import (
    CONFIG_PATH,
    DEFAULT_PROTOCOL_MINUTES,
    LATERAL_MIN,
    LATERAL_MAX,
)

# A real HX711 scale factor for this hardware is in the tens of
# thousands (the shipped device uses -28369). Small magnitudes mean the
# factory default (1.0) is still in place and "pressure" would be raw
# ADC counts.
MIN_PLAUSIBLE_SCALE_FACTOR = 1000.0


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
        # Calibration confidence. A device running on generated default
        # marks or a default scale factor used to be indistinguishable
        # from a calibrated one -- a corrupt config silently degraded to
        # fabricated geometry. Callers gate motion on marks_valid and
        # pressure on scale_calibrated.
        self.marks_valid = False
        self.scale_calibrated = False
        self.calibration_errors = []
        self.calibration_warnings = []

        # Treatment Settings defaults persisted by Setup's "Mark As Default"
        # (Phase 3.5 §15.4). Fallbacks match the legacy 50/10/10 + a 2/sec pulse.
        self.default_max_pressure = 50.0
        self.default_max_left = 10.0
        self.default_max_right = 10.0
        self.default_pulse_rate = 2.0
        self.default_duration = float(DEFAULT_PROTOCOL_MINUTES)

        # Per-device id for support tickets (Phase 3.5 §15.5); generated once.
        self.device_id = ""

    @property
    def calibrated(self) -> bool:
        return self.marks_valid and self.scale_calibrated

    def _flag_error(self, message: str):
        print(f"CALIBRATION: {message}")
        self.calibration_errors.append(message)

    def _flag_warning(self, message: str):
        print(f"CALIBRATION (warning): {message}")
        self.calibration_warnings.append(message)

    def get_config(self, config_path: Optional[str] = None):

        self.config = configparser.ConfigParser(allow_no_value=True)
        if config_path:
            self.configFile = config_path
        self.calibration_errors = []
        self.calibration_warnings = []
        self.marks_valid = False
        self.scale_calibrated = False
        # Load configuration

        if not os.path.exists(self.configFile):
            self._set_default_c_marks()
            self._set_default_a_marks()
            self._set_default_b_marks()
            self._write_default_config()
            self._flag_error(
                f"Config file missing at {self.configFile}; generated defaults "
                "written. Device is UNCALIBRATED until a real calibration is saved."
            )
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
            self._validate_calibration()

        except Exception as e:
            print(str(e))
            print(
                'Fatal error, could not load config file from "%s"'
                % self.configFile
            )
            self._set_default_c_marks()
            self._set_default_a_marks()
            self._set_default_b_marks()
            self._flag_error(
                f"Config file unreadable ({e}); generated default marks in use. "
                "Device is UNCALIBRATED."
            )

    def _load_marks(self, allSections):
        """Load actuator marks, falling back to safe defaults on malformed data.

        Any fallback flags the device uncalibrated -- generated defaults
        are geometry fabrications, not measurements.
        """
        if "CMarks" in allSections:
            try:
                self.CMarks = {k: int(v) for k, v in allSections["CMarks"].items()}
            except (ValueError, TypeError) as e:
                self._set_default_c_marks()
                self._flag_error(f"CMarks malformed ({e}); defaults in use")
        else:
            self._set_default_c_marks()
            self._flag_error("CMarks section missing; defaults in use")

        if "AMarks" in allSections:
            try:
                self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
            except (ValueError, TypeError) as e:
                self._set_default_a_marks()
                self._flag_error(f"AMarks malformed ({e}); defaults in use")
        else:
            self._set_default_a_marks()
            self._flag_error("AMarks section missing; defaults in use")

        if "BMarks" in allSections:
            try:
                self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}
            except (ValueError, TypeError) as e:
                self._set_default_b_marks()
                self._flag_error(f"BMarks malformed ({e}); defaults in use")
        else:
            self._set_default_b_marks()
            self._flag_error("BMarks section missing; defaults in use")

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
            "duration": "default_duration",
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
            "duration": self.default_duration,
        }

    def save_protocol_defaults(self, max_pressure, max_left, max_right, pulse_rate,
                               duration=None):
        """Persist new Treatment Settings defaults (values should be pre-clamped).

        ``duration`` is optional for backward compatibility; when omitted the
        existing persisted duration is kept.
        """
        self.default_max_pressure = float(max_pressure)
        self.default_max_left = float(max_left)
        self.default_max_right = float(max_right)
        self.default_pulse_rate = float(pulse_rate)
        if duration is not None:
            self.default_duration = float(duration)
        self.update_config()

    def ensure_device_id(self):
        """Return the persisted per-device id, generating + saving one if absent."""
        if not self.device_id:
            self.device_id = uuid.uuid4().hex
            self.update_config()
        return self.device_id

    @staticmethod
    def validate_marks(marks) -> Optional[str]:
        """Check a mark table: numeric keys, enough points, strictly
        monotonic positions, sane position range. Returns an error string
        or None if valid."""
        try:
            pairs = sorted((float(k), int(v)) for k, v in marks.items())
        except (ValueError, TypeError) as e:
            return f"non-numeric mark entry ({e})"
        if len(pairs) < 2:
            return f"only {len(pairs)} marks (need at least 2)"
        positions = [p for _, p in pairs]
        increasing = all(b > a for a, b in zip(positions, positions[1:]))
        decreasing = all(b < a for a, b in zip(positions, positions[1:]))
        if not (increasing or decreasing):
            return "positions are not strictly monotonic vs angle"
        if any(p < 0 or p > 65000 for p in positions):
            return "position outside the 0-65000 sensor range"
        return None

    def _validate_calibration(self):
        """Decide marks_valid / scale_calibrated after a clean load."""
        marks_ok = True
        for name, marks in (("CMarks", self.CMarks),
                            ("AMarks", self.AMarks),
                            ("BMarks", self.BMarks)):
            error = self.validate_marks(marks)
            if error:
                marks_ok = False
                self._flag_error(f"{name}: {error}")
        # Only meaningful if nothing already flagged a fallback
        self.marks_valid = marks_ok and not any(
            "defaults in use" in e or "UNCALIBRATED" in e
            for e in self.calibration_errors
        )

        # Range-vs-firmware-clamp mismatches are recorded but do not
        # block: some shipped tables exceed LATERAL_MIN/MAX and the
        # authoritative range is a pending hardware measurement.
        try:
            c_positions = [int(v) for v in self.CMarks.values()]
            if c_positions and (
                min(c_positions) < LATERAL_MIN or max(c_positions) > LATERAL_MAX
            ):
                self._flag_warning(
                    f"CMarks span {min(c_positions)}-{max(c_positions)}, outside "
                    f"the firmware clamp {LATERAL_MIN}-{LATERAL_MAX}; targets "
                    "will be clamped"
                )
        except (ValueError, TypeError):
            pass

        if abs(float(self.calibration)) < MIN_PLAUSIBLE_SCALE_FACTOR:
            self.scale_calibrated = False
            self._flag_error(
                f"Load-cell scale factor {self.calibration} is implausible "
                "(factory default?); pressure readings would be raw counts"
            )
        else:
            self.scale_calibrated = True

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

    def _atomic_write(self):
        """Write the config file atomically (temp file + fsync + rename).

        The calibration file used to be rewritten in place; a power cut
        mid-write -- routine on a kiosk Pi -- corrupted it, and the next
        boot silently ran on generated default geometry.
        """
        directory = os.path.dirname(os.path.abspath(self.configFile)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".kneespa_cfg_", dir=directory, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                self.config.write(tmp_file)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.configFile)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

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
        self._atomic_write()

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
            "duration": self.default_duration,
        })
        self._set_section("Device", {"id": self.device_id})

        print("Config updated")
        try:
            self._ensure_config_sections()
            self._atomic_write()
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
