"""CloudClient failure modes.

A patient lookup runs on a bare daemon thread, so it must ALWAYS return to
the UI (never raise); and the durable pending-upload queue must survive a
corrupt file and concurrent writers.
"""
import json
from io import BytesIO
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError
from uuid import uuid4

import pytest

from helpers.cloud_client import CloudClient

pytestmark = pytest.mark.unit


def make_client():
    return CloudClient(
        cloud_url="https://cloud.example", device_token="t", device_id="d"
    )


def _raise(exc):
    raise exc


def test_lookup_reports_invalid_json(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a, **k: _raise(ValueError("not json")))
    assert c.lookup_pin("1234") == {"error": "invalid_response", "retryable": True}


def test_lookup_reports_non_object_json(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a, **k: ["unexpected"])
    assert c.lookup_pin("1234") == {"error": "invalid_response", "retryable": True}


def test_lookup_passes_through_patient_dict(monkeypatch):
    c = make_client()
    monkeypatch.setattr(
        c, "_request", lambda *a, **k: {"patient_id": 1, "display_name": "J"}
    )
    assert c.lookup_pin("1234") == {"patient_id": 1, "display_name": "J"}


def test_queue_pending_quarantines_corrupt_file(tmp_path):
    c = make_client()
    path = tmp_path / "pending.json"
    path.write_text("{not json", encoding="utf-8")

    c._queue_pending({"client_record_id": "a"}, str(path))

    assert json.loads(path.read_text(encoding="utf-8")) == [
        {"record": {"client_record_id": "a"}}
    ]
    quarantined = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(quarantined) == 1
    assert not (tmp_path / "pending.json.tmp").exists()  # atomic replace


def test_retry_removes_only_uploaded_records(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    a, b, later = ({"client_record_id": str(uuid4())} for _ in range(3))
    path.write_text(json.dumps([a, b]), encoding="utf-8")

    def fake_post(record):
        if record == a:
            # Another thread queues "c" while the retry is mid-flight
            c._queue_pending(later, str(path))
            return receipt(record)
        return None  # "b" keeps failing

    monkeypatch.setattr(c, "post_treatment", fake_post)

    c.retry_pending(str(path))

    remaining = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["record"] for entry in remaining] == [b, later]


def test_retry_deletes_file_when_everything_uploads(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    path.write_text(json.dumps([{"client_record_id": str(uuid4())}]), encoding="utf-8")
    monkeypatch.setattr(c, "post_treatment", receipt)

    c.retry_pending(str(path))

    assert json.loads(path.read_text()) == []


def receipt(record, status=201):
    return {"_http_status": status, "id": str(uuid4()),
            "client_record_id": record["client_record_id"],
            "received_at": "2026-09-15T14:12:00Z"}


def test_sync_status_only_records_success_with_matching_receipt(tmp_path, monkeypatch):
    client = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4())}
    client._queue_pending(record, str(path))
    monkeypatch.setattr(client, "post_treatment", lambda record: {"ok": True})
    client.retry_pending(str(path))
    summary = client.sync_summary(str(path))
    assert summary["pending"] == 1
    assert summary["last_sync"] == "Not recorded yet"
    # Retry backoff must expire before the next attempt.
    path.write_text(json.dumps([record]), encoding="utf-8")
    monkeypatch.setattr(client, "post_treatment", receipt)
    client.retry_pending(str(path))
    summary = client.sync_summary(str(path))
    assert summary["pending"] == 0
    assert summary["last_sync"] != "Not recorded yet"
    stamp = summary["last_sync"]
    client.retry_pending(str(path))
    assert client.sync_summary(str(path))["last_sync"] == stamp
    client.close()


def test_sync_status_does_not_mutate_or_hide_corrupt_queue(tmp_path):
    client = make_client()
    path = tmp_path / "pending.json"
    path.write_text("corrupt", encoding="utf-8")
    assert client.sync_summary(str(path))["pending"] is None
    assert path.read_text() == "corrupt"
    client._read_pending(str(path))  # Normal outbox processing quarantines it.
    assert not path.exists()
    assert client.sync_summary(str(path))["pending"] is None
    client.close()


@pytest.mark.parametrize("status,body,error", [
    (404, {"error": "unknown_pin"}, "unknown_pin"),
    (409, {"error": "settings_not_supported", "detail": "Fix saved settings"},
     "settings_not_supported"),
    (401, {"detail": "Bad token"}, "unauthorized"),
    (403, {"detail": "Revoked"}, "forbidden"),
    (422, {"detail": [{"msg": "invalid"}]}, "validation_error"),
    (500, {}, "http_error"),
])
def test_structured_http_errors(monkeypatch, status, body, error):
    c = make_client()
    failure = HTTPError("https://cloud.example", status, "Error", {},
                        BytesIO(json.dumps(body).encode()))
    monkeypatch.setattr(c, "_request", lambda *a: _raise(failure))
    result = c.lookup_pin("0123")
    assert result["error"] == error
    assert result["http_status"] == status
    assert result["detail"] == body.get("detail")
    assert result["retryable"] == (status >= 500)


def test_lookup_preserves_zero_and_honors_rate_limit(monkeypatch):
    c = make_client()
    clock = [100.0]
    monkeypatch.setattr("helpers.cloud_client.time.monotonic", lambda: clock[0])
    failure = HTTPError("https://cloud.example", 429, "Limited", {"Retry-After": "90"},
                        BytesIO(b'{"error":"rate_limited","retry_after_s":30}'))
    request = MagicMock(side_effect=failure)
    monkeypatch.setattr(c, "_request", request)
    assert c.lookup_pin("0123")["retry_after_s"] == 90
    request.assert_called_once_with("POST", "/api/v1/device/patients/lookup", {"pin": "0123"})
    clock[0] += 20
    assert c.lookup_pin("0123")["retry_after_s"] == 70
    assert request.call_count == 1


@pytest.mark.parametrize("pin", [123, "123", "12345", "１２３４", "12 3", "١٢٣٤"])
def test_invalid_patient_pin_never_sent(monkeypatch, pin):
    c = make_client()
    request = MagicMock()
    monkeypatch.setattr(c, "_request", request)
    assert c.lookup_pin(pin)["error"] == "invalid_pin"
    request.assert_not_called()


def test_network_failure_is_distinct(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a: _raise(URLError("offline")))
    assert c.lookup_pin("0123") == {"error": "unavailable", "retryable": True}


@pytest.mark.parametrize("status", [200, 201])
def test_persist_before_post_and_remove_only_after_receipt(tmp_path, monkeypatch, status):
    c = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4()), "patient_id": str(uuid4()),
              "settings_at_end": {"pulse_rate_hz": 2.4}}
    snapshot = json.loads(json.dumps(record))

    def post(sent):
        assert json.loads(path.read_text())[0]["record"] == snapshot
        assert sent == snapshot
        return receipt(sent, status)

    monkeypatch.setattr(c, "post_treatment", post)
    future = c.post_treatment_async(record, str(path))
    record["settings_at_end"]["pulse_rate_hz"] = 0
    future.result(timeout=3)
    c.close(wait=True)
    assert json.loads(path.read_text()) == []


@pytest.mark.parametrize("reply", [None, {}, {"ok": True}, {"_http_status": 202}])
def test_incomplete_receipt_keeps_exact_body(tmp_path, monkeypatch, reply):
    c = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4())}
    c._queue_pending(record, str(path))
    monkeypatch.setattr(c, "post_treatment", lambda body: reply)
    c.retry_pending(str(path))
    entry = json.loads(path.read_text())[0]
    assert entry["record"] == record
    assert entry["error"]["error"] == "invalid_response"


def test_wrong_record_receipt_does_not_delete(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4())}
    c._queue_pending(record, str(path))
    monkeypatch.setattr(
        c, "post_treatment", lambda body: receipt({"client_record_id": str(uuid4())})
    )
    c.retry_pending(str(path))
    assert json.loads(path.read_text())[0]["record"] == record


@pytest.mark.parametrize("error,status", [("unauthorized", 401), ("forbidden", 403),
                                        ("client_record_conflict", 409), ("validation_error", 422)])
def test_permanent_rejections_persist_and_surface(tmp_path, monkeypatch, error, status):
    c = make_client()
    messages = []
    c.on_status = messages.append
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4())}
    c._queue_pending(record, str(path))
    post = MagicMock(return_value={"error": error, "http_status": status, "retryable": False})
    monkeypatch.setattr(c, "post_treatment", post)
    c.retry_pending(str(path))
    c.retry_pending(str(path))
    assert post.call_count == 1
    entry = json.loads(path.read_text())[0]
    assert entry["blocked"] is True and entry["record"] == record
    assert entry["error"]["error"] == error
    assert any("needs attention" in message for message in messages)


def test_restart_honors_429_across_entire_queue(tmp_path, monkeypatch):
    path = tmp_path / "pending.json"
    c = make_client()
    records = [{"client_record_id": str(uuid4())} for _ in range(2)]
    for record in records:
        c._queue_pending(record, str(path))
    post = MagicMock(return_value={
        "error": "rate_limited", "retryable": True, "retry_after_s": 300,
    })
    monkeypatch.setattr(c, "post_treatment", post)
    c.retry_pending(str(path))
    assert post.call_count == 1
    restarted = make_client()
    monkeypatch.setattr(restarted, "post_treatment", post)
    restarted.retry_pending(str(path), retry_blocked=True)
    assert post.call_count == 1


def test_queue_write_failure_never_posts(tmp_path, monkeypatch):
    c = make_client()
    post = MagicMock()
    monkeypatch.setattr(c, "post_treatment", post)
    monkeypatch.setattr(c, "_write_pending", lambda *a: _raise(OSError("disk full")))
    c.post_treatment_async(
        {"client_record_id": str(uuid4())}, str(tmp_path / "pending.json")
    ).result()
    c.close(wait=True)
    post.assert_not_called()


def test_http_request_headers_timeout_and_no_redirect(monkeypatch):
    c = make_client()
    response = MagicMock(status=200)
    response.read.return_value = b'{"server_time":"2026-09-15T12:00:00Z"}'
    response.__enter__.return_value = response
    opener = MagicMock()
    opener.open.return_value = response
    build = MagicMock(return_value=opener)
    monkeypatch.setattr("helpers.cloud_client.build_opener", build)
    c.ping()
    request = opener.open.call_args.args[0]
    assert request.full_url == "https://cloud.example/api/v1/device/ping"
    assert request.get_header("Authorization") == "Bearer t"
    assert request.get_header("X-device-id") == "d"
    assert opener.open.call_args.kwargs["timeout"] == 10
    redirect = build.call_args.args[0]
    assert redirect.redirect_request(None, None, 302, "", {}, "https://elsewhere") is None


@pytest.mark.parametrize("url,enabled", [("http://cloud.example", False),
                                        ("http://127.0.0.1:8000", True),
                                        ("https://cloud.example", True)])
def test_cloud_url_requires_https_except_local_test_server(url, enabled):
    assert CloudClient(url, "t", "d").enabled is enabled


def test_ping_does_not_claim_connection_on_unrelated_json(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a: {"status": "ok"})
    assert c.ping()["error"] == "invalid_response"


def test_valid_ping_reports_device_api_connection(monkeypatch):
    c = make_client()
    body = {"server_time": "2026-09-15T12:00:00Z", "device_name": "Test device",
            "min_app_version": "0.0.0"}
    monkeypatch.setattr(c, "_request", lambda *a: body)
    assert c.ping() == body


def test_retry_after_http_date_is_respected():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    deadline = datetime.now(timezone.utc) + timedelta(seconds=120)
    delay = CloudClient._retry_delay({}, {"Retry-After": format_datetime(deadline)})
    assert 119 <= delay <= 120


def test_operator_retry_preserves_body_after_auth_fixed(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4())}
    path.write_text(json.dumps([{"record": record, "blocked": True, "retry_at": 0,
                                 "error": {"error": "unauthorized", "retryable": False}}]))
    seen = []
    monkeypatch.setattr(c, "post_treatment", lambda body: seen.append(body) or receipt(body, 200))
    c.retry_pending(str(path), retry_blocked=True)
    assert seen == [record]
    assert json.loads(path.read_text()) == []


def test_duplicate_queue_id_cannot_replace_existing_body(tmp_path):
    c = make_client()
    path = tmp_path / "pending.json"
    record = {"client_record_id": str(uuid4()), "outcome": "completed"}
    assert c._queue_pending(record, str(path))
    assert c._queue_pending(record, str(path))
    assert not c._queue_pending(dict(record, outcome="fault"), str(path))
    assert json.loads(path.read_text()) == [{"record": record}]


def test_shutdown_finishes_submitted_write_without_uploading_queue(tmp_path, monkeypatch):
    from threading import Event

    c = make_client()
    path = tmp_path / "pending.json"
    entered, release = Event(), Event()
    write = c._queue_pending

    def pause_before_write(record, target):
        entered.set()
        assert release.wait(3)
        return write(record, target)

    monkeypatch.setattr(c, "_queue_pending", pause_before_write)
    post = MagicMock()
    monkeypatch.setattr(c, "post_treatment", post)
    record = {"client_record_id": str(uuid4())}
    future = c.post_treatment_async(record, str(path))
    assert entered.wait(3)
    c.close(wait=False)
    release.set()
    future.result(timeout=3)
    assert json.loads(path.read_text()) == [{"record": record}]
    post.assert_not_called()
