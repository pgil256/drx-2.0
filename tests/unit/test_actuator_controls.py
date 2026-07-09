# tests/unit/test_actuator_controls.py
"""Unit tests for KneeSpa actuator-movement and safety controls.

Union of the two development lines:
- the FAILSAFE base's control-gating regression tests (single supersedable
  enable timer; the lateral double-click lockup),
- the GUI line's move_actuator boundary/command tests, adapted to the base's
  guards (in-progress command debounce + marks_valid calibration gate), plus
  the emergency-stop scheduling and mid-protocol confirmation contracts.

Each target method is called UNBOUND against a lightweight stub ``self`` (a
``MagicMock``) that carries only the attributes the method actually reads, so
no Qt window / Arduino is constructed and the tests run on Windows.
"""
from unittest.mock import MagicMock, patch

import pytest
from PyQt5.QtWidgets import QPushButton

import kneespa
from kneespa import KneeSpa
import controllers.protocol_controller as pc_mod
from controllers.protocol_controller import ProtocolController
from config.config import Configuration
from config.constants import (
    ACTUATORS,
    AXIAL_MAX_INCHES,
    AXIAL_MIN_INCHES,
    HORIZONTAL_MAX_DEGREES,
    HORIZONTAL_MIN_DEGREES,
    LATERAL_MAX_DEGREES,
    LATERAL_MIN_DEGREES,
)

# Actuator IDs, mirroring KneeSpa.__init__ assignments.
ACTUATOR_A = ACTUATORS["AXIAL"]["ID"]        # "12" -- axial flexion (inches)
ACTUATOR_B = ACTUATORS["HORIZONTAL"]["ID"]   # "13" -- horizontal flexion (deg)
ACTUATOR_C = ACTUATORS["LATERAL"]["ID"]      # "14" -- lateral flexion (deg)


# ---------------------------------------------------------------------------
# Control gating (base regression: the lateral double-click control lockup)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# move_actuator boundary/command behavior (GUI line, adapted to base guards)
# ---------------------------------------------------------------------------
def make_kneespa_stub(**positions):
    """Build a minimal stub ``self`` for ``move_actuator``.

    Only the attributes read by ``move_actuator`` are populated: actuator id
    strings, a mocked ``arduino``, the current-position attributes, and a
    default-populated ``config`` with the base guards satisfied
    (actuator_command_in_progress False, marks_valid True)."""
    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()
    config.marks_valid = True  # the calibration gate is tested separately

    stub = MagicMock()
    stub.actuator_a = ACTUATOR_A
    stub.actuator_b = ACTUATOR_B
    stub.actuator_c = ACTUATOR_C
    stub.actuator_command_in_progress = False

    stub.arduino = MagicMock()
    stub.config = config

    stub.horizontal_flexion_position = positions.get("horizontal", 0)
    stub.axial_flexion_position = positions.get("axial", 0)
    stub.lateral_flexion_position = positions.get("lateral", 0)
    return stub


@pytest.mark.unit
class TestMoveActuatorGuards:
    """The base guards run before any motion state is touched."""

    def test_uncalibrated_marks_refuse_to_jog(self):
        """Generated default marks are fabricated geometry - jogging on them
        must warn and send nothing."""
        stub = make_kneespa_stub(horizontal=0)
        stub.config.marks_valid = False
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        stub.arduino.send.assert_not_called()
        stub._warn_uncalibrated.assert_called_once()


@pytest.mark.unit
class TestMoveActuatorHorizontal:
    """move_actuator for actuator B (horizontal flexion, degrees)."""

    def test_above_max_does_not_send(self):
        """Moving past HORIZONTAL_MAX_DEGREES is rejected with no command."""
        stub = make_kneespa_stub(horizontal=HORIZONTAL_MAX_DEGREES)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        stub.arduino.send.assert_not_called()
        # Position must be unchanged after a rejected move.
        assert stub.horizontal_flexion_position == HORIZONTAL_MAX_DEGREES

    def test_below_min_does_not_send(self):
        """Moving below HORIZONTAL_MIN_DEGREES is rejected with no command."""
        stub = make_kneespa_stub(horizontal=HORIZONTAL_MIN_DEGREES)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", -1)
        stub.arduino.send.assert_not_called()
        assert stub.horizontal_flexion_position == HORIZONTAL_MIN_DEGREES

    def test_in_range_sends_expected_command(self):
        """In-range move sends the calibrated absolute BMarks position."""
        # Start at 0; slow step (speed_factor <= 4) is 5, direction +1 -> 5 deg.
        stub = make_kneespa_stub(horizontal=0)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        stub.arduino.send.assert_called_once_with("I132280")
        assert stub.horizontal_flexion_position == 5

    def test_fast_speed_uses_larger_step(self):
        """speed_factor > 4 uses a step of 10 degrees."""
        stub = make_kneespa_stub(horizontal=-25)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "5", 1)
        # -25 + 10 = -15 -> calibrated BMarks position 760.
        stub.arduino.send.assert_called_once_with("I13760")
        assert stub.horizontal_flexion_position == -15

    def test_at_max_boundary_is_inclusive(self):
        """new_position exactly == max is allowed (limit check is strict >)."""
        # Start at 0, slow step 5 -> new_position 5 == HORIZONTAL_MAX_DEGREES.
        assert HORIZONTAL_MAX_DEGREES == 5
        stub = make_kneespa_stub(horizontal=0)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        stub.arduino.send.assert_called_once()
        assert stub.horizontal_flexion_position == HORIZONTAL_MAX_DEGREES

    def test_failed_send_does_not_change_displayed_position(self):
        stub = make_kneespa_stub(horizontal=-10)
        stub.arduino.send.return_value = False
        result = KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        assert result is False
        assert stub.horizontal_flexion_position == -10
        stub._reflect_setup.assert_not_called()
        stub.enable_actuator_controls.assert_called_once()


@pytest.mark.unit
class TestMoveActuatorAxial:
    """move_actuator for actuator A (axial flexion, inches)."""

    def test_above_max_does_not_send(self):
        """Moving past AXIAL_MAX_INCHES errors and sends no command."""
        stub = make_kneespa_stub(axial=AXIAL_MAX_INCHES)
        KneeSpa.move_actuator(stub, ACTUATOR_A, None, "1", 1)
        stub.arduino.send.assert_not_called()
        stub._show_timed_error.assert_called_once()
        assert stub.axial_flexion_position == AXIAL_MAX_INCHES

    def test_below_min_does_not_send(self):
        """Moving below AXIAL_MIN_INCHES is rejected with no command."""
        stub = make_kneespa_stub(axial=AXIAL_MIN_INCHES)
        KneeSpa.move_actuator(stub, ACTUATOR_A, None, "1", -1)
        stub.arduino.send.assert_not_called()
        assert stub.axial_flexion_position == AXIAL_MIN_INCHES

    def test_in_range_sends_expected_command(self):
        """In-range move sends ``A12<pos:.1f>`` and advances the position."""
        # Start at 0; slow step is 0.5, direction +1 -> 0.5 inches.
        stub = make_kneespa_stub(axial=0)
        KneeSpa.move_actuator(stub, ACTUATOR_A, None, "1", 1)
        stub.arduino.send.assert_called_once_with("A120.5")
        assert stub.axial_flexion_position == 0.5

    def test_fast_speed_uses_larger_step(self):
        """speed_factor > 4 uses a step of 1.0 inch."""
        stub = make_kneespa_stub(axial=0)
        KneeSpa.move_actuator(stub, ACTUATOR_A, None, "5", 1)
        stub.arduino.send.assert_called_once_with("A121.0")
        assert stub.axial_flexion_position == 1.0


@pytest.mark.unit
class TestMoveActuatorLateral:
    """move_actuator for actuator C (lateral flexion, degrees)."""

    def test_above_max_does_not_send(self):
        """Moving past LATERAL_MAX_DEGREES errors and sends no command."""
        stub = make_kneespa_stub(lateral=LATERAL_MAX_DEGREES)
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", 1)
        stub.arduino.send.assert_not_called()
        stub._show_timed_error.assert_called_once()
        assert stub.lateral_flexion_position == LATERAL_MAX_DEGREES

    def test_below_min_does_not_send(self):
        """Moving below LATERAL_MIN_DEGREES errors and sends no command."""
        stub = make_kneespa_stub(lateral=LATERAL_MIN_DEGREES)
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", -1)
        stub.arduino.send.assert_not_called()
        stub._show_timed_error.assert_called_once()
        assert stub.lateral_flexion_position == LATERAL_MIN_DEGREES

    def test_in_range_sends_mapped_position_command(self):
        """In-range move maps degrees through CMarks and sends ``K<position>``."""
        # Start at 0; slow step is 2.5, direction +1 -> 2.5 deg.
        stub = make_kneespa_stub(lateral=0)
        expected_pos = int(stub.config.CMarks["2.5"])
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", 1)
        stub.arduino.send.assert_called_once_with(f"K{expected_pos}")
        assert stub.lateral_flexion_position == 2.5


@pytest.mark.unit
class TestLegLengthBounds:
    @staticmethod
    def _stub(position):
        stub = MagicMock()
        stub.leg_length = position
        stub.LEG_LENGTH_MIN = 0.0
        stub.LEG_LENGTH_MAX = 6.0
        stub.arduino.send.return_value = True
        return stub

    def test_forward_at_max_sends_nothing(self):
        stub = self._stub(6.0)
        with patch.object(kneespa.GPIO, "output") as gpio_output:
            assert KneeSpa.forward_button_clicked(stub) is False
        gpio_output.assert_not_called()
        stub.arduino.send.assert_not_called()

    def test_reverse_at_min_sends_nothing(self):
        stub = self._stub(0.0)
        with patch.object(kneespa.GPIO, "output") as gpio_output:
            assert KneeSpa.reverse_button_clicked(stub) is False
        gpio_output.assert_not_called()
        stub.arduino.send.assert_not_called()

    def test_fast_forward_at_max_restores_without_spinner(self):
        stub = self._stub(6.0)
        assert KneeSpa.forward_fast_button_clicked(stub) is False
        stub.loading_spinner.show.assert_not_called()

    def test_failed_leg_send_keeps_estimate(self):
        stub = self._stub(2.0)
        stub.arduino.send.return_value = False
        with patch.object(kneespa.GPIO, "output") as gpio_output:
            assert KneeSpa.forward_button_clicked(stub) is False
        assert stub.leg_length == 2.0
        gpio_output.assert_not_called()

    def test_position_rounded_to_increment(self):
        """The new position is snapped to the nearest 2.5-degree increment."""
        # Start at 1.0; slow step 2.5 -> 3.5 -> rounds to 2.5 (nearest 2.5).
        stub = make_kneespa_stub(lateral=1.0)
        expected_pos = int(stub.config.CMarks["2.5"])
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", 1)
        stub.arduino.send.assert_called_once_with(f"K{expected_pos}")
        assert stub.lateral_flexion_position == 2.5


@pytest.mark.unit
class TestEmergencyStop:
    """Emergency-stop delegation + the controller's staged shutdown.

    The GPIO-line ordering is pinned separately in test_estop_gpio.py."""

    def test_window_delegates_to_controller(self):
        stub = MagicMock()
        KneeSpa.emergency_stop_clicked(stub, event=None)
        stub.protocol.emergency_stop_clicked.assert_called_once_with(None)

    def test_sends_stop_command(self):
        """The controller chain must emit the ``X`` (stop-all) serial command
        through the real stop_actuators implementation."""
        stub = MagicMock()
        stub.arduino.send.return_value = True
        stub.stop_actuators = lambda: KneeSpa.stop_actuators(stub)
        controller = ProtocolController(stub)

        with patch.object(pc_mod, "QTimer") as mock_qtimer, \
                patch.object(pc_mod, "GPIO"):
            controller.emergency_stop_clicked(None)

        stub.arduino.send.assert_called_once_with("X")
        # The staged shutdown is scheduled (non-blocking) via QTimer.singleShot.
        mock_qtimer.singleShot.assert_called_once()

    def test_schedules_phase_two(self):
        """After the stop command, phase 2 is scheduled with a 1s delay."""
        stub = MagicMock()
        controller = ProtocolController(stub)

        with patch.object(pc_mod, "QTimer") as mock_qtimer, \
                patch.object(pc_mod, "GPIO"):
            controller.emergency_stop_clicked(None)

        stub.stop_actuators.assert_called_once()
        args, _ = mock_qtimer.singleShot.call_args
        assert args[0] == 1000
        assert args[1] == controller._emergency_stop_phase2


@pytest.mark.unit
class TestConfirmMidProtocolChange:
    """_confirm_mid_protocol_change non-interactive return contract."""

    def _make_stub(self, running, warned):
        stub = MagicMock()
        stub.protocol_running = running
        stub.mid_protocol_warning_shown = warned
        return stub

    def test_returns_true_when_not_running(self):
        """When no protocol is running, the change proceeds without prompting."""
        stub = self._make_stub(running=False, warned=False)
        with patch.object(kneespa, "QtWidgets") as mock_qtw:
            result = KneeSpa._confirm_mid_protocol_change(stub)
        assert result is True
        mock_qtw.QMessageBox.warning.assert_not_called()

    def test_returns_true_when_already_warned(self):
        """Once the warning has been shown, it is not shown again."""
        stub = self._make_stub(running=True, warned=True)
        with patch.object(kneespa, "QtWidgets") as mock_qtw:
            result = KneeSpa._confirm_mid_protocol_change(stub)
        assert result is True
        mock_qtw.QMessageBox.warning.assert_not_called()

    def test_returns_true_and_sets_flag_when_user_accepts(self):
        """Accepting (Ok) proceeds, marks the warning shown, re-enables controls."""
        stub = self._make_stub(running=True, warned=False)
        with patch.object(kneespa, "QtWidgets") as mock_qtw:
            # Integer sentinels so the method's ``Ok | Cancel`` bit-or works;
            # warning() returns Ok to simulate the user accepting.
            mock_qtw.QMessageBox.Ok = 0x0400
            mock_qtw.QMessageBox.Cancel = 0x00400000
            mock_qtw.QMessageBox.warning.return_value = mock_qtw.QMessageBox.Ok
            result = KneeSpa._confirm_mid_protocol_change(stub)
        assert result is True
        assert stub.mid_protocol_warning_shown is True
        stub.enable_actuator_controls.assert_called_once()
        stub.disable_actuator_controls.assert_not_called()

    def test_returns_false_when_user_cancels(self):
        """Cancelling backs out: returns False and disables controls."""
        stub = self._make_stub(running=True, warned=False)
        with patch.object(kneespa, "QtWidgets") as mock_qtw:
            mock_qtw.QMessageBox.Ok = 0x0400
            mock_qtw.QMessageBox.Cancel = 0x00400000
            mock_qtw.QMessageBox.warning.return_value = mock_qtw.QMessageBox.Cancel
            result = KneeSpa._confirm_mid_protocol_change(stub)
        assert result is False
        # The warning must not be marked shown when the user backs out.
        assert stub.mid_protocol_warning_shown is False
        stub.disable_actuator_controls.assert_called_once()
        stub.enable_actuator_controls.assert_not_called()
