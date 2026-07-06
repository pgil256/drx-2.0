# tests/unit/test_limits_sync.py
"""H7: the host/firmware safety-limit pairs must not drift.

Thin pytest wrapper around scripts/check_limits_sync.py so the guard runs
in every local pytest invocation, not only in the dedicated CI step.
"""
import pathlib
import sys

import pytest

SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[2] / "scripts")


@pytest.mark.unit
def test_host_and_firmware_limits_in_sync():
    sys.path.insert(0, SCRIPTS_DIR)
    try:
        from check_limits_sync import check_limits_sync
    finally:
        sys.path.remove(SCRIPTS_DIR)

    problems = check_limits_sync()
    assert not problems, "\n".join(problems)
