"""Unit coverage for the physical-touch E2E runner's safe pure-Python seams."""

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "e2e_touchscreen.py"
SPEC = importlib.util.spec_from_file_location("e2e_touchscreen", MODULE_PATH)
e2e = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = e2e
SPEC.loader.exec_module(e2e)


def test_scaled_point_uses_device_viewport() -> None:
    driver = object.__new__(e2e.ClickDriver)
    driver.viewport = e2e.Rect(10, 20, 683, 384)

    assert driver.scaled((1366, 768)) == (693, 404)
    assert driver.scaled((683, 384)) == (352, 212)


def test_expand_all_selects_requested_full_flow() -> None:
    args = argparse.Namespace(
        all=True, setup=False, actuators=None, protocols=None, video=False
    )

    actuators, protocols, video = e2e.expand_selection(args)

    assert actuators == ["axial", "lateral", "horizontal", "leg-length"]
    assert protocols == [1, 2, 3]
    assert video is True


def test_setup_and_explicit_actuator_are_deduplicated() -> None:
    args = argparse.Namespace(
        all=False,
        setup=True,
        actuators=["axial", "leg-length"],
        protocols=[2],
        video=False,
    )

    actuators, protocols, video = e2e.expand_selection(args)

    assert actuators == ["axial", "lateral", "horizontal", "leg-length"]
    assert protocols == [2]
    assert video is False


def test_output_monitor_matches_only_after_marker(tmp_path: Path) -> None:
    log = e2e.RunLog(tmp_path / "e2e.log")
    monitor = e2e.OutputMonitor(log)
    monitor.feed("old DONE")
    marker = monitor.mark()
    monitor.feed("new Reset sequence finished signal received. Success: True")

    line = monitor.wait_for(("Success: True",), marker, 0.1)

    assert line.startswith("new Reset")


def test_redacted_click_does_not_log_pin_coordinates() -> None:
    driver = object.__new__(e2e.ClickDriver)
    driver.backend = "pyautogui"
    driver.log = MagicMock()
    driver._pyautogui = MagicMock()

    driver.click_absolute(580, 342, "PIN digit 1/4", redact_coordinates=True)

    driver.log.write.assert_called_once_with("TOUCH", "PIN digit 1/4 at [redacted]")


def test_serial_trace_is_opt_in_and_timestamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main_dir = Path(__file__).resolve().parents[2] / "main"
    monkeypatch.syspath_prepend(str(main_dir))
    trace_path = tmp_path / "serial.log"
    monkeypatch.setenv("KNEESPA_SERIAL_TRACE_FILE", str(trace_path))
    from helpers.arduino import Arduino

    arduino = Arduino()
    arduino._trace_serial("TX", "T")
    arduino._trace_serial("RX", "OK")

    text = trace_path.read_text(encoding="utf-8")
    assert "] TX T" in text
    assert "] RX OK" in text


def test_safe_stop_uses_setup_stop_for_current_actuator() -> None:
    runner = object.__new__(e2e.E2ERunner)
    runner.driver = MagicMock()
    runner.monitor = MagicMock()
    runner.monitor.mark.return_value = 12
    runner.log = MagicMock()
    runner._wait_done = MagicMock()
    runner.current_protocol = False
    runner.current_actuator = "lateral"

    runner.safe_stop()

    runner.driver.click.assert_called_once_with(
        (e2e.SETUP_X["stop"], e2e.SETUP_ROW_Y["lateral"]),
        "SAFETY STOP lateral",
    )
    runner._wait_done.assert_called_once_with(12, "best-effort actuator stop")
    assert runner.current_actuator is None
