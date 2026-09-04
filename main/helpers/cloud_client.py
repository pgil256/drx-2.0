"""HTTP client for the kneespa-cloud Device API.

Runs synchronous stdlib calls; callers are responsible for threading.
"""
import json
import os
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from helpers.logging import setup_logger


class CloudClient:
    TIMEOUT_S = 10
    # One lock for the pending-uploads file: the boot-time retry thread and
    # the per-treatment upload threads used to read-modify-write it
    # concurrently, and a crash mid-dump left a file nothing could parse.
    _pending_lock = threading.Lock()

    def __init__(self, cloud_url=None, device_token=None, device_id=None):
        self.logger = setup_logger(component="Cloud")
        self.cloud_url = (
            cloud_url or os.environ.get("KNEESPA_CLOUD_URL", "")
        ).rstrip("/")
        self.device_token = device_token or os.environ.get(
            "KNEESPA_DEVICE_TOKEN", ""
        )
        self.device_id = device_id or os.environ.get("KNEESPA_DEVICE_ID", "")
        self.enabled = bool(
            self.cloud_url and self.device_token and self.device_id
        )
        if not self.enabled:
            self.logger.info(
                "Cloud disabled (KNEESPA_CLOUD_URL / _DEVICE_TOKEN / _DEVICE_ID)"
            )

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.device_token}",
            "X-Device-Id": self.device_id,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, body=None):
        url = f"{self.cloud_url}{path}"
        data = json.dumps(body).encode("utf-8") if body else None
        req = Request(url, data=data, headers=self._headers(), method=method)
        resp = urlopen(req, timeout=self.TIMEOUT_S)
        return json.loads(resp.read().decode("utf-8"))

    def ping(self):
        if not self.enabled:
            return None
        try:
            return self._request("GET", "/api/v1/device/ping")
        except Exception as e:
            self.logger.warning("Cloud ping failed: %s", e)
            return None

    def lookup_pin(self, pin):
        """Resolve a patient PIN. Returns the patient dict, an ``{"error": ...}``
        dict for known refusals, or ``None`` when the cloud is unusable."""
        if not self.enabled:
            return None
        try:
            result = self._request(
                "POST", "/api/v1/device/patients/lookup", {"pin": pin}
            )
        except HTTPError as e:
            if e.code == 404:
                return {"error": "unknown_pin"}
            if e.code == 429:
                return {"error": "rate_limited"}
            self.logger.warning("Cloud lookup HTTP %d", e.code)
            return None
        except Exception as e:
            # URLError/OSError, but also a non-JSON 200 (captive portal,
            # proxy error page): this runs on a bare daemon thread, and an
            # escaped exception meant the UI never heard back at all.
            self.logger.warning("Cloud lookup failed: %s", e)
            return None
        # The UI indexes the result as a mapping; a JSON scalar or list is
        # not a patient record.
        return result if isinstance(result, dict) else None

    def post_treatment(self, record):
        if not self.enabled:
            return None
        try:
            return self._request("POST", "/api/v1/device/treatments", record)
        except Exception as e:
            self.logger.warning("Treatment upload failed: %s", e)
            return None

    def post_treatment_async(self, record, pending_path=None):
        def _upload():
            result = self.post_treatment(record)
            if result is None and pending_path:
                self._queue_pending(record, pending_path)

        threading.Thread(target=_upload, daemon=True).start()

    # ----- pending-upload queue (durable across restarts) -----
    @staticmethod
    def _record_key(record):
        if isinstance(record, dict) and record.get("client_record_id"):
            return str(record["client_record_id"])
        return json.dumps(record, sort_keys=True)

    def _read_pending(self, pending_path):
        """Return the queued records. An unreadable file is moved aside so
        one corrupt write (power loss mid-dump) cannot disable queuing forever."""
        if not os.path.exists(pending_path):
            return []
        try:
            with open(pending_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                raise ValueError("pending uploads file is not a JSON list")
            return data
        except (OSError, ValueError) as e:  # JSONDecodeError is a ValueError
            quarantine = f"{pending_path}.corrupt-{int(time.time())}"
            self.logger.error(
                "Pending uploads file unreadable (%s); moving it to %s", e, quarantine
            )
            try:
                os.replace(pending_path, quarantine)
            except OSError as move_err:
                self.logger.error("Could not quarantine pending uploads: %s", move_err)
            return []

    @staticmethod
    def _write_pending(pending_path, records):
        """Atomically replace the queue file (tmp + os.replace)."""
        if not records:
            if os.path.exists(pending_path):
                os.remove(pending_path)
            return
        d = os.path.dirname(os.path.abspath(pending_path)) or "."
        os.makedirs(d, exist_ok=True)
        tmp = f"{pending_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f)
        os.replace(tmp, pending_path)

    def retry_pending(self, pending_path):
        if not self.enabled or not pending_path:
            return
        with self._pending_lock:
            pending = self._read_pending(pending_path)
        if not pending:
            return
        uploaded = set()
        for record in pending:
            if self.post_treatment(record) is not None:
                uploaded.add(self._record_key(record))
        if not uploaded:
            return
        # Re-read under the lock: an upload thread may have queued more
        # records while the posts above were in flight.
        with self._pending_lock:
            try:
                current = self._read_pending(pending_path)
                remaining = [
                    r for r in current if self._record_key(r) not in uploaded
                ]
                self._write_pending(pending_path, remaining)
            except OSError as e:
                self.logger.warning("Could not update pending uploads: %s", e)

    def _queue_pending(self, record, pending_path):
        try:
            with self._pending_lock:
                pending = self._read_pending(pending_path)
                pending.append(record)
                self._write_pending(pending_path, pending)
            self.logger.info("Queued upload for retry (%d pending)", len(pending))
        except Exception as e:
            self.logger.error("Could not queue pending upload: %s", e)
