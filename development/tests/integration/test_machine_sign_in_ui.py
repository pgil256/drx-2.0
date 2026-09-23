"""Real-window QR sign-in, role boundaries and lifecycle race coverage."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from PyQt5.QtCore import QPoint

from controllers.machine_sign_in_controller import authorize
from helpers.machine_sign_in import MachineSignInClient, MachineStaffClient, REQUESTS, SESSION
from integration.test_window_wiring import window_run

pytestmark = pytest.mark.integration


@pytest.fixture
def sign_in(window_run, monkeypatch):
    w = window_run.window
    w.cloud_client.enabled = True
    w.cloud_client._headers.return_value = {
        "Authorization": "Bearer test-device", "X-Device-Id": "test-device",
    }
    controller = w.machine_sign_in
    controller.timer.stop()
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    identity = str(uuid4())
    data = {
        "request": {"id": identity, "expires_at": expiry, "display_code": "ABCD-EFGH",
                    "verification_url": "https://cloud.example/connect#code=private-approval",
                    "poll_interval_seconds": 5},
        "context": {"role": "patient", "site_id": str(uuid4()), "patient_id": str(uuid4()),
                    "expires_at": expiry, "permissions": ["patient.self"]},
        "state": "approved", "calls": [], "errors": {},
    }
    data["patient"] = {"patient_id": data["context"]["patient_id"], "display_name": "Test Patient",
                       "settings": {"protocol_number": 2, "duration_min": 12,
                                    "max_pressure_lb": 50, "max_left_deg": 10,
                                    "max_right_deg": 10, "pulse_rate_hz": 2.4},
                       "settings_source": "approved_plan", "plan_revision_id": str(uuid4())}

    def call(client, method, path, body=None, token=None):
        data["calls"].append((method, path))
        if path in data["errors"]:
            return data["errors"][path]
        if path == REQUESTS:
            return dict(data["request"])
        if path.endswith("/exchange"):
            return {"machine_session": "test-human-session", "role": data["context"]["role"],
                    "expires_at": expiry}
        if path == REQUESTS + "/" + identity:
            return {"state": data["state"], "expires_at": expiry}
        if path == SESSION:
            return dict(data["context"])
        if path == SESSION + "/patient":
            return dict(data["patient"])
        return {"ok": True}

    monkeypatch.setattr(MachineSignInClient, "call", call)
    yield w, controller, data
    controller.clear()


def show_qr(sign_in, qtbot):
    w, controller, _data = sign_in
    w.shell.show_login()
    w.shell.login_modal._switch.click()  # "Sign in with a QR code"
    qtbot.waitUntil(lambda: bool(controller._request) and not controller._busy)


def test_sign_in_opens_on_staff_pin_and_requests_qr_only_on_demand(sign_in, qtbot):
    w, controller, data = sign_in
    modal = w.shell.login_modal
    w.shell.show_login()
    assert modal.isVisible() and not modal.phone_mode()
    assert modal._keypad.isVisible() and modal._phone.isHidden()
    assert modal._switch.text() == "Sign in with a QR code"
    qtbot.wait(20)
    assert not controller._request and not data["calls"]
    modal._switch.click()
    qtbot.waitUntil(lambda: bool(controller._request) and not controller._busy)
    assert modal.phone_mode() and modal._keypad.isHidden()
    assert modal._switch.text() == "Use staff PIN"
    modal.close_overlay()
    w.shell.show_login()
    assert not modal.phone_mode()  # every opening starts on the PIN again


def approve(sign_in, qtbot):
    show_qr(sign_in, qtbot)
    w, controller, _data = sign_in
    controller._next_poll = 0
    controller._tick()
    qtbot.waitUntil(lambda: bool(w.current_user) and not controller._busy)


def test_patient_phone_sign_in_loads_exact_plan_without_pin(sign_in, qtbot):
    w, controller, data = sign_in
    approve(sign_in, qtbot)
    assert w.current_user["status"] == "patient"
    assert w.cloud_patient["patient_id"] == data["patient"]["patient_id"]
    assert w.cloud_patient["plan_revision_id"] == data["patient"]["plan_revision_id"]
    assert w.shell.treatment.settings_values()["max_pressure"] == 50
    assert w.shell.treatment.selected_protocol() == 2
    assert w.shell.login_modal.isHidden() and w.shell.patient_modal.isHidden()
    assert not w.shell.treatment._edit_treatment_button.isEnabled()
    w.shell._on_nav("device")
    assert w.shell._current == "protocols"
    assert not authorize(w, "patients.edit", Mock())
    assert not authorize(w, "service", Mock())
    assert not any("lookup" in path or "/admin/" in path for _, path in data["calls"])
    assert controller.client.token


def test_clinician_uses_machine_session_in_patient_editor(sign_in, qtbot):
    w, _controller, data = sign_in
    data["context"].update(role="clinician", patient_id=None,
                           permissions=["patients.view", "patients.edit", "plans.approve"])
    approve(sign_in, qtbot)
    assert w.current_user["status"] == "clinician"
    assert isinstance(w.patients.staff, MachineStaffClient)
    assert w.patients.staff.context["roles"] == ["clinician"]
    assert w.cloud_patient is None
    assert not any(path.endswith("/patient") or path.endswith("/me")
                   for _, path in data["calls"])


@pytest.mark.parametrize("state", ["denied", "cancelled", "expired", "consumed", "unknown"])
def test_terminal_request_never_exchanges(sign_in, qtbot, state):
    w, controller, data = sign_in
    data["state"] = state
    show_qr(sign_in, qtbot)
    controller._next_poll = 0
    controller._tick()
    qtbot.waitUntil(lambda: not controller._busy and not controller._request)
    assert w.current_user is None
    assert not any(path.endswith("/exchange") for _, path in data["calls"])
    assert w.shell.login_modal._qr.isHidden()


def test_plan_conflict_does_not_apply_defaults_or_sign_in(sign_in, qtbot):
    w, controller, data = sign_in
    data["errors"][SESSION + "/patient"] = {
        "error": "settings_not_supported", "http_status": 409,
    }
    show_qr(sign_in, qtbot)
    controller._next_poll = 0
    controller._tick()
    qtbot.waitUntil(lambda: not controller._request and not controller._busy)
    assert w.current_user is None and w.cloud_patient is None
    assert not controller.client.token
    assert "care team" in w.shell.login_modal._phone_status.text()


def test_fresh_check_and_plan_review_required_before_treatment(sign_in, qtbot):
    w, controller, data = sign_in
    approve(sign_in, qtbot)
    operation = Mock()
    assert not authorize(w, "treatment", operation)
    qtbot.waitUntil(lambda: operation.called)
    assert data["calls"][-2:] == [("GET", SESSION), ("GET", SESSION + "/patient")]
    data["patient"]["settings"]["max_pressure_lb"] = 55
    operation.reset_mock()
    assert not authorize(w, "treatment", operation)
    qtbot.waitUntil(lambda: not controller._busy)
    assert not operation.called
    assert w.shell.treatment.settings_values()["max_pressure"] == 55


def test_expiry_during_treatment_keeps_identity_and_safety_controls(sign_in, qtbot):
    w, controller, _data = sign_in
    approve(sign_in, qtbot)
    w.protocol.set_state("running")
    patient = w.cloud_patient
    controller.client.expires_at = time.time() - 1
    controller._tick()
    assert not controller.client.token
    assert w.cloud_patient is patient and w.protocol_running
    assert w.current_user["status"] == "patient"
    assert w.shell.login_modal.isHidden()
    controller.treatment_finished()
    assert w.current_user is None
    assert w.protocol_running  # Auth cleanup never commands the hardware.
    w.protocol.set_state("idle")


def test_logout_cancels_abandoned_code_and_queued_create(sign_in, qtbot):
    w, controller, data = sign_in
    show_qr(sign_in, qtbot)
    old_client, generation = controller.client, controller._generation
    w.shell.login_modal.close_overlay()
    qtbot.waitUntil(lambda: any(path.endswith("/cancel") for _, path in data["calls"]))
    assert not controller._request and w.current_user is None
    count = len(data["calls"])
    controller._completed(generation, "create", (old_client, data["request"]))
    qtbot.waitUntil(lambda: len(data["calls"]) > count)
    assert w.current_user is None and not controller._request


def test_approval_arriving_during_treatment_is_not_exchanged(sign_in, qtbot):
    w, controller, data = sign_in
    show_qr(sign_in, qtbot)
    w.protocol_running = True
    controller._completed(
        controller._generation, "poll", (controller.client, {"state": "approved"})
    )
    assert not any(path.endswith("/exchange") for _, path in data["calls"])
    assert not controller._request
    w.protocol_running = False


def test_qr_and_matching_code_fit_touchscreen(sign_in, qtbot, tmp_path):
    w, controller, _data = sign_in
    w.resize(1360, 768)
    show_qr(sign_in, qtbot)
    controller._tick()
    qtbot.wait(20)
    modal = w.shell.login_modal
    for child in (modal._qr, modal._display_code, modal._switch, modal._phone_status):
        assert modal.rect().contains(child.rect().translated(child.mapTo(modal, QPoint())))
    assert not modal._qr.pixmap().isNull()
    assert modal._display_code.text() == "ABCD-EFGH"
    assert modal.grab().save(str(tmp_path / "phone-sign-in.png"))


def test_patient_starts_only_after_recheck_and_completion_clears_session(sign_in, qtbot):
    w, controller, data = sign_in
    approve(sign_in, qtbot)
    w.start_or_stop_protocol()
    w.threadpool.start.assert_not_called()
    qtbot.waitUntil(lambda: w.threadpool.start.called)
    assert w.protocol_running
    assert w._treatment_patient["patient_id"] == data["patient"]["patient_id"]
    frozen = w.protocol._session.patient_id
    w.worker.signals.finished.emit(True)
    assert not controller.client.token and w.current_user is None
    assert w.protocol._session.patient_id == frozen
    record = w.cloud_client.post_treatment_async.call_args.args[0]
    assert record["patient_id"] == frozen
    assert "machine_session" not in record


def test_network_failure_blocks_new_treatment(sign_in, qtbot):
    w, controller, data = sign_in
    approve(sign_in, qtbot)
    data["errors"][SESSION] = {"error": "unavailable"}
    w.start_or_stop_protocol()
    qtbot.waitUntil(lambda: not controller._busy)
    w.threadpool.start.assert_not_called()
    assert not w.protocol_running


def test_technician_cannot_start_treatment_or_edit_patient(sign_in, qtbot):
    w, controller, data = sign_in
    data["context"].update(role="service_technician", patient_id=None,
                           permissions=["devices.view", "tickets.manage"])
    approve(sign_in, qtbot)
    assert w.shell._current == "device"
    w.start_or_stop_protocol()
    w.threadpool.start.assert_not_called()
    assert not authorize(w, "patients.edit", Mock())
    assert not controller._busy


def test_patient_change_ends_session_and_requests_fresh_phone_approval(sign_in, qtbot):
    w, controller, data = sign_in
    approve(sign_in, qtbot)
    w._show_patient_modal()
    qtbot.waitUntil(lambda: not controller._busy)
    assert w.current_user is None and w.cloud_patient is None
    assert not controller.client.token
    assert w.shell.login_modal.isVisible()
    assert w.shell.patient_modal.isHidden()
    assert sum(path == REQUESTS for _, path in data["calls"]) == 2


def test_lost_exchange_does_not_retry_or_sign_in(sign_in, qtbot):
    w, controller, data = sign_in
    path = REQUESTS + "/" + data["request"]["id"] + "/exchange"
    data["errors"][path] = {"error": "unavailable"}
    show_qr(sign_in, qtbot)
    controller._next_poll = 0
    controller._tick()
    qtbot.waitUntil(lambda: not controller._busy and not controller._request)
    controller._tick()
    assert sum(called_path == path for _, called_path in data["calls"]) == 1
    assert not w.current_user and not controller.client.token


def test_create_returning_during_treatment_is_cancelled(sign_in, qtbot):
    w, controller, data = sign_in
    w.protocol_running = True
    controller._completed(controller._generation, "create", (controller.client, data["request"]))
    qtbot.waitUntil(lambda: any(path.endswith("/cancel") for _, path in data["calls"]))
    assert not controller._request
    w.protocol_running = False


def test_local_pin_switch_cancels_request(sign_in, qtbot):
    w, controller, data = sign_in
    show_qr(sign_in, qtbot)
    w.shell.login_modal._switch.click()
    assert not controller._request
    assert w.shell.login_modal._phone.isHidden()
    assert w.shell.login_modal._keypad.isVisible()
    qtbot.waitUntil(lambda: any(path.endswith("/cancel") for _, path in data["calls"]))


def test_staff_api_session_rejection_returns_to_phone_sign_in(sign_in, qtbot):
    w, controller, data = sign_in
    data["context"].update(role="clinician", patient_id=None,
                           permissions=["patients.view", "patients.edit"])
    approve(sign_in, qtbot)
    controller.client.clear()  # The cookie-free transport clears on any API 401.
    controller._tick()
    qtbot.waitUntil(lambda: not controller._busy)
    assert w.current_user is None and w.shell.login_modal.isVisible()
    assert controller._request


def test_expiry_defers_login_overlay_until_device_movement_finishes(sign_in, qtbot):
    w, controller, _data = sign_in
    approve(sign_in, qtbot)
    w.actuator_command_in_progress = True
    controller.client.expires_at = time.time() - 1
    controller._tick()
    controller._tick()
    assert w.current_user and not controller.client.token
    assert w.shell.login_modal.isHidden()
    w.actuator_command_in_progress = False
    controller._tick()
    qtbot.waitUntil(lambda: not controller._busy)
    assert w.current_user is None and controller._request
