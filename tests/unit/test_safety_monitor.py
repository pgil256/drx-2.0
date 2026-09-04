# tests/unit/test_safety_monitor.py
"""Unit tests for the extracted Pi-side safety supervision.

This is the 'table-top safety logic' the audit flagged as living in
0%-tested UI code; it now runs against a stub window.
"""
import pytest
from unittest.mock import MagicMock

from controllers.safety_monitor import LIMIT_SETTLE_TOLERANCE, SafetyMonitor
from config.constants import (
    AXIAL_MAX,
    HORIZONTAL_MAX,
    HORIZONTAL_MIN,
    LATERAL_MIN,
    PRESSURE_MAX,
    PRESSURE_WARNING_MAX,
)


class StubPanel:
    def __init__(self):
        self.pressures = []
        self.faults = []
        self.warnings = []

    def update_pressure(self, pressure):
        self.pressures.append(pressure)

    def set_fault(self, reason):
        self.faults.append(reason)

    def set_warning(self, reason):
        self.warnings.append(reason)


class StubWindow:
    def __init__(self):
        self.treatment_panel = StubPanel()
        self.initial_setup_complete = True
        self.reset_in_progress = False
        self.protocol_running = False
        self.protocol_stop_requested = False
        self.protocol_state = "idle"
        self.worker = MagicMock()
        self.logger = MagicMock()
        self.config = MagicMock()
        self.config.AMarks = {"0.0": 160}
        self.config.BMarks = {"0.0": 1900}
        self.alerts = []
        self.alert_options = []
        self.timed_errors = []
        self.states = []
        self.resets = 0
        self.stops = 0

    def _show_safety_alert(self, message, **options):
        self.alerts.append(message)
        self.alert_options.append(options)

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

    def test_treatment_pressure_cap_is_below_warning_threshold(self, monitor):
        sm, w = monitor
        assert sm.on_status(1000, 2000, 1200, PRESSURE_MAX + 5) is True
        assert w.alerts == []
        assert w.treatment_panel.warnings == []

    def test_pressure_warning_requires_three_status_frames(self, monitor):
        sm, w = monitor

        pressure = PRESSURE_WARNING_MAX + 1
        assert sm.on_status(1000, 2000, 1200, pressure) is True
        assert sm.on_status(1000, 2000, 1200, pressure) is True
        assert w.alerts == []
        assert w.resets == 0

        assert sm.on_status(1000, 2000, 1200, pressure) is True
        assert w.resets == 0
        assert len(w.alerts) == 1
        assert "Pressure warning threshold exceeded" in w.alerts[0]
        assert w.treatment_panel.warnings
        assert w.states == []
        w.logger.warning.assert_called_once()

        # A sustained excursion warns once, not once per status frame.
        assert sm.on_status(1000, 2000, 1200, pressure) is True
        w.logger.warning.assert_called_once()
        assert len(w.alerts) == 1

    def test_normal_frame_clears_borderline_limit_count(self, monitor):
        sm, w = monitor

        pressure = PRESSURE_WARNING_MAX + 1
        assert sm.on_status(1000, 2000, 1200, pressure) is True
        assert sm.on_status(1000, 2000, 1200, PRESSURE_WARNING_MAX) is True
        assert sm.on_status(1000, 2000, 1200, pressure) is True
        assert sm.on_status(1000, 2000, 1200, pressure) is True

        assert w.alerts == []
        assert w.resets == 0

    def test_axial_over_limit_warns_without_stopping(self, monitor):
        sm, w = monitor
        assert sm.on_status(AXIAL_MAX + 100, 2000, 1200, 10.0) is True
        assert w.resets == 0
        assert w.states == []
        assert not w.worker.stop.called
        assert any("Axial position limit exceeded" in a for a in w.alerts)
        assert not any("Pressure" in a for a in w.alerts)

    def test_axial_and_pressure_both_over_limit_report_both(self, monitor):
        """When both trip at once the operator gets both messages, not one
        ambiguous combined alert."""
        sm, w = monitor
        pressure = PRESSURE_WARNING_MAX + 5
        assert sm.on_status(AXIAL_MAX + 100, 2000, 1200, pressure) is True
        assert len(w.alerts) == 1
        assert "Axial position limit exceeded" in w.alerts[0]
        assert "Pressure warning threshold exceeded" in w.alerts[0]
        assert w.resets == 0
        assert w.states == []
        w.logger.warning.assert_called_once()

    def test_lateral_under_limit_warns_without_stopping(self, monitor):
        sm, w = monitor
        beyond = LATERAL_MIN - LIMIT_SETTLE_TOLERANCE - 50  # past the settle band
        assert sm.on_status(1000, 2000, beyond, 10.0) is True
        assert sm.on_status(1000, 2000, beyond, 10.0) is True
        assert sm.on_status(1000, 2000, beyond, 10.0) is True
        assert any("Lateral" in a for a in w.alerts)
        assert w.states == []
        assert w.resets == 0

    # ----- legal moves must never be flagged by false limits -----
    def test_settling_just_past_a_limit_never_warns(self, monitor):
        """The -20 deg lateral mark IS LATERAL_MIN, so a legal move there
        settles a few counts past it; that used to warn after three frames."""
        sm, w = monitor
        for _ in range(10):
            assert sm.on_status(1000, 2000, LATERAL_MIN - 20, 10.0) is True
        assert w.alerts == []
        assert w.treatment_panel.warnings == []

    def test_horizontal_zero_is_legal(self, monitor):
        """BMarks puts the calibrated -25 deg mark at position 0."""
        sm, w = monitor
        for _ in range(5):
            assert sm.on_status(1000, 0, 1200, 10.0) is True
        assert w.alerts == []

    def test_bounds_follow_calibrated_tables(self, monitor):
        sm, w = monitor
        w.config.BMarks = {"-25": 0, "-20": 580, "-10": 1340, "0.0": 1759, "5": 2280}
        w.config.CMarks = {"-20.0": 500, "0.0": 1450, "20.0": 2400}

        # Everything the host can command through the tables is legal...
        for pos_b, pos_c in ((0, 500), (2280, 2400), (2280 + 40, 2400 + 40)):
            for _ in range(4):
                assert sm.on_status(1000, pos_b, pos_c, 10.0) is True
        assert w.alerts == []

        # ...and positions past the table (+tolerance) are still caught.
        for _ in range(3):
            sm.on_status(1000, 2280 + LIMIT_SETTLE_TOLERANCE + 30, 1450, 10.0)
        assert any("Horizontal position limit exceeded" in a for a in w.alerts)

    def test_static_constants_are_the_fallback(self, monitor):
        sm, w = monitor
        w.config.BMarks = {"0.0": 1900}  # one mark: unusable as a range
        lo, hi = sm._position_bounds("horizontal")
        assert (lo, hi) == (
            HORIZONTAL_MIN - LIMIT_SETTLE_TOLERANCE,
            HORIZONTAL_MAX + LIMIT_SETTLE_TOLERANCE,
        )

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
        assert sm.on_status(
            1000, 2000, 1200, PRESSURE_WARNING_MAX + 5
        ) is True
        assert w.resets == 0


@pytest.mark.unit
class TestFirmwareEvents:
    def test_busy_is_transient(self, monitor):
        sm, w = monitor
        sm.on_firmware_error("BUSY")
        assert w.states == []
        assert w.alerts == []

    def test_firmware_warning_during_startup_is_log_only(self, monitor):
        sm, w = monitor
        w.initial_setup_complete = False

        sm.on_firmware_warning("Host heartbeat lost")

        assert w.alerts == []
        assert w.treatment_panel.warnings == []
        w.logger.warning.assert_called_once_with(
            "Firmware warning during initialization (not shown): %s",
            "Host heartbeat lost",
        )

    def test_firmware_warning_during_reset_is_log_only(self, monitor):
        sm, w = monitor
        w.reset_in_progress = True

        sm.on_firmware_warning("Motor stalled")

        assert w.alerts == []
        assert w.treatment_panel.warnings == []

    @pytest.mark.parametrize(
        "message",
        ["Heartbeat lost", "Host heartbeat lost", "Motor stalled"],
    )
    def test_legacy_error_prefix_startup_advisory_is_log_only(
        self,
        monitor,
        message,
    ):
        sm, w = monitor
        w.initial_setup_complete = False

        sm.on_firmware_error(message)

        assert w.alerts == []
        assert w.treatment_panel.warnings == []

    def test_firmware_warning_after_setup_remains_visible(self, monitor):
        sm, w = monitor

        sm.on_firmware_warning("Motor stalled")

        assert w.treatment_panel.warnings == ["Motor stalled"]
        assert len(w.alerts) == 1

    def test_no_pressure_progress_warns_without_interrupting(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        w.protocol_state = "running"
        running_state = w.worker.is_running

        sm.on_firmware_error("No pressure progress")

        assert w.worker.is_running is running_state
        assert w.stops == 0
        assert w.states == []
        assert len(w.alerts) == 1
        assert w.timed_errors == []
        assert w.treatment_panel.faults == []
        assert w.treatment_panel.warnings == ["No pressure progress"]
        assert w.resets == 0
        w.logger.warning.assert_called_once()

    def test_pressure_limit_firmware_report_is_warning_only(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        running_state = w.worker.is_running

        sm.on_firmware_error("Pressure limit exceeded")

        assert w.worker.is_running is running_state
        assert w.states == []
        assert w.treatment_panel.warnings == ["Pressure limit exceeded"]
        assert len(w.alerts) == 1
        assert w.timed_errors == []
        w.logger.warning.assert_called_once()

    def test_invalid_pressure_during_intentional_stop_is_log_only(self, monitor):
        """A rejected P0 cleanup must not raise a second safety-stop popup."""
        sm, w = monitor
        w.protocol_running = True
        w.protocol_stop_requested = True
        w.protocol_state = "stopping"

        sm.on_firmware_error("Invalid P value")

        assert w.alerts == []
        assert w.timed_errors == []
        assert w.states == []
        assert w.treatment_panel.faults == []
        w.logger.warning.assert_called_once()

    def test_invalid_pressure_during_treatment_is_command_fault(self, monitor):
        """A real command rejection remains visible without claiming a trip."""
        sm, w = monitor
        w.protocol_running = True
        w.protocol_state = "running"

        sm.on_firmware_error("Invalid P value")

        assert w.worker.is_running is False
        assert w.stops == 1
        assert w.states == ["fault"]
        assert w.treatment_panel.faults == [
            "COMMAND REJECTED: Invalid P value"
        ]
        assert any("rejected a command" in error for error in w.timed_errors)
        assert w.alerts == []

    def test_position_read_failure_is_command_fault_not_safety_trip(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        w.protocol_state = "running"

        sm.on_firmware_error("Position read failed")

        assert w.stops == 1
        assert w.states == ["fault"]
        assert w.treatment_panel.faults == [
            "COMMAND REJECTED: Position read failed"
        ]
        assert any("rejected a command" in error for error in w.timed_errors)
        assert w.alerts == []

    def test_connection_lost_during_treatment(self, monitor):
        sm, w = monitor
        w.protocol_running = True
        running_state = w.worker.is_running
        sm.on_connection_lost()
        assert w.worker.is_running is running_state
        assert w.states == []
        assert w.treatment_panel.faults == []
        assert w.treatment_panel.warnings
        assert any("CONNECTION LOST" in a for a in w.alerts)
        assert w.resets == 0

    def test_connection_lost_idle_is_warning_only(self, monitor):
        sm, w = monitor
        w.protocol_running = False
        sm.on_connection_lost()
        assert any("CONNECTION LOST" in a for a in w.alerts)
        assert w.states == []
        assert w.resets == 0

    def test_zeros_mismatch_warns(self, monitor):
        sm, w = monitor
        sm.on_zeros_echo(160, 190)  # the classic truncation value
        assert any("Zero-mark mismatch" in e for e in w.timed_errors)

    def test_zeros_match_silent(self, monitor):
        sm, w = monitor
        sm.on_zeros_echo(160, 1900)
        assert w.timed_errors == []
