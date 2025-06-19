# config/constants.py

"""
Constants and configuration values for the KneeSpa application.
Centralizes all magic numbers and configuration settings.
"""

import os

# Application Info
APP_NAME = "KneeSpa"
APP_VERSION = "2.3"
APP_BASE_DIR = "/home/pi/drx-2.3/main/"

# Logging Configuration
LOG_FILE = "kneespa_app.log"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
LOG_LEVEL = "DEBUG"

# UI Constants
WINDOW_TITLE = "KneeSpa Control Interface"
DEGREES = "\u00b0"

# Page Indices
PAGES = {"HOME": 0, "SETUP": 1, "MAIN": 2, "HELP": 3, "PROFILE": 4}

# File Paths
UI_PATHS = {
    "MAIN_UI": os.path.join(APP_BASE_DIR, "ui/guis/kneespa.ui"),
    "LOGIN_UI": os.path.join(APP_BASE_DIR, "ui/guis/login.ui"),
    "LOGIN_HELP_UI": os.path.join(APP_BASE_DIR, "ui/guis/login-help.ui"),
    "ENTER_PATIENT_UI": os.path.join(APP_BASE_DIR, "ui/guis/enter-patient.ui"),
    "ENTER_PATIENT_HELP_UI": os.path.join(
        APP_BASE_DIR, "ui/guis/enter-patient-help.ui"
    ),
    "PROTOCOL_IMAGES": os.path.join(APP_BASE_DIR, "ui/media/images/graphics"),
    "VIDEOS": os.path.join(APP_BASE_DIR, "ui/media/videos/1.mp4"),
}

DATA_PATHS = {
    "USER_PINS": os.path.join(APP_BASE_DIR, "data/user_pins.csv"),
}

# GPIO Pin Configuration
EMERGENCYSTOP = 16
EXTRAFORWARD = 27
EXTRABACKWARD = 22
EXTRAENABLE = 17

# Path of config file
CONFIG_PATH = os.path.join(APP_BASE_DIR, "config/kneespa.cfg")

# Actuator Configuration
ACTUATORS = {
    "AXIAL": {
        "ID": "12",
        "LIMITS": (0, 4),  # inches
        "STEP_NORMAL": 0.5,
        "STEP_FAST": 1.0,
        "COMMAND_PREFIX": "A12",
        "UNITS": "in",
        "MULTIPLIER": 2,
        "FORMAT": "{:.1f}",
    },
    "HORIZONTAL": {
        "ID": "13",
        "LIMITS": (-25, 5),  # degrees
        "STEP_NORMAL": 5,
        "STEP_FAST": 10,
        "COMMAND_PREFIX": "B",
        "UNITS": DEGREES,
        "MULTIPLIER": 1,
        "FORMAT": "{:d}",
    },
    "LATERAL": {
        "ID": "14",
        "LIMITS": (-20, 20),  # degrees
        "STEP_NORMAL": 5,
        "STEP_FAST": 10,
        "COMMAND_PREFIX": "K",
        "UNITS": DEGREES,
        "MULTIPLIER": 1,
        "FORMAT": "{:d}",
    },
}

# Safety Limits
PRESSURE_MAX = 80  # Maximum safe pressure in lbs
AXIAL_MAX = 4600  # Maximum axial position
LATERAL_MIN = 500  # Minimum lateral position
LATERAL_MAX = 2400  # Maximum lateral position
HORIZONTAL_MIN = 50  # Minimum horizontal position (-5 degrees)
HORIZONTAL_MAX = 4500  # Maximum horizontal position (-25 degrees)

# Actuator Command Speed
LEG_LENGTH_SPEED_NORMAL = 0.5  # inches per second
LEG_LENGTH_SPEED_FAST = 1.0  # inches per second
LEG_LENGTH_MIN = 0.0  # Minimum leg length in inches
LEG_LENGTH_MAX = 6.0  # Maximum leg length in inches

# Movement Configuration
MOVEMENT_DELAY = 0.5  # seconds between movements
DEFAULT_HORIZONTAL_POSITION = -15  # degrees

# Default Positions
DEFAULT_AXIAL_POSITION = 0  # inches
DEFAULT_LATERAL_POSITION = 0  # degrees
DEFAULT_PRESSURE = 0  # pounds
DEFAULT_LEG_LENGTH_POSITION = 0  # inches

# Protocol Configuration
PROTOCOL_MAPPING = {
    1: "AC1",
    2: "AC2",
    3: "AC3"
}

# Protocol Default Settings
PROTOCOL_DEFAULT_SETTINGS = {
    "DEGREES0": 0,  # Center/neutral position
    "MIN_PRESSURE": 10,  # Minimum starting pressure in lbs
    "MAX_SAFE_PRESSURE": 80,  # Maximum safe pressure in lbs
    "HOLD_TIME_SHORT": 1,
    "HOLD_TIME_LONG": 5,  # Default hold duration in seconds
    "PRESSURE_INCREMENT": 10,  # Standard pressure increase step
    "ANGLE_INCREMENT": 5  # Standard angle adjustment step
}

# UI Style Constants
BUTTON_STYLES = {
    "START": """
        background-color: rgb(0, 200, 0);
        color: white;
        border: none;
        text-decoration: bold;
        font-size: 32px;
        font-weight: bold;
        border-radius: 12px;
    """,
    "STOP": """
        background-color: rgb(200, 0, 0);
        color: white;
        border: none;
        text-decoration: bold;
        font-size: 32px;
        font-weight: bold;
        border-radius: 12px;
    """,
}

# Arduino Communication
ARDUINO_SETTINGS = {
    "CALIBRATION_DELAY": 2000,  # ms
    "ZERO_MARK_DELAY": 5000,  # ms
    "COMMAND_DELAY": 1500,  # ms
    "BUFFER_WARNING_THRESHOLD": 0.8,  # 80% full
    "ARDUINO_BUFFER_SIZE": 64,  # Standard Arduino buffer size
    "ARDUINO_PORT": "/dev/serial0",  # Default Arduino port
    "CONNECTION_TIMEOUT_S": 30  # Timeout duration in seconds
}

# Email Configuration
EMAIL_CONFIG = {
    "SENDER_EMAIL": "ksdrxsmtp@gmail.com",
    "SENDER_PASSWORD": "nujyxfajvgouwvux",
    "RECEIVER_EMAIL": "ksdrxsmtp@gmail.com",
    "SMTP_SERVER": "smtp.gmail.com",
    "SMTP_PORT": 465,
}

# Error Messages
ERROR_MESSAGES = {
    "UI_NOT_FOUND": "UI file 'kneespa.ui' not found.",
    "CENTRAL_WIDGET_NOT_FOUND": "Central widget 'main_content' not found in the UI file.",
    "LOGIN_REQUIRED": "Please log in to start a protocol.",
    "ADMIN_REQUIRED": "Only admins can edit patient data.",
    "INVALID_PIN": "Invalid PIN. Please try again.",
    "INVALID_PROTOCOL": "Please select a valid protocol (1-9).",
    "ACTUATOR_ERROR": "Failed to initialize actuators. Please check connections.",
    "MOVEMENT_ERROR": "Error moving {} actuator. Check connections.",
    "ARDUINO_RESET_ERROR": "Could not complete reset sequence. Check connections.",
}

# Success Messages
SUCCESS_MESSAGES = {
    "PROTOCOL_COMPLETE": "The protocol has finished executing successfully.",
    "ARDUINO_RESET": "Arduino reset and actuators reinitialized.",
    "DATA_LOADED": "User data loaded successfully."
}


def validate_paths():
    """Validate that all required paths exist."""
    for category, paths in {**UI_PATHS, **DATA_PATHS}.items():
        if isinstance(paths, dict):
            for name, path in paths.items():
                if not os.path.exists(path):
                    raise FileNotFoundError(f"Required path not found: {path}")
        elif not os.path.exists(paths):
            raise FileNotFoundError(f"Required path not found: {paths}")


# Validate paths on import
try:
    validate_paths()
except FileNotFoundError as e:
    print(f"Configuration Error: {str(e)}")
    # You might want to log this error or handle it differently
    raise
