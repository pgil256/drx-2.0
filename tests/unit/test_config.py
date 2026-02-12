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
