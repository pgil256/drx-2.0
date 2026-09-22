"""Cookie-free device approval and memory-only human sessions.

All network methods are bounded and intended for background callers. Neither
approval URLs nor session tokens belong in logs, configuration or the outbox.
"""

import json
import math
import time
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener
from uuid import UUID

from helpers.cloud_client import CloudClient, _NoRedirect
from helpers.staff_client import StaffError


ROLES = {"patient": "Patient", "clinician": "Clinician",
         "service_technician": "Service technician"}
REQUESTS = "/api/v1/device/sign-in/requests"
SESSION = "/api/v1/device/session"


def deadline(value: str) -> float:
    """Require an explicit timezone on cloud expiry timestamps."""
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("Missing timezone")
    return stamp.timestamp()


def validate_request(result: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the phone URL without stripping its private approval fragment."""
    UUID(result["id"])
    url = result["verification_url"]
    parsed = urlsplit(url)
    parsed.port
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (len(url) > 512 or any(ord(c) <= 32 for c in url) or "\\" in url
            or parsed.scheme not in (("https", "http") if local else ("https",))
            or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.path != "/connect"
            or not parse_qs(parsed.fragment).get("code")
            or not isinstance(result["display_code"], str)
            or not 1 <= len(result["display_code"]) <= 32
            or deadline(result["expires_at"]) <= time.time()):
        raise ValueError("Invalid sign-in request")
    interval = result["poll_interval_seconds"]
    if type(interval) not in (int, float) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("Invalid polling interval")
    return dict(result, poll_interval_seconds=max(5, interval))


class MachineSignInClient:
    """A separate transport: no browser cookies and no treatment upload token."""

    def __init__(self, device: Any) -> None:
        self.cloud_url = device.cloud_url
        self.enabled = device.enabled is True
        self._device_headers = device._headers()
        self.token = ""
        self.context: Dict[str, Any] = {}
        self.expires_at = 0.0
        self.cooldown = [0.0]

    @property
    def not_before(self) -> float:
        return self.cooldown[0]

    @not_before.setter
    def not_before(self, value: float) -> None:
        self.cooldown[0] = value

    def call(self, method: str, path: str, body: Optional[Dict] = None,
             token: Optional[str] = None) -> Dict[str, Any]:
        """Return safe errors; honor Retry-After without sleeping on the UI thread."""
        if not self.enabled:
            return {"error": "disabled"}
        wait = self.not_before - time.monotonic()
        if wait > 0:
            return {"error": "rate_limited", "retry_after_s": math.ceil(wait)}
        headers = dict(self._device_headers)
        session = self.token if token is None else token
        if session:
            headers["X-KneeSpa-Machine-Session"] = session
        try:
            data = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
            request = Request(self.cloud_url + path, data=data, headers=headers, method=method)
            with build_opener(_NoRedirect()).open(request, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise ValueError("Expected an object")
                return result
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (ValueError, UnicodeError, OSError):
                payload = {}
            payload = payload if isinstance(payload, dict) else {}
            result = {"error": payload.get("code", "http_error"), "http_status": exc.code}
            if exc.code == 429 or (exc.headers and exc.headers.get("Retry-After")):
                delay = CloudClient._retry_delay(payload, exc.headers)
                self.not_before = time.monotonic() + delay
                result.update(error="rate_limited", retry_after_s=delay)
            if exc.code == 401:
                self.clear()
            return result
        except Exception:
            return {"error": "unavailable"}

    def create(self) -> Dict[str, Any]:
        return self.call("POST", REQUESTS, token="")

    def poll(self, identity: str) -> Dict[str, Any]:
        return self.call("GET", REQUESTS + "/" + str(UUID(identity)), token="")

    def cancel(self, identity: str) -> Dict[str, Any]:
        return self.call("POST", REQUESTS + "/" + str(UUID(identity)) + "/cancel", token="")

    def exchange(self, identity: str) -> Dict[str, Any]:
        """Never retry this method: an uncertain exchange requires a new QR."""
        result = self.call("POST", REQUESTS + "/" + str(UUID(identity)) + "/exchange", token="")
        if "error" in result:
            return result
        try:
            token = result["machine_session"]
            expiry = deadline(result["expires_at"])
            if (not isinstance(token, str) or not token or len(token) > 256
                    or any(ord(c) <= 32 for c in token) or expiry <= time.time()
                    or result["role"] not in ROLES):
                raise ValueError("Invalid session")
            self.token, self.expires_at = token, expiry
            self.context = {"role": result["role"]}
        except (KeyError, TypeError, ValueError, AttributeError):
            return {"error": "invalid_response"}
        return self.inspect()

    def inspect(self) -> Dict[str, Any]:
        if not self.token or self.expires_at <= time.time():
            self.clear()
            return {"error": "machine_session_expired", "http_status": 401}
        result = self.call("GET", SESSION)
        if "error" in result:
            return result
        try:
            UUID(result["site_id"])
            if (result["role"] not in ROLES or result["role"] != self.context.get("role")
                    or not isinstance(result["permissions"], list)
                    or not all(isinstance(p, str) for p in result["permissions"])
                    or deadline(result["expires_at"]) <= time.time()):
                raise ValueError("Invalid context")
            if result["role"] == "patient":
                UUID(result["patient_id"])
            for key in ("site_id", "patient_id"):
                if key in self.context and result.get(key) != self.context[key]:
                    raise ValueError("Session identity changed")
        except (KeyError, TypeError, ValueError, AttributeError):
            return {"error": "invalid_response"}
        self.context = result
        return result

    def patient(self) -> Dict[str, Any]:
        return self.call("GET", SESSION + "/patient")

    def clear(self) -> str:
        """Detach synchronously, so late work cannot keep using a retired token."""
        token, self.token = self.token, ""
        self.context = {}
        self.expires_at = 0.0
        return token

    def logout(self, token: str) -> Dict[str, Any]:
        return self.call("POST", SESSION + "/logout", token=token) if token else {}


class MachineStaffClient:
    """Patient-editor adapter using only the explicitly approved machine role."""

    def __init__(self, machine: MachineSignInClient) -> None:
        self.machine = machine
        self.context = self._context(machine.context)
        self.cookies = ()  # Compatibility with the editor's session cleanup.

    @staticmethod
    def _context(context: Dict) -> Dict:
        return {"clinic": {"id": context.get("site_id")},
                "roles": [context.get("role")], "permissions": context.get("permissions", [])}

    def check_context(self, permission: str = "patients.edit") -> Dict:
        result = self.machine.inspect()
        if ("error" in result or result.get("role") != "clinician"
                or permission not in result.get("permissions", [])):
            self.context = {}
            raise StaffError("permission_denied", "Sign in again with clinician access.")
        self.context = self._context(result)
        return self.context

    def request(self, method: str, path: str, body: Optional[Dict] = None) -> Dict:
        self.check_context()
        if not (path == "/patients" or path.startswith(("/patients/", "/patients?"))):
            raise StaffError("permission_denied", "This action requires the phone app.")
        result = self.machine.call(method, "/api/v1/admin" + path, body)
        if "error" in result:
            raise StaffError(result["error"], "Cloud request failed. Reload before trying again.",
                             uncertain=method != "GET" and result.get("http_status", 500) >= 500)
        return result

    def search_patients(self, name: str, page: int = 1) -> Dict:
        return self.request("GET", "/patients?" + urlencode(
            {"q": name, "status": "all", "page": page, "page_size": 25}))

    def logout(self) -> None:
        self.context = {}
