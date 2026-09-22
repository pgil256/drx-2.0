"""Staff-authenticated release discovery and bounded, verified downloads."""

import hashlib
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Callable, Dict, Optional
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request
from uuid import UUID

from helpers.staff_client import StaffClient, StaffError
from helpers.cloud_client import CloudClient

MAX_RELEASE_BYTES = 256 * 1024 * 1024
DOWNLOAD_DEADLINE_S = 300


class ReleaseClient(StaffClient):
    """Keep release cookies separate from patient access and device bearer tokens."""

    def metadata(self, value: dict, platform: str) -> Dict:
        try:
            release = dict(value)
            release_id = str(UUID(release["id"]))
            size = release["size_bytes"]
            digest = release["sha256"]
            if (release["platform"] != platform or platform not in ("raspberry-pi", "arduino")
                    or type(size) is not int or not 0 < size <= MAX_RELEASE_BYTES
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise ValueError()
            expected = f"/api/v1/admin/releases/{release_id}/download"
            url = urlsplit(release["download_url"])
            origin = urlsplit(self.cloud_url)
            if (url.query or url.fragment or url.username or url.password
                    or url.path != expected or
                    (url.netloc and (url.scheme, url.netloc) != (origin.scheme, origin.netloc))
                    or (url.scheme and not url.netloc)):
                raise ValueError()
            for key, maximum in (("version", 160), ("filename", 255), ("notes", 8000),
                                 ("created_at", 64)):
                if not isinstance(release.get(key, ""), str) or len(release.get(key, "")) > maximum:
                    raise ValueError()
            extension = Path(release["filename"]).suffix.lower()
            allowed = (".zip",) if platform == "raspberry-pi" else (".zip", ".hex", ".bin", ".ino")
            if extension not in allowed:
                raise ValueError()
            release.update(id=release_id, download_url=expected, extension=extension)
            return release
        except (KeyError, TypeError, ValueError, AttributeError):
            raise StaffError(
                "invalid_release", "The cloud returned invalid release metadata.") from None

    def latest(self) -> Dict:
        self.check_context("devices.view")
        result = self.request("GET", "/releases")
        latest = result.get("latest")
        if not isinstance(latest, dict):
            raise StaffError("invalid_release", "The release list could not be read.")
        return {platform: (self.metadata(latest[platform], platform)
                           if latest.get(platform) else None)
                for platform in ("raspberry-pi", "arduino")}

    def download(self, release: Dict, directory: Path,
                 progress: Optional[Callable[[int, int], None]] = None,
                 cancelled: Optional[Callable[[], bool]] = None) -> Path:
        release = self.metadata(release, release.get("platform"))
        self.check_context("devices.view")
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / (release["id"] + release["extension"])
        descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=str(directory))
        deadline = time.monotonic() + DOWNLOAD_DEADLINE_S
        request = Request(self.cloud_url + release["download_url"],
                          headers={"Accept": "application/octet-stream"})
        try:
            with os.fdopen(descriptor, "wb") as output:
                with self._opener.open(request, timeout=10) as response:
                    if response.status != 200:
                        raise StaffError("download_failed", "The release download was rejected.")
                    if response.headers.get("Content-Type", "").split(";")[0] != (
                            "application/octet-stream"):
                        raise StaffError(
                            "download_failed", "The cloud did not return a release file.")
                    if response.headers.get("X-Checksum-SHA256") != release["sha256"]:
                        raise StaffError("checksum", "The download checksum header did not match.")
                    length = response.headers.get("Content-Length")
                    if length is not None and length != str(release["size_bytes"]):
                        raise StaffError("size", "The download size header did not match.")
                    total, digest = 0, hashlib.sha256()
                    while True:
                        if cancelled is not None and cancelled():
                            raise StaffError(
                                "cancelled", "Download cancelled; installed files unchanged.")
                        if time.monotonic() >= deadline:
                            raise StaffError(
                                "timeout", "The download timed out. Check the connection.")
                        block = response.read(64 * 1024)
                        if not block:
                            break
                        total += len(block)
                        if total > min(release["size_bytes"], MAX_RELEASE_BYTES):
                            raise StaffError("size", "The download exceeded its expected size.")
                        digest.update(block)
                        output.write(block)
                        if progress:
                            progress(total, release["size_bytes"])
                    if total != release["size_bytes"] or digest.hexdigest() != release["sha256"]:
                        raise StaffError("checksum", "Download verification failed. Please retry.")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            return destination
        except HTTPError as exc:
            if exc.code == 429:
                self._not_before = time.monotonic() + CloudClient._retry_delay({}, exc.headers)
            if exc.code in (401, 403):
                self.context = {}
            messages = {
                401: "Cloud session expired. Sign in again.",
                403: "This account cannot download releases for the selected clinic.",
                404: "The release file is missing. Refresh releases or contact your administrator.",
                429: "The cloud is limiting downloads. Wait before trying again.",
            }
            raise StaffError("download_failed", messages.get(exc.code, "Release download failed."))
        except StaffError:
            raise
        except Exception:
            raise StaffError(
                "download_failed", "Download interrupted. Installed files are unchanged.")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
