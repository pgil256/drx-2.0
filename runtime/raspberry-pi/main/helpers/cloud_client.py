"""Bounded device API calls and a durable, receipt-checked treatment outbox.

Synchronous methods are for background callers. Asynchronous entry points run
disk/network work on a dedicated executor. Records are persisted before POST.
"""

import json
import math
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4

from helpers.cloud_contract import cloud_error_message
from helpers.device_records import read_json, write_json
from helpers.logging import setup_logger


class _NoRedirect(HTTPRedirectHandler):
    """Send credentials only to the explicitly configured origin."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class CloudClient:
    TIMEOUT_S = 10
    _pending_lock = threading.Lock()

    def __init__(self, cloud_url: Optional[str] = None, device_token: Optional[str] = None,
                 device_id: Optional[str] = None,
                 on_status: Optional[Callable[[str], None]] = None,
                 on_upload_error: Optional[Callable[[str, bool], None]] = None) -> None:
        self.logger = setup_logger(component="Cloud")
        self.cloud_url = (cloud_url or os.environ.get("KNEESPA_CLOUD_URL", "")).rstrip("/")
        self.device_token = device_token or os.environ.get("KNEESPA_DEVICE_TOKEN", "")
        self.device_id = device_id or os.environ.get("KNEESPA_DEVICE_ID", "")
        try:
            url = urlsplit(self.cloud_url)
        except ValueError:
            url = urlsplit("")
        secure = url.scheme == "https" or (
            url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
        )
        self.enabled = bool(
            self.cloud_url and self.device_token and self.device_id and secure
            and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment
        )
        self.on_status = on_status
        self.on_upload_error = on_upload_error
        self._reported_upload_errors = {}
        self._last_status = None
        self._lookup_not_before = 0.0
        self._closing = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cloud-outbox")
        self._retry_future: Optional[Future] = None
        self._operation_lock = threading.Lock()
        if not self.enabled:
            self.logger.info("Cloud disabled: incomplete configuration or unsupported URL")

    def _notify(self, message: str) -> None:
        if message == self._last_status:
            return
        self._last_status = message
        self.logger.info("%s", message)
        if self.on_status is not None:
            try:
                self.on_status(message)
            except Exception:
                self.logger.warning("Cloud status display is no longer available")

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.device_token}", "X-Device-Id": self.device_id,
                "Content-Type": "application/json"}

    def _report_upload_error(self, key: str, result: Dict[str, Any],
                             saved: bool = True) -> None:
        """Alert once per unresolved record; timer retries must not reopen windows."""
        signature = (result.get("error"), result.get("retryable", False), saved)
        previous = self._reported_upload_errors.get(key)
        if (previous and previous[0] == signature) or self._closing.is_set():
            return
        message = cloud_error_message(result)
        retryable = result.get("retryable", False)
        if saved:
            message += "\n\nThe treatment is saved on this device. "
            message += ("Upload will retry automatically." if retryable else
                        "Correct the problem, then retry the upload.")
        else:
            message += "\n\nThe treatment could not be saved for automatic upload."
        self._reported_upload_errors[key] = (signature, message, saved and not retryable)
        self._notify("Upload failed: " + cloud_error_message(result))
        if self.on_upload_error is not None:
            try:
                failures = list(self._reported_upload_errors.values())
                messages = list(dict.fromkeys(failure[1] for failure in failures))
                self.on_upload_error("\n\n".join(messages), any(item[2] for item in failures))
            except Exception:
                self.logger.warning("Upload error display is no longer available")

    @staticmethod
    def _retry_delay(body: Dict[str, Any], headers: Any) -> int:
        """Honor body delays and both seconds/date forms of Retry-After."""
        delays = [1.0]
        for raw in (body.get("retry_after_s"), headers.get("Retry-After") if headers else None):
            if raw is None:
                continue
            try:
                delay = float(raw)
            except (TypeError, ValueError):
                try:
                    deadline = parsedate_to_datetime(str(raw))
                    delay = (deadline - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    continue
            if math.isfinite(delay):
                delays.append(delay)
        return math.ceil(max(delays)) if len(delays) > 1 else 60

    def _request(self, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = json.dumps(body, allow_nan=False).encode("utf-8") if body is not None else None
        request = Request(self.cloud_url + path, data=data, headers=self._headers(), method=method)
        with build_opener(_NoRedirect()).open(request, timeout=self.TIMEOUT_S) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            result["_http_status"] = response.status
            return result

    def _call(self, method: str, path: str,
              body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"error": "disabled", "retryable": False}
        try:
            result = self._request(method, path, body)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except (OSError, ValueError, UnicodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            detail = payload.get("detail")
            structured = detail if isinstance(detail, dict) else payload
            default = {
                401: "unauthorized", 403: "forbidden", 404: "unknown_pin",
                409: "conflict", 422: "validation_error", 429: "rate_limited",
            }.get(exc.code, "http_error")
            result = {"error": structured.get("error", default), "detail": detail,
                      "http_status": exc.code,
                      "retryable": exc.code in (408, 429) or exc.code >= 500}
            if isinstance(structured.get("reason"), str):
                result["reason"] = structured["reason"]
            if exc.code == 429 or (exc.headers and exc.headers.get("Retry-After")):
                result["retry_after_s"] = self._retry_delay(structured, exc.headers)
            return result
        except (ValueError, UnicodeError):
            return {"error": "invalid_response", "retryable": True}
        except Exception:
            # Remote exception text can include credentials, URLs or PINs.
            return {"error": "unavailable", "retryable": True}

    def ping(self) -> Dict[str, Any]:
        result = self._call("GET", "/api/v1/device/ping")
        if "error" in result:
            return result
        try:
            server_time = datetime.fromisoformat(result["server_time"].replace("Z", "+00:00"))
            if (server_time.utcoffset() is None or not isinstance(result["device_name"], str)
                    or not isinstance(result["min_app_version"], str)):
                raise ValueError("Invalid device ping")
        except (KeyError, TypeError, ValueError, AttributeError):
            return {"error": "invalid_response", "retryable": True}
        return result

    def ping_async(self) -> Future:
        def check() -> None:
            if self._closing.is_set():
                return
            result = self.ping()
            self._notify(cloud_error_message(result) if "error" in result else "Cloud connected")

        return self._executor.submit(check)

    def lookup_pin(self, pin: str) -> Dict[str, Any]:
        """Preserve leading zeros and honor the server's lookup cooldown."""
        if not isinstance(pin, str) or re.fullmatch(r"[0-9]{4}", pin) is None:
            return {"error": "invalid_pin", "retryable": False}
        wait = self._lookup_not_before - time.monotonic()
        if wait > 0:
            return {"error": "rate_limited", "retry_after_s": math.ceil(wait), "retryable": True}
        result = self._call("POST", "/api/v1/device/patients/lookup", {"pin": pin})
        if result.get("error") == "rate_limited":
            self._lookup_not_before = time.monotonic() + result.get("retry_after_s", 60)
        return result

    def post_treatment(self, record: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("POST", "/api/v1/device/treatments", record)

    def post_treatment_async(self, record: Dict[str, Any],
                             pending_path: Optional[str] = None) -> Future:
        """Snapshot now, then persist on the background thread before sending."""
        snapshot = deepcopy(record)

        def upload() -> None:
            self._notify("Uploading treatment…")
            if not pending_path or not self._queue_pending(snapshot, pending_path):
                self._report_upload_error(
                    self._record_key(snapshot), {"error": "queue_error"}, saved=False
                )
                return
            if not self.enabled:
                self._report_upload_error(self._record_key(snapshot), {"error": "disabled"})
                return
            self.retry_pending(pending_path)

        return self._executor.submit(upload)

    def retry_pending_async(self, pending_path: str, retry_blocked: bool = False) -> Future:
        """Coalesce timer requests while a retry is already queued/running."""
        if self._retry_future is None or self._retry_future.done():
            self._retry_future = self._executor.submit(
                self.retry_pending, pending_path, retry_blocked
            )
        return self._retry_future

    def sync_summary(self, pending_path: str) -> Dict[str, Any]:
        """Expose counts and receipt time without exposing any treatment records."""
        try:
            with self._pending_lock:
                entries = self._read_pending(pending_path, quarantine=False)
                path = Path(pending_path)
                if any(path.parent.glob(path.name + ".corrupt-*")):
                    raise ValueError("A preserved upload queue needs attention")
            pending = len(entries)
            blocked = sum(entry.get("blocked") is True for entry in entries)
        except (OSError, ValueError, TypeError, KeyError):
            return {"pending": None, "blocked": None, "last_sync": "Unknown",
                    "message": "An unreadable or preserved upload queue needs support attention."}
        try:
            stamp = read_json(Path(pending_path).with_name("sync-status.json"))
            last_sync = stamp.get("last_successful_sync", "Not recorded yet")
        except (OSError, ValueError, AttributeError):
            last_sync = "Not recorded yet"
        return {"pending": pending, "blocked": blocked, "last_sync": last_sync,
                "message": self._last_status or ("Not checked" if self.enabled else "Not configured")}

    def _record_sync_success(self, pending_path: str) -> None:
        try:
            write_json(Path(pending_path).with_name("sync-status.json"), {
                "last_successful_sync": datetime.now(timezone.utc).isoformat(),
            })
        except OSError:
            self.logger.warning("Could not save the last successful sync time")

    def close(self, wait: bool = False) -> None:
        """Drain submitted writes on normal process exit after hardware cleanup."""
        self._closing.set()
        self._executor.shutdown(wait=wait)

    @staticmethod
    def _record_key(record: Dict[str, Any]) -> str:
        return str(record["client_record_id"])

    def _read_pending(self, pending_path: str, quarantine: bool = True) -> List[Dict[str, Any]]:
        if not os.path.exists(pending_path):
            return []
        try:
            with open(pending_path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            if not isinstance(data, list):
                raise ValueError("Pending uploads must be a list")
            entries = []
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("Invalid pending record")
                # Migrate old raw records without changing their IDs or bodies.
                entry = item if "record" in item else {"record": item}
                self._record_key(entry["record"])
                retry_at = entry.get("retry_at", 0)
                attempts = entry.get("attempts", 0)
                if (not isinstance(entry.get("error", {}), dict)
                        or not isinstance(retry_at, (int, float)) or not math.isfinite(retry_at)
                        or not isinstance(attempts, int) or attempts < 0):
                    raise ValueError("Invalid queue retry metadata")
                entries.append(entry)
            return entries
        except (ValueError, KeyError, TypeError):
            if not quarantine:
                raise
            quarantine = f"{pending_path}.corrupt-{uuid4().hex}"
            # Propagate quarantine failures, so unreadable data is never overwritten.
            os.replace(pending_path, quarantine)
            self._notify("Unreadable cloud queue preserved for support; contact support")
            return []

    @staticmethod
    def _write_pending(pending_path: str, entries: List[Dict[str, Any]]) -> None:
        directory = os.path.dirname(os.path.abspath(pending_path))
        os.makedirs(directory, exist_ok=True)
        temporary = f"{pending_path}.tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(entries, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pending_path)
        if os.name == "posix":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _queue_pending(self, record: Dict[str, Any], pending_path: str) -> bool:
        try:
            with self._pending_lock:
                entries = self._read_pending(pending_path)
                for entry in entries:
                    if self._record_key(entry["record"]) == self._record_key(record):
                        if entry["record"] != record:
                            raise ValueError("A queued ID cannot refer to a different body")
                        return True
                entries.append({"record": record})
                self._write_pending(pending_path, entries)
            return True
        except (OSError, ValueError, KeyError, TypeError):
            self.logger.error("Could not persist treatment record in cloud queue")
            return False

    @staticmethod
    def _matching_receipt(result: Any, record: Dict[str, Any]) -> bool:
        if not isinstance(result, dict) or result.get("_http_status") not in (200, 201):
            return False
        try:
            UUID(result["id"])
            received = datetime.fromisoformat(result["received_at"].replace("Z", "+00:00"))
            return (received.utcoffset() is not None
                    and UUID(result["client_record_id"]) == UUID(record["client_record_id"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            return False

    def retry_pending(self, pending_path: str, retry_blocked: bool = False) -> None:
        """Delete only receipted entries; retain backoff and rejection details."""
        if not self.enabled or not pending_path or self._closing.is_set():
            return
        with self._operation_lock:
            try:
                self._retry_pending(pending_path, retry_blocked)
            except (OSError, ValueError, KeyError, TypeError):
                self._report_upload_error("queue", {"error": "queue_error"}, saved=False)

    def _retry_pending(self, pending_path: str, retry_blocked: bool) -> None:
        if retry_blocked:
            self._reported_upload_errors.clear()
        with self._pending_lock:
            entries = self._read_pending(pending_path)
        # A 429 pauses the device's entire upload queue, including records
        # enqueued later. Persisted deadlines survive application restarts.
        for entry in entries:
            if (entry.get("error", {}).get("error") == "rate_limited"
                    and entry.get("retry_at", 0) > time.time()):
                self._notify("Upload pending: " + cloud_error_message(entry["error"]))
                self._report_upload_error(self._record_key(entry["record"]), entry["error"])
                return
        for entry in entries:
            if self._closing.is_set():
                return
            if entry.get("blocked") and not retry_blocked:
                self._notify("Upload needs attention: " + cloud_error_message(entry.get("error")))
                self._report_upload_error(self._record_key(entry["record"]), entry.get("error", {}))
                continue
            if entry.get("retry_at", 0) > time.time():
                self._notify("Upload pending: " + cloud_error_message(entry.get("error")))
                self._report_upload_error(self._record_key(entry["record"]), entry.get("error", {}))
                continue  # Explicit retries must also honor Retry-After.
            record = entry["record"]
            result = self.post_treatment(record)
            matched = self._matching_receipt(result, record)
            if not matched:
                if not isinstance(result, dict) or "error" not in result:
                    result = {"error": "invalid_response", "retryable": True}
                attempts = entry.get("attempts", 0) + 1
                delay = max(result.get("retry_after_s", 0), min(300, 5 * 2 ** min(attempts, 6)))
                entry = dict(
                    entry, attempts=attempts, error=result,
                    blocked=not result.get("retryable", False), retry_at=time.time() + delay,
                )
            with self._pending_lock:
                current = self._read_pending(pending_path)
                updated = []
                for pending in current:
                    if self._record_key(pending["record"]) == self._record_key(record):
                        if not matched:
                            updated.append(entry)
                    else:
                        updated.append(pending)
                self._write_pending(pending_path, updated)
            if not matched:
                prefix = "Upload needs attention: " if entry["blocked"] else "Upload pending: "
                self._notify(prefix + cloud_error_message(result))
                self._report_upload_error(self._record_key(record), result)
                if result.get("error") in ("rate_limited", "unauthorized", "forbidden"):
                    break
            else:
                self._record_sync_success(pending_path)
                self._reported_upload_errors.pop(self._record_key(record), None)
        with self._pending_lock:
            remaining = self._read_pending(pending_path)
        if entries and not remaining:
            self._notify("Treatments synced")
