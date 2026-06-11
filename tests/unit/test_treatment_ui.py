# tests/unit/test_treatment_ui.py
"""Tests for the always-visible treatment banner and the protocol
lifecycle state machine that drives it."""
import pytest
from PyQt5.QtWidgets import QPushButton, QWidget

from ui.widgets.treatment_status_panel import TreatmentStatusPanel
from controllers.protocol_controller import ProtocolController
from config.constants import BUTTON_STYLES  # noqa: F401  (style sanity)


@pytest.mark.unit
class TestTreatmentStatusPanel:
    def test_starts_hidden(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        assert not panel.isVisible()

    def test_running_state_shows_values(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(target_pressure=50, duration_s=720)
        assert panel.phase_label.text() == "TREATMENT RUNNING"
        assert "50" in panel.target_label.text()
        assert panel.time_label.text() == "12:00 left"
        assert panel.stop_button.isEnabled()

    def test_pressure_updates_show_measured_value(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.update_pressure(42.34)
        assert panel.pressure_label.text() == "42.3 lbs"

    def test_remaining_time_clamps_at_zero(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.update_remaining(-5)
        assert panel.time_label.text() == "0:00 left"

    def test_fault_state_persists_message(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_fault("Pressure limit exceeded")
        assert "SAFETY STOP" in panel.phase_label.text()
        assert "Pressure limit exceeded" in panel.phase_label.text()

    def test_stop_button_emits_signal(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(40, 60)
        with qtbot.waitSignal(panel.stop_requested, timeout=1000):
            panel.stop_button.click()

    def test_stopping_disables_stop_button(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_stopping()
        assert not panel.stop_button.isEnabled()

    def test_idle_resets(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(40, 60)
        panel.set_idle()
        assert not panel.isVisible()
        assert panel.pressure_label.text() == "-- lbs"


class _UiStub:
    def __init__(self, start_button):
        self.start_button = start_button


class _StubWindow:
    """Window surface the ProtocolController's state machine touches."""

    def __init__(self, qtbot):
        self.protocol_state = "idle"
        self.protocol_running = False
        self.errors = []
        button = QPushButton("Start")
        qtbot.addWidget(button)
        self.ui = _UiStub(button)
        self.treatment_panel = TreatmentStatusPanel()
        qtbot.addWidget(self.treatment_panel)

    def _show_timed_error(self, message):
        self.errors.append(message)


class StateMachineHarness:
    """ProtocolController over a stub window, exposing test conveniences."""

    def __init__(self, qtbot):
        self.window = _StubWindow(qtbot)
        self.controller = ProtocolController(self.window)
        self.ui = self.window.ui
        self.treatment_panel = self.window.treatment_panel

    @property
    def protocol_running(self):
        return self.window.protocol_running

    @property
    def errors(self):
        return self.window.errors

    def set_protocol_state(self, state):
        self.controller.set_state(state)

    def _block_nav_during_treatment(self):
        return self.controller.block_nav()


@pytest.mark.unit
class TestProtocolStateMachine:
    def test_running_state_drives_button(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("running")
        assert h.ui.start_button.text() == "Stop"
        assert h.protocol_running is True

    def test_idle_state_resets_button_and_panel(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("running")
        h.treatment_panel.set_running(40, 60)
        h.set_protocol_state("idle")
        assert h.ui.start_button.text() == "Start"
        assert h.protocol_running is False
        assert not h.treatment_panel.isVisible()

    def test_stopping_disables_start_button(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("stopping")
        assert not h.ui.start_button.isEnabled()
        assert h.protocol_running is True  # still owns the hardware

    def test_fault_keeps_banner_but_allows_restart(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.treatment_panel.set_fault("test")
        h.set_protocol_state("fault")
        assert h.ui.start_button.isEnabled()
        assert h.protocol_running is False

    def test_nav_blocked_while_active(self, qtbot):
        h = StateMachineHarness(qtbot)
        for state in ("starting", "running", "stopping"):
            h.set_protocol_state(state)
            assert h._block_nav_during_treatment() is True
        assert h.errors  # operator was told why

    def test_nav_allowed_when_idle_or_fault(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("idle")
        assert h._block_nav_during_treatment() is False
        h.set_protocol_state("fault")
        assert h._block_nav_during_treatment() is False
