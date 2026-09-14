"""Exercise CLI routing with application, window, exit, and logging boundaries faked."""

import sys
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
    window = MagicMock(spec=["show"])
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
    exit_process.assert_called_once_with(0)
    assert events == ["event-loop"] + (["print"] if print_logs else []) + (
        ["sync"] if sync_logs else []
    ) + ["exit"]
