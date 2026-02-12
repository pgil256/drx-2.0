# tests/unit/test_constants.py
import pytest

from config.constants import (
    PRESSURE_MAX, MIN_PRESSURE, AXIAL_MAX,
    LATERAL_MIN, LATERAL_MAX, HORIZONTAL_MIN, HORIZONTAL_MAX,
    EMERGENCYSTOP, EXTRAFORWARD, EXTRABACKWARD, EXTRAENABLE,
    ACTUATORS, PROTOCOL_MAPPING, PROTOCOL_DEFAULT_SETTINGS,
    ARDUINO_SETTINGS,
)


@pytest.mark.unit
class TestSafetyLimits:
    """Verify safety constants haven't been accidentally changed."""

    def test_pressure_max(self):
        assert PRESSURE_MAX == 80

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
        assert HORIZONTAL_MIN == 50
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


@pytest.mark.unit
class TestArduinoSettings:
    """Verify Arduino communication settings."""

    def test_port(self):
        assert ARDUINO_SETTINGS["ARDUINO_PORT"] == "/dev/serial0"

    def test_buffer_warning_threshold(self):
        assert 0 < ARDUINO_SETTINGS["BUFFER_WARNING_THRESHOLD"] < 1

    def test_connection_timeout_positive(self):
        assert ARDUINO_SETTINGS["CONNECTION_TIMEOUT_S"] > 0
