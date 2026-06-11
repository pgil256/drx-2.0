# tests/unit/test_actuator_controls.py
"""Regression tests for the lateral double-click control lockup.

Rapid repeated actuator clicks used to stack one QTimer per widget per
enable call; a disable could interleave with pending per-widget enables,
leaving controls permanently disabled until app restart. The fix tracks
an in-progress flag and a single supersedable enable timer.
"""
import pytest
from PyQt5.QtWidgets import QPushButton

from kneespa import KneeSpa


class ControlsHarness:
    """Bare object exposing only the state the control-gating methods use.

    Binds the real KneeSpa methods without constructing the full UI.
    """

    disable_actuator_controls = KneeSpa.disable_actuator_controls
    enable_actuator_controls = KneeSpa.enable_actuator_controls
    _apply_enable_actuator_controls = KneeSpa._apply_enable_actuator_controls
    move_actuator = KneeSpa.move_actuator

    def __init__(self, qtbot, n_buttons=3):
        self.protocol_running = False
        self.actuator_command_in_progress = False
        self.controls_enable_timer = None
        self.actuator_controls = []
        for _ in range(n_buttons):
            button = QPushButton()
            qtbot.addWidget(button)
            self.actuator_controls.append(button)

    def all_enabled(self):
        return all(w.isEnabled() for w in self.actuator_controls)

    def all_disabled(self):
        return all(not w.isEnabled() for w in self.actuator_controls)


@pytest.mark.unit
class TestActuatorControlGating:
    def test_disable_sets_flag_and_disables(self, qtbot):
        h = ControlsHarness(qtbot)
        h.disable_actuator_controls()
        assert h.actuator_command_in_progress is True
        assert h.all_disabled()

    def test_enable_reenables_after_delay_and_clears_state(self, qtbot):
        h = ControlsHarness(qtbot)
        h.disable_actuator_controls()
        h.enable_actuator_controls()
        assert h.actuator_command_in_progress is False
        qtbot.wait(300)
        assert h.all_enabled()
        assert h.controls_enable_timer is None

    def test_disable_cancels_pending_enable(self, qtbot):
        """The lockup scenario: a second command arrives while the first
        command's deferred enable is still pending. The disable must win."""
        h = ControlsHarness(qtbot)
        h.disable_actuator_controls()
        h.enable_actuator_controls()  # first command completed
        h.disable_actuator_controls()  # second command starts before timer fires
        qtbot.wait(300)
        assert h.all_disabled()
        assert h.actuator_command_in_progress is True
        assert h.controls_enable_timer is None

    def test_rapid_double_enable_uses_single_timer(self, qtbot):
        h = ControlsHarness(qtbot)
        h.disable_actuator_controls()
        h.enable_actuator_controls()
        first_timer = h.controls_enable_timer
        h.enable_actuator_controls()
        assert h.controls_enable_timer is not first_timer
        assert not first_timer.isActive()
        qtbot.wait(300)
        assert h.all_enabled()
        assert h.controls_enable_timer is None

    def test_enable_during_protocol_clears_flag_keeps_disabled(self, qtbot):
        h = ControlsHarness(qtbot)
        h.disable_actuator_controls()
        h.protocol_running = True
        h.enable_actuator_controls()
        assert h.actuator_command_in_progress is False
        qtbot.wait(300)
        assert h.all_disabled()

    def test_move_actuator_ignored_while_command_in_progress(self, qtbot):
        """move_actuator must return before touching any actuator state.

        The harness has none of the attributes the body uses, so reaching
        past the guard would raise AttributeError."""
        h = ControlsHarness(qtbot)
        h.actuator_command_in_progress = True
        h.move_actuator("12", 0.5, 1, 1)
