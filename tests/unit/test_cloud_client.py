"""CloudClient failure modes.

A patient lookup runs on a bare daemon thread, so it must ALWAYS return to
the UI (never raise); and the durable pending-upload queue must survive a
corrupt file and concurrent writers.
"""
import json

import pytest

from helpers.cloud_client import CloudClient

pytestmark = pytest.mark.unit


def make_client():
    return CloudClient(
        cloud_url="https://cloud.example", device_token="t", device_id="d"
    )


def _raise(exc):
    raise exc


def test_lookup_returns_none_on_non_json_body(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a, **k: _raise(ValueError("not json")))
    assert c.lookup_pin("1234") is None


def test_lookup_returns_none_for_non_object_json(monkeypatch):
    c = make_client()
    monkeypatch.setattr(c, "_request", lambda *a, **k: ["unexpected"])
    assert c.lookup_pin("1234") is None


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

    assert json.loads(path.read_text(encoding="utf-8")) == [{"client_record_id": "a"}]
    quarantined = [p for p in tmp_path.iterdir() if ".corrupt-" in p.name]
    assert len(quarantined) == 1
    assert not (tmp_path / "pending.json.tmp").exists()  # atomic replace


def test_retry_removes_only_uploaded_records(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    path.write_text(
        json.dumps([{"client_record_id": "a"}, {"client_record_id": "b"}]),
        encoding="utf-8",
    )

    def fake_post(record):
        if record["client_record_id"] == "a":
            # Another thread queues "c" while the retry is mid-flight
            c._queue_pending({"client_record_id": "c"}, str(path))
            return {"ok": True}
        return None  # "b" keeps failing

    monkeypatch.setattr(c, "post_treatment", fake_post)

    c.retry_pending(str(path))

    remaining = json.loads(path.read_text(encoding="utf-8"))
    assert [r["client_record_id"] for r in remaining] == ["b", "c"]


def test_retry_deletes_file_when_everything_uploads(tmp_path, monkeypatch):
    c = make_client()
    path = tmp_path / "pending.json"
    path.write_text(json.dumps([{"client_record_id": "a"}]), encoding="utf-8")
    monkeypatch.setattr(c, "post_treatment", lambda record: {"ok": True})

    c.retry_pending(str(path))

    assert not path.exists()
