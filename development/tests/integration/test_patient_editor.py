"""Patient intake must be touch-usable and preserve cancelled drafts."""

from uuid import uuid4

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QLabel, QPushButton

from ui.modals.patient_editor import PatientEditor
from ui.screens.treatment import SETTING_SPECS

pytestmark = pytest.mark.integration


def open_editor(themed_app, qtbot):
    editor = PatientEditor()
    qtbot.addWidget(editor)
    editor.open_patient({"patient_id": str(uuid4())},
                        {spec[0]: spec[2] for spec in SETTING_SPECS}, 1)
    editor.set_staff({"email": "test@example.com", "clinic": {"name": "Test clinic"},
                      "permissions": ["patients.edit"]})
    return editor


def test_name_keyboard_appears_on_touch_and_cancel_preserves_name(themed_app, qtbot):
    editor = open_editor(themed_app, qtbot)
    editor._name.setText("Original name")
    qtbot.mouseClick(editor._name, Qt.LeftButton)
    assert editor._keyboard.isVisible()
    editor._keyboard.text.setText("Cancelled name")
    editor._keyboard.reject()
    assert editor._name.text() == "Original name"
    qtbot.mouseClick(editor._name, Qt.LeftButton)
    keyboard = editor._keyboard
    keyboard.text.clear()
    next(key for key in keyboard._letters if key.text() == "A").click()
    keyboard._shift()
    next(key for key in keyboard._letters if key.text() == "n").click()
    keyboard.accept()
    assert editor._name.text() == "An"


def test_complete_plan_saved_atomically_and_blank_name_rejected(themed_app, qtbot):
    editor = open_editor(themed_app, qtbot)
    submitted = []
    editor.submitted.connect(submitted.append)
    editor._save.click()
    assert not submitted
    editor._name.setText("  Test Patient  ")
    editor._protocol.setCurrentIndex(3)
    for key, value in {"duration": 30, "max_pressure": 80, "max_left": 0,
                       "max_right": 20, "pulse_rate": 2.4}.items():
        editor._settings[key].set_value(value)
    editor._save.click()
    assert submitted[0]["display_name"] == "Test Patient"
    assert submitted[0]["settings"] == {
        "protocol_number": 4, "duration_min": 30, "max_pressure_lb": 80,
        "max_left_deg": 0, "max_right_deg": 20, "pulse_rate_hz": 2.4,
    }
    editor.set_pending(True)
    editor.reject()
    assert editor.isVisible()
    assert not editor._save.isEnabled()
    editor.show_error("Cloud unavailable")
    assert editor._save.isEnabled()
    assert editor._name.text().strip() == "Test Patient"


@pytest.mark.parametrize("state", ["new", "approve", "uncertain", "reload"])
def test_editor_and_keyboard_fit_touchscreen(themed_app, qtbot, tmp_path, state):
    editor = open_editor(themed_app, qtbot)
    editor._name.setText("Synthetic Patient")
    if state == "approve":
        editor._editing = True
        editor.set_staff({"permissions": ["patients.edit", "plans.approve"]})
        editor._approve.setChecked(True)
    elif state in ("uncertain", "reload"):
        editor.set_save_state(False, state == "uncertain", state == "reload")
        editor.show_error("The save may have succeeded. Check saved patients before retrying.")
    qtbot.wait(10)
    assert editor.width() <= 1360 and editor.height() <= 730
    assert editor._scroll.horizontalScrollBar().maximum() == 0
    for child in (editor._save, editor._cancel):
        assert editor.rect().contains(child.rect().translated(child.mapTo(editor, QPoint())))
    editor._scroll.verticalScrollBar().setValue(editor._scroll.verticalScrollBar().maximum())
    assert editor._scroll.viewport().rect().contains(
        editor._status.rect().translated(editor._status.mapTo(editor._scroll.viewport(), QPoint()))
    )
    editor._scroll.verticalScrollBar().setValue(0)
    assert editor.grab().save(str(tmp_path / "patient-editor.png"))
    qtbot.mouseClick(editor._name, Qt.LeftButton)
    assert editor._keyboard.width() <= 1360 and editor._keyboard.height() <= 700
    for key in editor._keyboard.findChildren(QPushButton):
        assert key.width() >= 48 and key.height() >= 48
    assert editor._keyboard.grab().save(str(tmp_path / "patient-keyboard.png"))


def test_staff_password_keyboard_is_masked_and_fits_screen(themed_app, qtbot, tmp_path):
    from PyQt5.QtWidgets import QLineEdit
    from ui.modals.staff_login import StaffLogin

    login = StaffLogin()
    qtbot.addWidget(login)
    login.show()
    qtbot.mouseClick(login._password, Qt.LeftButton)
    keyboard = login._keyboard
    assert keyboard.editor.echoMode() == QLineEdit.Password
    assert keyboard.width() <= 1360 and keyboard.height() <= 730
    buttons = {button.text(): button for button in keyboard.findChildren(QPushButton)}
    for character in "$%#&*()[]{}\\":
        buttons[character].click()
    keyboard.accept()
    assert login._password.text() == "$%#&*()[]{}\\"
    login.reject()
    assert login._password.text() == ""
