"""Treatment inputs must fit inside their panels at touchscreen resolution."""

from typing import Tuple

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QApplication, QLabel, QSlider
from pytestqt.qtbot import QtBot

from ui.app_shell import AppShell


pytestmark = pytest.mark.integration


@pytest.mark.parametrize("size", [(1360, 768), (1366, 768), (1352, 756)])
@pytest.mark.parametrize("protocol", [1, 2, 3, 4])
def test_settings_are_fully_visible(
    themed_app: QApplication, qtbot: QtBot, size: Tuple[int, int], protocol: int,
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(*size)
    shell.set_user("Simulator Administrator")
    shell.navigate("protocols")
    view = shell.treatment
    view.set_patient("Alexandria Elizabeth Montgomery-Wellington de la Cruz Example Patient")
    view.set_cloud_status(
        "Upload failed: record retained; authentication required before retrying."
    )
    view.select_protocol(protocol)
    shell.show()
    qtbot.wait(1)

    assert not any(slider.isVisible() for slider in view.findChildren(QSlider))
    assert all(button.isVisible() for button in view._proto_buttons.values())
    assert view._monitor_panel.width() == view._settings_panel.width()
    assert view._monitor_panel.geometry().bottom() < view._settings_panel.y()
    assert view._monitor_panel.height() > view._settings_panel.height()
    edit = view._edit_treatment_button
    assert edit.height() >= 56
    assert edit.width() >= 180
    assert view._pressure_stat.y() == view._time_stat.y()
    assert view._pressure_stat.x() < view._time_stat.x()
    summary_tops = set()
    for key, row in view._summary_rows.items():
        if row.isVisible():
            bounds = row.rect().translated(row.mapTo(shell, QPoint()))
            assert shell.rect().contains(bounds), key
            summary_tops.add(bounds.top())
    assert len(summary_tops) == 2
    for panel in (view._monitor_panel, view._settings_panel):
        for label in panel.findChildren(QLabel):
            if label.isVisibleTo(panel):
                assert label.width() >= label.minimumSizeHint().width(), label.text()
                assert label.height() >= label.minimumSizeHint().height(), label.text()
    view.open_treatment_editor()
    qtbot.wait(1)
    editor = view._editor
    assert editor.height() <= size[1] - 40
    for key, control in view._settings.items():
        if not control.isVisibleTo(editor):
            continue
        children = [control._left_btn, control._right_btn]
        children += control.findChildren(QLabel) + control.findChildren(QSlider)
        for child in children:
            ancestor = child.parentWidget()
            while ancestor is not None:
                bounds = child.rect().translated(child.mapTo(ancestor, QPoint()))
                assert ancestor.rect().contains(bounds), (
                    key, type(child).__name__, bounds, ancestor.rect()
                )
                if ancestor is editor:
                    break
                ancestor = ancestor.parentWidget()
        for button in (control._left_btn, control._right_btn):
            assert button.width() >= 64 and button.height() >= 64

    for label in editor.findChildren(QLabel):
        if label.isVisibleTo(editor):
            assert label.height() >= label.minimumSizeHint().height(), label.text()

    stop = view._estop_btn
    assert stop.isEnabled() and stop.height() >= 72
    assert shell.rect().contains(stop.rect().translated(stop.mapTo(shell, QPoint())))


@pytest.mark.parametrize("size", [(1360, 768), (1366, 768), (1352, 756)])
def test_switching_protocol_keeps_panels_and_run_buttons_in_place(
    themed_app: QApplication, qtbot: QtBot, size: Tuple[int, int],
) -> None:
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(*size)
    shell.set_user("Operator")
    shell.navigate("protocols")
    shell.show()
    view = shell.treatment
    geometry = None
    for protocol in (1, 2, 3, 4, 1):
        qtbot.mouseClick(view._proto_buttons[protocol], Qt.LeftButton)
        assert not view._editor.isVisible()
        qtbot.wait(10)
        widgets = (view._edit_treatment_button, view._readiness, view._pressure_stat,
                   view._start_btn, view._pause_btn, view._estop_btn,
                   *view._summary_rows.values())
        current = [widget.rect().translated(widget.mapTo(shell, QPoint()))
                   for widget in widgets]
        if geometry is None:
            geometry = current
        assert current == geometry, protocol
        assert view._settings["pulse_rate"]._left_btn.height() == 64


def test_editor_updates_summary_and_closes_on_navigation(themed_app, qtbot):
    shell = AppShell()
    qtbot.addWidget(shell)
    shell.setFixedSize(1360, 768)
    shell.set_user("Operator")
    shell.navigate("protocols")
    shell.show()
    view = shell.treatment
    view._proto_buttons[4].click()
    view._edit_treatment_button.click()
    view._settings["motor_speed"]._right_btn.click()
    view._settings["max_pressure"]._right_btn.click()
    view._editor.done_button.click()
    assert not view._editor.isVisible()
    assert view.selected_protocol() == 4
    assert view._title.text() == "Oscillating Decompression"
    assert view._summary_values["motor_speed"].text() == "55%"
    assert view._summary_values["max_pressure"].text() == "41 lbs"
    view.open_treatment_editor()
    shell.navigate("setup")
    assert not view._editor.isVisible()


def test_patient_settings_and_rollback_update_summary(themed_app, qtbot):
    from ui.screens.treatment import TreatmentScreen

    view = TreatmentScreen()
    qtbot.addWidget(view)
    changes = []
    view.setting_changed.connect(lambda key, value: changes.append((key, value)))
    view.set_settings({"duration": 20, "max_pressure": 60, "pulse_rate": 0})
    view.select_protocol(3)
    assert changes == []
    assert view._summary_values["duration"].text() == "20 min"
    assert view._summary_values["max_pressure"].text() == "60 lbs"
    assert view._summary_values["pulse_rate"].text() == "Off"
    assert view._summary_rows["max_left"].isHidden()
    assert not view._summary_rows["max_right"].isHidden()
    view.setting_changed.connect(lambda key, _value: view.set_settings({key: 60}))
    view._settings["max_pressure"]._right_btn.click()
    assert view._summary_values["max_pressure"].text() == "60 lbs"


def test_active_editor_keeps_stop_and_locks_prerun_settings(themed_app, qtbot):
    from ui.screens.treatment import TreatmentScreen

    view = TreatmentScreen()
    qtbot.addWidget(view)
    view.set_run_state(True, False)
    view.open_treatment_editor()
    assert view._settings["max_pressure"].isEnabled()
    assert not view._settings["duration"].isEnabled()
    assert not view._settings["motor_speed"].isEnabled()
    assert all(not button.isEnabled() for button in view._proto_buttons.values())
    stops = []
    view.estop_requested.connect(lambda: stops.append(True))
    view._editor.stop_button.click()
    assert stops == [True]
    assert not view._editor.isVisible()
    assert not view._settings["max_pressure"].isEnabled()
    view.open_treatment_editor()
    view.set_busy(True)
    assert not view._editor.isVisible()
    assert not view._edit_treatment_button.isEnabled()
    assert view._estop_btn.isEnabled()


def test_patient_lookup_closes_editor_and_prevents_reopening(themed_app, qtbot):
    from ui.screens.treatment import TreatmentScreen

    view = TreatmentScreen()
    qtbot.addWidget(view)
    view.open_treatment_editor()
    view.set_patient_pending(True)
    assert not view._editor.isVisible()
    view.open_treatment_editor()
    assert not view._editor.isVisible()
    view.set_patient_pending(False)
    view.open_treatment_editor()
    assert view._editor.isVisible()
