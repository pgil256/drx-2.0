# KneeSpa Test Suite Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a CI/CD-friendly test suite covering Python application code and Arduino firmware, runnable on Linux/WSL without hardware.

**Architecture:** Three-tier pytest suite (unit/integration/hardware) with a FakeArduino pty-based simulator for integration tests. Arduino firmware tested separately via PlatformIO + Unity with mock hardware libraries.

**Tech Stack:** pytest, pytest-mock, pytest-qt, pytest-cov, pytest-timeout, PlatformIO, Unity test framework

---

### Task 1: Test Infrastructure Setup

**Files:**
- Create: `requirements-test.txt`
- Create: `pytest.ini`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/hardware/__init__.py`
- Create: `tests/fixtures/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create requirements-test.txt**

```
# requirements-test.txt
pytest>=7.0
pytest-mock
pytest-qt
pytest-cov
pytest-timeout
```

**Step 2: Create pytest.ini**

```ini
[pytest]
markers =
    unit: Pure logic tests, no hardware or Qt
    integration: FakeArduino + Qt signal tests
    hardware: Requires real Pi + Arduino
testpaths = tests
timeout = 30
qt_api = pyqt5
```

**Step 3: Create directory structure with __init__.py files**

```bash
mkdir -p tests/unit tests/integration tests/hardware tests/fixtures tests/fixtures/sample_configs
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/hardware/__init__.py tests/fixtures/__init__.py
```

**Step 4: Create conftest.py with path setup and GPIO mock**

```python
# tests/conftest.py
import sys
import os
import pytest
from unittest.mock import MagicMock

# Add main/ to sys.path so imports like `from config.constants import ...` work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'main'))

# Mock RPi.GPIO before any module imports it
sys.modules['RPi'] = MagicMock()
sys.modules['RPi.GPIO'] = MagicMock()

# Set Qt to offscreen mode for headless testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
```

**Step 5: Install test dependencies**

Run: `pip install -r requirements-test.txt`

**Step 6: Verify pytest discovers the test directory**

Run: `python -m pytest --collect-only`
Expected: `no tests ran` (0 items collected, no errors)

**Step 7: Commit**

```bash
git add requirements-test.txt pytest.ini tests/
git commit -m "feat: add test infrastructure with pytest config and fixtures"
```

---

### Task 2: Sample Config Fixtures

**Files:**
- Create: `tests/fixtures/sample_configs/valid.cfg`
- Create: `tests/fixtures/sample_configs/corrupt.cfg`
- Create: `tests/fixtures/sample_configs/empty.cfg`
- Create: `tests/fixtures/sample_configs/missing_sections.cfg`

**Step 1: Create valid config fixture**

```ini
# tests/fixtures/sample_configs/valid.cfg
[Options]
flexion_position = 0
a_factor = 1900
b_factor = 1900
c_factor = 1900
unlock = false
calibration = 1.0

[CMarks]
-20.0 = 98
-17.5 = 318
-15.0 = 538
-12.5 = 758
-10.0 = 978
-7.5 = 1198
-5.0 = 1418
-2.5 = 1638
0.0 = 1858
2.5 = 2078
5.0 = 2298
7.5 = 2518
10.0 = 2738
12.5 = 2958
15.0 = 3178
17.5 = 3398

[AMarks]
0 = 0
1 = 475
2 = 950
3 = 1425
4 = 1900

[BMarks]
-25 = 0
-20 = 380
-15 = 760
-10 = 1140
-5 = 1520
0 = 1900
5 = 2280
```

**Step 2: Create corrupt config (bad types)**

```ini
# tests/fixtures/sample_configs/corrupt.cfg
[Options]
flexion_position = not_a_number
a_factor = abc

[CMarks]
-20.0 = not_an_int
```

**Step 3: Create empty config**

```ini
# tests/fixtures/sample_configs/empty.cfg
```

**Step 4: Create config with missing sections**

```ini
# tests/fixtures/sample_configs/missing_sections.cfg
[Options]
flexion_position = 0
a_factor = 1900
```

**Step 5: Commit**

```bash
git add tests/fixtures/sample_configs/
git commit -m "feat: add sample config fixtures for testing"
```

---

### Task 3: Unit Tests - Configuration (test_config.py)

**Files:**
- Create: `tests/unit/test_config.py`
- Reference: `main/config/config.py`

**Step 1: Write the failing tests**

```python
# tests/unit/test_config.py
import pytest
import os
import configparser
from unittest.mock import patch

from config.config import Configuration
from config.constants import CONFIG_PATH


@pytest.fixture
def config_with_valid_file(tmp_path):
    """Create a Configuration that reads from a valid config file."""
    cfg_path = tmp_path / "kneespa.cfg"
    # Copy valid fixture
    fixture_path = os.path.join(
        os.path.dirname(__file__), '..', 'fixtures', 'sample_configs', 'valid.cfg'
    )
    cfg_path.write_text(open(fixture_path).read())

    with patch('config.config.CONFIG_PATH', str(cfg_path)):
        config = Configuration()
        config.get_config()
    return config


@pytest.fixture
def config_with_missing_file(tmp_path):
    """Create a Configuration with no existing config file."""
    cfg_path = tmp_path / "nonexistent.cfg"
    with patch('config.config.CONFIG_PATH', str(cfg_path)):
        config = Configuration()
        config.get_config()
    return config, cfg_path


@pytest.fixture
def config_with_corrupt_file(tmp_path):
    """Create a Configuration that reads from a corrupt config file."""
    cfg_path = tmp_path / "kneespa.cfg"
    fixture_path = os.path.join(
        os.path.dirname(__file__), '..', 'fixtures', 'sample_configs', 'corrupt.cfg'
    )
    cfg_path.write_text(open(fixture_path).read())

    with patch('config.config.CONFIG_PATH', str(cfg_path)):
        config = Configuration()
        config.get_config()
    return config


@pytest.fixture
def config_missing_sections(tmp_path):
    """Create a Configuration with missing CMarks/AMarks/BMarks sections."""
    cfg_path = tmp_path / "kneespa.cfg"
    fixture_path = os.path.join(
        os.path.dirname(__file__), '..', 'fixtures', 'sample_configs', 'missing_sections.cfg'
    )
    cfg_path.write_text(open(fixture_path).read())

    with patch('config.config.CONFIG_PATH', str(cfg_path)):
        config = Configuration()
        config.get_config()
    return config


@pytest.mark.unit
class TestConfigurationValidFile:
    """Tests for reading a valid configuration file."""

    def test_cmarks_loaded(self, config_with_valid_file):
        config = config_with_valid_file
        assert len(config.CMarks) == 16
        assert config.CMarks["-20.0"] == 98
        assert config.CMarks["0.0"] == 1858
        assert config.CMarks["17.5"] == 3398

    def test_amarks_loaded(self, config_with_valid_file):
        config = config_with_valid_file
        assert len(config.AMarks) == 5
        assert config.AMarks["0"] == 0
        assert config.AMarks["4"] == 1900

    def test_bmarks_loaded(self, config_with_valid_file):
        config = config_with_valid_file
        assert len(config.BMarks) == 7
        assert config.BMarks["-25"] == 0
        assert config.BMarks["5"] == 2280

    def test_options_loaded(self, config_with_valid_file):
        config = config_with_valid_file
        assert config.flexion_position == 0
        assert config.a_factor == 1900
        assert config.b_factor == 1900
        assert config.c_factor == 1900
        assert config.calibration == 1.0


@pytest.mark.unit
class TestConfigurationMissingFile:
    """Tests for behavior when config file doesn't exist."""

    def test_creates_file(self, config_with_missing_file):
        config, cfg_path = config_with_missing_file
        assert cfg_path.exists()

    def test_has_default_flexion(self, config_with_missing_file):
        config, _ = config_with_missing_file
        assert config.flexion_position == 0


@pytest.mark.unit
class TestConfigurationCorruptFile:
    """Tests for behavior with corrupt config data."""

    def test_falls_back_to_default_cmarks(self, config_with_corrupt_file):
        config = config_with_corrupt_file
        # Should have defaults since CMarks had non-integer values
        assert len(config.CMarks) == 16

    def test_no_crash(self, config_with_corrupt_file):
        """Corrupt file should not raise an exception."""
        assert config_with_corrupt_file is not None


@pytest.mark.unit
class TestConfigurationMissingSections:
    """Tests for config files missing CMarks/AMarks/BMarks."""

    def test_default_cmarks_used(self, config_missing_sections):
        config = config_missing_sections
        assert len(config.CMarks) == 16

    def test_default_amarks_used(self, config_missing_sections):
        config = config_missing_sections
        assert len(config.AMarks) == 5
        assert config.AMarks["0"] == 0

    def test_default_bmarks_used(self, config_missing_sections):
        config = config_missing_sections
        assert len(config.BMarks) == 7


@pytest.mark.unit
class TestConfigurationRoundTrip:
    """Tests for writing and reading back config."""

    def test_write_read_roundtrip(self, tmp_path):
        cfg_path = tmp_path / "kneespa.cfg"

        with patch('config.config.CONFIG_PATH', str(cfg_path)):
            # Write
            config = Configuration()
            config.get_config()  # Creates default file

            # Re-read from valid fixture to have full sections
            fixture_path = os.path.join(
                os.path.dirname(__file__), '..', 'fixtures', 'sample_configs', 'valid.cfg'
            )
            cfg_path.write_text(open(fixture_path).read())
            config.get_config()

            # Modify a value
            config.a_factor = 2500
            config.update_config()

            # Read back
            config2 = Configuration()
            config2.get_config()
            assert config2.a_factor == 2500


@pytest.mark.unit
class TestConfigurationDefaults:
    """Tests for default mark values."""

    def test_default_cmarks_values(self):
        config = Configuration()
        config._set_default_c_marks()
        # First entry: angle = (0 * 2.5) - 20 = -20.0, position = (0 * 220) + 98 = 98
        assert config.CMarks["-20.0"] == 98
        # Last entry: angle = (15 * 2.5) - 20 = 17.5, position = (15 * 220) + 98 = 3398
        assert config.CMarks["17.5"] == 3398

    def test_default_amarks_values(self):
        config = Configuration()
        config._set_default_a_marks()
        assert config.AMarks["0"] == 0
        assert config.AMarks["1"] == 475
        assert config.AMarks["4"] == 1900

    def test_default_bmarks_values(self):
        config = Configuration()
        config._set_default_b_marks()
        assert config.BMarks["-25"] == 0
        assert config.BMarks["0"] == 1900
        assert config.BMarks["5"] == 2280

    def test_default_c_factor(self):
        config = Configuration()
        assert config.c_factor == 1900
```

**Step 2: Run tests to verify they fail/pass**

Run: `python -m pytest tests/unit/test_config.py -v -m unit`
Expected: Tests should pass (these test existing behavior)

**Step 3: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "feat: add unit tests for Configuration class"
```

---

### Task 4: Unit Tests - Constants (test_constants.py)

**Files:**
- Create: `tests/unit/test_constants.py`
- Reference: `main/config/constants.py`

**Step 1: Write the tests**

```python
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
```

**Step 2: Run tests**

Run: `python -m pytest tests/unit/test_constants.py -v -m unit`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_constants.py
git commit -m "feat: add unit tests for safety constants"
```

---

### Task 5: Unit Tests - Arduino Status Parsing (test_arduino_parse.py)

**Files:**
- Create: `tests/unit/test_arduino_parse.py`
- Reference: `main/helpers/arduino.py:359-437` (handle_com method)

**Step 1: Write the tests**

```python
# tests/unit/test_arduino_parse.py
import pytest
from unittest.mock import MagicMock, patch
from PyQt5.QtCore import QObject

from helpers.arduino import Arduino


@pytest.fixture
def arduino():
    """Create an Arduino instance with mocked serial connection."""
    a = Arduino()
    a.serial_com = MagicMock()
    a.serial_com.is_open = True
    a.connected = True
    return a


@pytest.mark.unit
class TestStatusParsing:
    """Tests for handle_com parsing STATUS_START messages."""

    def test_valid_status_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3|STATUS_END")
        assert blocker.args == [1500, 2000, 1200, 45.3]

    def test_truncated_status_no_crash(self, arduino):
        """Truncated status (missing STATUS_END) should not crash."""
        arduino.handle_com("STATUS_START|S|1500|2000|1200|45.3")
        # Should not raise

    def test_status_with_zero_pressure(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.status_emit, timeout=1000) as blocker:
            arduino.handle_com("STATUS_START|S|0|0|0|0.0|STATUS_END")
        assert blocker.args == [0, 0, 0, 0.0]

    def test_status_too_few_fields(self, arduino):
        """Status with fewer than 5 tokens after S should not emit."""
        # This should not crash - it just won't emit since len(tokens) < 5
        arduino.handle_com("STATUS_START|S|1500|2000|STATUS_END")


@pytest.mark.unit
class TestDoneResponse:
    """Tests for DONE response parsing."""

    def test_done_emits_signal(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.done_emit, timeout=1000):
            arduino.handle_com("DONE")


@pytest.mark.unit
class TestOKResponse:
    """Tests for OK response parsing."""

    def test_ok_sets_event(self, arduino):
        arduino.ok_event.clear()
        arduino.handle_com("OK")
        assert arduino.ok_event.is_set()

    def test_ok_in_longer_string(self, arduino):
        arduino.ok_event.clear()
        arduino.handle_com("OK received")
        assert arduino.ok_event.is_set()


@pytest.mark.unit
class TestPositionResponse:
    """Tests for position response parsing."""

    def test_position_p_format(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.position_emit, timeout=1000) as blocker:
            arduino.handle_com("P|1500")
        assert blocker.args[0] == 1500

    def test_position_e_format(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.position_emit, timeout=1000) as blocker:
            arduino.handle_com("E|100|200|forward|14")
        assert blocker.args == [100, 200, "forward", 14]


@pytest.mark.unit
class TestPressureResponse:
    """Tests for pressure response parsing."""

    def test_pressure_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.pressure_emit, timeout=1000) as blocker:
            arduino.handle_com("PR|45.5")
        assert blocker.args == ["45.5"]


@pytest.mark.unit
class TestWeightResponse:
    """Tests for weight response parsing."""

    def test_weight_response(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.display_weight_emit, timeout=1000) as blocker:
            arduino.handle_com("weight|32.1")
        assert blocker.args == ["32.1"]


@pytest.mark.unit
class TestReadyToGo:
    """Tests for ready-to-go response parsing."""

    def test_ready_to_go(self, arduino, qtbot):
        with qtbot.waitSignal(arduino.ready_to_go_emit, timeout=1000):
            arduino.handle_com("Ready to Go")


@pytest.mark.unit
class TestGarbageInput:
    """Tests for malformed/garbage input."""

    def test_empty_string(self, arduino):
        arduino.handle_com("")
        # Should not crash

    def test_random_garbage(self, arduino):
        arduino.handle_com("xyzabc123!@#")
        # Should not crash

    def test_partial_status_delimiter(self, arduino):
        arduino.handle_com("STATUS_START|")
        # Should not crash
```

**Step 2: Run tests**

Run: `python -m pytest tests/unit/test_arduino_parse.py -v -m unit`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_arduino_parse.py
git commit -m "feat: add unit tests for Arduino status parsing"
```

---

### Task 6: Unit Tests - Protocol Logic (test_protocol_logic.py)

**Files:**
- Create: `tests/unit/test_protocol_logic.py`
- Reference: `main/helpers/protocols.py:264-315` (set_to_c_distance), `main/helpers/protocols.py:115-127` (check_duration)

**Step 1: Write the tests**

```python
# tests/unit/test_protocol_logic.py
import pytest
import time
from unittest.mock import MagicMock, patch

from helpers.protocols import Protocols, MIN_PRESSURE, MAX_SAFE_PRESSURE, PRESSURE_INCREMENT
from config.config import Configuration


def make_protocol(**kwargs):
    """Create a Protocols instance with mocked Arduino and sane defaults."""
    defaults = dict(
        a_factor=1900,
        protocol="1",
        max_pressure=50,
        max_left=10.0,
        max_right=10.0,
        duration=1,  # 1 minute
        use_pulse=False,
        ser=MagicMock(),
        config=None,
    )
    defaults.update(kwargs)

    # Build config with defaults
    if defaults["config"] is None:
        config = Configuration()
        config._set_default_c_marks()
        config._set_default_a_marks()
        config._set_default_b_marks()
        defaults["config"] = config

    return Protocols(**defaults)


@pytest.mark.unit
class TestCheckDuration:
    """Tests for protocol duration checking."""

    def test_returns_true_within_duration(self):
        p = make_protocol(duration=1)  # 1 minute = 60 seconds
        p.start_time = time.time()
        assert p.check_duration() is True

    def test_returns_false_after_duration(self):
        p = make_protocol(duration=1)
        p.start_time = time.time() - 120  # 2 minutes ago
        assert p.check_duration() is False

    def test_returns_false_without_start_time(self):
        p = make_protocol()
        p.start_time = None
        assert p.check_duration() is False

    def test_updates_elapsed_time(self):
        p = make_protocol(duration=1)
        p.start_time = time.time() - 30  # 30 seconds ago
        p.check_duration()
        assert 29 <= p.elapsed_time <= 31


@pytest.mark.unit
class TestSetToCDistance:
    """Tests for C actuator position calculation and interpolation."""

    def test_exact_mark_lookup(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 1858  # Already at target to avoid timeout

        result = p.set_to_c_distance(0.0)
        assert result is True
        # Should have sent K command with position from CMarks["0.0"]
        p.arduino.send.assert_called_with("K1858")

    def test_negative_degree(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 98  # At target

        result = p.set_to_c_distance(-20.0)
        assert result is True
        p.arduino.send.assert_called_with("K98")

    def test_positive_degree(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 3398  # At target

        result = p.set_to_c_distance(17.5)
        assert result is True
        p.arduino.send.assert_called_with("K3398")

    def test_interpolation_between_marks(self):
        """Degrees between marks should interpolate position linearly."""
        p = make_protocol()
        p.is_running = True
        # -20.0 -> 98, -17.5 -> 318. Midpoint -18.75 -> ~208
        p.current_pos_c = 208

        result = p.set_to_c_distance(-18.75)
        assert result is True
        # The command should have a K prefix with an interpolated value
        call_arg = p.arduino.send.call_args[0][0]
        assert call_arg.startswith("K")
        position = int(call_arg[1:])
        # Should be approximately 208 (midpoint between 98 and 318)
        assert 195 <= position <= 220

    def test_clamps_below_minus_20(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 98

        result = p.set_to_c_distance(-25.0)  # Should clamp to -20
        assert result is True
        p.arduino.send.assert_called_with("K98")

    def test_clamps_above_20(self):
        p = make_protocol()
        p.is_running = True
        p.current_pos_c = 3398

        result = p.set_to_c_distance(25.0)  # Should clamp to 17.5 (max mark)
        assert result is True


@pytest.mark.unit
class TestProtocolInit:
    """Tests for protocol initialization logic."""

    def test_max_left_forced_negative(self):
        p = make_protocol(max_left=15.0)
        assert p.max_left == -15.0

    def test_max_right_forced_positive(self):
        p = make_protocol(max_right=-10.0)
        assert p.max_right == 10.0

    def test_duration_converted_to_seconds(self):
        p = make_protocol(duration=5)  # 5 minutes
        assert p.duration == 300

    def test_initial_state(self):
        p = make_protocol()
        assert p.is_running is False
        assert p.current_pressure == 0
        assert p.current_pos_c == 0


@pytest.mark.unit
class TestSetToPressure:
    """Tests for direct pressure setting."""

    def test_rejects_negative_pressure(self):
        p = make_protocol()
        p.is_running = True
        result = p.set_to_pressure(-10)
        assert result is False

    def test_rejects_over_max_pressure(self):
        p = make_protocol()
        p.is_running = True
        result = p.set_to_pressure(MAX_SAFE_PRESSURE + 1)
        assert result is False

    def test_rejects_when_not_running(self):
        p = make_protocol()
        p.is_running = False
        result = p.set_to_pressure(50)
        assert result is False

    def test_sends_pressure_command(self):
        p = make_protocol()
        p.is_running = True
        p.current_pressure = 50  # Already at target
        result = p.set_to_pressure(50)
        assert result is True
        p.arduino.send.assert_called_with("P50")


@pytest.mark.unit
class TestProtocolConstants:
    """Tests for protocol-level constants."""

    def test_min_pressure(self):
        assert MIN_PRESSURE == 10

    def test_max_safe_pressure(self):
        assert MAX_SAFE_PRESSURE == 80

    def test_pressure_increment(self):
        assert PRESSURE_INCREMENT == 10
```

**Step 2: Run tests**

Run: `python -m pytest tests/unit/test_protocol_logic.py -v -m unit`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/unit/test_protocol_logic.py
git commit -m "feat: add unit tests for protocol logic and interpolation"
```

---

### Task 7: FakeArduino Simulator

**Files:**
- Create: `tests/fixtures/fake_arduino.py`

**Step 1: Write the FakeArduino simulator**

```python
# tests/fixtures/fake_arduino.py
"""
FakeArduino: A pty-based Arduino simulator for integration testing.

Creates a virtual serial port pair. The Arduino class connects to one end,
and FakeArduino reads/writes the other. Simulates command responses,
gradual position movement, and pressure changes.
"""
import os
import pty
import time
import threading
import select


class FakeArduino:
    """Simulates Arduino firmware behavior over a virtual serial port."""

    def __init__(self):
        # State mirrors real Arduino globals
        self.position_a: int = 0
        self.position_b: int = 0
        self.position_c: int = 1200  # center
        self.pressure: float = 0.0
        self.jerking: bool = False
        self.b_running: bool = False
        self.measure_pressure: bool = False
        self.high_frequency_status: bool = False

        # Configurable behavior
        self.movement_speed: float = 5000.0  # units per second (fast for tests)
        self.pressure_rate: float = 50.0     # lbs per second (fast for tests)

        # Fault injection state
        self._stalled_actuator: str | None = None
        self._delay_ms: int = 0
        self._corrupt_next: bool = False
        self._disconnected: bool = False

        # Internal state
        self._master_fd: int | None = None
        self._slave_fd: int | None = None
        self._slave_path: str | None = None
        self._running: bool = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Movement targets
        self._target_position_a: int | None = None
        self._target_position_b: int | None = None
        self._target_position_c: int | None = None
        self._target_pressure: float | None = None

        # Track commands received (for assertions)
        self.commands_received: list[str] = []

    @property
    def port(self) -> str:
        """The virtual serial port path for the Arduino class to connect to."""
        return self._slave_path

    def start(self):
        """Create pty pair and start command processing thread."""
        self._master_fd, self._slave_fd = pty.openpty()
        self._slave_path = os.ttyname(self._slave_fd)
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop processing and close pty."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._slave_fd is not None:
            try:
                os.close(self._slave_fd)
            except OSError:
                pass
            self._slave_fd = None

    def _run_loop(self):
        """Main loop: read commands, update state, send responses."""
        buffer = b""
        last_movement_time = time.time()
        last_hf_status_time = time.time()

        while self._running and self._master_fd is not None:
            try:
                # Check for incoming data
                ready, _, _ = select.select([self._master_fd], [], [], 0.01)
                if ready:
                    try:
                        data = os.read(self._master_fd, 1024)
                        if data:
                            buffer += data
                    except OSError:
                        break

                # Process complete commands (newline-terminated)
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    cmd = line.decode(errors="replace").strip()
                    if cmd:
                        self.commands_received.append(cmd)
                        self._process_command(cmd)

                # Simulate gradual movement
                now = time.time()
                dt = now - last_movement_time
                last_movement_time = now
                self._update_movement(dt)
                self._update_pressure(dt)

                # High-frequency status updates
                if self.high_frequency_status and now - last_hf_status_time >= 0.1:
                    self._send_status()
                    last_hf_status_time = now

            except Exception as e:
                if self._running:
                    print(f"FakeArduino error: {e}")
                break

    def _process_command(self, cmd: str):
        """Handle an incoming command string."""
        if self._delay_ms > 0:
            time.sleep(self._delay_ms / 1000.0)

        if len(cmd) == 0:
            return

        cmd_type = cmd[0]

        if cmd_type == 'T':
            self._write("OK\n")

        elif cmd_type == 'Q':
            pass  # Status acknowledgment

        elif cmd_type == 'S':
            self._send_status()

        elif cmd_type == 'H':
            if len(cmd) > 2 and cmd[1:3] == "F1":
                self.high_frequency_status = True
                self._send_status()
                self._write("DONE\n")
            elif len(cmd) > 2 and cmd[1:3] == "F0":
                self.high_frequency_status = False
                self._write("DONE\n")

        elif cmd_type == 'P':
            target = float(cmd[1:]) if len(cmd) > 1 else 0
            self._target_pressure = target
            self.measure_pressure = True
            self._send_status()

        elif cmd_type == 'I':
            actuator_id = cmd[1:3]
            position = int(cmd[3:]) if len(cmd) > 3 else 0
            if actuator_id == "12":
                self._target_position_a = position
            elif actuator_id == "13":
                self._target_position_b = position
            elif actuator_id == "14":
                self._target_position_c = position
            self.b_running = True

        elif cmd_type == 'K':
            position = int(cmd[1:]) if len(cmd) > 1 else 0
            self._target_position_c = position
            self.b_running = True

        elif cmd_type == 'A':
            actuator_id = cmd[1:3]
            inches = float(cmd[3:]) if len(cmd) > 3 else 0
            fullinch = {"12": 430, "13": 620, "14": 1880}.get(actuator_id, 430)
            position = int(fullinch * inches)
            if actuator_id == "12":
                self._target_position_a = position
            elif actuator_id == "13":
                self._target_position_b = position
            elif actuator_id == "14":
                self._target_position_c = position
            self.b_running = True

        elif cmd_type == 'J':
            if len(cmd) > 1 and cmd[1] == 'S':
                self.jerking = False
            else:
                self.jerking = True

        elif cmd_type == 'X':
            self.b_running = False
            self.measure_pressure = False
            self.jerking = False
            self._target_position_a = None
            self._target_position_b = None
            self._target_position_c = None
            self._target_pressure = None
            self._write("DONE\n")

        elif cmd_type == 'Y':
            self._write("Reset|\n")
            self._write("DONE\n")

        elif cmd_type == 'G':
            actuator_id = cmd[1:3]
            pos = {"12": self.position_a, "13": self.position_b, "14": self.position_c}.get(actuator_id, 0)
            self._write(f"P|{pos}\n")
            self._write("DONE\n")

        elif cmd_type == 'L':
            stage = cmd[1] if len(cmd) > 1 else '0'
            if stage == '4':
                self._write(f"weight|{self.pressure}\n")
            elif stage == '5':
                self._write("DONE\n")
            elif stage == '6':
                self._send_status()
            else:
                self._write("DONE\n")

    def _update_movement(self, dt: float):
        """Gradually move actuators toward their targets."""
        step = int(self.movement_speed * dt)
        if step < 1:
            step = 1

        for attr, target_attr in [
            ("position_a", "_target_position_a"),
            ("position_b", "_target_position_b"),
            ("position_c", "_target_position_c"),
        ]:
            target = getattr(self, target_attr)
            if target is None:
                continue

            # Check stall
            actuator_letter = attr[-1]
            if self._stalled_actuator == actuator_letter:
                continue

            current = getattr(self, attr)
            if abs(current - target) <= step:
                setattr(self, attr, target)
                setattr(self, target_attr, None)
                if not any([self._target_position_a, self._target_position_b, self._target_position_c]):
                    self.b_running = False
                self._send_status()
            elif current < target:
                setattr(self, attr, current + step)
            else:
                setattr(self, attr, current - step)

    def _update_pressure(self, dt: float):
        """Gradually ramp pressure toward target."""
        if self._target_pressure is None:
            return

        step = self.pressure_rate * dt
        diff = self._target_pressure - self.pressure

        if abs(diff) <= step:
            self.pressure = self._target_pressure
            self._target_pressure = None
            self.measure_pressure = False
            self._send_status()
        elif diff > 0:
            self.pressure += step
        else:
            self.pressure -= step

    def _send_status(self):
        """Send status in the real Arduino format."""
        if self._corrupt_next:
            self._corrupt_next = False
            self._write("STATUS_START|GARBAGE|STATUS_END\n")
            return

        self._write(
            f"STATUS_START|S|{self.position_a}|{self.position_b}"
            f"|{self.position_c}|{self.pressure:.1f}|STATUS_END\n"
        )

    def _write(self, data: str):
        """Write data to the master side of the pty."""
        if self._master_fd is not None and not self._disconnected:
            try:
                os.write(self._master_fd, data.encode())
            except OSError:
                pass

    # --- Fault injection methods ---

    def simulate_disconnect(self):
        """Close the pty to simulate a serial disconnect."""
        self._disconnected = True
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    def simulate_stall(self, actuator: str):
        """Stop position updates for an actuator ('a', 'b', or 'c')."""
        self._stalled_actuator = actuator

    def clear_stall(self):
        """Resume normal movement."""
        self._stalled_actuator = None

    def simulate_pressure_overshoot(self, amount: float):
        """Add overshoot to current pressure."""
        self.pressure += amount

    def delay_responses(self, ms: int):
        """Add artificial delay before responding to commands."""
        self._delay_ms = ms

    def corrupt_status(self):
        """Make the next status response malformed."""
        self._corrupt_next = True

    def wait_for_command(self, prefix: str, timeout: float = 5.0) -> bool:
        """Wait until a command starting with `prefix` has been received."""
        start = time.time()
        while time.time() - start < timeout:
            if any(c.startswith(prefix) for c in self.commands_received):
                return True
            time.sleep(0.05)
        return False

    def get_last_command(self, prefix: str) -> str | None:
        """Get the most recent command starting with prefix."""
        for cmd in reversed(self.commands_received):
            if cmd.startswith(prefix):
                return cmd
        return None

    def clear_commands(self):
        """Clear the command history."""
        self.commands_received.clear()
```

**Step 2: Write a basic smoke test for the simulator**

Create `tests/unit/test_fake_arduino.py`:

```python
# tests/unit/test_fake_arduino.py
import pytest
import os
import time

from fixtures.fake_arduino import FakeArduino


@pytest.mark.unit
class TestFakeArduinoBasic:
    """Smoke tests for FakeArduino simulator."""

    def test_creates_pty(self):
        fake = FakeArduino()
        fake.start()
        try:
            assert fake.port is not None
            assert os.path.exists(fake.port)
        finally:
            fake.stop()

    def test_responds_to_test_command(self):
        fake = FakeArduino()
        fake.start()
        try:
            # Write T command to master and read response
            os.write(fake._master_fd, b"T\n")
            time.sleep(0.1)
            assert fake.wait_for_command("T", timeout=1.0)
        finally:
            fake.stop()

    def test_tracks_commands(self):
        fake = FakeArduino()
        fake.start()
        try:
            os.write(fake._master_fd, b"P50\n")
            time.sleep(0.2)
            assert fake.wait_for_command("P", timeout=1.0)
            assert fake.get_last_command("P") == "P50"
        finally:
            fake.stop()

    def test_pressure_ramp(self):
        fake = FakeArduino()
        fake.start()
        try:
            os.write(fake._master_fd, b"P50\n")
            time.sleep(0.5)
            # Pressure should be moving toward 50
            assert fake.pressure > 0
        finally:
            fake.stop()

    def test_emergency_stop(self):
        fake = FakeArduino()
        fake.start()
        try:
            os.write(fake._master_fd, b"P50\n")
            time.sleep(0.1)
            os.write(fake._master_fd, b"X\n")
            time.sleep(0.1)
            assert fake.measure_pressure is False
            assert fake.b_running is False
            assert fake.jerking is False
        finally:
            fake.stop()

    def test_position_movement(self):
        fake = FakeArduino()
        fake.position_c = 1200
        fake.start()
        try:
            os.write(fake._master_fd, b"K1800\n")
            time.sleep(0.5)
            # Position should be moving toward 1800
            assert fake.position_c > 1200
        finally:
            fake.stop()
```

**Step 3: Run tests**

Run: `python -m pytest tests/unit/test_fake_arduino.py -v -m unit`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/fixtures/fake_arduino.py tests/unit/test_fake_arduino.py
git commit -m "feat: add FakeArduino pty-based simulator with smoke tests"
```

---

### Task 8: Integration Conftest - FakeArduino Fixture

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Add FakeArduino fixture to conftest.py**

Add to `tests/conftest.py`:

```python
# Add to tests/conftest.py (append after existing content)
from fixtures.fake_arduino import FakeArduino


@pytest.fixture
def fake_arduino_pair():
    """
    Create a FakeArduino and a real Arduino instance connected via pty.

    Yields:
        tuple: (arduino_instance, fake_arduino_instance)
    """
    from unittest.mock import patch
    from helpers.arduino import Arduino

    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port

    yield arduino, fake

    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


@pytest.fixture
def config_with_defaults():
    """Create a Configuration instance with default mark values."""
    from config.config import Configuration
    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.a_factor = 1900
    config.b_factor = 1900
    config.c_factor = 1900
    config.calibration = 1.0
    config.flexion_position = 0
    return config


@pytest.fixture
def protocol_factory(fake_arduino_pair, config_with_defaults):
    """
    Factory for creating Protocols instances connected to FakeArduino.

    Returns a callable that creates Protocols with overridable defaults.
    """
    from helpers.protocols import Protocols

    arduino, fake = fake_arduino_pair

    def create_protocol(**kwargs):
        defaults = dict(
            a_factor=1900,
            protocol="1",
            max_pressure=50,
            max_left=10.0,
            max_right=10.0,
            duration=1,
            use_pulse=False,
            ser=arduino,
            config=config_with_defaults,
        )
        defaults.update(kwargs)
        return Protocols(**defaults), fake

    return create_protocol
```

**Step 2: Verify fixtures work**

Run: `python -m pytest tests/ --collect-only`
Expected: No import errors, fixtures discoverable

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "feat: add FakeArduino integration fixtures to conftest"
```

---

### Task 9: Integration Tests - Arduino Communication (test_arduino_comm.py)

**Files:**
- Create: `tests/integration/test_arduino_comm.py`
- Reference: `main/helpers/arduino.py`

**Step 1: Write the tests**

```python
# tests/integration/test_arduino_comm.py
import pytest
import time
import serial
from unittest.mock import patch

from helpers.arduino import Arduino
from fixtures.fake_arduino import FakeArduino


@pytest.fixture
def connected_pair():
    """Create FakeArduino + Arduino with an open serial connection."""
    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True

    import threading
    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    yield arduino, fake

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


@pytest.mark.integration
class TestArduinoConnection:
    """Tests for Arduino connection management."""

    def test_verify_connection_sends_T(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.verify_connection(tries=1, timeout_s=3.0)
        assert result is True
        assert fake.wait_for_command("T", timeout=2.0)


@pytest.mark.integration
class TestArduinoSend:
    """Tests for sending commands to Arduino."""

    def test_send_pressure_command(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("P50")
        assert result is True
        assert fake.wait_for_command("P50", timeout=2.0)

    def test_send_position_command(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("K1500")
        assert result is True
        assert fake.wait_for_command("K1500", timeout=2.0)

    def test_send_emergency_stop(self, connected_pair):
        arduino, fake = connected_pair
        result = arduino.send("X")
        assert result is True
        assert fake.wait_for_command("X", timeout=2.0)

    def test_send_when_disconnected(self):
        arduino = Arduino()
        arduino.connected = False
        arduino.serial_com = None
        # Should attempt reconnect and fail gracefully
        with patch.object(arduino, 'reconnect', return_value=False):
            result = arduino.send("T")
        assert result is False


@pytest.mark.integration
class TestArduinoStatusSignals:
    """Tests for status signal emission."""

    def test_status_emit_on_status_response(self, connected_pair, qtbot):
        arduino, fake = connected_pair
        # Send a command that triggers status
        arduino.send("HF1")

        # Wait for status_emit signal
        with qtbot.waitSignal(arduino.status_emit, timeout=3000) as blocker:
            pass  # HF1 triggers immediate status send from FakeArduino

        pos_a, pos_b, pos_c, pressure = blocker.args
        assert isinstance(pos_a, int)
        assert isinstance(pressure, float)


@pytest.mark.integration
class TestArduinoCorruptData:
    """Tests for handling corrupt serial data."""

    def test_corrupt_status_no_crash(self, connected_pair):
        arduino, fake = connected_pair
        fake.corrupt_status()
        arduino.send("S")
        time.sleep(0.5)
        # Should not crash - verify arduino is still functional
        result = arduino.verify_connection(tries=1, timeout_s=3.0)
        assert result is True
```

**Step 2: Run tests**

Run: `python -m pytest tests/integration/test_arduino_comm.py -v -m integration`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_arduino_comm.py
git commit -m "feat: add integration tests for Arduino serial communication"
```

---

### Task 10: Integration Tests - Protocols (test_protocols.py)

**Files:**
- Create: `tests/integration/test_protocols.py`
- Reference: `main/helpers/protocols.py`

**Step 1: Write the tests**

```python
# tests/integration/test_protocols.py
import pytest
import time
import serial
import threading
from unittest.mock import patch

from helpers.arduino import Arduino
from helpers.protocols import Protocols
from config.config import Configuration
from fixtures.fake_arduino import FakeArduino


@pytest.fixture
def protocol_env():
    """Set up full protocol test environment with FakeArduino."""
    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True

    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.calibration = 1.0

    yield arduino, fake, config

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


def make_protocol(arduino, config, **kwargs):
    """Helper to build a Protocols instance with defaults."""
    defaults = dict(
        a_factor=1900,
        protocol="1",
        max_pressure=30,  # Low for fast tests
        max_left=5.0,
        max_right=5.0,
        duration=1,  # 1 minute (will be cut short by checking is_running)
        use_pulse=False,
        ser=arduino,
        config=config,
    )
    defaults.update(kwargs)
    return Protocols(**defaults)


@pytest.mark.integration
class TestProtocol1Axial:
    """Tests for Protocol 1 (axial pressure only)."""

    def test_sends_pressure_commands(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=30, duration=1)

        # Run protocol in a thread (it blocks)
        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for pressure commands to appear
        assert fake.wait_for_command("HF1", timeout=5.0)
        assert fake.wait_for_command("P", timeout=10.0)

        # Stop protocol
        p.is_running = False
        thread.join(timeout=15)

    def test_finished_signal_emitted(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        # Use very short duration so protocol finishes quickly
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, duration=1)
        fake.pressure = 20  # Pre-set pressure so ramp completes instantly
        fake._target_pressure = None
        fake.measure_pressure = False

        with qtbot.waitSignal(p.signals.finished, timeout=90000):
            thread = threading.Thread(target=p.run, daemon=True)
            thread.start()

        thread.join(timeout=5)


@pytest.mark.integration
class TestProtocol2LeftLateral:
    """Tests for Protocol 2 (left lateral)."""

    def test_moves_c_actuator_left(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="2", max_left=10.0, max_pressure=20)
        fake.pressure = 20  # Skip pressure ramp

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should send K command for left position
        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocol3RightLateral:
    """Tests for Protocol 3 (right lateral)."""

    def test_moves_c_actuator_right(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="3", max_right=10.0, max_pressure=20)
        fake.pressure = 20  # Skip pressure ramp

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocol4Oscillating:
    """Tests for Protocol 4 (oscillating lateral)."""

    def test_sends_multiple_k_commands(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(
            arduino, config, protocol="4",
            max_left=5.0, max_right=5.0, max_pressure=20
        )
        fake.pressure = 20  # Skip pressure ramp

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should get at least one K command
        assert fake.wait_for_command("K", timeout=15.0)

        p.is_running = False
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocolStop:
    """Tests for stopping a running protocol."""

    def test_stop_sends_emergency_stop(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=50)

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for protocol to start
        time.sleep(1)

        # Stop it
        p.stop()

        # Should have sent X command
        assert fake.wait_for_command("X", timeout=5.0)
        thread.join(timeout=15)


@pytest.mark.integration
class TestProtocolPulseToggle:
    """Tests for pulse mode toggling."""

    def test_pulse_sends_j_command(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, use_pulse=True)
        fake.pressure = 20  # Skip pressure ramp

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Should eventually send J for pulsing
        found = fake.wait_for_command("J", timeout=20.0)

        p.is_running = False
        thread.join(timeout=15)
        assert found

    def test_pulse_toggle_off_sends_js(self, protocol_env, qtbot):
        arduino, fake, config = protocol_env
        p = make_protocol(arduino, config, protocol="1", max_pressure=20, use_pulse=True)
        fake.pressure = 20

        thread = threading.Thread(target=p.run, daemon=True)
        thread.start()

        # Wait for pulse to start
        fake.wait_for_command("J", timeout=20.0)

        # Toggle pulse off
        p.use_pulse = False
        time.sleep(1)

        # Should send JS to stop pulsing
        assert fake.wait_for_command("JS", timeout=10.0)

        p.is_running = False
        thread.join(timeout=15)
```

**Step 2: Run tests**

Run: `python -m pytest tests/integration/test_protocols.py -v -m integration --timeout=120`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_protocols.py
git commit -m "feat: add integration tests for all four protocols"
```

---

### Task 11: Integration Tests - Reset Worker (test_reset_worker.py)

**Files:**
- Create: `tests/integration/test_reset_worker.py`
- Reference: `main/helpers/reset_worker.py`

**Step 1: Write the tests**

```python
# tests/integration/test_reset_worker.py
import pytest
import time
import serial
import threading
from unittest.mock import MagicMock

from helpers.reset_worker import ResetWorker
from config.config import Configuration
from fixtures.fake_arduino import FakeArduino
from helpers.arduino import Arduino


@pytest.fixture
def reset_env():
    """Set up environment for reset worker testing."""
    fake = FakeArduino()
    fake.start()

    arduino = Arduino()
    arduino.ARDUINO_PORT = fake.port
    arduino.serial_com = serial.Serial(fake.port, 115200, timeout=1, write_timeout=1)
    arduino.connected = True
    arduino._running = True

    reader = threading.Thread(target=arduino.read_from_com, daemon=True)
    reader.start()

    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.calibration = 1.0

    # Mock main_window with I2Cstatus
    main_window = MagicMock()
    main_window.I2Cstatus = 0

    yield arduino, fake, config, main_window

    arduino._running = False
    time.sleep(0.2)
    fake.stop()
    if arduino.serial_com and arduino.serial_com.is_open:
        arduino.serial_com.close()


def auto_ack_i2c(fake, main_window, delay=0.5):
    """Background thread that sets I2Cstatus=1 whenever FakeArduino sends DONE."""
    def worker():
        last_count = len(fake.commands_received)
        while getattr(main_window, '_ack_running', True):
            if len(fake.commands_received) > last_count:
                last_count = len(fake.commands_received)
                time.sleep(delay)
                main_window.I2Cstatus = 1
            time.sleep(0.05)

    main_window._ack_running = True
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


@pytest.mark.integration
class TestResetWorkerSequence:
    """Tests for the reset sequence command order."""

    def test_sends_y_command(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.2)

        worker = ResetWorker(arduino, config, main_window)

        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()

        # Y should be the first command
        assert fake.wait_for_command("Y", timeout=10.0)

        # Wait for worker to finish
        thread.join(timeout=60)
        main_window._ack_running = False

    def test_sends_calibration_command(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.2)

        worker = ResetWorker(arduino, config, main_window)

        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        thread.join(timeout=60)
        main_window._ack_running = False

        # L0 calibration should have been sent
        assert fake.wait_for_command("L0", timeout=1.0)

    def test_finished_signal_emitted(self, reset_env, qtbot):
        arduino, fake, config, main_window = reset_env
        ack_thread = auto_ack_i2c(fake, main_window, delay=0.2)

        worker = ResetWorker(arduino, config, main_window)

        with qtbot.waitSignal(worker.signals.finished, timeout=60000) as blocker:
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()

        thread.join(timeout=5)
        main_window._ack_running = False
        # blocker.args[0] is the success boolean
        assert blocker.args[0] is True
```

**Step 2: Run tests**

Run: `python -m pytest tests/integration/test_reset_worker.py -v -m integration --timeout=120`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_reset_worker.py
git commit -m "feat: add integration tests for reset worker sequence"
```

---

### Task 12: Integration Tests - Pressure Dialog (test_pressure_dialog.py)

**Files:**
- Create: `tests/integration/test_pressure_dialog.py`
- Reference: `main/ui/dialogs/pressure_dialog.py`

**Step 1: Write the tests**

```python
# tests/integration/test_pressure_dialog.py
import pytest
from PyQt5.QtWidgets import QApplication

from ui.dialogs.pressure_dialog import PressureDialog


@pytest.mark.integration
class TestPressureDialogDisplay:
    """Tests for pressure dialog UI updates."""

    def test_initial_state(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        assert "0 lbs" in dialog.pressure_label.text()

    def test_update_shows_pressure(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(45.0)
        assert "45.0 lbs" in dialog.pressure_label.text()

    def test_green_under_50(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(30.0)
        style = dialog.pressure_label.styleSheet()
        assert "#27ae60" in style  # Green color

    def test_orange_between_50_and_70(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(55.0)
        style = dialog.pressure_label.styleSheet()
        assert "#f39c12" in style  # Orange color

    def test_red_above_70(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(75.0)
        style = dialog.pressure_label.styleSheet()
        assert "#e74c3c" in style  # Red color

    def test_small_change_not_updated(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(50.0)
        old_text = dialog.pressure_label.text()
        dialog.update_pressure(50.3)  # Change < 0.5
        assert dialog.pressure_label.text() == old_text

    def test_large_change_updated(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(50.0)
        dialog.update_pressure(51.0)  # Change >= 0.5
        assert "51.0 lbs" in dialog.pressure_label.text()

    def test_none_pressure_handled(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(None)
        # Should not crash
```

**Step 2: Run tests**

Run: `python -m pytest tests/integration/test_pressure_dialog.py -v -m integration`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_pressure_dialog.py
git commit -m "feat: add integration tests for pressure dialog UI"
```

---

### Task 13: Run Full Test Suite and Verify Coverage

**Step 1: Run all unit tests**

Run: `python -m pytest tests/unit/ -v -m unit`
Expected: All PASS

**Step 2: Run all integration tests**

Run: `python -m pytest tests/integration/ -v -m integration --timeout=120`
Expected: All PASS

**Step 3: Run full suite with coverage**

Run: `python -m pytest -m "unit or integration" --cov=main --cov-report=term-missing --timeout=120`
Expected: Coverage report showing tested modules

**Step 4: Commit final state**

```bash
git add -A
git commit -m "feat: complete Python test suite with unit and integration tests"
```

---

### Task 14: Arduino Firmware Test Infrastructure (PlatformIO)

**Files:**
- Create: `main/motor/platformio.ini`
- Create: `main/motor/test/mock_wire.h`
- Create: `main/motor/test/mock_serial.h`
- Create: `main/motor/test/mock_hx711.h`

**Note:** This task sets up the PlatformIO project structure and mock headers. The actual test files (Tasks 15-18) depend on this. This requires PlatformIO CLI (`pio`) to be installed.

**Step 1: Create platformio.ini**

```ini
; main/motor/platformio.ini
[env:native]
platform = native
test_framework = unity
build_flags = -DUNIT_TEST -std=c++11
build_src_filter = -<*>

[env:mega]
platform = atmelavr
board = megaatmega2560
framework = arduino
test_framework = unity
```

**Step 2: Create mock_wire.h**

```cpp
// main/motor/test/mock_wire.h
#ifndef MOCK_WIRE_H
#define MOCK_WIRE_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <string.h>

#define MAX_WIRE_COMMANDS 100
#define MAX_WIRE_DATA 64

struct WireCommand {
    uint8_t address;
    uint8_t data[MAX_WIRE_DATA];
    int dataLen;
};

class MockWire {
public:
    // Recorded commands
    WireCommand commands[MAX_WIRE_COMMANDS];
    int commandCount = 0;

    // Configurable position return values
    uint16_t position_12 = 0;
    uint16_t position_13 = 0;
    uint16_t position_14 = 0;

    // Internal state
    uint8_t _currentAddress = 0;
    uint8_t _txBuffer[MAX_WIRE_DATA];
    int _txLen = 0;
    uint8_t _rxBuffer[4];
    int _rxLen = 0;
    int _rxIndex = 0;

    void begin() {}

    void beginTransmission(uint8_t address) {
        _currentAddress = address;
        _txLen = 0;
    }

    uint8_t write(uint8_t data) {
        if (_txLen < MAX_WIRE_DATA) {
            _txBuffer[_txLen++] = data;
        }
        return 1;
    }

    uint8_t endTransmission() {
        if (commandCount < MAX_WIRE_COMMANDS) {
            commands[commandCount].address = _currentAddress;
            memcpy(commands[commandCount].data, _txBuffer, _txLen);
            commands[commandCount].dataLen = _txLen;
            commandCount++;
        }
        return 0;
    }

    uint8_t requestFrom(uint8_t address, uint8_t count) {
        _rxIndex = 0;
        uint16_t pos = 0;
        if (address == 12) pos = position_12;
        else if (address == 13) pos = position_13;
        else if (address == 14) pos = position_14;

        _rxBuffer[0] = pos & 0xFF;
        _rxBuffer[1] = (pos >> 8) & 0xFF;
        _rxLen = 2;
        return 2;
    }

    int available() { return _rxLen - _rxIndex; }

    uint8_t read() {
        if (_rxIndex < _rxLen) return _rxBuffer[_rxIndex++];
        return 0;
    }

    void reset() {
        commandCount = 0;
        _txLen = 0;
        _rxLen = 0;
        _rxIndex = 0;
    }
};

extern MockWire Wire;

#endif // UNIT_TEST
#endif // MOCK_WIRE_H
```

**Step 3: Create mock_serial.h**

```cpp
// main/motor/test/mock_serial.h
#ifndef MOCK_SERIAL_H
#define MOCK_SERIAL_H

#ifdef UNIT_TEST

#include <stdint.h>
#include <string.h>
#include <string>
#include <queue>

#define MAX_OUTPUT_SIZE 4096

class MockSerial {
public:
    // Captured output
    char output[MAX_OUTPUT_SIZE];
    int outputLen = 0;

    // Input queue
    std::queue<std::string> inputQueue;
    std::string currentInput;
    int inputIndex = 0;

    void begin(long baud) {}

    int available() {
        if (inputIndex < (int)currentInput.length()) return 1;
        if (!inputQueue.empty()) {
            currentInput = inputQueue.front();
            inputQueue.pop();
            inputIndex = 0;
            return 1;
        }
        return 0;
    }

    int read() {
        if (inputIndex < (int)currentInput.length()) {
            return currentInput[inputIndex++];
        }
        return -1;
    }

    size_t print(const char* s) {
        int len = strlen(s);
        if (outputLen + len < MAX_OUTPUT_SIZE) {
            memcpy(output + outputLen, s, len);
            outputLen += len;
        }
        return len;
    }

    size_t print(int val) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%d", val);
        return print(buf);
    }

    size_t print(float val) {
        char buf[32];
        snprintf(buf, sizeof(buf), "%.1f", val);
        return print(buf);
    }

    size_t println(const char* s) {
        size_t n = print(s);
        n += print("\n");
        return n;
    }

    size_t println(int val) {
        size_t n = print(val);
        n += print("\n");
        return n;
    }

    size_t println(float val) {
        size_t n = print(val);
        n += print("\n");
        return n;
    }

    size_t println() { return print("\n"); }

    // Test helpers
    void injectCommand(const std::string& cmd) {
        inputQueue.push(cmd + "\n");
    }

    std::string getOutput() {
        return std::string(output, outputLen);
    }

    bool outputContains(const std::string& needle) {
        return getOutput().find(needle) != std::string::npos;
    }

    void reset() {
        outputLen = 0;
        while (!inputQueue.empty()) inputQueue.pop();
        currentInput.clear();
        inputIndex = 0;
    }
};

extern MockSerial Serial;
extern MockSerial Serial1;

#endif // UNIT_TEST
#endif // MOCK_SERIAL_H
```

**Step 4: Create mock_hx711.h**

```cpp
// main/motor/test/mock_hx711.h
#ifndef MOCK_HX711_H
#define MOCK_HX711_H

#ifdef UNIT_TEST

class HX711 {
public:
    float _units = 0.0;
    float _scale = 1.0;
    bool _tared = false;

    void begin(int dout, int sck) {}

    void set_scale(float scale) { _scale = scale; }

    void tare() { _tared = true; }

    float get_units(int times = 1) { return _units; }

    // Test helper
    void setUnits(float units) { _units = units; }
};

#endif // UNIT_TEST
#endif // MOCK_HX711_H
```

**Step 5: Commit**

```bash
git add main/motor/platformio.ini main/motor/test/
git commit -m "feat: add PlatformIO config and mock headers for Arduino testing"
```

---

### Task 15: Arduino Tests - Command Parsing (test_command_parse)

**Files:**
- Create: `main/motor/test/test_command_parse/test_command_parse.cpp`

**Note:** These tests verify the Arduino command parsing logic. They require extracting `processCommand()` and related functions into a testable form. Since the motor.ino is a monolithic file, the tests will `#include` it with mocks substituted via `#ifdef UNIT_TEST`.

**Step 1: Create test file**

```cpp
// main/motor/test/test_command_parse/test_command_parse.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

// Instantiate mock globals
MockWire Wire;
MockSerial Serial;
MockSerial Serial1;

// Provide stubs for Arduino functions used in motor.ino
unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) {}

// Include the main firmware
// (processCommand and related functions will be available)
#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    bRunning = false;
    measurePressure = false;
    jerking = false;
    desiredPressure = 0;
    desiredPosition = 0;
    highFrequencyStatus = false;
    _millis_value = 0;
}

void tearDown(void) {}

// --- Test command ---
void test_T_responds_OK(void) {
    processCommand("T");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK"));
}

// --- Pressure command ---
void test_P_sets_desired_pressure(void) {
    processCommand("P50");
    TEST_ASSERT_EQUAL_FLOAT(50.0, desiredPressure);
    TEST_ASSERT_TRUE(measurePressure);
}

void test_P_ignored_when_running(void) {
    bRunning = true;
    processCommand("P50");
    TEST_ASSERT_EQUAL_FLOAT(0.0, desiredPressure);
}

// --- Position command ---
void test_I_sets_position(void) {
    Wire.position_12 = 100;
    processCommand("I121500");
    TEST_ASSERT_EQUAL(1500, desiredPosition);
    TEST_ASSERT_TRUE(bRunning);
}

void test_I_ignored_when_running(void) {
    bRunning = true;
    processCommand("I121500");
    TEST_ASSERT_EQUAL(3, desiredPosition);  // unchanged from default
}

// --- K command (lateral) ---
void test_K_sets_c_position(void) {
    Wire.position_14 = 1000;
    processCommand("K1800");
    TEST_ASSERT_EQUAL(14, smcDeviceNumber);
    TEST_ASSERT_EQUAL(1800, desiredPosition);
    TEST_ASSERT_TRUE(bRunning);
}

// --- Jerk commands ---
void test_J_starts_jerking(void) {
    processCommand("J");
    TEST_ASSERT_TRUE(jerking);
}

void test_JS_stops_jerking(void) {
    jerking = true;
    processCommand("JS");
    TEST_ASSERT_FALSE(jerking);
}

// --- High frequency status ---
void test_HF1_enables(void) {
    processCommand("HF1");
    TEST_ASSERT_TRUE(highFrequencyStatus);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_HF0_disables(void) {
    highFrequencyStatus = true;
    processCommand("HF0");
    TEST_ASSERT_FALSE(highFrequencyStatus);
}

// --- Emergency stop ---
void test_X_stops_everything(void) {
    bRunning = true;
    measurePressure = true;
    jerking = true;
    processCommand("X");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

// --- Buffer overflow protection ---
void test_long_command_rejected(void) {
    // Create a command longer than MAX_COMMAND_LENGTH
    char longCmd[150];
    memset(longCmd, 'A', 149);
    longCmd[149] = '\0';
    processCommand(String(longCmd));
    TEST_ASSERT_TRUE(Serial1.outputContains("ERROR"));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_T_responds_OK);
    RUN_TEST(test_P_sets_desired_pressure);
    RUN_TEST(test_P_ignored_when_running);
    RUN_TEST(test_I_sets_position);
    RUN_TEST(test_I_ignored_when_running);
    RUN_TEST(test_K_sets_c_position);
    RUN_TEST(test_J_starts_jerking);
    RUN_TEST(test_JS_stops_jerking);
    RUN_TEST(test_HF1_enables);
    RUN_TEST(test_HF0_disables);
    RUN_TEST(test_X_stops_everything);
    RUN_TEST(test_long_command_rejected);

    return UNITY_END();
}

#endif // UNIT_TEST
```

**Step 2: Run tests (if PlatformIO installed)**

Run: `cd main/motor && pio test -e native -v`
Expected: All PASS (or skip if PlatformIO not installed yet)

**Step 3: Commit**

```bash
git add main/motor/test/test_command_parse/
git commit -m "feat: add Arduino command parsing tests (PlatformIO/Unity)"
```

---

### Task 16: Arduino Tests - Safety (test_safety)

**Files:**
- Create: `main/motor/test/test_safety/test_safety.cpp`

**Step 1: Create test file**

```cpp
// main/motor/test/test_safety/test_safety.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

MockWire Wire;
MockSerial Serial;
MockSerial Serial1;

unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) {}

#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    bRunning = false;
    measurePressure = false;
    jerking = false;
    _millis_value = 0;
}

void tearDown(void) {}

void test_emergency_stop_clears_all_state(void) {
    bRunning = true;
    measurePressure = true;
    jerking = true;
    jerksCompleted = 5;

    emergencyStop();

    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_EQUAL(0, jerksCompleted);
}

void test_emergency_stop_sets_motor_speeds_to_zero(void) {
    emergencyStop();

    // Should have sent speed=0 to all 3 motor controllers
    // Each emergencyStop sets smcDeviceNumber and calls setMotorSpeed(0)
    // Wire should have received commands for devices 12, 13, 14
    bool found_12 = false, found_13 = false, found_14 = false;
    for (int i = 0; i < Wire.commandCount; i++) {
        if (Wire.commands[i].address == 12) found_12 = true;
        if (Wire.commands[i].address == 13) found_13 = true;
        if (Wire.commands[i].address == 14) found_14 = true;
    }
    TEST_ASSERT_TRUE(found_12);
    TEST_ASSERT_TRUE(found_13);
    TEST_ASSERT_TRUE(found_14);
}

void test_x_command_triggers_emergency_stop(void) {
    bRunning = true;
    processCommand("X");
    TEST_ASSERT_FALSE(bRunning);
    TEST_ASSERT_FALSE(measurePressure);
    TEST_ASSERT_FALSE(jerking);
}

void test_commands_accepted_after_emergency_stop(void) {
    emergencyStop();

    // System should be recoverable - commands should still work
    Serial1.reset();
    processCommand("T");
    TEST_ASSERT_TRUE(Serial1.outputContains("OK"));
}

void test_emergency_stop_during_jerking(void) {
    jerking = true;
    jerkDirection = 1;
    jerksCompleted = 3;

    emergencyStop();

    TEST_ASSERT_FALSE(jerking);
    TEST_ASSERT_EQUAL(0, jerksCompleted);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_emergency_stop_clears_all_state);
    RUN_TEST(test_emergency_stop_sets_motor_speeds_to_zero);
    RUN_TEST(test_x_command_triggers_emergency_stop);
    RUN_TEST(test_commands_accepted_after_emergency_stop);
    RUN_TEST(test_emergency_stop_during_jerking);

    return UNITY_END();
}

#endif // UNIT_TEST
```

**Step 2: Commit**

```bash
git add main/motor/test/test_safety/
git commit -m "feat: add Arduino safety tests (emergency stop, recovery)"
```

---

### Task 17: Arduino Tests - Status Reporting (test_status)

**Files:**
- Create: `main/motor/test/test_status/test_status.cpp`

**Step 1: Create test file**

```cpp
// main/motor/test/test_status/test_status.cpp
#ifdef UNIT_TEST

#include <unity.h>
#include "../mock_wire.h"
#include "../mock_serial.h"
#include "../mock_hx711.h"

MockWire Wire;
MockSerial Serial;
MockSerial Serial1;
HX711 scale;

unsigned long _millis_value = 0;
unsigned long millis() { return _millis_value; }
void delay(unsigned long ms) {}

#include "../../motor.ino"

void setUp(void) {
    Serial.reset();
    Serial1.reset();
    Wire.reset();
    Wire.position_12 = 1500;
    Wire.position_13 = 2000;
    Wire.position_14 = 1200;
    scale.setUnits(45.3);
    noStatus = false;
    isProcessingStatus = false;
    statusAcknowledged = true;
    highFrequencyStatus = false;
    _millis_value = 0;
}

void tearDown(void) {}

void test_status_format(void) {
    sendStatus();
    std::string out = Serial1.getOutput();
    TEST_ASSERT_TRUE(out.find("STATUS_START|S|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|STATUS_END") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|1500|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|2000|") != std::string::npos);
    TEST_ASSERT_TRUE(out.find("|1200|") != std::string::npos);
}

void test_status_skipped_when_nostatus(void) {
    noStatus = true;
    bool sent = sendStatus();
    TEST_ASSERT_FALSE(sent);
}

void test_status_skipped_when_processing(void) {
    isProcessingStatus = true;
    bool sent = sendStatus();
    TEST_ASSERT_FALSE(sent);
}

void test_q_acknowledges_status(void) {
    statusAcknowledged = false;
    processCommand("Q");
    TEST_ASSERT_TRUE(statusAcknowledged);
}

void test_s_command_triggers_status(void) {
    processCommand("S");
    std::string out = Serial1.getOutput();
    TEST_ASSERT_TRUE(out.find("STATUS_START") != std::string::npos);
}

void test_calibration_l0_sends_done(void) {
    processCommand("L0-4360.14");
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_calibration_l1_tare(void) {
    processCommand("L1");
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

void test_calibration_l4_weight(void) {
    scale.setUnits(32.1);
    processCommand("L4");
    TEST_ASSERT_TRUE(Serial1.outputContains("weight|"));
}

void test_calibration_l5_zero_marks(void) {
    processCommand("L5100 200");
    TEST_ASSERT_EQUAL(100, AZERO);
    TEST_ASSERT_TRUE(Serial1.outputContains("DONE"));
}

int main(int argc, char **argv) {
    UNITY_BEGIN();

    RUN_TEST(test_status_format);
    RUN_TEST(test_status_skipped_when_nostatus);
    RUN_TEST(test_status_skipped_when_processing);
    RUN_TEST(test_q_acknowledges_status);
    RUN_TEST(test_s_command_triggers_status);
    RUN_TEST(test_calibration_l0_sends_done);
    RUN_TEST(test_calibration_l1_tare);
    RUN_TEST(test_calibration_l4_weight);
    RUN_TEST(test_calibration_l5_zero_marks);

    return UNITY_END();
}

#endif // UNIT_TEST
```

**Step 2: Commit**

```bash
git add main/motor/test/test_status/
git commit -m "feat: add Arduino status reporting and calibration tests"
```

---

### Task 18: Final Commit and Summary

**Step 1: Run full Python test suite one final time**

Run: `python -m pytest -m "unit or integration" -v --timeout=120`

**Step 2: Generate coverage report**

Run: `python -m pytest -m "unit or integration" --cov=main --cov-report=term-missing --timeout=120`

**Step 3: Final commit with any adjustments**

```bash
git add -A
git commit -m "feat: complete KneeSpa test suite - Python and Arduino coverage"
```

**Step 4: Push to GitHub**

```bash
git push origin main
```
