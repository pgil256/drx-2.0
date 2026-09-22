"""Registration handoff must return to PIN lookup without writing patient records."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QWidget

from controllers.patient_controller import PatientController
from ui.modals.patient_modal import PatientModal
from ui.modals.patient_portal import PatientPortal

pytestmark = pytest.mark.integration

PORTAL_URL = "https://kneespa-cloud.onrender.com/patients/new"


def test_registration_qr_and_return_action_fit_touchscreen(themed_app, qtbot, tmp_path):
    dialog = PatientPortal()
    qtbot.addWidget(dialog)
    dialog.set_portal_url(PORTAL_URL)
    dialog.open()
    qtbot.wait(10)
    assert dialog._qr.isVisible() and not dialog._qr.pixmap().isNull()
    assert dialog._address.text() == PORTAL_URL
    assert dialog.width() <= 1360 and dialog.height() <= 730
    for child in (dialog._qr, dialog._address, dialog._status, dialog._back):
        assert dialog.rect().contains(child.rect().translated(child.mapTo(dialog, QPoint())))
    assert dialog.grab().save(str(tmp_path / "patient-portal.png"))
    assert dialog._qr.pixmap().save(str(tmp_path / "patient-portal-qr.png"))
    with qtbot.waitSignal(dialog.finished):
        dialog._back.click()


@pytest.mark.parametrize("url", [
    "", "/patients/new", "http://clinic.example/patients/new",
    "https://user:password@clinic.example/patients/new",
    "https://clinic.example/patients/new?token=secret",
    "https://clinic.example/patients/new#patient-123", "https://localhost/patients/new",
    "https://clinic.example:invalid/patients/new", "https://[broken",
    "https://clinic.example/line\nbreak", "https://clinic.example/" + "a" * 513,
])
def test_bad_address_clears_previous_qr_without_displaying_secrets(themed_app, qtbot, url):
    dialog = PatientPortal()
    qtbot.addWidget(dialog)
    dialog.set_portal_url(PORTAL_URL)
    dialog.set_portal_url(url)
    assert dialog._qr.isHidden()
    assert dialog._qr.pixmap() is None or dialog._qr.pixmap().isNull()
    assert dialog._address.text() == ""
    assert "not set up" in dialog._status.text()


@pytest.mark.parametrize("error", [ImportError, ValueError])
def test_qr_failure_keeps_manual_address_and_recovers(themed_app, qtbot, monkeypatch, error):
    from ui.modals import patient_portal

    dialog = PatientPortal()
    qtbot.addWidget(dialog)
    with monkeypatch.context() as patch:
        patch.setattr(patient_portal, "portal_qr_pixmap", Mock(side_effect=error))
        dialog.set_portal_url(PORTAL_URL)
    assert dialog._qr.isHidden()
    assert dialog._address.text() == PORTAL_URL
    assert "Open the address" in dialog._instructions.text()
    dialog.set_portal_url(PORTAL_URL)
    assert not dialog._qr.isHidden()
    assert "Scan with" in dialog._instructions.text()


@pytest.fixture
def patient_controller(themed_app, qtbot, monkeypatch):
    monkeypatch.delenv("KNEESPA_PATIENT_PORTAL_URL", raising=False)
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(1366, 768)
    window.current_user = "Test operator"
    window.protocol_running = False
    window._closing = False
    window._patient_lookup_pending = False
    window.cloud_client = SimpleNamespace(cloud_url="https://kneespa-cloud.onrender.com")
    window._on_patient_edit = Mock()
    window.shell = SimpleNamespace(patient_modal=PatientModal(window), treatment=Mock())
    window._show_patient_modal = Mock(
        side_effect=lambda: window.shell.patient_modal.open_over(window)
    )
    controller = PatientController(window)
    controller.staff.request = Mock(side_effect=AssertionError("No staff API calls during handoff"))
    window.shell.patient_modal.add_requested.connect(controller.add)
    window.show()
    window.shell.patient_modal.open_over(window)
    return controller


@pytest.mark.parametrize("close", ["back", "escape"])
def test_add_returns_to_explicit_pin_entry_without_staff_login(patient_controller, qtbot, close):
    controller = patient_controller
    window = controller.window
    window.shell.patient_modal._add.click()
    assert controller.portal.isVisible()
    assert controller.portal._address.text() == PORTAL_URL
    assert not window.shell.patient_modal.isVisible()
    assert not controller.editor.isVisible() and not controller.login.isVisible()
    assert controller.flow is None
    window._on_patient_edit.assert_called_once()
    if close == "back":
        controller.portal._back.click()
    else:
        qtbot.keyClick(controller.portal, Qt.Key_Escape)
    window._show_patient_modal.assert_called_once()
    assert window.shell.patient_modal.isVisible()
    controller.staff.request.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("protocol_running", True), ("_patient_lookup_pending", True),
    ("current_user", None), ("_closing", True),
])
def test_handoff_respects_session_and_treatment_guards(patient_controller, field, value):
    setattr(patient_controller.window, field, value)
    patient_controller.add()
    assert not patient_controller.portal.isVisible()
    patient_controller.window._on_patient_edit.assert_not_called()


def test_logout_dismisses_qr_without_reopening_patient_entry(patient_controller):
    controller = patient_controller
    controller.add()
    controller.window.current_user = None
    controller.clear_session()
    assert not controller.portal.isVisible()
    controller.window._show_patient_modal.assert_not_called()


def test_explicit_portal_override_is_used(patient_controller, monkeypatch):
    url = "https://clinic.example/intake"
    monkeypatch.setenv("KNEESPA_PATIENT_PORTAL_URL", url)
    patient_controller.add()
    assert patient_controller.portal._address.text() == url
