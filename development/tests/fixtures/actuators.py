"""Real-button harness for actuator control gating."""

from PyQt5.QtWidgets import QPushButton
from pytestqt.qtbot import QtBot

from kneespa import KneeSpa


class ControlsHarness:
    """Bare object exposing only the state the control-gating methods use.

    Binds the real KneeSpa methods without constructing the full UI.
    """

    disable_actuator_controls = KneeSpa.disable_actuator_controls
    enable_actuator_controls = KneeSpa.enable_actuator_controls
    _apply_enable_actuator_controls = KneeSpa._apply_enable_actuator_controls
    move_actuator = KneeSpa.move_actuator

    def __init__(self, qtbot: QtBot, n_buttons: int = 3) -> None:
        self.protocol_running = False
        self.protocol_state = "idle"
        self.reset_in_progress = False
        self.initial_setup_complete = True
        self.actuator_command_in_progress = False
        self.controls_enable_timer = None
        self.actuator_controls = []
        for _ in range(n_buttons):
            button = QPushButton()
            qtbot.addWidget(button)
            self.actuator_controls.append(button)

    def all_enabled(self) -> bool:
        return all(w.isEnabled() for w in self.actuator_controls)

    def all_disabled(self) -> bool:
        return all(not w.isEnabled() for w in self.actuator_controls)
