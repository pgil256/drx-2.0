import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

import pytest

from config.constants import (
    PRESSURE_MAX, PRESSURE_WARNING_MAX, MIN_PRESSURE, AXIAL_MAX,
    LATERAL_MIN, LATERAL_MAX, HORIZONTAL_MIN, HORIZONTAL_MAX,
    EMERGENCYSTOP, EXTRAFORWARD, EXTRABACKWARD, EXTRAENABLE,
    ACTUATORS, PROTOCOL_MAPPING, PROTOCOL_DEFAULT_SETTINGS,
    ARDUINO_SETTINGS,
)
from config import constants


@pytest.mark.unit
@pytest.mark.parametrize("nested", [False, True])
def test_required_paths_must_exist_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool,
) -> None:
    """Missing shipped resources fail validation until actually created."""
    resource = tmp_path / "ui" / "media" / "videos"
    paths = {"VIDEOS": {"DEMO": str(resource)} if nested else str(resource)}
    monkeypatch.setattr(constants, "UI_PATHS", paths)
    with pytest.raises(FileNotFoundError, match="Required path not found"):
        constants.validate_paths()

    os.makedirs(resource)
    constants.validate_paths()
    assert resource.is_dir()


def read_isolated_constants(overrides: Dict[str, str]) -> dict:
    """Import constants in a child with synthetic settings, preserving parent imports."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("KNEESPA_")}
    env.update(overrides)
    env["KNEESPA_SKIP_PATH_VALIDATION"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", "\n".join([
            "import json, sys",
            "sys.path.insert(0, 'main')",
            "from config import constants as c",
            "print(json.dumps({name: getattr(c, name) for name in "
            "('APP_BASE_DIR', 'CONFIG_PATH', 'LOG_DIR', 'DATA_PATHS', 'UI_PATHS', "
            "'EMAIL_CONFIG')}))",
        ])],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return json.loads(result.stdout)


@pytest.mark.unit
class TestEnvironmentOverrides:
    """Configured paths and SMTP settings reach their runtime consumers."""

    def test_base_directory_controls_default_paths(self, tmp_path: Path) -> None:
        base = tmp_path / "device files"
        values = read_isolated_constants({"KNEESPA_BASE_DIR": str(base)})
        assert values["APP_BASE_DIR"] == str(base)
        assert Path(values["CONFIG_PATH"]) == base.parent / "config" / "kneespa.cfg"
        assert Path(values["LOG_DIR"]) == base.parent / "logs"
        assert {key: Path(value) for key, value in values["DATA_PATHS"].items()} == {
            "USER_PINS": base / "data" / "user_pins.csv",
            "AUTH_STATE": base / "data" / "auth_state.json",
            "PENDING_UPLOADS": base / "data" / "pending_uploads.json",
        }
        assert Path(values["UI_PATHS"]["VIDEOS"]) == base / "ui" / "media" / "videos"

    def test_explicit_config_path_overrides_base(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom config.cfg"
        values = read_isolated_constants({
            "KNEESPA_BASE_DIR": str(tmp_path / "base"),
            "KNEESPA_CONFIG_PATH": str(custom),
        })
        assert values["CONFIG_PATH"] == str(custom)

    def test_smtp_environment_overrides(self) -> None:
        values = read_isolated_constants({
            "KNEESPA_SMTP_USERNAME": "sender@example.invalid",
            "KNEESPA_SMTP_PASSWORD": "synthetic-test-password",
            "KNEESPA_ASSISTANCE_EMAIL": "help@example.invalid",
            "KNEESPA_TICKET_EMAIL": "tickets@example.invalid",
            "KNEESPA_SMTP_SERVER": "smtp.example.invalid",
            "KNEESPA_SMTP_PORT": "2465",
        })
        assert values["EMAIL_CONFIG"] == {
            "SENDER_EMAIL": "sender@example.invalid",
            "SENDER_PASSWORD": "synthetic-test-password",
            "RECEIVER_EMAIL": "help@example.invalid",
            "TICKET_EMAIL": "tickets@example.invalid",
            "SMTP_SERVER": "smtp.example.invalid",
            "SMTP_PORT": 2465,
        }


@pytest.mark.unit
class TestSafetyLimits:
    """Verify safety constants haven't been accidentally changed."""

    def test_pressure_max(self):
        assert PRESSURE_MAX == 80

    def test_pressure_warning_max(self):
        assert PRESSURE_WARNING_MAX == 100

    def test_min_pressure(self):
        assert MIN_PRESSURE == 10

    def test_min_less_than_max_pressure(self):
        assert MIN_PRESSURE < PRESSURE_MAX

    def test_axial_max(self):
        assert AXIAL_MAX == 4600

    def test_lateral_range(self):
        assert LATERAL_MIN == 500
        assert LATERAL_MAX == 2400
        assert LATERAL_MIN < LATERAL_MAX

    def test_horizontal_range(self):
        # The calibrated -25 deg BMarks mark is position 0; a floor of 50 clamped
        # and then flagged legal -25 deg moves (211 false warnings in device logs).
        assert HORIZONTAL_MIN == 0
        assert HORIZONTAL_MAX == 4500
        assert HORIZONTAL_MIN < HORIZONTAL_MAX


@pytest.mark.unit
class TestGPIOPins:
    """Verify GPIO pin assignments are valid BCM pin numbers."""

    def test_emergency_stop_pin(self):
        assert 0 <= EMERGENCYSTOP <= 27

    def test_extra_forward_pin(self):
        assert 0 <= EXTRAFORWARD <= 27

    def test_extra_backward_pin(self):
        assert 0 <= EXTRABACKWARD <= 27

    def test_extra_enable_pin(self):
        assert 0 <= EXTRAENABLE <= 27

    def test_no_duplicate_pins(self):
        pins = [EMERGENCYSTOP, EXTRAFORWARD, EXTRABACKWARD, EXTRAENABLE]
        assert len(pins) == len(set(pins)), "GPIO pins must be unique"


@pytest.mark.unit
class TestActuatorConfig:
    """Verify actuator configuration is consistent."""

    def test_all_actuators_defined(self):
        assert "AXIAL" in ACTUATORS
        assert "HORIZONTAL" in ACTUATORS
        assert "LATERAL" in ACTUATORS

    def test_actuator_limits_ordered(self):
        for name, cfg in ACTUATORS.items():
            low, high = cfg["LIMITS"]
            assert low < high, f"{name} limits are inverted: {low} >= {high}"

    def test_actuator_ids_unique(self):
        ids = [cfg["ID"] for cfg in ACTUATORS.values()]
        assert len(ids) == len(set(ids))

    def test_actuator_command_prefixes(self):
        assert ACTUATORS["AXIAL"]["COMMAND_PREFIX"] == "A12"
        assert ACTUATORS["HORIZONTAL"]["COMMAND_PREFIX"] == "B"
        assert ACTUATORS["LATERAL"]["COMMAND_PREFIX"] == "K"


@pytest.mark.unit
class TestProtocolConfig:
    """Verify protocol configuration values."""

    def test_protocol_mapping_has_four_protocols(self):
        assert len(PROTOCOL_MAPPING) == 4
        for i in range(1, 5):
            assert i in PROTOCOL_MAPPING

    def test_protocol_defaults_pressure_range(self):
        assert PROTOCOL_DEFAULT_SETTINGS["MIN_PRESSURE"] == 10
        assert PROTOCOL_DEFAULT_SETTINGS["MAX_SAFE_PRESSURE"] == 80
        assert PROTOCOL_DEFAULT_SETTINGS["MIN_PRESSURE"] < PROTOCOL_DEFAULT_SETTINGS["MAX_SAFE_PRESSURE"]

    def test_pressure_increment_positive(self):
        assert PROTOCOL_DEFAULT_SETTINGS["PRESSURE_INCREMENT"] > 0

    def test_numeric_pulse_cadence_enabled_by_default(self):
        env = os.environ.copy()
        env.pop("KNEESPA_PULSE_RATE_FIRMWARE", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'main'); "
                    "from config.constants import PULSE_RATE_FIRMWARE_SUPPORT; "
                    "print(int(PULSE_RATE_FIRMWARE_SUPPORT))"
                ),
            ],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
        assert result.stdout.strip() == "1"

    def test_numeric_pulse_cadence_has_zero_override(self):
        env = os.environ.copy()
        env["KNEESPA_PULSE_RATE_FIRMWARE"] = "0"
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; sys.path.insert(0, 'main'); "
                    "from config.constants import PULSE_RATE_FIRMWARE_SUPPORT; "
                    "print(int(PULSE_RATE_FIRMWARE_SUPPORT))"
                ),
            ],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )
        assert result.stdout.strip() == "0"


@pytest.mark.unit
class TestArduinoSettings:
    """Verify Arduino communication settings."""

    def test_port(self):
        assert ARDUINO_SETTINGS["ARDUINO_PORT"] == "/dev/serial0"

    def test_buffer_warning_threshold(self):
        assert 0 < ARDUINO_SETTINGS["BUFFER_WARNING_THRESHOLD"] < 1

    def test_connection_timeout_positive(self):
        assert ARDUINO_SETTINGS["CONNECTION_TIMEOUT_S"] > 0
