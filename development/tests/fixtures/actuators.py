"""Real-button harness for actuator control gating."""

import threading
from unittest.mock import MagicMock

from PyQt5.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from controllers.device_state import DeviceStateAttributes
from controllers.motion_controller import (
    MotionAttributes, MotionController, WindowSetupView,
)
from kneespa import KneeSpa


class ControlsHarness(DeviceStateAttributes, MotionAttributes):
    """A bare window around a real MotionController, wired as KneeSpa wires it.

    The Setup controls are real buttons, reached through the same
    WindowSetupView the window uses, so window-level callers (the connection
    manager's DONE handling) exercise the real gate. The device flags live in
    a DeviceState and the positions and timers on the controller, as on the
    real window.
    """

    disable_actuator_controls = KneeSpa.disable_actuator_controls
    enable_actuator_controls = KneeSpa.enable_actuator_controls
    move_actuator = KneeSpa.move_actuator

    def __init__(self, qtbot: QtBot, n_buttons: int = 3) -> None:
        self.logger = MagicMock()
        self.protocol_running = False
        self.protocol_state = "idle"
        self.reset_in_progress = False
        self.initial_setup_complete = True
        self.actuator_command_in_progress = False
        self.arduino = None
        self.config = None
        self.loading_spinner = MagicMock()
        self._show_timed_error = MagicMock()
        self._warn_uncalibrated = MagicMock()
        self._set_badge = MagicMock()
        self.shell = MagicMock()
        self.I2Cstatus_event = threading.Event()
        self.actuator_controls = []
        for _ in range(n_buttons):
            button = QPushButton()
            qtbot.addWidget(button)
            self.actuator_controls.append(button)
        self.motion = MotionController(
            lambda: self.arduino, lambda: self.config, self.device_state,
            WindowSetupView(self), logger=self.logger,
            leg=lambda: getattr(self, "leg", None),
            done_event=self.I2Cstatus_event,
            protocol_running=lambda: self.protocol_running,
        )

    def all_enabled(self) -> bool:
        return all(w.isEnabled() for w in self.actuator_controls)

    def all_disabled(self) -> bool:
        return all(not w.isEnabled() for w in self.actuator_controls)
