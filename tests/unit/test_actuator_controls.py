# tests/unit/test_actuator_controls.py
"""
Unit tests for KneeSpa actuator-movement and safety controls.

These tests exercise three methods of the (very large) ``KneeSpa``
``QMainWindow`` *without* constructing the window. Each target method is called
UNBOUND against a lightweight stub ``self`` (a ``MagicMock``) that carries only
the attributes the method actually reads. This keeps the tests fast,
deterministic and Windows-runnable.

Methods under test:
  * ``move_actuator(actuator, step, speed_factor, direction)`` -- position
    clamping to configured limits and the exact serial command emitted at the
    boundaries (below-min, above-max, in-range) for each actuator.
  * ``emergency_stop_clicked(event)`` -- emits the ``X`` (stop-all) command and
    schedules the staged shutdown.
  * ``_confirm_mid_protocol_change()`` -- the non-interactive return contract of
    the mid-protocol safety confirmation dialog.

Per the medical-device test policy, these tests assert the CURRENT behavior of
``kneespa.py`` only; they never modify production code.
"""

from unittest.mock import MagicMock, patch

import pytest

import kneespa
from kneespa import KneeSpa
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


def make_kneespa_stub(**positions):
    """
    Build a minimal stub ``self`` for ``move_actuator``.

    Only the attributes read by ``move_actuator`` are populated:
      * actuator id strings, a mocked ``arduino`` (records ``.send`` calls),
      * the three current-position attributes,
      * a default-populated ``config`` (for the lateral ``CMarks`` lookup),
      * stubbed UI widgets / loading spinner / control toggles.
    """
    config = Configuration()
    config._set_default_c_marks()
    config._set_default_a_marks()
    config._set_default_b_marks()

    stub = MagicMock()
    stub.actuator_a = ACTUATOR_A
    stub.actuator_b = ACTUATOR_B
    stub.actuator_c = ACTUATOR_C

    stub.arduino = MagicMock()
    stub.config = config

    stub.horizontal_flexion_position = positions.get("horizontal", 0)
    stub.axial_flexion_position = positions.get("axial", 0)
    stub.lateral_flexion_position = positions.get("lateral", 0)

    # UI widgets / helpers the method touches are MagicMocks by default
    # because ``stub`` is itself a MagicMock; ``stub.ui`` autocreates children.
    return stub


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
        """In-range move sends ``A13<inches>`` and advances the position."""
        # Start at 0; slow step (speed_factor <= 4) is 5, direction +1 -> 5 deg.
        stub = make_kneespa_stub(horizontal=0)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        # inches = abs((pos + 25) / 5) = abs((5 + 25) / 5) = 6.0
        stub.arduino.send.assert_called_once_with(f"A{ACTUATOR_B}6.0")
        assert stub.horizontal_flexion_position == 5

    def test_fast_speed_uses_larger_step(self):
        """speed_factor > 4 uses a step of 10 degrees."""
        stub = make_kneespa_stub(horizontal=-25)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "5", 1)
        # -25 + 10 = -15 -> inches = abs((-15 + 25) / 5) = 2.0
        stub.arduino.send.assert_called_once_with(f"A{ACTUATOR_B}2.0")
        assert stub.horizontal_flexion_position == -15

    def test_at_max_boundary_is_inclusive(self):
        """new_position exactly == max is allowed (limit check is strict >)."""
        # Start at 0, slow step 5 -> new_position 5 == HORIZONTAL_MAX_DEGREES.
        assert HORIZONTAL_MAX_DEGREES == 5
        stub = make_kneespa_stub(horizontal=0)
        KneeSpa.move_actuator(stub, ACTUATOR_B, None, "1", 1)
        stub.arduino.send.assert_called_once()
        assert stub.horizontal_flexion_position == HORIZONTAL_MAX_DEGREES


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
        # CMarks["2.5"] == 1569 in the default configuration.
        stub = make_kneespa_stub(lateral=0)
        expected_pos = stub.config.CMarks["2.5"]
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", 1)
        stub.arduino.send.assert_called_once_with(f"K{expected_pos}")
        assert stub.lateral_flexion_position == 2.5

    def test_position_rounded_to_increment(self):
        """The new position is snapped to the nearest 2.5-degree increment."""
        # Start at 1.0; slow step 2.5 -> 3.5 -> rounds to 2.5 (nearest 2.5).
        stub = make_kneespa_stub(lateral=1.0)
        expected_pos = stub.config.CMarks["2.5"]
        KneeSpa.move_actuator(stub, ACTUATOR_C, None, "1", 1)
        stub.arduino.send.assert_called_once_with(f"K{expected_pos}")
        assert stub.lateral_flexion_position == 2.5


@pytest.mark.unit
class TestEmergencyStop:
    """emergency_stop_clicked safety behavior."""

    def test_sends_stop_command(self):
        """Emergency stop must emit the ``X`` (stop-all) serial command."""
        stub = MagicMock()
        stub.arduino = MagicMock()
        # stop_actuators is the real implementation; call it unbound so the
        # ``X`` command actually reaches the mocked arduino.
        stub.stop_actuators = lambda: KneeSpa.stop_actuators(stub)

        with patch.object(kneespa, "QTimer") as mock_qtimer:
            KneeSpa.emergency_stop_clicked(stub, event=None)

        stub.arduino.send.assert_called_once_with("X")
        # The staged shutdown is scheduled (non-blocking) via QTimer.singleShot.
        mock_qtimer.singleShot.assert_called_once()

    def test_schedules_phase_two(self):
        """After the stop command, phase 2 is scheduled with a 1s delay."""
        stub = MagicMock()
        stub.arduino = MagicMock()
        stub.stop_actuators = MagicMock()

        with patch.object(kneespa, "QTimer") as mock_qtimer:
            KneeSpa.emergency_stop_clicked(stub, event=None)

        stub.stop_actuators.assert_called_once()
        args, _ = mock_qtimer.singleShot.call_args
        assert args[0] == 1000
        assert args[1] == stub._emergency_stop_phase2


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
