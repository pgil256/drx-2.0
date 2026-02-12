# tests/integration/test_pressure_dialog.py
import pytest
from PyQt5.QtWidgets import QApplication

from ui.dialogs.pressure_dialog import PressureDialog


@pytest.mark.integration
class TestPressureDialogDisplay:
    """Tests for pressure dialog UI updates."""

    def test_initial_state(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        assert "0 lbs" in dialog.pressure_label.text()

    def test_update_shows_pressure(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(45.0)
        assert "45.0 lbs" in dialog.pressure_label.text()

    def test_green_under_50(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(30.0)
        style = dialog.pressure_label.styleSheet()
        assert "#27ae60" in style  # Green color

    def test_orange_between_50_and_70(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(55.0)
        style = dialog.pressure_label.styleSheet()
        assert "#f39c12" in style  # Orange color

    def test_red_above_70(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(75.0)
        style = dialog.pressure_label.styleSheet()
        assert "#e74c3c" in style  # Red color

    def test_small_change_not_updated(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(50.0)
        old_text = dialog.pressure_label.text()
        dialog.update_pressure(50.3)  # Change < 0.5
        assert dialog.pressure_label.text() == old_text

    def test_large_change_updated(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(50.0)
        dialog.update_pressure(51.0)  # Change >= 0.5
        assert "51.0 lbs" in dialog.pressure_label.text()

    def test_none_pressure_handled(self, qtbot):
        dialog = PressureDialog()
        qtbot.addWidget(dialog)
        dialog.update_pressure(None)
        # Should not crash
