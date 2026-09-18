"""Exercise CLI routing with application, window, exit, and logging boundaries faked."""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

import kneespa
import ui.theme

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "argv,debug,config,print_logs,sync_logs",
    [
        ([], False, None, False, None),
        (["--debug"], True, None, False, None),
        (["--config", "custom config.cfg"], False, "custom config.cfg", False, None),
        (["--print-logs"], False, None, True, None),
        (["--sync-logs", "log copies"], False, None, False, "log copies"),
        (["--debug", "--config", "custom config.cfg", "--print-logs", "--sync-logs", "log copies"],
         True, "custom config.cfg", True, "log copies"),
    ],
    ids=["defaults", "debug", "config", "print-logs", "sync-logs", "combined"],
)
def test_main_routes_options(
    monkeypatch: pytest.MonkeyPatch,
    argv: List[str],
    debug: bool,
    config: Optional[str],
    print_logs: bool,
    sync_logs: Optional[str],
) -> None:
    """Options reach the window and log handlers; log work follows the event loop."""
    events = []
    app = MagicMock(spec=["setStyle", "exec_"])
    app.exec_.side_effect = lambda: events.append("event-loop")
    app_cls = MagicMock(return_value=app)
    window = MagicMock(spec=["show", "restart_requested"])
    window.restart_requested = False
    window_cls = MagicMock(return_value=window)
    printer = MagicMock(side_effect=lambda: events.append("print"))
    sync = MagicMock(side_effect=lambda path: events.append("sync"))
    exit_process = MagicMock(side_effect=lambda code: events.append("exit"))
    monkeypatch.setattr(sys, "argv", ["kneespa.py", *argv])
    monkeypatch.setattr(kneespa, "QApplication", app_cls)
    monkeypatch.setattr(kneespa, "KneeSpa", window_cls)
    monkeypatch.setattr(kneespa, "_install_excepthook", MagicMock())
    monkeypatch.setattr(ui.theme, "apply_theme", MagicMock())
    monkeypatch.setattr(kneespa, "_print_recent_logs", printer)
    monkeypatch.setattr(kneespa, "_sync_logs", sync)
    monkeypatch.setattr(kneespa, "os", SimpleNamespace(_exit=exit_process))
    monkeypatch.setattr(kneespa.logging, "shutdown", MagicMock())

    kneespa.main()

    app_cls.assert_called_once_with(["kneespa.py", *argv])
    window_cls.assert_called_once_with(debug_mode=debug, config_path=config)
    window.show.assert_called_once_with()
    app.exec_.assert_called_once_with()
    if print_logs:
        printer.assert_called_once_with()
    else:
        printer.assert_not_called()
    if sync_logs:
        sync.assert_called_once_with(sync_logs)
    else:
        sync.assert_not_called()
    exit_process.assert_not_called()
    assert events == ["event-loop"] + (["print"] if print_logs else []) + (
        ["sync"] if sync_logs else []
    )


def test_print_and_sync_use_run_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    """The existing CLI helpers follow the new file names and sibling directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    paths = [log_dir / "python_timestamp.log", log_dir / "arduino_timestamp.log"]
    for path in paths:
        path.write_text(f"older output\nlatest {path.stem}\n", encoding="utf-8")
        Path(f"{path}.1").write_text("preceding segment\n", encoding="utf-8")
    monkeypatch.setattr(kneespa, "LoggerSetup", lambda: SimpleNamespace(
        log_dir=str(log_dir), main_log_file=str(paths[0]), serial_log_file=str(paths[1]),
    ))
    kneespa._print_recent_logs(lines=1)
    printed = capsys.readouterr().out
    assert "older output" not in printed
    assert "latest python_timestamp" in printed
    assert "latest arduino_timestamp" in printed
    kneespa._print_recent_logs(lines=3)
    assert capsys.readouterr().out.count("preceding segment") == 2
    destination = tmp_path / "copies"
    kneespa._sync_logs(str(destination))
    for path in paths:
        assert (destination / path.name).read_bytes() == path.read_bytes()
        assert (destination / f"{path.name}.1").read_bytes() == Path(f"{path}.1").read_bytes()
    kneespa._sync_logs(str(log_dir))  # Syncing to the logs folder itself is harmless.


def test_startup_failure_logged_and_console_restored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A startup exception reaches the app log without leaving stdout wrapped."""
    monkeypatch.setattr(sys, "argv", ["kneespa.py"])
    monkeypatch.setattr(kneespa, "QApplication", MagicMock())
    monkeypatch.setattr(kneespa, "KneeSpa", MagicMock(side_effect=RuntimeError("startup failed")))
    monkeypatch.setattr(kneespa, "_install_excepthook", MagicMock())
    monkeypatch.setattr(ui.theme, "apply_theme", MagicMock())
    stdout, stderr = sys.stdout, sys.stderr
    with pytest.raises(RuntimeError, match="startup failed"):
        kneespa.main()
    assert sys.stdout is stdout
    assert sys.stderr is stderr
    assert "Application failed" in caplog.text
    assert "startup failed" in caplog.text
