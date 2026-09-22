"""Explicit dashboard credentials and transport selection for simulated hardware."""

import hashlib
import json
from pathlib import Path
from typing import Dict, Optional, Type
from urllib.parse import urlsplit

from dotenv import dotenv_values


DEFAULT_CLOUD_ENV = (
    Path(__file__).resolve().parents[3]
    / "devices/development/cloud-simulator/raspberry-pi/cloud.env"
)
CLOUD_KEYS = ("KNEESPA_CLOUD_URL", "KNEESPA_DEVICE_ID", "KNEESPA_DEVICE_TOKEN")


def cloud_environment(path: Path) -> Dict[str, str]:
    """Read only explicit credentials; keep a persistent outbox per cloud/device."""
    path = path.resolve()
    if not path.is_file():
        raise ValueError(
            f"Cloud profile missing: {path}. Register a simulator device in the dashboard "
            "and save its URL, device ID, and token here (see simulator README)."
        )
    values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    env = {key: (values.get(key) or "").strip() for key in CLOUD_KEYS}
    missing = [key for key, value in env.items() if not value]
    if missing:
        raise ValueError("Cloud profile needs: " + ", ".join(missing))
    # This optional public link follows the explicit simulator profile, never the Pi environment.
    env["KNEESPA_PATIENT_PORTAL_URL"] = (values.get("KNEESPA_PATIENT_PORTAL_URL") or "").strip()
    if any(any(ord(char) < 32 or ord(char) > 126 for char in value)
           for value in env.values()):
        raise ValueError("Cloud profile values must be single-line ASCII text")
    env["KNEESPA_CLOUD_URL"] = env["KNEESPA_CLOUD_URL"].rstrip("/")
    try:
        url = urlsplit(env["KNEESPA_CLOUD_URL"])
        secure = url.scheme == "https" or (
            url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
        )
        valid = (secure and url.hostname and not url.username and not url.password
                 and not url.query and not url.fragment and url.path in ("", "/"))
        url.port  # Validate the port before any network operation.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Cloud URL must be an HTTPS origin (HTTP only on loopback)")
    identity = json.dumps([env["KNEESPA_CLOUD_URL"], env["KNEESPA_DEVICE_ID"]])
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    env["KNEESPA_PENDING_UPLOADS_PATH"] = str(
        path.parent / "data" / key / "pending_uploads.json"
    )
    return env


def cloud_client_class(bridge: object, external: bool = False) -> Type:
    """Use the production HTTP client only when dashboard mode is selected."""
    # Import after the isolated device environment has been installed.
    from helpers.cloud_client import CloudClient

    if external:
        return CloudClient

    class LocalCloudClient(CloudClient):
        """Retain the real outbox with a local demo transport boundary."""

        def __init__(self, **kwargs: object) -> None:
            super().__init__(cloud_url=bridge.manifest["http_url"],
                             device_token=bridge.manifest["token"],
                             device_id="simulator", **kwargs)

        def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
            return bridge.request("cloud", {"method": method, "path": path, "body": body})

    return LocalCloudClient


def staff_client_class(bridge: object, external: bool = False) -> Type:
    """Use isolated synthetic staff sessions for the local simulator only."""
    from uuid import uuid4
    from helpers.staff_client import ERRORS, StaffClient, StaffError

    if external:
        return StaffClient

    class LocalStaffClient(StaffClient):
        def __init__(self, cloud_url: str) -> None:
            super().__init__(cloud_url)
            self._local_session = str(uuid4())

        def request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
            result = bridge.request("staff", {"session": self._local_session,
                                               "method": method, "path": path, "body": body})
            if "error" in result:
                code = result["error"]
                raise StaffError(code, ERRORS.get(code, "Local cloud unavailable."),
                                 result.get("uncertain", False))
            return result

    return LocalStaffClient
