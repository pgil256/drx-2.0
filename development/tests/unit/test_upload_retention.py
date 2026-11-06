"""The upload queue keeps patient records private and does not keep refused ones forever.

pending_uploads.json holds treatment records with patient IDs. It used to be
written with the default umask, and records the cloud refused (non-retryable)
plus quarantined .corrupt-* queues stayed on the device indefinitely.
"""
import json
import os
import stat
import time
from uuid import uuid4

import pytest

import helpers.cloud_client as cloud_module
from helpers.cloud_client import CloudClient

pytestmark = pytest.mark.unit

DAY = 24 * 3600
posix_only = pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")


def make_client():
    return CloudClient(cloud_url="https://cloud.example", device_token="t", device_id="d")


def entry(error=None, blocked=None, blocked_at=None, retry_at=0):
    item = {"record": {"client_record_id": str(uuid4())}, "retry_at": retry_at}
    if error is not None:
        item["error"] = {"error": error, "retryable": not blocked}
        item["blocked"] = bool(blocked)
    if blocked_at is not None:
        item["blocked_at"] = blocked_at
    return item


def write(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ids(entries):
    return {item["record"]["client_record_id"] for item in entries}


def retain(client, path):
    with client._pending_lock:
        client._apply_retention(str(path))


@posix_only
def test_queue_file_and_directory_are_private(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir(mode=0o755)
    path = directory / "pending_uploads.json"

    CloudClient._write_pending(str(path), [entry()])

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_expired_rejected_records_are_removed_and_others_kept(tmp_path):
    now = time.time()
    path = tmp_path / "pending_uploads.json"
    old_rejected = entry("validation_error", True, now - 91 * DAY)
    new_rejected = entry("validation_error", True, now - 10 * DAY)
    old_auth = entry("unauthorized", True, now - 400 * DAY)
    retryable = entry("unavailable", False, retry_at=now + 60)
    plain = entry()
    write(path, [old_rejected, new_rejected, old_auth, retryable, plain])

    retain(make_client(), path)

    assert ids(read(path)) == ids([new_rejected, old_auth, retryable, plain])


def test_rejected_records_beyond_the_count_limit_drop_oldest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(CloudClient, "REJECTED_MAX_COUNT", 3)
    now = time.time()
    path = tmp_path / "pending_uploads.json"
    rejected = [entry("conflict", True, now - age * DAY) for age in (5, 4, 3, 2, 1)]
    retryable = entry("unavailable", False)
    write(path, rejected + [retryable])

    retain(make_client(), path)

    assert ids(read(path)) == ids(rejected[2:] + [retryable])


def test_records_rejected_before_the_upgrade_start_their_clock_now(tmp_path):
    path = tmp_path / "pending_uploads.json"
    legacy = entry("validation_error", True)  # no blocked_at
    write(path, [legacy])
    before = time.time()

    retain(make_client(), path)

    [kept] = read(path)
    assert kept["blocked_at"] >= before


def test_retry_stamps_a_rejection_once_and_clears_it_when_retryable(tmp_path, monkeypatch):
    path = tmp_path / "pending_uploads.json"
    pending = entry()
    write(path, [pending])
    client = make_client()
    monkeypatch.setattr(client, "post_treatment",
                        lambda record: {"error": "validation_error", "retryable": False})

    def expire_backoff():
        # Explicit retries honour the backoff; let it elapse between calls.
        items = read(path)
        items[0]["retry_at"] = 0
        write(path, items)

    client.retry_pending(str(path))
    first = read(path)[0]["blocked_at"]
    expire_backoff()
    client.retry_pending(str(path), retry_blocked=True)
    assert read(path)[0]["attempts"] == 2
    assert read(path)[0]["blocked_at"] == first

    monkeypatch.setattr(client, "post_treatment",
                        lambda record: {"error": "unavailable", "retryable": True})
    expire_backoff()
    client.retry_pending(str(path), retry_blocked=True)
    assert read(path)[0]["attempts"] == 3
    assert "blocked_at" not in read(path)[0]


def test_old_unreadable_queues_are_removed(tmp_path, monkeypatch):
    path = tmp_path / "pending_uploads.json"
    corrupt = tmp_path / "pending_uploads.json.corrupt-abc"
    corrupt.write_text("not json", encoding="utf-8")
    client = make_client()

    retain(client, path)
    assert corrupt.exists()

    later = time.time() + 91 * DAY
    monkeypatch.setattr(cloud_module.time, "time", lambda: later)
    retain(client, path)
    assert not corrupt.exists()


def test_purge_removes_rejected_records_and_unreadable_queues_only(tmp_path):
    now = time.time()
    path = tmp_path / "pending_uploads.json"
    rejected = entry("validation_error", True, now)
    auth = entry("forbidden", True, now)
    retryable = entry("unavailable", False)
    write(path, [rejected, auth, retryable])
    corrupt = tmp_path / "pending_uploads.json.corrupt-abc"
    corrupt.write_text("not json", encoding="utf-8")
    client = make_client()

    assert client.purge_counts(str(path)) == {"records": 1, "files": 1}
    assert client.purge_rejected(str(path)) == {"records": 1, "files": 1}

    assert ids(read(path)) == ids([auth, retryable])
    assert not corrupt.exists()


def test_purge_leaves_an_unreadable_live_queue_for_support(tmp_path):
    path = tmp_path / "pending_uploads.json"
    path.write_text("not json", encoding="utf-8")
    client = make_client()

    with pytest.raises(ValueError):
        client.purge_rejected(str(path))
    assert path.read_text(encoding="utf-8") == "not json"
    assert not list(tmp_path.glob("pending_uploads.json.corrupt-*"))
