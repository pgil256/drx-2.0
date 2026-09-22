"""Phone approval lifecycle, role gates and nonblocking session revalidation."""

import threading
import time
from typing import Any, Callable, Dict

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from helpers.cloud_contract import validate_patient
from helpers.logging import setup_logger
from helpers.machine_sign_in import (
    MachineSignInClient, MachineStaffClient, ROLES, deadline, validate_request,
)


def authorize(window: Any, action: str, callback: Callable) -> bool:
    """Preserve local staff login; cloud actors always pass the machine gate."""
    user = getattr(window, "current_user", None)
    if not isinstance(user, dict) or not user.get("machine_sign_in"):
        return True
    controller = getattr(window, "machine_sign_in", None)
    return controller is not None and controller.authorize(action, callback)


class MachineSignInController(QObject):
    completed = pyqtSignal(int, str, object)

    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window
        self.logger = setup_logger(component="Machine sign-in")
        self.client = MachineSignInClient(window.cloud_client)
        self._generation = 0
        self._retired = threading.Event()
        self._busy = False
        self._request: Dict = {}
        self._next_poll = 0.0
        self._next_check = 0.0
        self._callback = None
        self._authorized = None
        self.completed.connect(self._completed)
        modal = window.shell.login_modal
        modal.phone_requested.connect(self.begin)
        modal.phone_cancelled.connect(self.cancel_request)
        modal.closed.connect(self.cancel_request)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    @property
    def modal(self) -> Any:
        return self.window.shell.login_modal

    def active_treatment(self) -> bool:
        w = self.window
        return w.protocol_running or w.protocol_state in ("starting", "running", "stopping")

    def _controls_owned(self) -> bool:
        return self.active_treatment() or any(
            getattr(self.window, flag, False) is True for flag in (
                "_calibration_active", "_device_maintenance_active", "reset_in_progress",
                "actuator_command_in_progress",
            )
        )

    def _run(self, action: str, operation: Callable) -> None:
        if self._busy:
            return
        generation, retired, client = self._generation, self._retired, self.client
        self._busy = True

        def execute() -> None:
            try:
                result = operation()
            except Exception:
                self.logger.warning("Machine sign-in operation failed: %s", action)
                result = {"error": "invalid_response"}
            if retired.is_set():
                if action == "create" and "id" in result:
                    try:
                        client.cancel(result["id"])
                    except (ValueError, TypeError, AttributeError):
                        pass
                client.logout(client.clear())
                return
            try:
                self.completed.emit(generation, action, (client, result))
            except RuntimeError:
                client.logout(client.clear())

        threading.Thread(target=execute, daemon=True, name="machine-sign-in").start()

    def clear(self) -> None:
        """Retire callbacks before discarding credentials on logout or user change."""
        self._generation += 1
        self._retired.set()
        old, identity = self.client, self._request.get("id")
        token = old.clear()
        self.client = MachineSignInClient(self.window.cloud_client)
        # Refresh/retry must also respect a server cooldown.
        self.client.cooldown = old.cooldown
        self._retired = threading.Event()
        self._request = {}
        self._busy = False
        self._callback = None
        self._authorized = None
        self.modal.clear_phone()

        def revoke() -> None:
            if identity:
                try:
                    old.cancel(identity)
                except (ValueError, TypeError, AttributeError):
                    pass
            old.logout(token)

        if token or identity:
            threading.Thread(target=revoke, daemon=True, name="machine-sign-out").start()

    def cancel_request(self) -> None:
        if self._request or (self._busy and not self.client.token):
            self.clear()

    def begin(self) -> None:
        w = self.window
        if self._controls_owned() or w._closing:
            return
        if w.current_user:
            w._on_logout()
            if w.current_user:
                return  # Movement or maintenance can also block user changes.
        self.clear()
        self.modal.phone_status("Creating a secure sign-in code…", retry=False)
        self._run("create", self.client.create)

    @staticmethod
    def _message(result: Dict) -> str:
        if (result.get("http_status") == 409
                and result.get("error") == "settings_not_supported"):
            return "Your care team needs to review your treatment plan before you can continue."
        if result.get("http_status") == 401:
            return "Sign-in ended. Scan a new QR code to sign in again."
        if result.get("error") == "disabled":
            return "Phone sign-in needs this machine’s registered cloud connection."
        if result.get("error") == "rate_limited":
            return "Please wait {} seconds before trying again.".format(
                result.get("retry_after_s", 60))
        return "Cloud sign-in could not be confirmed. Check the connection and try a new QR code."

    def _completed(self, generation: int, action: str, payload: object) -> None:
        client, result = payload
        if generation != self._generation or self.window._closing:
            # The result may have entered Qt's queue just before cancellation.
            def discard() -> None:
                if action == "create" and isinstance(result.get("id"), str):
                    try:
                        client.cancel(result["id"])
                    except (ValueError, TypeError, AttributeError):
                        pass
                client.logout(client.clear())

            threading.Thread(target=discard, daemon=True).start()
            return
        self._busy = False
        if action in ("create", "poll", "exchange") and self.active_treatment():
            if action == "create" and isinstance(result.get("id"), str):
                self._request = {"id": result["id"]}
            self.clear()
            return
        if "error" in result:
            message = self._message(result)
            if action == "poll" and result.get("error") in ("rate_limited", "unavailable"):
                self._next_poll = time.monotonic() + max(5, result.get("retry_after_s", 5))
                self.modal.phone_status(message, retry=False, keep_qr=True)
            elif action in ("check", "authorize"):
                self._callback = None
                if result.get("http_status") == 401:
                    self._expired()
                elif action == "authorize":
                    self.window._show_timed_error(message)
                self._next_check = time.monotonic() + 15
            else:
                self.clear()
                self.modal.phone_status(message)
            return
        if action == "create":
            try:
                self._request = validate_request(result)
                self.modal.show_phone_request(self._request)
            except (KeyError, TypeError, ValueError, AttributeError, ImportError):
                # Retain a valid ID for cancellation even if rendering fails.
                if isinstance(result.get("id"), str):
                    self._request = {"id": result["id"]}
                self.clear()
                self.modal.phone_status("The sign-in QR could not be displayed. Try again.")
                return
            self._next_poll = time.monotonic() + self._request["poll_interval_seconds"]
        elif action == "poll":
            state = result.get("state")
            if state == "pending":
                self._next_poll = time.monotonic() + self._request["poll_interval_seconds"]
            elif state == "approved":
                self.modal.phone_status("Approval received. Checking your access…", retry=False)
                identity, client = self._request["id"], self.client

                def exchange() -> Dict:
                    context = client.exchange(identity)
                    if "error" in context:
                        return context
                    if context["role"] == "patient":
                        patient = client.patient()
                        if "error" in patient:
                            return patient
                        return {"context": context, "patient": patient}
                    return {"context": context}

                self._run("exchange", exchange)
            else:
                messages = {"denied": "Sign-in was declined on the phone.",
                            "cancelled": "This code was cancelled.",
                            "expired": "This code expired.",
                            "consumed": "This code was already used."}
                self.clear()
                self.modal.phone_status(messages.get(state, "Sign-in could not be confirmed.")
                                        + " Request a new QR code.")
        elif action == "exchange":
            self._signed_in(result)
        elif action == "authorize":
            callback, self._callback = self._callback, None
            if callback is None or (self.active_treatment() and callback[0] != "settings"):
                return
            permission, operation = callback
            if self.window.current_user is None:
                return
            if not self._allows(permission, result["context"]):
                self.window._show_timed_error("Your approved role cannot perform this action.")
                return
            if permission == "treatment" and result["context"]["role"] == "patient":
                if not self._check_patient_plan(result.get("patient")):
                    return
            self._authorized = permission
            try:
                if permission == "treatment":
                    self.window._seed_modern_run_inputs()
                operation()
            finally:
                self._authorized = None
        self._next_check = time.monotonic() + 15

    def _signed_in(self, result: Dict) -> None:
        w, context = self.window, result["context"]
        patient = None
        if context["role"] == "patient":
            try:
                patient, values, protocol = validate_patient(result.get("patient"))
                if patient["patient_id"] != context["patient_id"]:
                    raise ValueError("Patient mismatch")
            except (ValueError, KeyError):
                self.clear()
                self.modal.phone_status("Your care team needs to review your treatment plan.")
                return
        self._request = {}
        w.patients.clear_session()
        w._patient_lookup_id += 1
        w._patient_lookup_pending = False
        w.cloud_patient = patient
        role = context["role"]
        name = (patient or {}).get("display_name") or ROLES[role]
        w.current_user = {"username": name, "status": role, "machine_sign_in": True}
        w.shell.treatment.clear_patient()
        if patient:
            w.shell.treatment.set_settings(values)
            w.shell.treatment.select_protocol(protocol)
            w.shell.treatment.set_patient(name)
        if role == "clinician":
            w.patients.staff = MachineStaffClient(self.client)
        w.shell.set_access_role(role)
        destination = "device" if role == "service_technician" else "protocols"
        w.shell.login_succeeded(name, goto=destination,
                               title=ROLES[role])
        # Clinicians select a patient explicitly on the Treatment screen.

    @staticmethod
    def _allows(action: str, context: Dict) -> bool:
        role = context.get("role")
        if action == "treatment":
            return ((role == "patient" and "patient.self" in context.get("permissions", []))
                    or (role == "clinician" and "patients.view" in context.get("permissions", [])))
        if action in ("setup", "device"):
            return role in ("clinician", "service_technician")
        if action == "service":
            return role == "service_technician"
        if action == "settings":
            return role == "clinician" and "patients.edit" in context.get("permissions", [])
        return role == "clinician" and action in context.get("permissions", [])

    def authorize(self, action: str, callback: Callable) -> bool:
        """Recheck on a worker, then run one UI action within that authorization."""
        if (self._authorized == action and self.client.token
                and self.client.expires_at > time.time()):
            return True
        if (self._busy or self.window._closing
                or (self.active_treatment() and action != "settings")):
            return False
        if not self.client.token or self.client.expires_at <= time.time():
            self._expired()
            return False
        if not self._allows(action, self.client.context):
            self.window._show_timed_error("Sign in with a role that permits this action.")
            return False
        self._callback = (action, callback)
        client = self.client

        def check() -> Dict:
            context = client.inspect()
            if "error" in context:
                return context
            result = {"context": context}
            if action == "treatment" and context["role"] == "patient":
                patient = client.patient()
                if "error" in patient:
                    return patient
                result["patient"] = patient
            return result

        self._run("authorize", check)
        return False

    def _check_patient_plan(self, response: Dict) -> bool:
        try:
            patient, values, protocol = validate_patient(response)
            if patient["patient_id"] != self.client.context["patient_id"]:
                raise ValueError("Patient mismatch")
        except (ValueError, KeyError):
            self.window._show_timed_error("Your care team needs to review your treatment plan.")
            return False
        w = self.window
        changed = (not w.cloud_patient or w.cloud_patient.get("settings") != patient["settings"]
                   or any(w.shell.treatment.settings_values().get(k) != v
                          for k, v in values.items())
                   or w.shell.treatment.selected_protocol() != protocol)
        w.cloud_patient = patient
        if changed:
            w.shell.treatment.set_settings(values)
            w.shell.treatment.select_protocol(protocol)
            w._show_timed_error(
                "Your plan was updated. Review the settings, then press Start again."
            )
        return not changed

    def _expired(self) -> None:
        self.clear()
        if self._controls_owned():
            # Keep the frozen treatment identity and its safety controls until completion.
            self.window.shell.treatment.set_cloud_status(
                "Sign-in ended; finish treatment or device movement before signing in."
            )
        else:
            self.window._on_logout()
            self.window.shell.show_login()

    def _tick(self) -> None:
        if self.window._closing:
            self.timer.stop()
            return
        if self._request and "expires_at" in self._request:
            remaining = max(0, int(deadline(self._request["expires_at"]) - time.time()))
            self.modal.set_phone_remaining(remaining)
            if not remaining:
                self.clear()
                self.modal.phone_status("This code expired. Request a new QR code.")
            elif not self._busy and time.monotonic() >= self._next_poll:
                client, identity = self.client, self._request["id"]
                self._run("poll", lambda: client.poll(identity))
        elif self.client.token:
            if self.client.expires_at <= time.time():
                self._expired()
            elif not self._busy and time.monotonic() >= self._next_check:
                self._run("check", self.client.inspect)
        elif ((self.window.current_user or {}).get("machine_sign_in")
              and not self._controls_owned()):
            # A staff API call may have received a 401 on its own worker.
            self._expired()

    def treatment_finished(self) -> None:
        """End human access without changing the outcome display or hardware state."""
        user = self.window.current_user or {}
        if not user.get("machine_sign_in"):
            return
        self.clear()
        self.window.patients.clear_session()
        self.window.current_user = None
        self.window.cloud_patient = None
        self.window.shell.set_user(None)
        self.window.shell.treatment.set_cloud_status(
            "Treatment finished. Sign in for the next visit."
        )
