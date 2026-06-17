# tests/integration/test_timer_dialog.py
import time

import pytest

from ui.dialogs.timer_dialog import TimerDialog


@pytest.mark.integration
class TestTimerDialogConstruction:
    """Tests for constructing the TimerDialog offscreen."""

    def test_constructs_without_crashing(self, qtbot):
        """The dialog can be created and registered with qtbot."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        assert dialog is not None

    def test_initial_label_text(self, qtbot):
        """The time label starts at the zeroed MM:SS placeholder."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        assert dialog.time_label.text() == "Time Remaining: 00:00"

    def test_window_title(self, qtbot):
        """The dialog uses the expected window title."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        assert dialog.windowTitle() == "Protocol Timer"

    def test_initial_protocol_state_unset(self, qtbot):
        """Protocol start time and duration are unset on construction."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        assert dialog.protocol_start_time is None
        assert dialog.protocol_duration is None


@pytest.mark.integration
class TestTimerDialogUpdateTime:
    """Tests for updating and formatting the displayed time."""

    def test_update_with_explicit_seconds_updates_label(self, qtbot):
        """Passing remaining_seconds updates the displayed label."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(125)
        assert dialog.time_label.text() == "Time Remaining: 02:05"

    def test_update_formats_as_mm_ss(self, qtbot):
        """Time is zero-padded to MM:SS."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(5)
        assert dialog.time_label.text() == "Time Remaining: 00:05"

    def test_update_formats_minutes_over_ten(self, qtbot):
        """Minutes beyond ten are rendered without truncation."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(15 * 60 + 42)  # 942 seconds -> 15:42
        assert dialog.time_label.text() == "Time Remaining: 15:42"

    def test_update_exact_minute(self, qtbot):
        """A whole-minute value shows zero seconds."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(180)
        assert dialog.time_label.text() == "Time Remaining: 03:00"

    def test_update_with_zero(self, qtbot):
        """Zero seconds renders as 00:00."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(0)
        assert dialog.time_label.text() == "Time Remaining: 00:00"

    def test_update_with_float_seconds_truncated(self, qtbot):
        """Float input is coerced to an integer number of seconds."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(90.9)
        assert dialog.time_label.text() == "Time Remaining: 01:30"

    def test_update_with_no_args_and_no_state(self, qtbot):
        """With no args and no protocol state, the label falls back to 00:00."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time()
        assert dialog.time_label.text() == "Time Remaining: 00:00"


@pytest.mark.integration
class TestTimerDialogColorCoding:
    """Tests for the remaining-time color coding behavior."""

    def test_normal_color_above_60(self, qtbot):
        """More than a minute remaining uses the default color."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(120)
        assert "#2c3e50" in dialog.time_label.styleSheet()

    def test_low_color_between_30_and_60(self, qtbot):
        """Between 30 and 60 seconds uses the orange 'low' color."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(45)
        assert "#f39c12" in dialog.time_label.styleSheet()

    def test_critical_color_at_or_below_30(self, qtbot):
        """At or below 30 seconds uses the red 'critical' color."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.update_time(15)
        assert "#e74c3c" in dialog.time_label.styleSheet()


@pytest.mark.integration
class TestTimerDialogProtocolTime:
    """Tests for the protocol-time initialization and countdown."""

    def test_initialize_protocol_time_sets_state(self, qtbot):
        """initialize_protocol_time stores the start time and duration."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        start = time.time()
        dialog.initialize_protocol_time(start, 300)
        assert dialog.protocol_start_time == start
        assert dialog.protocol_duration == 300

    def test_initialize_protocol_time_updates_label(self, qtbot):
        """Initializing with a fresh start time shows roughly the full duration."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.initialize_protocol_time(time.time(), 300)
        # Almost no time has elapsed, so it should read near 05:00.
        assert dialog.time_label.text() in (
            "Time Remaining: 05:00",
            "Time Remaining: 04:59",
        )

    def test_update_time_from_state_counts_down(self, qtbot):
        """update_time() derives remaining seconds from stored state."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        # Start 100 seconds ago with a 300s duration -> ~200s remaining.
        dialog.initialize_protocol_time(time.time() - 100, 300)
        dialog.update_time()
        assert dialog.time_label.text() in (
            "Time Remaining: 03:20",
            "Time Remaining: 03:19",
        )

    def test_update_time_from_state_clamps_at_zero(self, qtbot):
        """Elapsed beyond the duration clamps remaining time to 00:00."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        # Started well past the duration -> should not go negative.
        dialog.initialize_protocol_time(time.time() - 600, 300)
        dialog.update_time()
        assert dialog.time_label.text() == "Time Remaining: 00:00"


@pytest.mark.integration
class TestTimerDialogShowHide:
    """Tests that showing and hiding the dialog does not crash."""

    def test_show_and_close_without_crashing(self, qtbot):
        """Showing then closing the dialog (no parent) does not raise."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.isVisible()
        dialog.close()
        assert not dialog.isVisible()

    def test_show_event_with_parent_state_initializes(self, qtbot):
        """showEvent pulls protocol state from a parent that exposes it."""

        class _Parent(TimerDialog):
            """A stand-in parent that carries protocol timing attributes."""

        parent = _Parent()
        qtbot.addWidget(parent)
        parent.protocol_start_time = time.time()
        parent.protocol_duration = 300

        dialog = TimerDialog(parent=parent)
        qtbot.addWidget(dialog)
        dialog.show()
        # showEvent should have initialized the child's state from the parent.
        assert dialog.protocol_duration == 300
        assert dialog.protocol_start_time == parent.protocol_start_time
        dialog.close()

    def test_show_event_without_parent_state_stays_unset(self, qtbot):
        """showEvent with no parent leaves protocol state untouched."""
        dialog = TimerDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        assert dialog.protocol_start_time is None
        assert dialog.protocol_duration is None
        dialog.close()
