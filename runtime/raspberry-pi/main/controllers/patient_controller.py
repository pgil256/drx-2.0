"""Coordinate staff authentication and patient drafts without blocking device control."""

import os
import threading
from copy import deepcopy
from typing import Any, Callable, Dict

from PyQt5.QtCore import QObject, pyqtSignal

from main.config.constants import PATIENT_PORTAL_PATH
from helpers.cloud_contract import validate_patient
from helpers.patient_registration import PatientRegistration
from helpers.staff_client import StaffClient, StaffError
from controllers.machine_sign_in_controller import authorize
from ui.modals.patient_editor import PatientEditor
from ui.modals.patient_portal import PatientPortal
from ui.modals.patient_reconcile import PatientReconcile
from ui.modals.staff_login import StaffLogin


class PatientController(QObject):
    completed = pyqtSignal(int, str, object)

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.staff = StaffClient(window.cloud_client.cloud_url)
        self.flow = None
        self._request_id = 0
        self._pending = False
        self._lookup_generation = 0
        self.editor = PatientEditor(window)
        self.portal = PatientPortal(window)
        self.portal.finished.connect(self._return_to_patient_pin)
        self.login = StaffLogin(self.editor)
        self.reconcile = PatientReconcile(self.editor)
        self.editor.submitted.connect(self.save)
        self.editor.sign_in_requested.connect(self.sign_in)
        self.editor.reconcile_requested.connect(self.show_reconcile)
        self.editor.reload_requested.connect(lambda: self._run("reload", self.flow.load))
        self.editor.rejected.connect(self._cancel_editor)
        self.login.login_requested.connect(self._login)
        self.login.mfa_requested.connect(self._mfa)
        self.login.clinic_requested.connect(self._clinic)
        self.login.rejected.connect(self._cancel_login)
        self.reconcile.search_requested.connect(self.search)
        self.reconcile.existing_requested.connect(self._use_existing)
        self.reconcile.not_created_confirmed.connect(self._allow_create_retry)
        self.completed.connect(self._completed)

    def _allowed(self) -> bool:
        return bool(self.window.current_user and not self.window.protocol_running
                    and not self.window._closing)

    def _login(self, email: str, password: str) -> None:
        staff = self.staff
        self._run("login", lambda: staff.login(email, password))

    def _mfa(self, code: str, recovery: bool) -> None:
        staff = self.staff
        self._run("login", lambda: staff.verify_mfa(code, recovery))

    def _clinic(self, clinic: str) -> None:
        staff = self.staff
        self._run("clinic", lambda: staff.select_clinic(clinic))

    def add(self) -> None:
        """Let clinicians register in the web app before entering the patient PIN."""
        if not self._allowed() or self.window._patient_lookup_pending:
            return
        if not authorize(self.window, "patients.edit", self.add):
            return
        self.window._on_patient_edit()
        self.window.shell.patient_modal.hide()
        portal_url = os.environ.get("KNEESPA_PATIENT_PORTAL_URL", "").strip()
        if not portal_url:
            portal_url = self.window.cloud_client.cloud_url.rstrip("/") + PATIENT_PORTAL_PATH
        self.portal.set_portal_url(portal_url)
        self.portal.open()

    def _return_to_patient_pin(self, _result: int) -> None:
        if self._allowed() and not self.window._patient_lookup_pending:
            self.window._show_patient_modal()

    def edit(self) -> None:
        if (not self._allowed() or self.window._patient_lookup_pending
                or not self.window.cloud_patient):
            return
        if not authorize(self.window, "patients.edit", self.edit):
            return
        self.flow = PatientRegistration(self.staff, self.window.cloud_client,
                                        self.window.cloud_patient)
        self.editor.open_patient(self.window.cloud_patient,
                                 self.window.shell.treatment.settings_values(),
                                 self.window.shell.treatment.selected_protocol(), editing=True)
        self.editor.set_staff(self.staff.context)
        if self.staff.context:
            self._run("load", self.flow.load)

    def sign_in(self) -> None:
        if not self._allowed() or self._pending:
            return
        if self.window.current_user.get("machine_sign_in"):
            self.window._on_logout()
            self.window.shell.show_login(phone=True)
            return
        self._replace_staff()
        if self.flow is not None:
            self.flow.staff = self.staff
        self.editor.set_staff({})
        self.login.set_stage("login")
        self.login.open()

    def _replace_staff(self) -> None:
        old = self.staff
        self.staff = StaffClient(self.window.cloud_client.cloud_url)
        if old.context or list(old.cookies):
            threading.Thread(target=old.logout, daemon=True).start()

    def clear_session(self) -> None:
        """Invalidate late work and discard the old operator's in-memory cookies."""
        self._request_id += 1
        self._pending = False
        self.flow = None
        self._replace_staff()
        self.editor.set_pending(False)
        self.editor.hide()
        self.portal.hide()
        self.login.accept()
        self.login._password.clear()
        self.login._code.clear()
        self.reconcile.hide()

    def _cancel_login(self) -> None:
        self._request_id += 1
        self._set_pending(False)
        self._replace_staff()
        if self.flow:
            self.flow.staff = self.staff
        self.editor.set_staff({})

    def _cancel_editor(self) -> None:
        if self.flow is not None and self.flow.patient is None and self._allowed():
            self.window.shell.patient_modal.open_over(self.window.shell)

    def _set_pending(self, pending: bool) -> None:
        self._pending = pending
        self.window._patient_lookup_pending = pending
        self.window.shell.treatment.set_patient_pending(pending)
        self.editor.set_pending(pending)
        self.login.set_pending(pending)
        self.reconcile.set_pending(pending)

    def _run(self, action: str, operation: Callable[[], Any]) -> None:
        if not self._allowed() or self._pending:
            return
        self._request_id += 1
        request_id = self._request_id
        self._lookup_generation = self.window._patient_lookup_id
        self._set_pending(True)

        def execute() -> None:
            try:
                result = operation()
            except StaffError as exc:
                result = exc
            except Exception:
                self.window.logger.error("Patient cloud operation failed: %s", action)
                result = StaffError("unavailable", "Cloud request failed. Your form has been kept.")
            try:
                self.completed.emit(request_id, action, result)
            except RuntimeError:
                pass  # The window closed while the bounded request was finishing.

        threading.Thread(target=execute, daemon=True).start()

    def _completed(self, request_id: int, action: str, result: object) -> None:
        if (request_id != self._request_id or not self._allowed()
                or self._lookup_generation != self.window._patient_lookup_id):
            return
        self._set_pending(False)
        if isinstance(result, StaffError):
            if action in ("login", "clinic"):
                if result.code == "mfa_challenge_expired":
                    self.login.set_stage("login")
                self.login.show_error(str(result))
            elif action in ("search", "existing"):
                self.reconcile.show_error(str(result))
            else:
                if result.code in ("not_authenticated", "session_expired", "csrf_failed",
                                    "permission_denied", "clinic_mismatch", "no_clinic_access"):
                    self.editor.set_staff({})
                self.editor.set_save_state(bool(self.flow.created), self.flow.uncertain,
                                           self.flow.needs_reload)
                self.editor.show_error(str(result))
            return
        if action == "login":
            self.login.set_stage("mfa" if result.get("mfa_required") else "clinic", result)
        elif action in ("clinic", "context"):
            self.editor.set_staff(result)
            self.login.accept()
            if self.flow.patient is not None:
                self._run("load", self.flow.load)
        elif action in ("load", "reload"):
            self.editor._name.setText(result.get("display_name") or "")
            if action == "reload":
                settings = ((result.get("plan") or {}).get("current") or {}).get("settings")
                settings = settings or result.get("current_settings")
                if settings:
                    try:
                        patient, values, protocol = validate_patient(dict(
                            self.flow.patient, settings=settings,
                            display_name=result.get("display_name"),
                        ))
                    except ValueError:
                        self.editor.show_error(
                            "The saved cloud plan needs correction in the dashboard."
                        )
                        return
                    self.editor.open_patient(patient, values, protocol, editing=True)
            self.editor.set_save_state(False, False, False)
            self.editor.set_staff(self.staff.context)
            self.editor._status.setText(
                "Name changes are saved to the cloud. Settings apply to this treatment."
            )
        elif action == "search":
            self.reconcile.show_results(result)
        elif action in ("save", "existing"):
            self._link(result)

    def save(self, draft: Dict) -> None:
        if self.flow is None:
            return
        snapshot = deepcopy(draft)
        approve, reason = self.editor._approve.isChecked(), self.editor._reason.text()
        flow = self.flow
        if flow.created is not None:
            self._run("save", flow.resolve_created)
        else:
            self._run("save", lambda: flow.save(snapshot, approve, reason))

    def _link(self, result: Dict) -> None:
        try:
            patient, values, protocol = validate_patient(result)
        except ValueError:
            self.editor.show_error(
                "The cloud returned invalid patient details. Patient was not linked."
            )
            return
        self.window.cloud_patient = patient
        view = self.window.shell.treatment
        view.set_settings(values)
        view.select_protocol(protocol)
        view.set_patient(
            patient.get("display_name") or patient.get("external_ref") or patient["patient_id"]
        )
        if patient.get("pin"):
            view.set_patient_pin(patient["pin"])
        self.flow.patient = patient
        self.flow.created = None
        self.flow.uncertain = False
        self.reconcile.accept()
        self.editor.accept()

    def show_reconcile(self) -> None:
        self.reconcile.open()
        self.search(1)

    def search(self, page: int) -> None:
        name = self.editor._name.text().strip()
        staff = self.staff
        self.reconcile._loaded = False
        self.reconcile._confirmed.setChecked(False)
        self._run("search", lambda: staff.search_patients(name, page))

    def _use_existing(self, identity: str, pin: str) -> None:
        flow = self.flow
        self._run("existing", lambda: flow.use_existing(identity, pin))

    def _allow_create_retry(self) -> None:
        self.flow.uncertain = False
        self.flow.created = None
        self.editor.set_save_state(False, False, False)
        self.editor._status.setText("Review the form, then select Save patient to try again.")
