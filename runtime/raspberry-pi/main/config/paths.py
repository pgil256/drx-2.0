"""Locate shared application files and independent, per-device runtime state."""

import os
from pathlib import Path


APP_BASE_DIR = os.path.abspath(os.environ.get(
    "KNEESPA_BASE_DIR", str(Path(__file__).resolve().parents[1]),
))
_app = Path(APP_BASE_DIR)
# Retain support for custom application directories used by local tooling.
PROJECT_DIR = str(
    _app.parents[2] if _app.parent.name == "raspberry-pi" and _app.parent.parent.name == "runtime"
    else _app.parent
)
DEVICE_DIR = os.path.abspath(os.environ.get(
    "KNEESPA_DEVICE_DIR", os.path.join(PROJECT_DIR, "devices", "local"),
))
DEVICE_STATE_DIR = os.path.join(DEVICE_DIR, "raspberry-pi")


def load_device_environment() -> None:
    """Read only the selected device's env files; process environment wins."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for name in (".env", "cloud.env"):
        load_dotenv(os.path.join(DEVICE_STATE_DIR, name), override=False)


load_device_environment()
