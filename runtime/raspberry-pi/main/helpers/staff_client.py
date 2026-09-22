"""Memory-only, cookie-aware staff API client; never uses device credentials."""

import json
import math
import time
from http.cookiejar import CookieJar
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from helpers.cloud_client import CloudClient, _NoRedirect


class StaffError(Exception):
    """A safe UI error, including whether a submitted write has an unknown outcome."""

    def __init__(self, code: str, message: str, uncertain: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


ERRORS = {
    "invalid_credentials": "The cloud email or password was not accepted.",
    "not_authenticated": "Sign in to the cloud again. Your form has been kept.",
    "session_expired": "Your cloud session expired. Sign in again; your form has been kept.",
    "mfa_challenge_expired": "The sign-in attempt expired. Enter your email and password again.",
    "mfa_invalid": "That verification code was not accepted.",
    "permission_denied": "This cloud account does not have permission for this action.",
    "no_clinic_access": "This cloud account does not have access to the selected clinic.",
    "csrf_failed": "Cloud session verification failed. Sign in again.",
    "origin_rejected": "The cloud rejected this connection. Contact support.",
    "stale_update": "The patient was changed elsewhere. Reload and review before saving again.",
    "stale_plan": "The treatment plan changed elsewhere. Reload and review before saving again.",
    "validation_error": "The cloud rejected a field. Check the entered values.",
    "account_disabled": "This cloud staff account is disabled.",
    "not_found": "The patient or clinic is no longer available to this account.",
}


class StaffClient:
    """All methods run on a worker thread. The cookie jar is never written to disk."""

    def __init__(self, cloud_url: str) -> None:
        self.cloud_url = cloud_url.rstrip("/")
        try:
            url = urlsplit(self.cloud_url)
            secure = url.scheme == "https" or (
                url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
            )
            self.enabled = bool(secure and url.hostname and not url.username and not url.password
                                and not url.query and not url.fragment and not url.path)
        except ValueError:
            self.enabled = False
        self.cookies = CookieJar()
        self._opener = build_opener(_NoRedirect(), HTTPCookieProcessor(self.cookies))
        self._not_before = 0.0
        self.clinic_id: Optional[str] = None
        self.context: Dict[str, Any] = {}

    def request(self, method: str, path: str,
                body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            raise StaffError("disabled", "Configure the cloud connection before signing in.")
        wait = self._not_before - time.monotonic()
        if wait > 0:
            raise StaffError("rate_limited", f"Wait {math.ceil(wait)} seconds before trying again.")
        headers = {"Content-Type": "application/json"}
        if method not in ("GET", "HEAD"):
            # Let CookieJar choose the current unexpired cookie for this exact URL.
            probe = Request(self.cloud_url + "/api/v1/admin" + path)
            self.cookies.add_cookie_header(probe)
            for part in (probe.get_header("Cookie") or "").split(";"):
                name, _, value = part.strip().partition("=")
                if name == "kneespa_csrf":
                    headers["X-CSRF-Token"] = value
        data = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
        request = Request(self.cloud_url + "/api/v1/admin" + path, data=data,
                          headers=headers, method=method)
        mutation = method not in ("GET", "HEAD") and path not in ("/login", "/login/mfa")
        try:
            with self._opener.open(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                if response.status not in (200, 201) or not isinstance(result, dict):
                    raise ValueError("Invalid staff response")
                return result
        except HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeError, OSError):
                result = {}
            result = result if isinstance(result, dict) else {}
            code = result.get("code")
            if not isinstance(code, str):
                code = {401: "not_authenticated", 403: "permission_denied",
                        404: "not_found", 422: "validation_error", 429: "rate_limited"}.get(
                            exc.code, "unavailable")
            if exc.code == 429:
                delay = CloudClient._retry_delay(result, exc.headers)
                self._not_before = time.monotonic() + delay
                raise StaffError("rate_limited", f"Wait {delay} seconds before trying again.")
            if exc.code in (401, 403):
                self.context = {}
            raise StaffError(code, ERRORS.get(code, "Cloud request failed. Please try again."),
                             uncertain=mutation and (exc.code >= 500 or 300 <= exc.code < 400))
        except Exception:
            raise StaffError("unavailable", "Cloud unavailable. Check the connection.",
                             uncertain=mutation)

    def login(self, email: str, password: str) -> Dict[str, Any]:
        self.cookies.clear()
        self.clinic_id = None
        self.context = {}
        result = self.request("POST", "/login", {"email": email, "password": password})
        if result.get("mfa_required") is True:
            return {"mfa_required": True}
        return self.request("GET", "/me")

    def verify_mfa(self, code: str, recovery: bool = False) -> Dict[str, Any]:
        self.request("POST", "/login/mfa", {"recovery_code" if recovery else "code": code})
        return self.request("GET", "/me")

    def select_clinic(self, clinic_id: str, permission: str = "patients.edit") -> Dict[str, Any]:
        result = self.request("POST", "/clinic/select", {"site_id": clinic_id})
        if result.get("clinic_id") != clinic_id:
            raise StaffError("clinic_mismatch", "The selected clinic was not confirmed.")
        self.clinic_id = clinic_id
        return self.check_context(permission)

    def check_context(self, permission: str = "patients.edit") -> Dict[str, Any]:
        context = self.request("GET", "/me")
        clinic = context.get("clinic") or {}
        if not self.clinic_id or clinic.get("id") != self.clinic_id:
            self.context = {}
            raise StaffError("clinic_mismatch", "Select the device's clinic before saving.")
        if permission not in context.get("permissions", []):
            self.context = {}
            raise StaffError("permission_denied", ERRORS["permission_denied"])
        self.context = context
        return context

    def search_patients(self, name: str, page: int = 1) -> Dict[str, Any]:
        self.check_context()
        return self.request("GET", "/patients?" + urlencode(
            {"q": name, "status": "all", "page": page, "page_size": 25}
        ))

    def logout(self) -> None:
        try:
            self.request("POST", "/logout", {})
        except StaffError:
            pass
        finally:
            self.cookies.clear()
            self.context = {}
            self.clinic_id = None
