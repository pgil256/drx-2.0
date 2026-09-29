# development/tests/unit/test_limits_sync.py
"""H7: the host/firmware safety-limit pairs must not drift.

Thin pytest wrapper around development/scripts/check_limits_sync.py so the guard runs
in every local pytest invocation, not only in the dedicated CI step.
"""
import pathlib
import sys

import pytest

SCRIPTS_DIR = str(pathlib.Path(__file__).resolve().parents[2] / "scripts")


def _load_checker():
    sys.path.insert(0, SCRIPTS_DIR)
    try:
        import check_limits_sync
    finally:
        sys.path.remove(SCRIPTS_DIR)
    return check_limits_sync


@pytest.mark.unit
def test_host_and_firmware_limits_in_sync():
    problems = _load_checker().check_limits_sync()
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_paired_define_the_firmware_never_reads_is_reported(monkeypatch, tmp_path):
    """A matching but unused #define cannot vouch for the value actually enforced."""
    checker = _load_checker()
    source = checker.MOTOR_INO.read_text(encoding="utf-8")
    live = "const float PRESSURE_TARGET_BAND = PRESSURE_TARGET_TOLERANCE_LBS;"
    assert live in source
    motor = tmp_path / "motor.ino"
    motor.write_text(source.replace(live, "const float PRESSURE_TARGET_BAND = 2.0;"),
                     encoding="utf-8")
    monkeypatch.setattr(checker, "MOTOR_INO", motor)

    problems = checker.check_limits_sync()

    assert len(problems) == 1
    assert "PRESSURE_TARGET_TOLERANCE_LBS is never used" in problems[0]


@pytest.mark.unit
@pytest.mark.parametrize("source,used", [
    ("#define LIMIT 5\nint x = LIMIT;\n", True),
    ("#define LIMIT 5\n// LIMIT is documented only\n", False),
    ("#define LIMIT 5\n/* LIMIT\n   in a block comment */\n", False),
    ("#define LIMIT 5\nint LIMIT_OTHER = 1;\n", False),
])
def test_define_use_ignores_comments_and_longer_names(source, used):
    assert _load_checker().define_is_used(source, "LIMIT") is used
