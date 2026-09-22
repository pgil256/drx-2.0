"""Exercise real cookies/CSRF over loopback; no clinic data or real credentials."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from helpers.staff_client import StaffClient, StaffError

pytestmark = pytest.mark.unit
CLINIC = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def staff_server():
    state = {"requests": [], "mfa": False, "selected": False, "reject": None, "csrf": "first"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            path = self.path.removeprefix("/api/v1/admin")
            state["requests"].append((self.command, path, dict(self.headers), body))
            status, result, cookies = 200, {"ok": True}, []
            if state["reject"]:
                status, result = state["reject"]
            elif path == "/login":
                result = {"mfa_required": state["mfa"]}
                cookies = (["kneespa_mfa=challenge; Path=/api/v1/admin/login"] if state["mfa"] else
                           ["kneespa_session=session; Path=/", "kneespa_csrf=first; Path=/"])
            elif path == "/login/mfa":
                assert "kneespa_mfa=challenge" in self.headers.get("Cookie", "")
                assert len(body) == 1 and next(iter(body)) in ("code", "recovery_code")
                cookies = ["kneespa_session=session; Path=/", "kneespa_csrf=first; Path=/"]
            elif path == "/me":
                assert "kneespa_session=session" in self.headers.get("Cookie", "")
                result = {"email": "test@example.com", "permissions": ["patients.edit"],
                          "clinics": [{"id": CLINIC, "name": "Test Clinic"}],
                          "clinic": {"id": CLINIC if state["selected"] else "different"}}
                state["csrf"] = "rotated"
                cookies = ["kneespa_csrf=rotated; Path=/"]
            elif path == "/clinic/select":
                assert self.headers.get("X-CSRF-Token") == state["csrf"]
                state["selected"] = True
                result = {"ok": True, "clinic_id": body["site_id"]}
                cookies = [f"kneespa_clinic={body['site_id']}; Path=/"]
            else:
                assert self.headers.get("X-CSRF-Token") == state["csrf"]
            self.send_response(status)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            if status == 429:
                self.send_header("Retry-After", "60")
            if status == 302:
                self.send_header("Location", "/redirect-target")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        do_GET = handle_request
        do_POST = handle_request
        do_PATCH = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield StaffClient(f"http://127.0.0.1:{server.server_port}"), state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("mfa,recovery", [(False, False), (True, False), (True, True)])
def test_sign_in_mfa_select_and_current_csrf(staff_server, mfa, recovery):
    client, state = staff_server
    state["mfa"] = mfa
    result = client.login("test@example.com", "synthetic-password")
    if mfa:
        assert result == {"mfa_required": True}
        assert not client.context
        result = client.verify_mfa("123456", recovery=recovery)
    assert result["clinics"][0]["id"] == CLINIC
    assert client.clinic_id is None
    client.select_clinic(CLINIC)
    client.request("POST", "/patients", {"display_name": "Synthetic"})
    headers = state["requests"][-1][2]
    assert headers["X-Csrf-Token"] == "rotated"
    assert "Authorization" not in headers and "X-Device-Id" not in headers
    client.logout()
    assert not list(client.cookies) and not client.context


def test_unexpected_clinic_stops_before_creation(staff_server):
    client, state = staff_server
    client.login("test@example.com", "synthetic")
    client.clinic_id = CLINIC
    with pytest.raises(StaffError, match="Select the device"):
        client.check_context()
    assert not any(row[1] == "/patients" for row in state["requests"])


@pytest.mark.parametrize("status,code,uncertain", [(401, "session_expired", False),
    (403, "csrf_failed", False), (422, "validation_error", False),
    (500, "server_error", True), (302, "redirect", True)])
def test_errors_and_redirects_never_replay_creation(staff_server, status, code, uncertain):
    client, state = staff_server
    state["reject"] = (status, {"code": code, "detail": "server message"})
    with pytest.raises(StaffError) as error:
        client.request("POST", "/patients", {"display_name": "Synthetic"})
    assert error.value.uncertain is uncertain
    assert len(state["requests"]) == 1


def test_rate_limit_prevents_repeat_request(staff_server):
    client, state = staff_server
    state["reject"] = (429, {"code": "rate_limited", "retry_after_s": 30})
    for _ in range(2):
        with pytest.raises(StaffError, match="Wait 60"):
            client.login("test@example.com", "synthetic")
    assert len(state["requests"]) == 1
