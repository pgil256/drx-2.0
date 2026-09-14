"""Shared reset-worker builders with real Event and polling alternatives."""

import threading
from types import SimpleNamespace
from typing import Any

from fixtures.protocols import make_arduino
from helpers.reset_worker import ResetWorker


def make_main_window(use_event: bool = True) -> SimpleNamespace:
    """Build an explicit main_window with the attributes ResetWorker inspects.

    A real ``threading.Event`` is used for I2Cstatus_event so the event-based
    code path in _wait_for_done exercises real wait/clear semantics. ``worker``
    is set to None so the run() safety check treats no protocol as running.
    """
    mw = SimpleNamespace()
    mw.I2Cstatus = 0
    if use_event:
        mw.I2Cstatus_event = threading.Event()
    mw.worker = None
    return mw


def make_config(scale_calibrated: bool = True) -> SimpleNamespace:
    """Build an explicit config with the marks/calibration ResetWorker reads."""
    config = SimpleNamespace()
    config.AMarks = {"0.0": 0, "0": 0}
    # Step 4 homes actuator B to the calibrated -10 deg BMarks position (1140).
    config.BMarks = {"0.0": 1900, "0": 1900, "-15": 760, "-10": 1140}
    # run() reads CMarks["{:.1f}".format(0)] == CMarks["0.0"]
    config.CMarks = {"0.0": 1450}
    config.calibration = 1.0
    config.scale_calibrated = scale_calibrated
    return config


def make_worker(arduino: Any = None, config: Any = None,
                main_window: Any = None, use_event: bool = True) -> ResetWorker:
    """Construct a ResetWorker with explicit offline collaborators."""
    if arduino is None:
        arduino = make_arduino()
    if config is None:
        config = make_config()
    if main_window is None:
        main_window = make_main_window(use_event=use_event)
    return ResetWorker(arduino, config, main_window)
