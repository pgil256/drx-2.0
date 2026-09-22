"""The staff handoff's identity, approval, and uncertain-create boundaries."""

from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest

from helpers.patient_registration import PatientRegistration
from helpers.staff_client import StaffError

pytestmark = pytest.mark.unit


def draft():
    return {"patient_id": str(uuid4()), "display_name": "Synthetic Patient",
            "settings": {"protocol_number": 4, "duration_min": 12, "max_pressure_lb": 50,
                         "max_left_deg": 10, "max_right_deg": 0, "pulse_rate_hz": 2.4}}


def workflow(patient=None):
    staff = Mock()
    staff.check_context.return_value = {"permissions": ["patients.edit", "plans.approve"]}
    device = Mock()
    return PatientRegistration(staff, device, patient), staff, device


def test_create_uses_flat_staff_fields_and_verifies_server_identity():
    flow, staff, device = workflow()
    form = draft()
    identity = str(uuid4())
    staff.request.return_value = {"id": identity, "pin": "0123", "plan_approved": False}
    device.lookup_pin.return_value = dict(form, patient_id=identity)
    result = flow.save(form)
    staff.request.assert_called_once_with("POST", "/patients", {
        "display_name": form["display_name"], **form["settings"], "approve_initial_plan": False,
    })
    device.lookup_pin.assert_called_once_with("0123")
    assert result["patient_id"] == identity and result["pin"] == "0123"
    assert identity != form["patient_id"]


def test_successful_create_with_review_required_is_not_created_twice():
    flow, staff, device = workflow()
    identity = str(uuid4())
    staff.request.return_value = {"id": identity, "pin": "0007"}
    device.lookup_pin.return_value = {"error": "settings_not_supported", "reason": "plan_review_required"}
    for _ in range(2):
        with pytest.raises(StaffError, match="clinician must review"):
            flow.save(draft())
    assert staff.request.call_count == 1
    device.lookup_pin.return_value = dict(draft(), patient_id=identity)
    assert flow.resolve_created()["patient_id"] == identity
    assert staff.request.call_count == 1


def test_matching_pin_in_wrong_clinic_never_links_patient():
    flow, staff, device = workflow()
    staff.request.return_value = {"id": str(uuid4()), "pin": "0123"}
    device.lookup_pin.return_value = draft()
    with pytest.raises(StaffError, match="different clinic"):
        flow.save(draft())
    assert flow.created is not None


@pytest.mark.parametrize("failure", [StaffError("unavailable", "offline", uncertain=True),
                                    {"id": "bad", "pin": "1234"}, {"id": str(uuid4())}])
def test_uncertain_create_is_never_replayed(failure):
    flow, staff, _device = workflow()
    if isinstance(failure, Exception):
        staff.request.side_effect = failure
    else:
        staff.request.return_value = failure
    for _ in range(2):
        with pytest.raises(StaffError):
            flow.save(draft())
    assert flow.uncertain
    assert staff.request.call_count == 1


def test_expired_session_keeps_draft_without_creating():
    flow, staff, _device = workflow()
    staff.check_context.side_effect = StaffError("session_expired", "Sign in again")
    form = draft()
    before = deepcopy(form)
    with pytest.raises(StaffError):
        flow.save(form)
    assert form == before
    assert not flow.uncertain
    staff.request.assert_not_called()


def test_profile_edit_uses_loaded_version_and_settings_are_local_unless_approved():
    original = draft()
    flow, staff, _device = workflow(original)
    staff.request.return_value = {"id": original["patient_id"], "status": "active",
                                  "display_name": original["display_name"], "version": 7,
                                  "plan": {"current": None}}
    flow.load()
    staff.request.reset_mock()
    staff.request.return_value = {"ok": True, "version": 8}
    form = deepcopy(original)
    form["display_name"] = "Edited Name"
    form["settings"]["max_pressure_lb"] = 60
    result = flow.save(form)
    staff.request.assert_called_once_with("PATCH", "/patients/" + original["patient_id"], {
        "display_name": "Edited Name", "expected_version": 7,
    })
    assert result["settings"]["max_pressure_lb"] == 60


def test_plan_approval_is_explicit_and_preserves_expected_revision():
    original = draft()
    flow, staff, _device = workflow(original)
    revision = str(uuid4())
    flow.profile = {"version": 3, "display_name": original["display_name"],
                    "plan": {"current": {"id": revision}}}
    staff.request.return_value = {"id": str(uuid4())}
    flow.save(original, approve=True, reason="Reviewed on device")
    staff.check_context.assert_called_with("plans.approve")
    staff.request.assert_called_once_with("POST", "/patients/" + original["patient_id"] + "/plan", {
        **original["settings"], "reason": "Reviewed on device", "expected_current_revision_id": revision,
    })


def test_partial_profile_save_does_not_replay_after_stale_plan():
    original = draft()
    flow, staff, _device = workflow(original)
    flow.profile = {"version": 3, "display_name": "Old name", "plan": {"current": None}}
    staff.request.side_effect = [{"ok": True, "version": 4}, StaffError("stale_plan", "Reload")]
    with pytest.raises(StaffError, match="Patient name saved"):
        flow.save(original, approve=True, reason="Clinical review")
    assert flow.needs_reload
    assert flow.profile["version"] == 4
    with pytest.raises(StaffError, match="Reload"):
        flow.save(original, approve=True, reason="Clinical review")
    assert staff.request.call_count == 2
