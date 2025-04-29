"""
Protocol Settings Module
Contains settings classes and constants for protocol execution
"""
from dataclasses import dataclass
from typing import Optional
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QSlider, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from main.config.constants import (
    MIN_PRESSURE, MAX_SAFE_PRESSURE, PULSE_INTERVAL_DEFAULT,
    PROTOCOL_DEFAULTS
)

from main.config.constants import (
    MIN_PRESSURE, MAX_SAFE_PRESSURE, PULSE_INTERVAL_DEFAULT,
    PROTOCOL_DEFAULTS
)

@dataclass
class ProtocolSettings:
    """Holds all settings for a protocol run"""
    duration_minutes: int = 15
    use_pulse: bool = False
    pressure_tolerance: int = PROTOCOL_DEFAULTS.get("MAX_PRESSURE", 40) // 2  # Default pressure
    max_left_angle: float = 20.0  # Default left angle limit
    max_right_angle: float = 20.0  # Default right angle limit
    pulse_interval_seconds: int = PULSE_INTERVAL_DEFAULT  # Default pulse interval
    protocol_name: str = "Default"  # Protocol name/number
    
    def to_dict(self):
        """Convert settings to dictionary"""
        return {
            "duration_minutes": self.duration_minutes,
            "use_pulse": self.use_pulse,
            "pressure_tolerance": self.pressure_tolerance,
            "max_left_angle": self.max_left_angle,
            "max_right_angle": self.max_right_angle,
            "pulse_interval_seconds": self.pulse_interval_seconds,
            "protocol_name": self.protocol_name
        }
        
    @classmethod
    def from_dict(cls, data):
        """Create settings from dictionary"""
        return cls(
            duration_minutes=data.get("duration_minutes", 15),
            use_pulse=data.get("use_pulse", False),
            pressure_tolerance=data.get("pressure_tolerance", PROTOCOL_DEFAULTS.get("MAX_PRESSURE", 40) // 2),
            max_left_angle=data.get("max_left_angle", 20.0),
            max_right_angle=data.get("max_right_angle", 20.0),
            pulse_interval_seconds=data.get("pulse_interval_seconds", PULSE_INTERVAL_DEFAULT),
            protocol_name=data.get("protocol_name", "Default")
        )

# Protocol constants
PROTOCOL_TYPES = {
    "1": "Standard Protocol",
    "2": "Progressive Protocol",
    "3": "Custom Protocol"
}

# Protocol phases - move to constants.py later if needed by multiple modules
PHASE_SETUP = "setup"
PHASE_WARMUP = "warmup"
PHASE_TREATMENT = "treatment"
PHASE_COOLDOWN = "cooldown"
PHASE_COMPLETE = "complete"