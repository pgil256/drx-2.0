"""Machine sessions must not inherit browser authority or replay exchanges."""

import json
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from helpers import machine_sign_in as api
from helpers.staff_client import StaffError

pytestmark = pytest.mark.unit


def future_stamp():
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


def client():
    return api.MachineSignInClient(SimpleNamespace(
        cloud_url="https://cloud.example", enabled=True,
        _headers=lambda: {"Authorization": "Bearer device-secret", "X-Device-Id": "device-id",
                          "Content-Type": "application/json"},
    ))


def context(role="patient"):
    return {"role": role, "site_id": str(uuid4()), "patient_id": str(uuid4()),
            "permissions": ["patient.self"] if role == "patient" else ["patients.edit"],
            "expires_at": future_stamp()}


def request():
    return {"id": str(uuid4()), "verification_url": "https://cloud.example/connect#code=secret",
            "display_code": "ABCD-EFGH", "expires_at": future_stamp(),
            "poll_interval_seconds": 5}


def response(payload):
    stream = BytesIO(json.dumps(payload).encode())
    stream.status = 200
    return stream


def test_machine_transport_uses_device_headers_and_never_cookies(monkeypatch):
    opener = Mock()
    opener.open.side_effect = [response({"ok": True}), response({"ok": True})]
    factory = Mock(return_value=opener)
    monkeypatch.setattr(api, "build_opener", factory)
    c = client()
    c.token = "human-secret"
    c.call("GET", api.SESSION)
    c.create()
    first, second = [call.args[0] for call in opener.open.call_args_list]
    headers = {k.lower(): v for k, v in first.header_items()}
    assert headers["authorization"] == "Bearer device-secret"
    assert headers["x-device-id"] == "device-id"
    assert headers["x-kneespa-machine-session"] == "human-secret"
    assert "cookie" not in headers and "x-clinic-id" not in headers
    assert "x-kneespa-machine-session" not in {k.lower() for k, _ in second.header_items()}
    assert isinstance(factory.call_args.args[0], api._NoRedirect)
    assert len(factory.call_args.args) == 1


def test_429_cooldown_blocks_refresh_and_honors_retry_after(monkeypatch):
    opener = Mock()
    opener.open.side_effect = HTTPError("https://cloud.example", 429, "Rate limited",
                                      {"Retry-After": "90"}, BytesIO(b'{"code":"slow_down"}'))
    monkeypatch.setattr(api, "build_opener", lambda *args: opener)
    c = client()
    assert c.create()["retry_after_s"] == 90
    assert c.poll(str(uuid4()))["error"] == "rate_limited"
    replacement = client()
    replacement.cooldown = c.cooldown
    assert replacement.create()["retry_after_s"] >= 89
    assert opener.open.call_count == 1


def test_401_forgets_token_and_context(monkeypatch):
    opener = Mock()
    opener.open.side_effect = HTTPError("https://cloud.example", 401, "Expired", {},
                                      BytesIO(b'{"code":"machine_session_expired"}'))
    monkeypatch.setattr(api, "build_opener", lambda *args: opener)
    c = client()
    c.token, c.context, c.expires_at = "secret", context(), time.time() + 60
    assert c.inspect()["http_status"] == 401
    assert not c.token and not c.context


def test_lost_exchange_is_attempted_once(monkeypatch):
    c = client()
    opener = Mock()
    opener.open.side_effect = TimeoutError("do not log token")
    monkeypatch.setattr(api, "build_opener", lambda *args: opener)
    assert c.exchange(str(uuid4())) == {"error": "unavailable"}
    assert opener.open.call_count == 1
    assert not c.token


@pytest.mark.parametrize("update", [
    {"verification_url": "http://cloud.example/connect#code=secret"},
    {"verification_url": "https://user:secret@cloud.example/connect#code=secret"},
    {"verification_url": "https://cloud.example/connect?code=secret"},
    {"verification_url": "https://cloud.example/connect"},
    {"poll_interval_seconds": float("nan")}, {"poll_interval_seconds": True},
    {"expires_at": "2001-01-01T00:00:00Z"}, {"id": "../../admin"},
])
def test_invalid_qr_contract_is_rejected(update):
    with pytest.raises((ValueError, TypeError, KeyError)):
        api.validate_request(dict(request(), **update))


def test_qr_keeps_complete_private_fragment_and_minimum_poll_interval():
    source = dict(request(), poll_interval_seconds=1)
    checked = api.validate_request(source)
    assert checked["verification_url"] == source["verification_url"]
    assert checked["poll_interval_seconds"] == 5


def test_session_cannot_change_approved_role_or_identity():
    c = client()
    c.token, c.expires_at, c.context = "secret", time.time() + 60, context()
    c.call = Mock(return_value=dict(c.context, role="clinician"))
    assert c.inspect()["error"] == "invalid_response"
    c.call.return_value = dict(c.context, patient_id=str(uuid4()))
    assert c.inspect()["error"] == "invalid_response"


def test_staff_adapter_rechecks_device_session_and_never_uses_admin_me():
    c = client()
    c.context = context("clinician")
    c.inspect = Mock(return_value=c.context)
    c.call = Mock(return_value={"id": str(uuid4())})
    staff = api.MachineStaffClient(c)
    staff.request("PATCH", "/patients/" + str(uuid4()), {"display_name": "Updated"})
    c.inspect.assert_called_once()
    assert c.call.call_args.args[1].startswith("/api/v1/admin/patients/")
    assert staff.context["clinic"]["id"] == c.context["site_id"]
    with pytest.raises(StaffError):
        staff.request("GET", "/me")
    c.inspect.return_value = context("patient")
    with pytest.raises(StaffError):
        staff.request("GET", "/patients")


def test_restart_starts_without_a_human_token():
    c = client()
    c.token = "secret"
    assert not client().token
    assert c.clear() == "secret"
    assert not c.token
