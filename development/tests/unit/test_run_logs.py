"""Check on-disk run logs using fresh processes and a fake serial port."""

import io
import logging
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from helpers.logging import DiagnosticFileHandler

pytestmark = pytest.mark.unit


def test_each_process_keeps_a_pair_with_console_and_raw_serial(tmp_path: Path) -> None:
    """A normal run needs no trace flag and never overwrites an earlier log pair."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("KNEESPA_")}
    env["KNEESPA_BASE_DIR"] = str(tmp_path / "main")
    env["KNEESPA_SKIP_PATH_VALIDATION"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "runtime" / "raspberry-pi" / "main")
    script = """
import logging
import sys
from unittest.mock import MagicMock
from helpers.logging import LoggerSetup, setup_logger
from helpers.arduino import Arduino

logs = LoggerSetup()
assert logs is LoggerSetup()
logs.start_console_capture()
print('printed app output')
print('stderr diagnostic', file=sys.stderr)
setup_logger(component='RunTest').debug('debug app record')
arduino = Arduino()
port = MagicMock(is_open=True, in_waiting=1)
arduino.serial_com = port
arduino._write_now('T')
port.write.assert_called_once_with(b'T\\n')
incoming = iter(['OK\\r\\n', 'LOG|firmware detail\\r\\n', '  unknown data  \\r\\n'])
def read_line():
    line = next(incoming)
    if line.startswith('  '):
        arduino._running = False
    return line.encode()
port.readline.side_effect = read_line
arduino._running = True
arduino.read_from_com()
print('final partial line', end='')
logs.stop_console_capture()
logging.shutdown()
"""
    log_dir = tmp_path / "devices" / "local" / "raspberry-pi" / "logs"
    before = {}
    for run in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=tmp_path, env=env,
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("printed app output") == 1
        assert result.stderr.count("stderr diagnostic") == 1
        assert len(list(log_dir.glob("*.log"))) == (run + 1) * 2
        for path, contents in before.items():
            assert path.read_bytes() == contents
        before = {path: path.read_bytes() for path in log_dir.glob("*.log")}

    for path in log_dir.glob("python_*.log"):
        contents = path.read_text(encoding="utf-8")
        for expected in ("printed app output", "stderr diagnostic", "debug app record",
                         "Firmware: firmware detail", "final partial line"):
            assert expected in contents
        serial_path = path.with_name(path.name.replace("python_", "arduino_", 1))
        serial = serial_path.read_text(encoding="utf-8")
        assert "] TX T\n" in serial
        assert "] RX OK\n" in serial
        assert "] RX LOG|firmware detail\n" in serial
        assert "] RX   unknown data  \n" in serial
        assert "printed app output" not in serial
        assert "RX   unknown data" not in contents


def test_log_write_failure_does_not_recurse_through_captured_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A disk failure disables just its handler without risking the serial loop."""
    handler = DiagnosticFileHandler(tmp_path / "failure.log", encoding="utf-8")
    console = io.StringIO()
    capture = MagicMock()
    monkeypatch.setattr(sys, "__stderr__", console)
    monkeypatch.setattr(sys, "stderr", capture)
    try:
        monkeypatch.setattr(handler.stream, "write", MagicMock(side_effect=OSError("disk full")))
        handler.emit(logging.LogRecord("test", logging.INFO, "", 0, "RX OK", (), None))
        assert handler.level > logging.CRITICAL
        assert "Log file disabled" in console.getvalue()
        capture.write.assert_not_called()
    finally:
        handler.close()
