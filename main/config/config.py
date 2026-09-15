import configparser
import copy
import os
import shutil
import tempfile
import uuid
from typing import Dict, Mapping, Optional

from helpers.motor_speed import motor_speed_values

from config.constants import (
    CONFIG_PATH,
    DEFAULT_CONFIG_PATH,
    DEFAULT_PROTOCOL_MINUTES,
    LEGACY_CONFIG_PATH,
)

# A real HX711 scale factor for this hardware is in the tens of
# thousands (the shipped device uses -28369). Small magnitudes mean the
# factory default (1.0) is still in place and "pressure" would be raw
# ADC counts.
MIN_PLAUSIBLE_SCALE_FACTOR = 1000.0


class Configuration:
    def __init__(self, config_path: Optional[str] = None):
        self.flexion_position = 0
        self.a_factor = 1900
        self.b_factor = 1900
        self.c_factor = 1900
        # "unlock" was a legacy unused option that carried a real code in
        # shipped configs; it is no longer read, written, or defaulted.
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
        # (Phase 3.5 §15.4). Fallbacks: 40 lbs / 10° / 10° + a 2/sec pulse.
        self.default_max_pressure = 40.0
        self.default_max_left = 10.0
        self.default_max_right = 10.0
        self.default_pulse_rate = 2.0
        self.default_duration = float(DEFAULT_PROTOCOL_MINUTES)
        for key, value in motor_speed_values().items():
            setattr(self, f"default_{key}", value)
        # True only once an operator has pressed "Mark As Default" (or a
        # file written by that action was loaded). Until then the code
        # defaults above apply and are NOT persisted: update_config() used
        # to write them on every save, so a default changed in code never
        # reached a device whose kneespa.cfg already carried the old value.
        self.protocol_defaults_marked = False

        # Per-device id for support tickets (Phase 3.5 §15.5); generated once.
        self.device_id = ""
        self.device_number = 1

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
        self._migrate_legacy_config()

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
            self.config.read(self.configFile, encoding="utf-8")

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
        if self.config.get(section, "marked", fallback="") != "1":
            print(
                "Ignoring [ProtocolDefaults] that was auto-written rather than "
                "marked by an operator; using code defaults"
            )
            return
        self.protocol_defaults_marked = True
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
        for key in motor_speed_values():
            try:
                values = motor_speed_values({key: self.config.getfloat(
                    section, key, fallback=getattr(self, f"default_{key}")
                )})
                setattr(self, f"default_{key}", values[key])
            except (ValueError, TypeError):
                print(f"Invalid ProtocolDefaults.{key}; using default motor speed")

    def _migrate_legacy_config(self) -> None:
        """Copy legacy calibration once, without overwriting an existing config.

        Custom config paths keep their existing behavior. Copy failures propagate
        instead of silently replacing real calibration with generated defaults.
        """
        if (
            os.path.abspath(self.configFile) != os.path.abspath(DEFAULT_CONFIG_PATH)
            or os.path.exists(self.configFile)
            or not os.path.isfile(LEGACY_CONFIG_PATH)
        ):
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.configFile)), exist_ok=True)
        with open(LEGACY_CONFIG_PATH, "rb") as source:
            try:
                destination = open(self.configFile, "xb")
            except FileExistsError:
                return
            try:
                with destination:
                    shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
            except Exception:
                os.unlink(self.configFile)
                raise
        print(f"Copied legacy configuration from {LEGACY_CONFIG_PATH} to {self.configFile}")

    def _load_device(self) -> None:
        """Load the device identity and a device number from 1 through 3."""
        if self.config.has_section("Device") and self.config.has_option("Device", "id"):
            self.device_id = self.config["Device"]["id"]
        raw_number = self.config.get("Device", "number", fallback="1")
        try:
            number = int(raw_number)
            if number not in (1, 2, 3):
                raise ValueError("must be 1, 2, or 3")
        except (ValueError, TypeError):
            print(f"Invalid Device.number {raw_number!r}; using default 1")
            number = 1
        self.device_number = number
        self._set_section("Device", {"number": number})

    def _set_section(
        self, section: str, mapping: Mapping[str, object],
        parser: Optional[configparser.ConfigParser] = None,
    ) -> None:
        """Write a flat string-valued section, creating it if missing."""
        parser = self.config if parser is None else parser
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in mapping.items():
            parser.set(section, key, str(value))

    def protocol_defaults(self):
        """Return the persisted Treatment Settings defaults as a dict."""
        return {
            "max_pressure": self.default_max_pressure,
            "max_left": self.default_max_left,
            "max_right": self.default_max_right,
            "pulse_rate": self.default_pulse_rate,
            "duration": self.default_duration,
            **{key: getattr(self, f"default_{key}") for key in motor_speed_values()},
        }

    def save_protocol_defaults(
        self, max_pressure: float, max_left: float, max_right: float, pulse_rate: float,
        duration: Optional[float] = None,
        motor_speeds: Optional[Mapping[str, float]] = None,
    ) -> None:
        """Persist new Treatment Settings defaults (values should be pre-clamped).

        ``duration`` is optional for backward compatibility; when omitted the
        existing persisted duration is kept.

        Write errors propagate without publishing any candidate values, so the
        caller can report failure and the previous defaults remain available.
        """
        defaults = {
            "max_pressure": float(max_pressure),
            "max_left": float(max_left),
            "max_right": float(max_right),
            "pulse_rate": float(pulse_rate),
            "duration": self.default_duration if duration is None else float(duration),
            **motor_speed_values(self.protocol_defaults() if motor_speeds is None else motor_speeds),
        }
        candidate = copy.deepcopy(self.config)
        self._populate_config(candidate, defaults)
        self._ensure_config_sections(candidate)
        self._atomic_write(candidate)
        self.config = candidate
        for key, value in defaults.items():
            setattr(self, f"default_{key}", value)
        self.protocol_defaults_marked = True

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
        # CMarks is operator-calibrated device data. Once its keys and values
        # have parsed as numbers in _load_marks(), preserve it exactly rather
        # than imposing generated geometry, monotonicity, or range policy.
        for name, marks in (("AMarks", self.AMarks),
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

        if abs(float(self.calibration)) < MIN_PLAUSIBLE_SCALE_FACTOR:
            self.scale_calibrated = False
            self._flag_error(
                f"Load-cell scale factor {self.calibration} is implausible "
                "(factory default?); pressure readings would be raw counts"
            )
        else:
            self.scale_calibrated = True

    def _ensure_config_sections(
        self, parser: Optional[configparser.ConfigParser] = None,
    ) -> None:
        """Ensure defaults are persisted for sections missing from the file."""
        parser = self.config if parser is None else parser
        if not parser.has_section("Options"):
            parser.add_section("Options")
        for section_name, marks in {
            "CMarks": self.CMarks,
            "AMarks": self.AMarks,
            "BMarks": self.BMarks,
        }.items():
            if not parser.has_section(section_name):
                parser.add_section(section_name)
            for key, value in marks.items():
                if not parser.has_option(section_name, key):
                    parser.set(section_name, key, str(value))

    def _atomic_write(self, candidate: Optional[configparser.ConfigParser] = None) -> None:
        """Write the config file atomically (temp file + fsync + rename).

        The calibration file used to be rewritten in place; a power cut
        mid-write -- routine on a kiosk Pi -- corrupted it, and the next
        boot silently ran on generated default geometry.

        Args:
            candidate: Parser to persist, or the live parser when omitted.
                This method does not publish the candidate to live state.

        Raises:
            Exception: Write errors propagate to the caller after temp-file cleanup.
        """
        parser = self.config if candidate is None else candidate
        directory = os.path.dirname(os.path.abspath(self.configFile)) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".kneespa_cfg_", dir=directory, text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                parser.write(tmp_file)
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
            "calibration": str(self.calibration),
        }
        self.config["AMarks"] = {k: str(v) for k, v in self.AMarks.items()}
        self.config["BMarks"] = {k: str(v) for k, v in self.BMarks.items()}
        self.config["CMarks"] = {k: str(v) for k, v in self.CMarks.items()}
        self._set_section("Device", {"id": self.device_id, "number": self.device_number})
        self._atomic_write()

    def _populate_config(
        self, parser: configparser.ConfigParser, defaults: Optional[Dict[str, float]] = None,
    ) -> None:
        """Copy current values and optional new defaults into the selected parser."""
        section = "Options"
        if not parser.has_section(section):
            parser.add_section(section)

        # List of configuration options to update
        config_options = [
            "flexion_position", "a_factor", "b_factor", "c_factor",
            "calibration"
        ]

        # Set each option in the config
        for option in config_options:
            if hasattr(self, option):
                parser.set(section, option, str(getattr(self, option)))

        # Persist the Phase-3.5 sections alongside the legacy Options.
        # Protocol defaults are only written once an operator marked them;
        # a stale auto-written section is dropped so the file cannot pin
        # old code defaults.
        if defaults is not None or self.protocol_defaults_marked:
            self._set_section("ProtocolDefaults", {
                "marked": 1,
                **(self.protocol_defaults() if defaults is None else defaults),
            }, parser)
        elif parser.has_section("ProtocolDefaults"):
            parser.remove_section("ProtocolDefaults")
        self._set_section("Device", {
            "id": self.device_id, "number": self.device_number,
        }, parser)

    def update_config(self):
        """Update current values, retaining this caller's legacy error reporting."""
        self._populate_config(self.config)
        print("Config updated")
        try:
            self._ensure_config_sections()
            self._atomic_write()
        except Exception as e:
            print(str(e))
            print(f'Fatal error, could not write config file to "{self.configFile}"')

    def _set_default_c_marks(self):
        """Set default CMarks values for lateral actuator."""
        self.CMarks = {
            "-20.0": 500,
            "-17.5": 635,
            "-15.0": 770,
            "-12.5": 905,
            "-10.0": 1042,
            "-7.5": 1203,
            "-5.0": 1364,
            "-2.5": 1526,
            "0.0": 1688,
            "2.5": 1806,
            "5.0": 1925,
            "7.5": 2044,
            "10.0": 2162,
            "12.5": 2223,
            "15.0": 2282,
            "17.5": 2341,
            "20.0": 2400,
        }

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
