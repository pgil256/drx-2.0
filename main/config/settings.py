# config/settings.py

"""
Application settings manager for KneeSpa.
Handles both static configuration and runtime settings.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

class Settings:
    """
    Settings manager for the KneeSpa application.
    Handles configuration loading, saving, and runtime settings management.
    """
    
    _instance = None
    
    def __new__(cls):
        """Ensure singleton pattern for settings."""
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize settings with default values."""
        if hasattr(self, '_initialized'):
            return
            
        self._initialized = True
        self.app_dir = "/home/pi/drx-2.0/main"
        self.config_dir = os.path.join(self.app_dir, "config")
        self.settings_file = os.path.join(self.config_dir, "settings.json")
        
        # Default settings
        self._settings = {
            # System Settings
            'debug_mode': False,
            'log_level': 'INFO',
            'backup_enabled': True,
            'backup_interval': 24,  # hours
            
            # UI Settings
            'fullscreen': True,
            'theme': 'default',
            'hour_format': '24',
            'language': 'en',
            
            # Hardware Settings
            'arduino_port': '/dev/ttyUSB0',
            'arduino_baud_rate': 9600,
            'gpio_enabled': True,
            
            # Protocol Settings
            'default_cycles': 10,
            'max_pressure': 100,
            'min_pressure': 0,
            'pressure_increment': 5,
            
            # Actuator Calibration
            'axial_factor': 1.0,
            'lateral_factor': 1.0,
            'horizontal_factor': 1.0,
            
            # Safety Limits
            'max_temperature': 50,  # Celsius
            'emergency_stop_enabled': True,
            'movement_timeout': 30,  # seconds
            
            # Data Management
            'auto_save': True,
            'save_interval': 5,  # minutes
            'max_log_size': 10,  # MB
            'data_retention': 90,  # days
            
            # Network Settings
            'remote_backup': False,
            'backup_server': '',
            'backup_user': '',
            'backup_path': '',
        }
        
        # Load saved settings
        self.load_settings()

    def load_settings(self) -> None:
        """Load settings from JSON file."""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r') as f:
                    saved_settings = json.load(f)
                    self._settings.update(saved_settings)
                logging.info("Settings loaded successfully")
        except Exception as e:
            logging.error(f"Error loading settings: {str(e)}")
            self.save_settings()  # Create default settings file

    def save_settings(self) -> None:
        """Save current settings to JSON file."""
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=4)
            logging.info("Settings saved successfully")
        except Exception as e:
            logging.error(f"Error saving settings: {str(e)}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key to retrieve
            default: Default value if key doesn't exist
            
        Returns:
            Setting value or default
        """
        return self._settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Set a setting value and save to file.
        
        Args:
            key: Setting key to update
            value: New value to set
        """
        self._settings[key] = value
        self.save_settings()

    def get_all(self) -> Dict[str, Any]:
        """Get all settings as dictionary."""
        return self._settings.copy()

    def reset(self, key: Optional[str] = None) -> None:
        """
        Reset settings to default.
        
        Args:
            key: Specific key to reset, or None for all
        """
        if key is None:
            self.__init__()
        elif key in self._settings:
            self._settings[key] = self.__init__()._settings[key]
        self.save_settings()

    def validate_paths(self) -> bool:
        """
        Validate that all required paths exist.
        
        Returns:
            bool: True if all paths are valid
        """
        required_paths = [
            self.app_dir,
            os.path.join(self.app_dir, "ui"),
            os.path.join(self.app_dir, "data"),
            os.path.join(self.app_dir, "logs")
        ]
        
        for path in required_paths:
            if not os.path.exists(path):
                logging.error(f"Required path not found: {path}")
                return False
        return True

    def setup_logging(self) -> None:
        """Configure application logging based on settings."""
        log_file = os.path.join(self.app_dir, "logs", "kneespa.log")
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        
        logging.basicConfig(
            filename=log_file,
            level=getattr(logging, self.get('log_level', 'INFO')),
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

    def ensure_data_directories(self) -> None:
        """Ensure all required data directories exist."""
        directories = [
            os.path.join(self.app_dir, "data/users"),
            os.path.join(self.app_dir, "data/patients"),
            os.path.join(self.app_dir, "data/protocols"),
            os.path.join(self.app_dir, "data/backups"),
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

    def backup_settings(self) -> None:
        """Create a backup of current settings."""
        if not self.get('backup_enabled'):
            return
            
        backup_dir = os.path.join(self.app_dir, "data/backups")
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"settings_backup_{timestamp}.json")
        
        try:
            with open(backup_file, 'w') as f:
                json.dump(self._settings, f, indent=4)
            logging.info(f"Settings backup created: {backup_file}")
        except Exception as e:
            logging.error(f"Error creating settings backup: {str(e)}")

# Global settings instance
settings = Settings()