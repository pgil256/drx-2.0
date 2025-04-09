"""
Unit tests for configuration handling.
"""
import pytest
import os
import tempfile
import configparser
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, Tuple

# Add project root to Python path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from main.config.config import Configuration
from tests.fixtures.test_logger import capture_logs


@pytest.fixture
def temp_config_file() -> Tuple[str, configparser.ConfigParser]:
    """Create a temporary config file for testing.
    
    Returns:
        Tuple of (file path, config parser instance)
    """
    # Create a temporary file
    config_file = tempfile.NamedTemporaryFile(delete=False, suffix=".cfg")
    config_path = config_file.name
    config_file.close()
    
    # Create a config parser and sample config
    config = configparser.ConfigParser(allow_no_value=True)
    
    # Add some test sections and options
    config["Options"] = {
        "flexion_position": "100",
        "a_factor": "430",
        "b_factor": "620",
        "c_factor": "1900",
        "unlock": "123456",
        "calibration": "-4360.14"
    }
    
    config["CMarks"] = {
        "0.0": "300",   # Neutral position
        "-5.0": "200",  # Left 5 degrees
        "5.0": "400",   # Right 5 degrees
        "-10.0": "100", # Left 10 degrees
        "10.0": "500"   # Right 10 degrees
    }
    
    config["AMarks"] = {
        "0.0": "50",
        "1.0": "100"
    }
    
    config["BMarks"] = {
        "0.0": "75",
        "1.0": "150"
    }
    
    # Write the config to the file
    with open(config_path, 'w') as f:
        config.write(f)
    
    return config_path, config


@pytest.mark.unit
class TestConfiguration:
    """Test suite for Configuration class."""
    
    def test_get_list(self):
        """Test get_list static method."""
        result = Configuration.get_list("item1, item2,item3", sep=",", chars=None)
        assert result == ["item1", "item2", "item3"]
        
        # Test with different separator
        result = Configuration.get_list("item1|item2|item3", sep="|")
        assert result == ["item1", "item2", "item3"]
        
        # Test with character stripping
        result = Configuration.get_list(" item1 , *item2* , item3 ", chars=" *")
        assert result == ["item1", "item2", "item3"]
        
    @patch('main.config.config.CONFIG_PATH')
    def test_load_existing_config(self, mock_config_path, temp_config_file):
        """Test loading an existing configuration file."""
        config_path, expected_config = temp_config_file
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config = Configuration()
            
            # Load the config
            with patch.object(config, 'configFile', config_path):
                config.get_config()
                
            # Check that values were loaded correctly
            assert config.flexion_position == 100
            assert config.a_factor == 430
            assert config.b_factor == 620
            assert config.c_factor == 1900
            assert config.unlock == "123456"
            assert config.calibration == -4360.14
            
            # Check that CMarks were loaded
            assert isinstance(config.CMarks, dict)
            assert config.CMarks["0.0"] == 300
            assert config.CMarks["5.0"] == 400
            
            # Check AMarks and BMarks
            assert config.AMarks["0.0"] == 50
            assert config.BMarks["1.0"] == 150
            
    @patch('main.config.config.CONFIG_PATH')
    def test_create_config_if_not_exists(self, mock_config_path):
        """Test creating a configuration file if it doesn't exist."""
        # Create a temp file path that doesn't exist
        temp_dir = tempfile.mkdtemp()
        config_path = os.path.join(temp_dir, "nonexistent_config.cfg")
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config = Configuration()
            
            # Load the config (should create a new one)
            with patch.object(config, 'configFile', config_path):
                config.get_config()
                
            # Check that the file was created
            assert os.path.exists(config_path)
            
            # Clean up
            os.unlink(config_path)
            os.rmdir(temp_dir)
            
    @patch('main.config.config.CONFIG_PATH')
    def test_missing_required_section(self, mock_config_path):
        """Test handling missing required sections."""
        # Create a config file with missing sections
        config_file = tempfile.NamedTemporaryFile(delete=False, suffix=".cfg")
        config_path = config_file.name
        config_file.close()
        
        config = configparser.ConfigParser()
        config["Options"] = {"flexion_position": "100"}
        # Note: Missing the CMarks section
        
        with open(config_path, 'w') as f:
            config.write(f)
            
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config_obj = Configuration()
            
            # Load the config
            with patch.object(config_obj, 'configFile', config_path):
                config_obj.get_config()
                
            # Check for error in logs
            assert logs.contains_message("Missing required configuration")
            
        # Clean up
        os.unlink(config_path)
        
    @patch('main.config.config.CONFIG_PATH')
    def test_invalid_value(self, mock_config_path):
        """Test handling invalid values in config."""
        # Create a config file with invalid values
        config_file = tempfile.NamedTemporaryFile(delete=False, suffix=".cfg")
        config_path = config_file.name
        config_file.close()
        
        config = configparser.ConfigParser()
        config["Options"] = {
            "flexion_position": "100",
            "a_factor": "not_a_number",  # Invalid value
            "c_factor": "1900",
        }
        config["CMarks"] = {"0.0": "300"}
        config["AMarks"] = {"0.0": "50"}
        config["BMarks"] = {"0.0": "75"}
        
        with open(config_path, 'w') as f:
            config.write(f)
            
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config_obj = Configuration()
            
            # Load the config
            with patch.object(config_obj, 'configFile', config_path):
                config_obj.get_config()
                
            # Check for error in logs
            assert logs.contains_message("Invalid configuration value")
            
        # Clean up
        os.unlink(config_path)
        
    @patch('main.config.config.CONFIG_PATH')
    def test_update_config(self, mock_config_path, temp_config_file):
        """Test updating configuration values."""
        config_path, expected_config = temp_config_file
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config = Configuration()
            
            # Load the config
            with patch.object(config, 'configFile', config_path):
                config.get_config()
                
                # Modify some values
                config.flexion_position = 150
                config.c_factor = 2000
                config.calibration = -5000.0
                
                # Update the config
                config.update_config()
                
            # Re-read the config file to check values were saved
            updated_config = configparser.ConfigParser()
            updated_config.read(config_path)
            
            assert updated_config["Options"]["flexion_position"] == "150"
            assert updated_config["Options"]["c_factor"] == "2000"
            assert updated_config["Options"]["calibration"] == "-5000.0"
            
        # Clean up
        os.unlink(config_path)
        
    @patch('main.config.config.CONFIG_PATH')
    def test_permission_error_on_save(self, mock_config_path):
        """Test handling permission errors when saving."""
        config_path, expected_config = temp_config_file
        mock_config_path.return_value = config_path
        
        with capture_logs() as logs:
            # Initialize the configuration
            config = Configuration()
            
            # Load the config
            with patch.object(config, 'configFile', config_path):
                config.get_config()
                
                # Simulate permission error when writing
                with patch('builtins.open') as mock_open:
                    mock_open.side_effect = PermissionError("Permission denied")
                    
                    # Try to update the config
                    config.update_config()
                    
                    # Check for error in logs
                    assert logs.contains_message("Permission denied")
                    
        # Clean up
        os.unlink(config_path)