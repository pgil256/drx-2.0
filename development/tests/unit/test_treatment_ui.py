# development/tests/unit/test_treatment_ui.py
"""Tests for the always-visible treatment banner and the protocol
lifecycle state machine that drives it."""
from types import SimpleNamespace

import pytest
from PyQt5.QtWidgets import QWidget

from ui.widgets.treatment_status_panel import TreatmentStatusPanel
from controllers.protocol_controller import ProtocolController
from ui.screens.treatment import TreatmentScreen


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

    def test_device_warning_is_orange_and_uses_warning_copy(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_warning("Pressure limit exceeded")
        assert panel.phase_label.text() == (
            "DEVICE SAFETY WARNING: Pressure limit exceeded"
        )
        from ui.theme import resolve
        assert resolve("--banner-warning") in panel.styleSheet()
        assert not panel.pressure_label.isVisibleTo(panel)  # not a pressure event
        assert panel.dismiss_button.isVisible()

    def test_suppressed_banner_never_shows_during_protocol(self, qtbot):
        """With a protocol active the banner stays off-screen for every
        mode, while its state keeps tracking so nothing is lost."""
        state = {"protocol": "running"}
        panel = TreatmentStatusPanel(
            suppress_when=lambda: state["protocol"] != "idle"
        )
        qtbot.addWidget(panel)
        panel.set_running(target_pressure=50, duration_s=720)
        assert not panel.isVisible()
        assert panel.phase_label.text() == "TREATMENT RUNNING"
        panel.set_warning("Lateral position limit exceeded")
        assert not panel.isVisible()
        panel.set_stopping()
        assert not panel.isVisible()
        state["protocol"] = "fault"
        panel.set_fault("Pressure limit exceeded")
        assert not panel.isVisible()
        assert "Pressure limit exceeded" in panel.phase_label.text()

    def test_suppression_hides_a_banner_left_over_from_idle(self, qtbot):
        """An idle-time advisory banner must not linger once a run starts."""
        state = {"protocol": "idle"}
        panel = TreatmentStatusPanel(
            suppress_when=lambda: state["protocol"] != "idle"
        )
        qtbot.addWidget(panel)
        panel.set_warning("Advisory only")
        assert panel.isVisible()
        state["protocol"] = "starting"
        panel.set_running(target_pressure=40, duration_s=60)
        assert not panel.isVisible()
        state["protocol"] = "idle"
        panel.set_warning("Advisory again")
        assert panel.isVisible()

    def test_dismiss_idle_warning_hides_banner(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_warning("Advisory only")

        panel.dismiss_button.click()

        assert not panel.isVisible()

    def test_dismiss_running_warning_restores_treatment_banner(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(50, 720)
        panel.set_phase("RAMPING PRESSURE")
        panel.set_warning("Advisory only")
        panel.update_remaining(715)

        panel.dismiss_button.click()

        assert panel.isVisible()
        assert panel.phase_label.text() == "RAMPING PRESSURE"
        assert panel.time_label.text() == "11:55 left"
        assert panel.stop_button.isEnabled()
        assert not panel.dismiss_button.isVisible()

    def test_fault_cannot_be_dismissed_or_replaced_by_warning(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_fault("Pressure limit exceeded")

        panel.set_warning("Advisory only")
        panel.dismiss_warning()

        assert panel.isVisible()
        assert panel.phase_label.text() == (
            "SAFETY STOP: Pressure limit exceeded"
        )
        assert not panel.dismiss_button.isVisible()

    def test_stop_button_emits_signal(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(40, 60)
        assert panel.stop_button.text() == "EMERGENCY STOP"
        with qtbot.waitSignal(panel.stop_requested, timeout=1000):
            panel.stop_button.click()

    def test_stopping_keeps_emergency_stop_available(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_stopping()
        assert panel.stop_button.isEnabled()

    def test_idle_resets(self, qtbot):
        panel = TreatmentStatusPanel()
        qtbot.addWidget(panel)
        panel.set_running(40, 60)
        panel.set_idle()
        assert not panel.isVisible()
        assert panel.pressure_label.text() == "-- lbs"


class _StubWindow:
    """Window surface the ProtocolController's state machine touches."""

    def __init__(self, qtbot):
        self.protocol_state = "idle"
        self.protocol_running = False
        self.reset_in_progress = False
        self.errors = []
        self.shell = SimpleNamespace(treatment=TreatmentScreen())
        self.shell.treatment.set_device_status("Ready", "Review settings.", True)
        qtbot.addWidget(self.shell.treatment)
        self.treatment_panel = TreatmentStatusPanel()
        qtbot.addWidget(self.treatment_panel)

    def _show_timed_error(self, message):
        self.errors.append(message)


class StateMachineHarness:
    """ProtocolController over a stub window, exposing test conveniences."""

    def __init__(self, qtbot):
        self.window = _StubWindow(qtbot)
        self.controller = ProtocolController(self.window)
        self.view = self.window.shell.treatment
        self.treatment_panel = self.window.treatment_panel

    @property
    def protocol_running(self):
        return self.window.protocol_running

    @property
    def errors(self):
        return self.window.errors

    def set_protocol_state(self, state):
        self.controller.set_state(state)

    def _block_active_treatment_exit(self):
        return self.controller.block_active_treatment_exit()


@pytest.mark.unit
class TestProtocolStateMachine:
    def test_running_state_drives_button(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("running")
        assert not h.view._start_btn.isEnabled()
        assert h.view._pause_btn.isEnabled()
        assert h.protocol_running is True

    def test_idle_state_resets_button_and_panel(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("running")
        h.treatment_panel.set_running(40, 60)
        h.set_protocol_state("idle")
        assert h.view._start_btn.text() == "START"
        assert h.view._start_btn.isEnabled()
        assert h.protocol_running is False
        assert not h.treatment_panel.isVisible()

    def test_stopping_disables_start_button(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("stopping")
        assert not h.view._start_btn.isEnabled()
        assert h.protocol_running is True  # still owns the hardware

    def test_idle_during_reset_keeps_start_disabled(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.window.reset_in_progress = True
        h.set_protocol_state("idle")
        assert not h.view._start_btn.isEnabled()

    def test_fault_keeps_banner_and_requires_recovery(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.treatment_panel.set_fault("test")
        h.set_protocol_state("fault")
        assert not h.view._start_btn.isEnabled()
        assert h.protocol_running is False

    def test_logout_and_exit_blocked_while_active(self, qtbot):
        h = StateMachineHarness(qtbot)
        for state in ("starting", "running", "stopping"):
            h.set_protocol_state(state)
            assert h._block_active_treatment_exit() is True
        assert h.errors  # operator was told why

    def test_logout_and_exit_allowed_when_idle_or_fault(self, qtbot):
        h = StateMachineHarness(qtbot)
        h.set_protocol_state("idle")
        assert h._block_active_treatment_exit() is False
        h.set_protocol_state("fault")
        assert h._block_active_treatment_exit() is False
