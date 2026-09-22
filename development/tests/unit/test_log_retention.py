"""Exercise rollover, shared retention, and bounded shutdown tails on real files."""

import io
import logging
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc
from typing import Optional
from unittest.mock import MagicMock

import pytest

from helpers.logging import (
    DiagnosticFileHandler,
    LogRetention,
    _process_exists,
    read_recent_log_lines,
)


pytestmark = pytest.mark.unit


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord("retention-test", logging.INFO, "", 0, message, (), None)


def _run_log(directory: Path, kind: str, pid: int, part: str = "") -> Path:
    return directory / f"{kind}_20000101-000000-000000_{pid}.log{part}"


def _sized_log(path: Path, size: int, modified: int) -> Path:
    path.write_bytes(b"x" * size)
    os.utime(path, (modified, modified))
    return path


def test_rotation_preserves_records_in_ascending_segments(tmp_path: Path) -> None:
    """Small limits simulate several 20 MiB rollovers, including UTF-8 byte sizes."""
    path = _run_log(tmp_path, "python", os.getpid())
    handler = DiagnosticFileHandler(str(path), max_bytes=64)
    messages = [f"{index:02d}: " + "\u00e9" * 15 for index in range(12)]
    try:
        for message in messages:
            handler.handle(_record(message))
    finally:
        handler.close()
    parts = [Path(f"{path}.{index}") for index in range(1, 12)] + [path]
    assert all(part.stat().st_size <= 64 for part in parts)
    assert "".join(part.read_text(encoding="utf-8") for part in parts).splitlines() == messages
    assert read_recent_log_lines(str(path), 4) == [message + "\n" for message in messages[-4:]]


@pytest.mark.parametrize("legacy_api", [False, True], ids=["current", "pre-python39"])
def test_encoding_errors_are_escaped_before_and_after_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy_api: bool,
) -> None:
    """Older FileHandlers accept no errors keyword and expose no errors attribute."""
    if legacy_api:
        original_init = logging.FileHandler.__init__

        def legacy_init(
            self: logging.FileHandler, filename: str, mode: str = "a",
            encoding: Optional[str] = None, delay: bool = False,
        ) -> None:
            original_init(self, filename, mode=mode, encoding=encoding, delay=delay)
            if hasattr(self, "errors"):
                del self.errors

        monkeypatch.setattr(logging.FileHandler, "__init__", legacy_init)

    path = tmp_path / "encoding.log"
    handler = DiagnosticFileHandler(str(path), max_bytes=16)
    try:
        handler.handle(_record("first \udcff"))
        handler.handle(_record("next \udcff"))
        assert handler.level <= logging.CRITICAL
    finally:
        handler.close()
    assert Path(f"{path}.1").read_text(encoding="utf-8") == "first \\udcff\n"
    assert path.read_text(encoding="utf-8") == "next \\udcff\n"


def test_single_oversized_record_is_kept_intact(tmp_path: Path) -> None:
    path = tmp_path / "large.log"
    handler = DiagnosticFileHandler(str(path), max_bytes=16)
    try:
        handler.handle(_record("x" * 50))
        handler.handle(_record("next"))
    finally:
        handler.close()
    assert Path(f"{path}.1").read_text() == "x" * 50 + "\n"
    assert path.read_text() == "next\n"


def test_shared_budget_removes_oldest_closed_files_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("helpers.logging._process_exists", lambda pid: pid == os.getpid())
    active = _sized_log(_run_log(tmp_path, "python", os.getpid()), 40, 1)
    old = _sized_log(_run_log(tmp_path, "python", 11111), 70, 2)
    rotated = _sized_log(_run_log(tmp_path, "arduino", os.getpid(), ".1"), 50, 3)
    recent = _sized_log(_run_log(tmp_path, "arduino", 22222), 60, 4)
    unrelated = _sized_log(tmp_path / "notes.log", 200, 1)
    malformed = _sized_log(tmp_path / "python_unknown.log", 200, 1)
    nested = tmp_path / "e2e"
    nested.mkdir()
    nested_log = _sized_log(_run_log(nested, "python", 33333), 200, 1)

    LogRetention(str(tmp_path), budget_bytes=100).cleanup(force=True)

    assert not old.exists()
    assert not rotated.exists()
    assert active.stat().st_size + recent.stat().st_size == 100
    assert all(path.exists() for path in (unrelated, malformed, nested_log))


def test_budget_is_enforced_during_a_run_with_both_log_handlers(tmp_path: Path) -> None:
    """Rollover prunes closed segments even if the application never restarts."""
    retention = LogRetention(str(tmp_path), budget_bytes=160, interval_s=3600)
    paths = [_run_log(tmp_path, kind, os.getpid()) for kind in ("python", "arduino")]
    handlers = [DiagnosticFileHandler(str(path), max_bytes=64, retention=retention)
                for path in paths]
    try:
        for index in range(40):
            handlers[index % 2].handle(_record(f"{index:02d}: " + "x" * 28))
            assert sum(path.stat().st_size for path in tmp_path.iterdir()) <= 160
        assert paths[0].read_text().startswith("38:")
        assert paths[1].read_text().startswith("39:")
    finally:
        for handler in handlers:
            handler.close()


def test_periodic_cleanup_runs_without_rotation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [100.0]
    monkeypatch.setattr("helpers.logging.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("helpers.logging._process_exists", lambda pid: pid == os.getpid())
    retention = LogRetention(str(tmp_path), budget_bytes=50, interval_s=60)
    path = _run_log(tmp_path, "python", os.getpid())
    handler = DiagnosticFileHandler(str(path), max_bytes=1000, retention=retention)
    try:
        handler.handle(_record("one"))
        old = _sized_log(_run_log(tmp_path, "arduino", 11111), 100, 1)
        clock[0] = 159.0
        handler.handle(_record("two"))
        assert old.exists()
        clock[0] = 160.0
        handler.handle(_record("three"))
        assert not old.exists()
        assert path.read_text().splitlines() == ["one", "two", "three"]
    finally:
        handler.close()


def test_startup_prunes_previous_runs_and_configures_both_handlers(tmp_path: Path) -> None:
    """A fresh application import applies retention before it starts logging."""
    directory = tmp_path / "devices" / "local" / "raspberry-pi" / "logs"
    directory.mkdir(parents=True)
    seed = """
import os
from pathlib import Path
import sys
path = Path(sys.argv[1]) / f'python_20000101-000000-000000_{os.getpid()}.log'
path.write_bytes(b'x' * 5000)
print(path.name)
"""
    seeded = subprocess.run(
        [sys.executable, "-c", seed, str(directory)], capture_output=True, text=True,
        check=True, timeout=10,
    )
    old = directory / seeded.stdout.strip()
    assert old.exists()
    env = {key: value for key, value in os.environ.items() if not key.startswith("KNEESPA_")}
    env["KNEESPA_BASE_DIR"] = str(tmp_path / "main")
    env["KNEESPA_SKIP_PATH_VALIDATION"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "runtime" / "raspberry-pi" / "main")
    start = """
from config import constants
assert constants.LOG_MAX_FILE_BYTES == 20 * 1024 * 1024
assert constants.LOG_TOTAL_BUDGET_BYTES == 1024 * 1024 * 1024
constants.LOG_MAX_FILE_BYTES = 1024
constants.LOG_TOTAL_BUDGET_BYTES = 2048
from helpers.logging import DiagnosticFileHandler, LoggerSetup
setup = LoggerSetup()
for logger in (setup.logger, setup.serial_logger):
    handlers = [h for h in logger.handlers if isinstance(h, DiagnosticFileHandler)]
    assert len(handlers) == 1
    assert handlers[0].max_bytes == 1024
    assert handlers[0].retention is setup.retention
assert setup.retention.budget_bytes == 2048
"""
    subprocess.run(
        [sys.executable, "-c", start], env=env, cwd=tmp_path, capture_output=True,
        text=True, check=True, timeout=10,
    )
    assert not old.exists()
    assert len(list(directory.glob("*.log"))) == 2


def test_another_process_keeps_its_open_log_until_it_exits(tmp_path: Path) -> None:
    """Use a real child so the Windows/POSIX process checks protect a live writer."""
    script = """
import os
from pathlib import Path
import sys
path = Path(sys.argv[1]) / f'python_20000101-000000-000000_{os.getpid()}.log'
with path.open('w') as stream:
    stream.write('still writing\\n')
    stream.flush()
    print(os.getpid(), flush=True)
    sys.stdin.read()
"""
    with subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as child:
        try:
            # Windows virtualenv launchers may have a different PID from their interpreter.
            writer_pid = int(child.stdout.readline().strip())
            path = _run_log(tmp_path, "python", writer_pid)
            retention = LogRetention(str(tmp_path), budget_bytes=0)
            assert _process_exists(writer_pid)
            retention.cleanup(force=True)
            assert path.exists()
            child.communicate(timeout=10)
            assert child.returncode == 0
            assert not _process_exists(writer_pid)
            retention.cleanup(force=True)
            assert not path.exists()
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)


def test_cleanup_failure_preserves_logging_and_tries_other_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("helpers.logging._process_exists", lambda pid: pid == os.getpid())
    protected = _sized_log(_run_log(tmp_path, "arduino", 11111), 30, 1)
    removable = _sized_log(_run_log(tmp_path, "arduino", 22222), 40, 2)
    original_remove = os.remove

    def remove(path: str) -> None:
        if Path(path) == protected:
            raise PermissionError("file locked")
        original_remove(path)

    monkeypatch.setattr("helpers.logging.os.remove", remove)
    warning = io.StringIO()
    monkeypatch.setattr(sys, "__stderr__", warning)
    captured_stderr = MagicMock()
    monkeypatch.setattr(sys, "stderr", captured_stderr)
    path = _run_log(tmp_path, "python", os.getpid())
    retention = LogRetention(str(tmp_path), budget_bytes=40)
    handler = DiagnosticFileHandler(str(path), retention=retention)
    try:
        handler.handle(_record("first"))
        handler.handle(_record("second"))
        assert protected.exists()
        assert not removable.exists()
        assert path.read_text() == "first\nsecond\n"
        assert warning.getvalue().count("Log cleanup failed") == 1
        captured_stderr.write.assert_not_called()
    finally:
        handler.close()


def test_rollover_failure_does_not_escape_or_recurse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "failure.log"
    handler = DiagnosticFileHandler(str(path), max_bytes=8)
    monkeypatch.setattr("helpers.logging.os.rename", MagicMock(side_effect=OSError("disk error")))
    captured_stderr = MagicMock()
    monkeypatch.setattr(sys, "stderr", captured_stderr)
    monkeypatch.setattr(sys, "__stderr__", io.StringIO())
    try:
        handler.handle(_record("first"))
        handler.handle(_record("second"))
        assert handler.level > logging.CRITICAL
        assert path.read_text() == "first\n"
        captured_stderr.write.assert_not_called()
    finally:
        handler.close()


def test_tail_memory_stays_bounded_for_large_files(tmp_path: Path) -> None:
    path = tmp_path / "large.log"
    with path.open("w", encoding="utf-8") as stream:
        for _ in range(20000):
            stream.write("x" * 500 + "\n")
        stream.write("last line without newline")
    tracemalloc.start()
    try:
        recent = read_recent_log_lines(str(path), 200)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(recent) == 200
    assert recent[-1] == "last line without newline"
    assert peak < 1024 * 1024
    assert read_recent_log_lines(str(path), 0) == []
    assert read_recent_log_lines(str(path), -1) == []


def test_tail_accepts_empty_missing_and_invalid_utf8_files(tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.touch()
    assert read_recent_log_lines(str(path)) == []
    assert read_recent_log_lines(str(tmp_path / "missing.log")) == []
    Path(f"{path}.1").write_bytes(b"older\ninvalid \xff\n")
    path.write_bytes(b"newest\n")
    assert read_recent_log_lines(str(path), 2) == ["invalid \ufffd\n", "newest\n"]
