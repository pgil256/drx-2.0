"""Cloud opt-in, credential isolation, and durable uploads over actual HTTP."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
from unittest.mock import Mock
from uuid import uuid4

import pytest

from helpers.cloud_client import CloudClient
from simulator.session.cloud import cloud_client_class, cloud_environment
from simulator.session.profile import prepare_environment


pytestmark = pytest.mark.unit


def write_profile(path: Path, **overrides: str) -> Path:
    values = {"KNEESPA_CLOUD_URL": "https://cloud.example",
              "KNEESPA_DEVICE_ID": "drx-desktop-sim-01", "KNEESPA_DEVICE_TOKEN": "test-token"}
    values.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()),
                    encoding="utf-8")
    return path


def test_default_mode_ignores_inherited_cloud_credentials(tmp_path, monkeypatch):
    for key in ("KNEESPA_CLOUD_URL", "KNEESPA_DEVICE_ID", "KNEESPA_DEVICE_TOKEN",
                "KNEESPA_PENDING_UPLOADS_PATH"):
        monkeypatch.setenv(key, "physical-device-state")
    env = prepare_environment(tmp_path)
    assert not any(key in env for key in ("KNEESPA_CLOUD_URL", "KNEESPA_DEVICE_TOKEN",
                                         "KNEESPA_PENDING_UPLOADS_PATH"))
    bridge = SimpleNamespace(manifest={"http_url": "http://127.0.0.1:8000", "token": "local"},
                             request=Mock(return_value={"local": True}))
    client = cloud_client_class(bridge)()
    try:
        assert client.device_id == "simulator"
        assert client._request("GET", "/ping") == {"local": True}
        bridge.request.assert_called_once()
    finally:
        client.close()


def test_cloud_profile_whitelists_values_and_keeps_hardware_isolated(tmp_path, monkeypatch):
    path = write_profile(tmp_path / "saved/cloud.env", KNEESPA_CONFIG_PATH="real.cfg",
                         ADMIN_PIN="9999", KNEESPA_PENDING_UPLOADS_PATH="real-outbox.json",
                         KNEESPA_PATIENT_PORTAL_URL="https://cloud.example/patients/new")
    monkeypatch.setenv("KNEESPA_DEVICE_TOKEN", "physical-token")
    env = prepare_environment(tmp_path / "session", path)
    assert env["KNEESPA_DEVICE_TOKEN"] == "test-token"
    assert env["ADMIN_PIN"] == "1234"
    assert env["KNEESPA_PATIENT_PORTAL_URL"] == "https://cloud.example/patients/new"
    assert env["KNEESPA_CONFIG_PATH"].startswith(str(tmp_path / "session"))
    assert env["KNEESPA_PENDING_UPLOADS_PATH"].startswith(str(path.parent / "data"))
    assert cloud_client_class(Mock(), external=True) is CloudClient


def test_outbox_survives_new_session_and_token_rotation_but_isolates_devices(tmp_path):
    path = write_profile(tmp_path / "saved/cloud.env")
    first = prepare_environment(tmp_path / "one", path)["KNEESPA_PENDING_UPLOADS_PATH"]
    write_profile(path, KNEESPA_DEVICE_TOKEN="rotated")
    assert prepare_environment(tmp_path / "two", path)["KNEESPA_PENDING_UPLOADS_PATH"] == first
    write_profile(path, KNEESPA_DEVICE_ID="different-device")
    assert cloud_environment(path)["KNEESPA_PENDING_UPLOADS_PATH"] != first
    write_profile(path, KNEESPA_CLOUD_URL="https://different.example")
    assert cloud_environment(path)["KNEESPA_PENDING_UPLOADS_PATH"] != first


@pytest.mark.parametrize("url", ["http://cloud.example", "https://u:secret@cloud.example",
                                  "https://cloud.example/?secret=1", "https://cloud.example/#x",
                                  "https://cloud.example/api", "https://cloud.example:invalid"])
def test_invalid_cloud_origins_fail_before_launch_without_disclosing_values(tmp_path, url):
    path = write_profile(tmp_path / "cloud.env", KNEESPA_CLOUD_URL=url)
    with pytest.raises(ValueError, match="HTTPS origin") as error:
        cloud_environment(path)
    assert url not in str(error.value)


def test_missing_profile_or_token_cannot_fall_back_to_inherited_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("KNEESPA_DEVICE_TOKEN", "live-secret")
    path = tmp_path / "cloud.env"
    with pytest.raises(ValueError, match="profile missing"):
        cloud_environment(path)
    write_profile(path, KNEESPA_DEVICE_TOKEN="")
    with pytest.raises(ValueError, match="KNEESPA_DEVICE_TOKEN"):
        cloud_environment(path)
    write_profile(path, KNEESPA_DEVICE_TOKEN="'${KNEESPA_DEVICE_TOKEN}'")
    assert cloud_environment(path)["KNEESPA_DEVICE_TOKEN"] == "${KNEESPA_DEVICE_TOKEN}"


def test_real_http_headers_lookup_and_upload_receipt_survive_relaunch(tmp_path, monkeypatch):
    requests = []
    patient_id = str(uuid4())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def respond(self, body: Dict, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self) -> None:
            requests.append((self.path, dict(self.headers), None))
            self.respond({"server_time": "2026-09-21T12:00:00Z",
                          "device_name": "Test simulator", "min_app_version": "3.0"})

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, dict(self.headers), body))
            if self.path.endswith("lookup"):
                self.respond({"patient_id": patient_id})
            else:
                self.respond({"id": str(uuid4()), "client_record_id": body["client_record_id"],
                              "received_at": "2026-09-21T12:00:00Z"}, status=201)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    path = write_profile(tmp_path / "saved/cloud.env",
                         KNEESPA_CLOUD_URL=f"http://127.0.0.1:{server.server_port}")
    env = prepare_environment(tmp_path / "one", path)
    for key, value in env.items():
        if key.startswith("KNEESPA_"):
            monkeypatch.setenv(key, value)
    client_type = cloud_client_class(Mock(), external=True)
    first, second = client_type(), client_type()
    record = {"client_record_id": str(uuid4()), "patient_id": patient_id}
    pending = env["KNEESPA_PENDING_UPLOADS_PATH"]
    try:
        assert first.ping()["device_name"] == "Test simulator"
        assert first.lookup_pin("0123")["patient_id"] == patient_id
        assert first._queue_pending(record, pending)
        first.close(wait=True)
        relaunched = prepare_environment(tmp_path / "two", path)
        assert relaunched["KNEESPA_PENDING_UPLOADS_PATH"] == pending
        second.retry_pending_async(pending).result(timeout=5)
        assert json.loads(Path(pending).read_text()) == []
        assert [item[0] for item in requests] == ["/api/v1/device/ping",
                                                "/api/v1/device/patients/lookup",
                                                "/api/v1/device/treatments"]
        assert requests[1][2] == {"pin": "0123"}
        assert requests[2][2] == record
        for _, headers, _ in requests:
            assert headers["Authorization"] == "Bearer test-token"
            assert headers["X-Device-Id"] == "drx-desktop-sim-01"
    finally:
        first.close(wait=True)
        second.close(wait=True)
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
