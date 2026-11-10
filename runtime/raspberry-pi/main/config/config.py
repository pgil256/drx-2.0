import configparser
import copy
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Dict, Mapping, Optional

from helpers.motor_speed import motor_speed_values

from config.constants import (
    APP_NAME,
    CONFIG_PATH,
    DEFAULT_CONFIG_PATH,
    DEFAULT_PROTOCOL_MINUTES,
    LEGACY_CONFIG_PATH,
)

# A plain child of the application logger: helpers.logging creates the run's
# log files when imported, which tools that only read a configuration must
# not trigger. Records reach the app handlers once the app has set them up.
logger = logging.getLogger(f"{APP_NAME}.config")

# A real HX711 scale factor for this hardware is in the tens of
# thousands (the shipped device uses -28369). Small magnitudes mean the
# factory default (1.0) is still in place and "pressure" would be raw
# ADC counts.
MIN_PLAUSIBLE_SCALE_FACTOR = 1000.0


class ConfigUnreadableError(OSError):
    """A save was refused because the file on disk failed to load.

    Saving would replace whatever calibration and identity the file still
    holds with generated defaults. An OSError, so callers report it the way
    they already report any other failed write.
    """


class Configuration:
    def __init__(self, config_path: Optional[str] = None):
        self.flexion_position = 0
        self.a_factor = 1900
        self.b_factor = 1900
        self.c_factor = 1900
        # "unlock" was a legacy unused option that carried a real code in
        # shipped configs; it is no longer read, written, or defaulted.
        self.calibration = 1.0
        # Legacy AMarks were not used for axial commands. Opt in only after
        # a technician measures the axial endpoints in the service wizard.
        self.axial_service_calibrated = False
        # Values that are in the file but did not parse, as (section, option)
        # -> the default used in memory instead. A save leaves their text in
        # the file: writing the default over `b_factor = 372O` destroyed the
        # only record of what the technician meant, and the default then
        # loaded cleanly on every later start.
        self._mistyped: Dict[tuple, object] = {}
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
        # True when the file exists but could not be loaded (a bad line from
        # a hand edit, SD-card corruption). The values in memory are then
        # generated defaults, so every write is refused: the next startup
        # used to save them over the calibration and identity in the file.
        # Cleared only by a load that succeeds.
        self.unreadable = False
        # Where the file that failed to load was copied for whoever repairs
        # it, or None if it loaded or the copy could not be made.
        self.unreadable_copy: Optional[str] = None
        # Mark tables that were generated at load because the file's section
        # was missing or would not parse. A save does not add them to the
        # file: once saved, they loaded as a real calibration on the next
        # start, or stayed as extra rows in a table whose typo was then
        # fixed. Only a calibration that commits the whole table writes it.
        self._generated_marks = set()

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
        self._temporary_device_id = ""
        self.device_number = 1

    @property
    def calibrated(self) -> bool:
        return self.marks_valid and self.scale_calibrated

    def _flag_error(self, message: str):
        logger.warning("CALIBRATION: %s", message)
        self.calibration_errors.append(message)

    def get_config(self, config_path: Optional[str] = None):

        self.config = configparser.ConfigParser(allow_no_value=True)
        self._mistyped = {}
        if config_path:
            self.configFile = config_path
        self.calibration_errors = []
        self.marks_valid = False
        self.scale_calibrated = False
        self.unreadable = False
        self.unreadable_copy = None
        self._generated_marks = set()
        # Load configuration
        self.axial_service_calibrated = False
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
            # Not ConfigParser.read(): it skips a file it cannot open, which
            # then looks like an empty one and gets defaults saved over it.
            with open(self.configFile, encoding="utf-8") as source:
                self.config.read_file(source)

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
            logger.exception('Fatal error, could not load config file from "%s"', self.configFile)
            self.unreadable = True
            self.unreadable_copy = self._keep_unreadable_copy()
            self._set_default_c_marks()
            self._set_default_a_marks()
            self._set_default_b_marks()
            self._flag_error(
                f"Config file unreadable ({e}); generated default marks in use. "
                "Device is UNCALIBRATED. The file was left unchanged: fix or "
                "restore it, then restart."
            )

    def _keep_unreadable_copy(self) -> Optional[str]:
        """Copy the file that failed to load beside itself; return the copy's path.

        The application does not write to the file in this state, but the
        copy keeps the evidence if a repair by hand goes wrong. It is
        named <file>.unreadable-<UTC time>, created owner-only (0600) like
        the configuration itself, and never replaces an earlier copy. The
        same content is kept once, so a device restarting on the same bad
        file does not fill its storage. A failure here is logged and must
        not stop startup.
        """
        try:
            with open(self.configFile, "rb") as source:
                content = source.read()
            directory = os.path.dirname(os.path.abspath(self.configFile))
            prefix = os.path.basename(self.configFile) + ".unreadable-"
            for name in sorted(os.listdir(directory)):
                earlier = os.path.join(directory, name)
                if name.startswith(prefix) and os.path.isfile(earlier):
                    with open(earlier, "rb") as kept:
                        if kept.read() == content:
                            logger.warning(
                                'The unreadable config file is already kept at "%s"', earlier
                            )
                            return earlier
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            for attempt in range(100):
                path = os.path.join(
                    directory, prefix + stamp + (f"-{attempt}" if attempt else "")
                )
                try:
                    fd = os.open(path, flags, 0o600)
                    break
                except FileExistsError:
                    continue
            else:
                raise FileExistsError(f"no free name for a copy at {path}")
            try:
                with os.fdopen(fd, "wb") as target:
                    target.write(content)
                    target.flush()
                    os.fsync(target.fileno())
            except Exception:
                os.unlink(path)  # a partial copy would pass for the evidence
                raise
            logger.warning('Kept a copy of the unreadable config file at "%s"', path)
            return path
        except Exception:
            logger.exception(
                'Could not keep a copy of the unreadable config file "%s"', self.configFile
            )
            return None

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
                self._generated_marks.add("CMarks")
                self._flag_error(f"CMarks malformed ({e}); defaults in use")
        else:
            self._set_default_c_marks()
            self._generated_marks.add("CMarks")
            self._flag_error("CMarks section missing; defaults in use")

        if "AMarks" in allSections:
            try:
                self.AMarks = {k: int(v) for k, v in allSections["AMarks"].items()}
            except (ValueError, TypeError) as e:
                self._set_default_a_marks()
                self._generated_marks.add("AMarks")
                self._flag_error(f"AMarks malformed ({e}); defaults in use")
        else:
            self._set_default_a_marks()
            self._generated_marks.add("AMarks")
            self._flag_error("AMarks section missing; defaults in use")

        if "BMarks" in allSections:
            try:
                self.BMarks = {k: int(v) for k, v in allSections["BMarks"].items()}
            except (ValueError, TypeError) as e:
                self._set_default_b_marks()
                self._generated_marks.add("BMarks")
                self._flag_error(f"BMarks malformed ({e}); defaults in use")
        else:
            self._set_default_b_marks()
            self._generated_marks.add("BMarks")
            self._flag_error("BMarks section missing; defaults in use")

    def _load_options(self):
        """Load scalar options with type-aware fallback defaults."""
        section = "Options"
        if not self.config.has_section(section):
            self.config.add_section(section)

        try:
            self.axial_service_calibrated = self.config.getboolean(
                section, "axial_service_calibrated", fallback=False,
            )
        except ValueError:
            self.axial_service_calibrated = False
            self._mistyped[(section, "axial_service_calibrated")] = False
            self._flag_error("Invalid axial_service_calibrated flag; device is UNCALIBRATED")

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
                logger.warning("Error parsing %s: %s, using default", option_name, e)
                value = option_settings["default"]
                self._flag_mistyped_option(option_name, raw_value, value)
                # The live parser keeps the text as written, so the saves
                # that copy it (hardware service, calibration restore) do too.
                self._mistyped[(section, option_name)] = value
            setattr(self, option_name, value)

    def _flag_mistyped_option(self, name: str, raw: object, default: object) -> None:
        """Report an [Options] value that is present but did not parse.

        A hand edit such as ``b_factor = 372O`` (letter O) used to load as
        the default with only a log line, so the device ran on a factor
        nobody measured and still looked calibrated.
        """
        if name == "calibration":
            # Not worded as "UNCALIBRATED": _validate_calibration() takes
            # that word to mean the mark tables cannot be trusted. Pressure
            # is blocked by its check that the default 1.0 is implausible.
            self._flag_error(
                f"[Options] calibration = {raw!r} is not a number, so the "
                "load-cell scale factor was not loaded. Correct the value in "
                "the file and restart."
            )
        elif name in ("a_factor", "b_factor", "c_factor"):
            self._flag_error(
                f"[Options] {name} = {raw!r} is not a whole number; default "
                f"{default} in use. Device is UNCALIBRATED: correct the value "
                "in the file and restart."
            )
        # flexion_position is loaded and saved but used by nothing, so it
        # gets the log line above and does not disable the device.

    def _keeps_mistyped(self, section: str, option: str, value: object) -> bool:
        """Whether a save must leave this option's text as it is in the file.

        True while the value in memory is still the default that stood in for
        text that did not parse. A value set on purpose since then is saved
        as usual, and the option is no longer treated as mistyped.
        """
        key = (section, option)
        if key not in self._mistyped:
            return False
        if value == self._mistyped[key]:
            return True
        del self._mistyped[key]
        return False

    def is_mistyped(self, option: str) -> bool:
        """Whether an [Options] value in memory is only a stand-in default.

        A calibration backup must not record that default as the device's
        own value: restoring it would write the default over the text.
        """
        key = ("Options", option)
        return key in self._mistyped and getattr(self, option) == self._mistyped[key]

    def _load_protocol_defaults(self):
        """Load persisted Treatment Settings defaults, keeping __init__ fallbacks
        for any malformed/absent value."""
        section = "ProtocolDefaults"
        if not self.config.has_section(section):
            return
        if self.config.get(section, "marked", fallback="") != "1":
            logger.info(
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
                    logger.warning(
                        "Error parsing ProtocolDefaults.%s: %s, using default", key, e
                    )
        for key in motor_speed_values():
            try:
                values = motor_speed_values({key: self.config.getfloat(
                    section, key, fallback=getattr(self, f"default_{key}")
                )})
                setattr(self, f"default_{key}", values[key])
            except (ValueError, TypeError):
                logger.warning("Invalid ProtocolDefaults.%s; using default motor speed", key)

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
        logger.info(
            "Copied legacy configuration from %s to %s", LEGACY_CONFIG_PATH, self.configFile
        )

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
            # A label, not calibration: the device runs as number 1 and is
            # not disabled. The text stays in the file so it can be corrected.
            logger.warning(
                "Invalid Device.number %r; running as device 1. The value was "
                "left in the file: correct it there and restart.", raw_number,
            )
            self.device_number = 1
            self._mistyped[("Device", "number")] = 1
            return
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
        self.commit(candidate, {
            **{f"default_{key}": value for key, value in defaults.items()},
            "protocol_defaults_marked": True,
        }, revalidate=False)

    def commit(self, candidate: configparser.ConfigParser,
               attrs: Mapping[str, object], revalidate: bool = True) -> None:
        """Persist a candidate parser, then publish it and the matching values.

        Live state changes only after the file was written (B1/F7): a write
        error propagates with the previous parser and attributes untouched.
        ``revalidate`` recomputes calibration confidence from the new values.
        """
        self._atomic_write(candidate)
        self.config = candidate
        for name, value in attrs.items():
            setattr(self, name, value)
            # The caller wrote a reviewed value for this option into the
            # candidate, so its mistyped text is gone from the file.
            self._mistyped.pop(("Options", name), None)
        if revalidate:
            self._validate_calibration()

    def ensure_device_id(self):
        """Return the persisted per-device id, generating + saving one if absent.

        While the file is unreadable its own id cannot be read and nothing
        may be saved, so the caller gets an id for this run only. It is
        marked "temporary-" wherever it is shown, is never stored in
        device_id, and is not written to the file once that loads again.
        """
        if self.device_id:
            return self.device_id
        if self.unreadable:
            if not self._temporary_device_id:
                self._temporary_device_id = "temporary-" + uuid.uuid4().hex[:12]
            return self._temporary_device_id
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
        # Re-evaluate service validation errors after a technician repairs a
        # table. Keep load/fallback errors: untouched defaults are not measured.
        service_error_prefix = "Axial service calibration: "
        self.calibration_errors = [
            error for error in self.calibration_errors
            if not error.startswith(service_error_prefix)
        ]
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
        if self.axial_service_calibrated:
            # Lazy import avoids a module dependency cycle. Only opted-in
            # axial tables obey the stricter measured-distance contract.
            from helpers.hardware_service import validate_axis_marks

            try:
                validate_axis_marks("axial", self.AMarks)
            except (ValueError, TypeError) as error:
                marks_ok = False
                self._flag_error(f"{service_error_prefix}{error}")
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
        """Ensure the parser holds the sections a save writes.

        A mark table that was generated at load is left out, so the file
        keeps its missing or mistyped section instead of gaining generated
        marks.
        """
        parser = self.config if parser is None else parser
        if not parser.has_section("Options"):
            parser.add_section("Options")
        for section_name, marks in {
            "CMarks": self.CMarks,
            "AMarks": self.AMarks,
            "BMarks": self.BMarks,
        }.items():
            if section_name in self._generated_marks:
                continue
            if not parser.has_section(section_name):
                parser.add_section(section_name)
            for key, value in marks.items():
                if not parser.has_option(section_name, key):
                    parser.set(section_name, key, str(value))

    def refuse_if_unreadable(self) -> None:
        """Raise ConfigUnreadableError if the file failed to load.

        Every write does this. A caller that prepares anything on disk
        before its save calls it first, so a refused save leaves nothing.
        """
        if self.unreadable:
            raise ConfigUnreadableError(
                f'"{self.configFile}" failed to load and was left unchanged; '
                "nothing can be saved until it is fixed or restored and the "
                "application restarted"
            )

    def _atomic_write(self, candidate: Optional[configparser.ConfigParser] = None) -> None:
        """Write the config file atomically (temp file + fsync + rename).

        The calibration file used to be rewritten in place; a power cut
        mid-write -- routine on a kiosk Pi -- corrupted it, and the next
        boot silently ran on generated default geometry.

        Args:
            candidate: Parser to persist, or the live parser when omitted.
                This method does not publish the candidate to live state.

        Raises:
            ConfigUnreadableError: The file failed to load; nothing is written.
            Exception: Write errors propagate to the caller after temp-file cleanup.
        """
        self.refuse_if_unreadable()
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
            "axial_service_calibrated": str(self.axial_service_calibrated),
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
            "calibration", "axial_service_calibrated"
        ]

        # Set each option in the config
        for option in config_options:
            if hasattr(self, option) and not self._keeps_mistyped(
                section, option, getattr(self, option),
            ):
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
        device: Dict[str, object] = {"id": self.device_id}
        if not self._keeps_mistyped("Device", "number", self.device_number):
            device["number"] = self.device_number
        self._set_section("Device", device, parser)

    def update_config(self):
        """Update current values, retaining this caller's legacy error reporting."""
        if self.unreadable:
            logger.error(
                'Config not written: "%s" failed to load and was left unchanged. '
                "Fix or restore the file, then restart.", self.configFile,
            )
            return
        self._populate_config(self.config)
        logger.info("Config updated")
        try:
            self._ensure_config_sections()
            self._atomic_write()
        except Exception:
            logger.exception('Fatal error, could not write config file to "%s"', self.configFile)

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
