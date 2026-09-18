"""Behavioral tests for the local audit runner and its process exit status."""

import importlib.util
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import List
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit
RUNNER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "validate_fixes.py"


@pytest.fixture
def runner() -> ModuleType:
    """Load the runner without invoking its command-line entry point."""
    spec = importlib.util.spec_from_file_location("validate_fixes", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "statuses,expected", [([0, 0], 0), ([7], 7), ([0, 1], 1), ([0, 4], 4)],
    ids=["success", "limits-failure", "test-failure", "pytest-usage-error"],
)
def test_runs_in_repo_with_current_interpreter_and_propagates_status(
    runner: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    statuses: List[int],
    expected: int,
) -> None:
    """A foreign caller directory must not change the gate or mask child failures."""
    monkeypatch.chdir(tmp_path)
    run = MagicMock(side_effect=[subprocess.CompletedProcess([], code) for code in statuses])
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.validate_fixes() == expected
    commands = [
        [sys.executable, str(runner.ROOT / "development" / "scripts" / "check_limits_sync.py")],
        [sys.executable, "-m", "pytest", "-q", *runner.TEST_NODES],
    ]
    assert run.call_count == len(statuses)
    for call, command in zip(run.call_args_list, commands):
        assert call.args == (command,)
        assert call.kwargs == {"cwd": runner.ROOT, "check": False}


def test_launch_error_is_reported_as_failure(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """An unavailable interpreter cannot yield a successful validation result."""
    run = MagicMock(side_effect=OSError("launch refused"))
    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.validate_fixes() == 1
    assert "launch refused" in capsys.readouterr().err
    run.assert_called_once()


def test_entry_point_exits_with_child_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shell command exposes the same nonzero status as its failing child."""
    run = MagicMock(return_value=subprocess.CompletedProcess([], 7))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(RUNNER_PATH), run_name="__main__")
    assert error.value.code == 7


@pytest.mark.parametrize("failure", ["limits", "pytest"])
def test_real_child_failure_propagates(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str,
) -> None:
    """Real subprocess failures propagate; failed limits prevent the pytest child."""
    root = tmp_path / "fixture repo"
    (root / "development" / "scripts").mkdir(parents=True)
    (root / "development" / "scripts" / "check_limits_sync.py").write_text(
        "raise SystemExit(7)\n" if failure == "limits" else "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    # Isolate child collection/configuration from this repository and parent pytest options.
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "test_failure.py").write_text(
        "from pathlib import Path\n"
        "def test_failure():\n"
        "    Path('pytest-ran').touch()\n"
        "    assert False, 'deliberate gate failure'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "TEST_NODES", ("test_failure.py::test_failure",))
    monkeypatch.chdir(tmp_path)

    assert runner.validate_fixes() == (7 if failure == "limits" else 1)
    assert (root / "pytest-ran").exists() is (failure == "pytest")
