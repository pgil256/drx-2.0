"""Keep test-run application logs out of the device state folder."""

import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

from config.constants import APP_NAME
from config.paths import DEVICE_DIR
from helpers.logging import DiagnosticFileHandler, LoggerSetup

pytestmark = pytest.mark.unit
REPO_ROOT = Path(__file__).resolve().parents[3]


def _inside(path: str, directory: str) -> bool:
    path, directory = os.path.realpath(path), os.path.realpath(directory)
    try:
        common = os.path.commonpath([path, directory])
    except ValueError:  # Different Windows drives.
        return False
    return os.path.normcase(common) == os.path.normcase(directory)


def test_session_logs_stay_out_of_device_state() -> None:
    """The logger singleton and its open files live in the session's temporary folder."""
    setup = LoggerSetup()
    paths = [setup.log_dir] + [
        handler.baseFilename
        for name in (APP_NAME, f"{APP_NAME}.serial")
        for handler in logging.getLogger(name).handlers
        if isinstance(handler, DiagnosticFileHandler)
    ]
    for directory in (DEVICE_DIR, str(REPO_ROOT / "devices")):
        assert not [path for path in paths if _inside(path, directory)]


def test_narrow_run_keeps_logs_out_of_device_state(tmp_path: Path) -> None:
    """A single-file run imports unit/conftest.py before pytest_configure runs."""
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("KNEESPA_", "PYTEST_"))
    }
    # A regression then writes into this disposable profile, not the checkout's.
    device_dir = tmp_path / "devices"
    env["KNEESPA_DEVICE_DIR"] = str(device_dir)
    test_file = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-o", f"cache_dir={tmp_path / 'cache'}",
         f"{test_file}::test_session_logs_stay_out_of_device_state"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(device_dir.rglob("*.log"))
