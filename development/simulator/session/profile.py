"""Prepare independent synthetic device state before importing the application."""
import configparser
import os
from pathlib import Path
from typing import Dict, Optional

from simulator.core.plant import Plant


def prepare_environment(directory: Path, cloud_env: Optional[Path] = None) -> Dict[str, str]:
    """Create session-local configuration and explicitly replace inherited paths."""
    root = directory.resolve() / "device"
    state = root / "raspberry-pi"
    for child in ("config", "data", "logs"):
        (state / child).mkdir(parents=True, exist_ok=True)
    config_path = state / "config/kneespa.cfg"
    if not config_path.exists():
        profile = Plant().profile
        parser = configparser.ConfigParser()
        parser["Device"] = {"number": "1"}
        parser["Options"] = {"calibration": str(profile["scale_factor"]),
                             "a_factor": "2580", "b_factor": "1900", "c_factor": "1900"}
        parser["AMarks"] = {str(i): str(i * 430) for i in range(5)}
        parser["BMarks"] = {key: str(value) for key, value in profile["horizontal_marks"].items()}
        parser["CMarks"] = {f"{float(key):.1f}": str(value)
                            for key, value in profile["lateral_marks"].items()}
        with config_path.open("w", encoding="utf-8") as stream:
            parser.write(stream)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("KNEESPA_", "ADMIN_", "USER_PIN", "USER_USERNAME", "USER_EMAIL")):
            env.pop(key)
    env.update({
        "KNEESPA_DEVICE_DIR": str(root), "KNEESPA_CONFIG_PATH": str(config_path),
        "KNEESPA_AUDIO_CONFIG_DIR": str(state / "config/audio"),
        "KNEESPA_SKIP_PATH_VALIDATION": "1", "KNEESPA_PROTOCOL_V2": "1",
        "KNEESPA_SMTP_USERNAME": "simulator@localhost", "KNEESPA_SMTP_PASSWORD": "local-only",
        "KNEESPA_ASSISTANCE_EMAIL": "capture@localhost", "KNEESPA_TICKET_EMAIL": "capture@localhost",
        "ADMIN_PIN": "1234", "ADMIN_USERNAME": "Simulator Administrator",
        "ADMIN_EMAIL": "simulator@localhost", "USER_PIN": "5678",
        "USER_USERNAME": "Simulator Operator", "USER_EMAIL": "simulator@localhost",
    })
    if cloud_env is not None:
        from simulator.session.cloud import cloud_environment
        env.update(cloud_environment(cloud_env))
    return env
