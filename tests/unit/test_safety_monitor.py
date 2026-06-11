# tests/unit/test_safety_monitor.py
"""Unit tests for the extracted Pi-side safety supervision.

This is the 'table-top safety logic' the audit flagged as living in
0%-tested UI code; it now runs against a stub window.
"""
import pytest
from unittest.mock import MagicMock

from controllers.safety_monitor import SafetyMonitor
from config.constants import AXIAL_MAX, PRESSURE_MAX, LATERAL_MIN


class StubPanel:
    def __init__(self):
        self.pressures = []
        self.faults = []

    def update_pressure(self, pressure):
        self.pressures.append(pressure)

    def set_fault(self, reason):
        self.faults.append(reason)


class StubWindow:
    def __init__(self):
        self.treatment_panel = StubPanel()
        self.initial_setup_complete = True
        self.protocol_running = False
        self.worker = MagicMock()
        self.logger = MagicMock()
        self.config = MagicMock()
        self.config.AMarks = {"0.0": 160}
        self.config.BMarks = {"0.0": 1900}
        self.alerts = []
        self.timed_errors = []
        self.states = []
        self.resets = 0
        self.stops = 0

    def _show_safety_alert(self, message):
        self.alerts.append(message)

    def _show_timed_error(self, message):
        self.timed_errors.append(message)

    def set_protocol_state(self, state):
        self.states.append(state)

    def reset_arduino(self):
        self.resets += 1

    def stop_actuators(self):
        self.stops += 1


@pytest.fixture
def monitor():
    window = StubWindow()
    return SafetyMonitor(window), window


@pytest.mark.unit
class TestStatusChecks:
    def test_normal_status_passes_and_feeds_panel(self, monitor):
        sm, w = monitor
        assert sm.on_status(1000, 2000, 1200, 40.0) is True
        assert w.treatment_panel.pressures == [40.0]
        assert w.resets == 0

    def test_pressure_over_limit_triggers_stop(self, monitor):
        sm, w = monitor
        assert sm.on_status(1000, 2000, 1200, PRESSURE_MAX + 5) is False
        assert w.states == ["fault"]
        assert w.worker.stop.called
        assert w.resets == 1
        assert w.initial_setup_complete is False
        assert any("limit exceeded" in a for a in w.alerts)

    def test_axial_over_limit_triggers_stop(self, monitor):
        sm, w = monitor
        assert sm.on_status(AXIAL_MAX + 100, 2000, 1200, 10.0) is False
        assert w.resets == 1

    def test_lateral_under_limit_triggers_stop(self, monitor):
        sm, w = monitor
        assert sm.on_status(1000, 2000, LATERAL_MIN - 50, 10.0) is False
        assert any("Lateral" in a for a in w.alerts)

    def test_checks_gated_until_setup_complete(self, monitor):
        """During resets the values are transient; only the panel updates."""
        sm, w = monitor
        w.initial_setup_complete = False
        assert sm.on_status(AXIAL_MAX + 100, 0, 0, 999.0) is True
        assert w.resets == 0
        assert w.treatment_panel.pressures == [999.0]

    def test_no_worker_does_not_crash(self, monitor):
        sm, w = monitor
        w.worker = None
        assert sm.on_status(1000, 2000, 1200, PRESSURE_MAX + 5) is False
        assert w.resets == 1


@pytest.mark.unit
class TestFirmwareEvents:
    def test_busy_is_transient(self, monitor):
        sm, w = monitor
        sm.on_firmware_error("BUSY")
        assert w.states == []
        assert w.alerts == []

    def test_safety_stop_flags_worker_and_alerts(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        sm.on_firmware_error("Pressure limit exceeded")
        assert w.worker.is_running is False
        assert w.states == ["fault"]
        assert w.treatment_panel.faults == ["Pressure limit exceeded"]
        assert any("DEVICE SAFETY STOP" in a for a in w.alerts)

    def test_connection_lost_during_treatment(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        sm.on_connection_lost()
        assert w.states == ["fault"]
        assert w.treatment_panel.faults == ["CONNECTION LOST"]
        assert any("CONNECTION LOST" in a for a in w.alerts)
        assert w.resets == 1

    def test_connection_lost_idle_skips_alert(self, monitor):
        sm, w = monitor
        w.protocol_running = False
        sm.on_connection_lost()
        assert w.alerts == []
        assert w.resets == 1

    def test_zeros_mismatch_warns(self, monitor):
        sm, w = monitor
        sm.on_zeros_echo(160, 190)  # the classic truncation value
        assert any("Zero-mark mismatch" in e for e in w.timed_errors)

    def test_zeros_match_silent(self, monitor):
        sm, w = monitor
        sm.on_zeros_echo(160, 1900)
        assert w.timed_errors == []
