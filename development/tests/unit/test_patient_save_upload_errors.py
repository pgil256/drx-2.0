"""Cloud patient writes and automatic-upload failure notifications."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest

from helpers.cloud_client import CloudClient

pytestmark = pytest.mark.unit


def test_upload_failure_alerts_once_and_retries_without_losing_record(tmp_path, monkeypatch):
    errors = Mock()
    client = CloudClient("https://cloud.example", "token", "device", on_upload_error=errors)
    record = {"client_record_id": str(uuid4()), "patient_id": str(uuid4())}
    path = str(tmp_path / "pending.json")
    clock = [1000]
    monkeypatch.setattr("helpers.cloud_client.time.time", lambda: clock[0])
    post = Mock(return_value={"error": "unavailable", "retryable": True})
    monkeypatch.setattr(client, "post_treatment", post)
    client.post_treatment_async(record, path).result(timeout=3)
    errors.assert_called_once()
    message, manual_retry = errors.call_args.args
    assert "saved on this device" in message and "retry automatically" in message
    assert manual_retry is False
    client.retry_pending(path)
    clock[0] += 500
    client.retry_pending(path)
    assert errors.call_count == 1
    assert json.loads((tmp_path / "pending.json").read_text())[0]["record"] == record
    post.return_value = {"_http_status": 201, "id": str(uuid4()),
                         "client_record_id": record["client_record_id"],
                         "received_at": "2026-09-21T12:00:00Z"}
    clock[0] += 500
    client.retry_pending(path)
    assert json.loads((tmp_path / "pending.json").read_text()) == []
    assert client._last_status == "Treatments synced"
    client.close()


def test_disk_failure_does_not_claim_record_is_saved(tmp_path, monkeypatch):
    errors = Mock()
    client = CloudClient("https://cloud.example", "token", "device", on_upload_error=errors)
    monkeypatch.setattr(client, "_queue_pending", lambda *args: False)
    post = Mock()
    monkeypatch.setattr(client, "post_treatment", post)
    client.post_treatment_async({"client_record_id": str(uuid4())},
                                str(tmp_path / "pending.json")).result(timeout=3)
    message, can_retry = errors.call_args.args
    assert "could not be saved" in message
    assert "is saved" not in message
    assert not can_retry
    post.assert_not_called()
    client.close()


def test_rejected_upload_is_saved_and_has_manual_recovery(tmp_path, monkeypatch):
    errors = Mock()
    client = CloudClient("https://cloud.example", "token", "device", on_upload_error=errors)
    monkeypatch.setattr(client, "post_treatment", lambda *args: {
        "error": "unauthorized", "retryable": False,
    })
    client.post_treatment_async({"client_record_id": str(uuid4())},
                                str(tmp_path / "pending.json")).result(timeout=3)
    assert errors.call_args.args[1] is True
    assert "saved on this device" in errors.call_args.args[0]
    client.close()
