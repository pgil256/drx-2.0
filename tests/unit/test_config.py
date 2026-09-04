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
        assert len(config.CMarks) == 17

    def test_no_crash(self, config_with_corrupt_file):
        """Corrupt file should not raise an exception."""
        assert config_with_corrupt_file is not None


@pytest.mark.unit
class TestConfigurationMissingSections:
    """Tests for config files missing CMarks/AMarks/BMarks."""

    def test_default_cmarks_used(self, config_missing_sections):
        config = config_missing_sections
        assert len(config.CMarks) == 17

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
class TestCalibrationState:
    """A device on generated defaults must be distinguishable from a
    calibrated one; corrupt configs used to degrade silently."""

    def test_missing_file_flags_uncalibrated(self, config_with_missing_file):
        config, _ = config_with_missing_file
        assert config.marks_valid is False
        assert config.calibrated is False
        assert config.calibration_errors

    def test_corrupt_file_flags_uncalibrated(self, config_with_corrupt_file):
        config = config_with_corrupt_file
        assert config.calibrated is False
        assert any("defaults in use" in e for e in config.calibration_errors)

    def test_valid_marks_but_default_scale_factor(self, config_with_valid_file):
        config = config_with_valid_file
        # The fixture's mark tables are real and monotonic...
        assert config.marks_valid is True
        # ...but calibration = 1.0 is the raw-counts factory default
        assert config.scale_calibrated is False
        assert config.calibrated is False

    def test_plausible_scale_factor_accepted(self, tmp_path):
        fixture_path = os.path.join(
            os.path.dirname(__file__), '..', 'fixtures', 'sample_configs', 'valid.cfg'
        )
        content = open(fixture_path).read().replace(
            "calibration = 1.0", "calibration = -28369.0"
        )
        cfg_path = tmp_path / "kneespa.cfg"
        cfg_path.write_text(content)
        config = Configuration(config_path=str(cfg_path))
        config.get_config()
        assert config.scale_calibrated is True
        assert config.calibrated is True

    def test_validate_marks_rejects_non_monotonic(self):
        error = Configuration.validate_marks(
            {"-20.0": 500, "0.0": 1450, "20.0": 1400}
        )
        assert error is not None
        assert "monotonic" in error

    def test_validate_marks_rejects_single_point(self):
        assert Configuration.validate_marks({"0.0": 1450}) is not None

    def test_validate_marks_accepts_decreasing_table(self):
        # Some axes may be wired with inverted sense
        assert Configuration.validate_marks(
            {"-20.0": 2400, "0.0": 1450, "20.0": 500}
        ) is None

    def test_cmarks_are_not_semantically_validated(self):
        config = Configuration()
        config.CMarks = {"-20.0": 500, "0.0": 1700, "20.0": 1600}
        config._set_default_a_marks()
        config._set_default_b_marks()
        config.calibration = -28369.0

        config._validate_calibration()

        assert config.marks_valid is True
        assert not any(error.startswith("CMarks:") for error in config.calibration_errors)


@pytest.mark.unit
class TestAtomicWrite:
    def test_no_temp_files_left_behind(self, tmp_path):
        cfg_path = tmp_path / "kneespa.cfg"
        config = Configuration(config_path=str(cfg_path))
        config.get_config()  # creates default file
        config.a_factor = 2222
        config.update_config()
        leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".kneespa_cfg_")]
        assert leftovers == []
        config2 = Configuration(config_path=str(cfg_path))
        config2.get_config()
        assert config2.a_factor == 2222


@pytest.mark.unit
class TestConfigurationDefaults:
    """Tests for default mark values."""

    def test_default_cmarks_are_numeric(self):
        config = Configuration()
        config._set_default_c_marks()
        assert config.CMarks
        assert all(isinstance(key, str) for key in config.CMarks)
        assert all(isinstance(value, int) for value in config.CMarks.values())

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
