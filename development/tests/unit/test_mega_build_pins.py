"""The release installer's Mega build must use the repo firmware's exact pins.

The installer writes its own platformio.ini (MEGA_BUILD) for uploaded firmware
sources, so a pin bumped in runtime/arduino/motor/platformio.ini alone would
build field updates with a different toolchain than CI and the flash script.
"""
import configparser
import pathlib

import pytest

from helpers.release_installer import MEGA_BUILD

PLATFORMIO_INI = (pathlib.Path(__file__).resolve().parents[3]
                  / "runtime" / "arduino" / "motor" / "platformio.ini")
PINNED_KEYS = ("platform", "lib_deps")

pytestmark = pytest.mark.unit


def _mega_env(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    section = parser["env:mega"]
    return {key: [line.strip() for line in section[key].splitlines() if line.strip()]
            for key in PINNED_KEYS}


def test_installer_mega_pins_match_repo_firmware():
    repo = _mega_env(PLATFORMIO_INI.read_text(encoding="utf-8"))
    assert _mega_env(MEGA_BUILD) == repo


@pytest.mark.parametrize("key", PINNED_KEYS)
def test_repo_firmware_pins_are_exact(key):
    for value in _mega_env(PLATFORMIO_INI.read_text(encoding="utf-8"))[key]:
        name, _, version = value.partition("@")
        assert version, "%s is not pinned: %s" % (key, value)
        assert not any(c in version for c in "^~<>=*"), "%s is a range: %s" % (key, value)
