"""Patient intake/edit workflow for the documented staff + device API contract."""

import re
from copy import deepcopy
from typing import Any, Dict, Optional
from uuid import UUID

from helpers.cloud_contract import cloud_error_message, validate_patient
from helpers.staff_client import StaffClient, StaffError


class PatientRegistration:
    """Keep save receipts and uncertain outcomes separate from a linked patient."""

    def __init__(self, staff: StaffClient, device: Any,
                 patient: Optional[Dict[str, Any]] = None) -> None:
        self.staff = staff
        self.device = device
        self.patient = deepcopy(patient)
        self.profile: Optional[Dict[str, Any]] = None
        self.created: Optional[Dict[str, Any]] = None
        self.uncertain = False
        self.needs_reload = False

    def load(self) -> Dict[str, Any]:
        self.staff.check_context()
        identity = str(UUID(self.patient["patient_id"]))
        profile = self.staff.request("GET", "/patients/" + identity)
        if (profile.get("id") != identity or profile.get("status") != "active"
                or type(profile.get("version")) is not int):
            raise StaffError("invalid_patient", "This patient is no longer available for editing.")
        self.profile = profile
        self.needs_reload = False
        return profile

    def save(self, draft: Dict[str, Any], approve: bool = False,
             reason: str = "") -> Dict[str, Any]:
        """Never automatically repeat intake or approve a plan implicitly."""
        if self.uncertain:
            raise StaffError("uncertain_create", "Check saved patients before submitting again.")
        if self.needs_reload:
            raise StaffError("reload_required", "Reload and review before saving again.")
        name = draft.get("display_name", "").strip()
        if not name or len(name) > 200:
            raise StaffError("validation_error", "Enter a patient name (up to 200 characters).")
        try:
            validate_patient(draft)
        except ValueError:
            raise StaffError("validation_error", "Check the treatment settings before saving.")
        context = self.staff.check_context("plans.approve" if approve else "patients.edit")
        if "patients.edit" not in context.get("permissions", []):
            raise StaffError("permission_denied", "This account cannot edit patients.")
        if self.patient is None:
            return self._create(draft, name, approve)
        if self.profile is None:
            raise StaffError("reload_required", "Load the patient before saving.")
        if approve and len(reason.strip()) < 3:
            raise StaffError("validation_error", "Enter a reason for approving the treatment plan.")
        identity = str(UUID(self.patient["patient_id"]))
        if name != self.profile.get("display_name"):
            try:
                saved = self.staff.request("PATCH", "/patients/" + identity, {
                    "display_name": name, "expected_version": self.profile["version"],
                })
                if saved.get("ok") is not True or type(saved.get("version")) is not int:
                    raise StaffError("invalid_response", "Patient save was not confirmed.", True)
                self.profile.update(display_name=name, version=saved["version"])
            except StaffError as exc:
                self.needs_reload = exc.uncertain or exc.code == "stale_update"
                raise
        if approve:
            current = (self.profile.get("plan") or {}).get("current") or {}
            try:
                plan = self.staff.request("POST", "/patients/" + identity + "/plan", {
                    **draft["settings"], "reason": reason.strip(),
                    "expected_current_revision_id": current.get("id"),
                })
                UUID(plan["id"])
                self.profile.setdefault("plan", {})["current"] = plan
            except (ValueError, KeyError, TypeError):
                self.needs_reload = True
                raise StaffError("invalid_response", "Plan save was not confirmed. Reload to review.")
            except StaffError as exc:
                self.needs_reload = exc.uncertain or exc.code == "stale_plan"
                raise StaffError(exc.code, "Patient name saved. " + str(exc), exc.uncertain)
        # This identity was already verified through device lookup. Local settings
        # remain editable for this treatment, without approving a cloud prescription.
        patient, _values, _protocol = validate_patient(dict(
            self.patient, display_name=name, settings=deepcopy(draft["settings"])
        ))
        self.patient = patient
        return patient

    def _create(self, draft: Dict[str, Any], name: str, approve: bool) -> Dict[str, Any]:
        if self.created is None:
            try:
                result = self.staff.request("POST", "/patients", {
                    "display_name": name, **draft["settings"], "approve_initial_plan": approve,
                })
                identity = str(UUID(result["id"]))
                pin = result["pin"]
                if not isinstance(pin, str) or re.fullmatch(r"[0-9]{4}", pin) is None:
                    raise ValueError("Invalid PIN")
                self.created = {"id": identity, "pin": pin}
            except (ValueError, KeyError, TypeError, AttributeError):
                self.uncertain = True
                raise StaffError(
                    "uncertain_create", "The save could not be confirmed. Check saved patients."
                )
            except StaffError as exc:
                self.uncertain = exc.uncertain
                if self.uncertain:
                    raise StaffError(
                        "uncertain_create",
                        "The save may have succeeded. Check saved patients before retrying.",
                    )
                raise
        return self.resolve_created()

    def resolve_created(self) -> Dict[str, Any]:
        result = self.device.lookup_pin(self.created["pin"])
        if not isinstance(result, dict) or "error" in result:
            reason = result.get("reason") if isinstance(result, dict) else None
            message = ("A clinician must review the plan in the cloud dashboard."
                       if reason == "plan_review_required" else cloud_error_message(result))
            raise StaffError(
                "saved_not_linked", f"Patient saved · PIN {self.created['pin']}. {message}"
            )
        try:
            patient, _values, _protocol = validate_patient(result)
        except ValueError:
            raise StaffError(
                "saved_not_linked", "Patient saved; cloud lookup returned invalid settings."
            )
        if patient["patient_id"] != self.created["id"]:
            raise StaffError(
                "saved_not_linked",
                "Patient saved in a different clinic. Check the device's clinic before linking.",
            )
        return dict(patient, pin=self.created["pin"])

    def use_existing(self, identity: str, pin: str) -> Dict[str, Any]:
        self.created = {"id": str(UUID(identity)), "pin": pin}
        return self.resolve_created()
