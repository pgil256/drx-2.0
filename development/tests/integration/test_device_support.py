"""Device navigation and support drafts remain usable at kiosk resolution."""

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel

from ui.app_shell import AppShell, PAGES

pytestmark = pytest.mark.integration


@pytest.fixture
def shell(themed_app, qtbot):
    view = AppShell()
    qtbot.addWidget(view)
    view.setFixedSize(1352, 756)
    view.show()
    return view


def fill_ticket(view):
    view.contact_name.setText("Operator")
    view.contact_email.setText("operator@example.test")
    view.subject.setText("Controller disconnects")
    view.description.setPlainText("The controller disconnects after reset.")


def test_device_gates_login_and_preserves_destination(shell):
    assert "help" not in shell.nav_rail._buttons
    shell.nav_rail._buttons["device"].click()
    assert shell.login_modal.isVisible()
    shell.login_succeeded("Operator")
    assert shell.stack.currentIndex() == PAGES.index("device")
    assert shell.device.hardware_button.isEnabled()
    shell.logout()
    assert not shell.device.calibration_button.isEnabled()


@pytest.mark.parametrize("section", range(4))
def test_support_tabs_fit_display(shell, qtbot, section):
    shell.navigate("support")
    screen = shell.support
    assert [b.text() for b in screen._section_buttons] == [
        "Protocols", "Controls", "Troubleshooting", "Contact Support",
    ]
    qtbot.mouseClick(screen._section_buttons[section], Qt.LeftButton)
    qtbot.wait(10)
    scroll = screen._sections.currentWidget()
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() == 0
    for label in scroll.widget().findChildren(QLabel):
        if label.isVisible():
            height = label.heightForWidth(label.width()) if label.hasHeightForWidth() else 0
            assert label.height() >= height, label.text()


def test_ticket_validation_duplicate_prevention_and_retry(shell):
    screen = shell.support
    sent = []
    screen.submit_ticket_requested.connect(sent.append)
    screen.ticket_button.click()
    assert not sent
    fill_ticket(screen)
    screen.ticket_button.click()
    assert len(sent) == 1
    screen.set_delivery_state("sending", "Sending request…")
    screen.ticket_button.click()
    assert len(sent) == 1
    assert not screen.description.isEnabled()
    screen.set_delivery_state("failed", "Offline. Retry.")
    assert screen.description.toPlainText() == sent[0]["description"]
    screen.ticket_button.click()
    assert sent[0] == sent[1]
    screen.set_delivery_state("sent", "Ticket sent. Request reference: KS-EXAMPLE.")
    assert not screen.description.toPlainText()
    assert "KS-EXAMPLE" in screen._delivery_status.text()


def test_operator_change_clears_ticket_even_during_delivery(shell):
    shell.set_user("First operator")
    fill_ticket(shell.support)
    shell.support.set_delivery_state("sending", "Sending…")
    shell.logout()
    shell.support.set_delivery_state("failed", "Offline")
    assert not shell.support.contact_name.text()
    assert not shell.support.contact_email.text()
    assert not shell.support.description.toPlainText()


def test_device_settings_only_emit_for_operator_changes(shell, qtbot):
    screen = shell.device
    events = []
    screen.setting_requested.connect(lambda *args: events.append(args))
    shell.set_user("Operator")
    shell.navigate("device")
    screen.set_setting("volume", 65)
    screen.set_setting("brightness", 80)
    assert not events
    screen.sliders["volume"].setValue(70)
    assert events == [("volume", 70)]
    screen.set_setting("brightness", None, "No controllable backlight")
    assert not screen.sliders["brightness"].isEnabled()
    qtbot.wait(10)
    assert screen._device_id.isVisible()


def test_touch_keyboard_can_enter_reply_email_and_cancel_edits(shell, qtbot):
    from PyQt5.QtWidgets import QPushButton

    shell.navigate("support")
    screen = shell.support
    screen._select_section(3)
    qtbot.mouseClick(screen.contact_email, Qt.LeftButton)
    keyboard = screen._keyboard
    assert keyboard.isVisible()
    keys = {button.text(): button for button in keyboard.findChildren(QPushButton)}
    for char in "a+b@example.test":
        keys[char].click()
    keys["Done"].click()
    assert screen.contact_email.text() == "a+b@example.test"
    qtbot.mouseClick(screen.contact_email, Qt.LeftButton)
    screen._keyboard.editor.setText("discarded@example.test")
    screen._keyboard.reject()
    assert screen.contact_email.text() == "a+b@example.test"


def test_description_keyboard_enforces_limit_and_keeps_newlines(shell, qtbot):
    shell.navigate("support")
    screen = shell.support
    screen._select_section(3)
    qtbot.mouseClick(screen.description.viewport(), Qt.LeftButton)
    keyboard = screen._keyboard
    keyboard.editor.setPlainText("x" * 4001)
    assert not keyboard.done_button.isEnabled()
    keyboard.accept()
    assert keyboard.isVisible()
    keyboard.editor.setPlainText("First line\nSecond line")
    keyboard.done_button.click()
    assert screen.description.toPlainText() == "First line\nSecond line"


def test_logout_dismisses_unsaved_touch_entry(shell, qtbot):
    shell.set_user("Operator")
    shell.navigate("support")
    screen = shell.support
    screen._select_section(3)
    qtbot.mouseClick(screen.contact_email, Qt.LeftButton)
    screen._keyboard.editor.setText("discarded@example.test")
    shell.logout()
    assert screen._keyboard is None
    assert not screen.contact_email.text()


@pytest.mark.parametrize("section", range(3))
def test_device_tabs_keep_controls_reachable_at_panel_size(shell, qtbot, section):
    shell.set_user("Operator")
    shell.navigate("device")
    screen = shell.device
    if section == 2:
        screen.unlock_service()
    else:
        screen._select_section(section)
    screen.set_history([{
        "file": "hardware-example.json", "date": "2026-09-21T14:20:00Z",
        "operator": "Example Technician", "kind": "Hardware tests",
        "result": "Incomplete / skipped checks", "saved": False,
    }], ["calibration-20260921T142000Z.json"])
    qtbot.wait(20)
    scroll = screen._sections.currentWidget()
    assert scroll.horizontalScrollBar().maximum() == 0
    if section == 0:
        assert scroll.verticalScrollBar().maximum() == 0
    else:
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    for label in scroll.widget().findChildren(QLabel):
        if label.isVisible() and label.hasHeightForWidth():
            assert label.height() >= label.heightForWidth(label.width()), label.text()
    assert screen.history_table.rowHeight(0) >= 48


def test_wifi_password_and_touch_keyboard_stay_masked(themed_app, qtbot):
    from PyQt5.QtWidgets import QLineEdit
    from ui.modals.device_dialogs import WifiDialog

    dialog = WifiDialog([{"ssid": "Clinic", "signal": "80%", "security": "WPA2"}])
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.mouseClick(dialog.password, Qt.LeftButton)
    keyboard = dialog.keyboard
    assert keyboard is not None
    assert dialog.password.echoMode() == QLineEdit.Password
    assert keyboard.editor.echoMode() == QLineEdit.Password
    keyboard.editor.setText("test password")
    keyboard.done_button.click()
    assert dialog.password.text() == "test password"
    assert keyboard.editor.text() == ""
