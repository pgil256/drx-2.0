"""Safety alerts: one visible box at a time, freed once dismissed (V10)."""
import sys
from unittest.mock import MagicMock

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox

from kneespa import KneeSpa

pytestmark = [
    pytest.mark.unit,
    # Showing any QMessageBox crashes Qt 5.15's offscreen platform on Windows
    # (an access violation, which ends the whole test run). It works on
    # Linux, as in CI and on the Pi.
    pytest.mark.skipif(sys.platform == "win32",
                       reason="QMessageBox.show() crashes the offscreen platform on Windows"),
]


class AlertHost(QMainWindow):
    """A bare window with the real alert method and the logger it uses."""

    _show_safety_alert = KneeSpa._show_safety_alert

    def __init__(self):
        super().__init__()
        self.logger = MagicMock()


def flush_deletes():
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def host(qtbot):
    window = AlertHost()
    qtbot.addWidget(window)
    yield window
    alert = getattr(window, "_active_safety_alert", None)
    if alert is not None and not sip.isdeleted(alert):
        alert.close()
    flush_deletes()


def test_a_dismissed_alert_is_deleted_and_the_next_one_shows(host):
    host._show_safety_alert("CONTROLLER FAULT: PRESSURE_LIMIT")
    first = host._active_safety_alert
    assert first.isVisible()

    first.button(QMessageBox.Ok).click()
    flush_deletes()

    assert sip.isdeleted(first)  # used to stay alive, owned by the window
    assert host._active_safety_alert is None
    host._show_safety_alert("CONNECTION LOST")  # used to risk a deleted box
    second = host._active_safety_alert
    assert second is not first
    assert second.isVisible()
    assert second.text() == "CONNECTION LOST"


def test_alerts_while_one_is_open_still_join_it(host):
    host._show_safety_alert("first", warning=True)
    host._show_safety_alert("second")
    box = host._active_safety_alert
    assert box.text() == "first\n\nsecond"
    assert box.windowTitle() == "SAFETY STOP"  # an emergency is never a warning
    assert len(host.findChildren(QMessageBox)) == 1
