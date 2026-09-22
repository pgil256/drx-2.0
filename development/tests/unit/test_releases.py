"""Release verification and isolated installation tests; never flash the host."""

import hashlib
import io
from pathlib import Path
import stat
from unittest.mock import Mock
from urllib.error import HTTPError
import zipfile

import pytest

from helpers import release_installer as module
from helpers.device_records import read_json, write_json
from helpers.release_client import ReleaseClient
from helpers.release_installer import ReleaseInstaller, extract_package, firmware_recovery, validate_hex
from helpers.staff_client import StaffError

pytestmark = pytest.mark.unit
RELEASE_ID = "e9984c77-9bea-41b3-9d3d-ebaf5dd8b660"


def metadata(data=b"release", platform="raspberry-pi", filename="software.zip"):
    return dict(id=RELEASE_ID, platform=platform, filename=filename, version="2.1",
                notes="Test release", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                download_url=f"/api/v1/admin/releases/{RELEASE_ID}/download")


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, release):
        super().__init__(data)
        self.headers = {"Content-Type": "application/octet-stream",
                        "X-Checksum-SHA256": release["sha256"],
                        "Content-Length": str(release["size_bytes"])}


@pytest.mark.parametrize("change", [
    {"download_url": "https://foreign.test/api/v1/admin/releases/x/download"},
    {"download_url": f"/api/v1/admin/releases/{RELEASE_ID}/download?redirect=1"},
    {"size_bytes": True}, {"size_bytes": 0}, {"size_bytes": 257 * 1024 * 1024},
    {"sha256": "invalid"}, {"id": "not-a-uuid"}, {"platform": "arduino"},
    {"filename": "software.exe"}, {"notes": "x" * 8001},
])
def test_metadata_rejects_malformed_or_foreign_release(change):
    client = ReleaseClient("https://cloud.example.test")
    with pytest.raises(StaffError):
        client.metadata(dict(metadata(), **change), "raspberry-pi")


def test_latest_requires_staff_permission_and_does_not_sort_version():
    client = ReleaseClient("https://cloud.example.test")
    client.check_context = Mock()
    client.request = Mock(return_value={"latest": {
        "raspberry-pi": dict(metadata(), version="older-version"), "arduino": None}})
    assert client.latest()["raspberry-pi"]["version"] == "older-version"
    client.check_context.assert_called_once_with("devices.view")
    client.request.assert_called_once_with("GET", "/releases")


@pytest.mark.parametrize("failure", [None, "hash", "size", "header", "content", "cancel", "redirect"])
def test_download_verifies_actual_bytes_and_cleans_partial_files(tmp_path, failure):
    data = b"verified release bytes"
    release = metadata(data)
    client = ReleaseClient("https://cloud.example.test")
    client.check_context = Mock()
    response = Response(b"x" * len(data) if failure == "hash" else data, release)
    if failure == "size":
        response = Response(data + b"extra", release)
    if failure == "header":
        response.headers["X-Checksum-SHA256"] = "0" * 64
    if failure == "content":
        response.headers["Content-Type"] = "text/html"
    client._opener = Mock()
    client._opener.open.return_value = response
    if failure == "redirect":
        client._opener.open.side_effect = HTTPError("", 302, "redirect", {}, io.BytesIO())
    if failure:
        with pytest.raises(StaffError):
            client.download(release, tmp_path, cancelled=lambda: failure == "cancel")
        assert list(tmp_path.iterdir()) == []
    else:
        path = client.download(release, tmp_path)
        assert path.read_bytes() == data
        request = client._opener.open.call_args.args[0]
        assert request.full_url == client.cloud_url + release["download_url"]
        assert request.get_header("Authorization") is None
        assert list(tmp_path.iterdir()) == [path]


def software_package(tmp_path, extra=None):
    package = tmp_path / "software.zip"
    files = {"main/kneespa.py": "VALUE = 'new'\n", "main/ui/app_shell.py": "",
             "main/config/constants.py": "APP_VERSION = '2.1'\n", "main/helpers/arduino.py": "",
             "launch.sh": "#!/bin/sh\n"}
    files.update(extra or {})
    with zipfile.ZipFile(package, "w") as archive:
        for name, content in files.items():
            info = zipfile.ZipInfo()
            info.filename = "runtime/raspberry-pi/" + name
            archive.writestr(info, content)
    return package


@pytest.mark.parametrize("bad", ["../escape.py", "main/../../escape.py", "main/.env",
                                    "main/kneespa.cfg", "main/logs/data", "main\\bad.py"])
def test_archive_rejects_traversal_or_device_state(tmp_path, bad):
    path = software_package(tmp_path, {bad: "secret"})
    with pytest.raises(ValueError):
        extract_package(path, tmp_path / "output", "raspberry-pi")
    assert not (tmp_path / "output").exists()


def test_archive_rejects_links_and_duplicate_paths(tmp_path):
    path = software_package(tmp_path)
    link = zipfile.ZipInfo("runtime/raspberry-pi/main/link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(link, "../../../devices/config")
    with pytest.raises(ValueError, match="Links"):
        extract_package(path, tmp_path / "output", "raspberry-pi")
    path = software_package(tmp_path, {"main/KneeSpa.py": "duplicate"})
    with pytest.raises(ValueError, match="duplicate"):
        extract_package(path, tmp_path / "output", "raspberry-pi")


@pytest.fixture
def prepared(tmp_path):
    runtime, state = tmp_path / "runtime", tmp_path / "devices/raspberry-pi"
    (runtime / "raspberry-pi/main").mkdir(parents=True)
    (runtime / "raspberry-pi/main/kneespa.py").write_text("OLD = True\n")
    state.mkdir(parents=True)
    (state / "kneespa.cfg").write_text("calibration kept")
    package = software_package(tmp_path)
    release = ReleaseClient("https://cloud.example.test").metadata(metadata(package.read_bytes()),
                                                                  "raspberry-pi")
    installer = ReleaseInstaller(runtime, state)
    return installer, installer.prepare(package, release)


def test_software_installs_with_backup_and_preserves_device_state(prepared):
    installer, job = prepared
    installer.install(job, lambda _: None)
    assert "new" in (installer.runtime / "raspberry-pi/main/kneespa.py").read_text()
    assert (Path(job["work"]) / "previous-software/main/kneespa.py").read_text() == "OLD = True\n"
    assert (installer.state / "kneespa.cfg").read_text() == "calibration kept"
    assert read_json(installer.root / "installed.json")["raspberry-pi"]["id"] == RELEASE_ID


def test_software_activation_failure_restores_previous_install(prepared, monkeypatch):
    installer, job = prepared
    original = module.os.replace

    def fail_candidate(source, target):
        if Path(source).name.startswith(".software-next-"):
            raise OSError("simulated disk failure")
        original(source, target)

    monkeypatch.setattr(module.os, "replace", fail_candidate)
    with pytest.raises(OSError):
        installer.install(job, lambda _: None)
    assert (installer.runtime / "raspberry-pi/main/kneespa.py").read_text() == "OLD = True\n"
    assert not (installer.root / "installed.json").exists()
    assert not list(installer.runtime.glob(".software-*"))


def test_prepared_files_cannot_change_after_verification(prepared):
    installer, job = prepared
    (Path(job["source"]) / "main/kneespa.py").write_text("altered")
    with pytest.raises(ValueError, match="changed"):
        installer.install(job, lambda _: None)
    assert (installer.runtime / "raspberry-pi/main/kneespa.py").read_text() == "OLD = True\n"


def intel_record(address, kind, data):
    record = bytes([len(data), address >> 8, address & 255, kind]) + data
    return ":" + (record + bytes([-sum(record) & 255])).hex().upper() + "\n"


def firmware_hex():
    return intel_record(0, 0, b"\x0c\x94\x00\x00") + intel_record(0, 1, b"")


def test_hex_rejects_bootloader_writes_and_invalid_checksum(tmp_path):
    image = tmp_path / "firmware.hex"
    image.write_text(firmware_hex())
    validate_hex(image)
    image.write_text(firmware_hex().replace("0C94", "0C95"))
    with pytest.raises(ValueError):
        validate_hex(image)
    image.write_text(intel_record(0, 4, b"\x00\x03") +
                     intel_record(0xE000, 0, b"\x00\x00") + intel_record(0, 1, b""))
    with pytest.raises(ValueError):
        validate_hex(image)


@pytest.mark.parametrize("fail", [False, True])
def test_flash_backs_up_first_verifies_and_leaves_recovery_latch(tmp_path, monkeypatch, fail):
    installer = ReleaseInstaller(tmp_path / "runtime", tmp_path / "state")
    image = tmp_path / "firmware.hex"
    image.write_text(firmware_hex())
    release = ReleaseClient("https://cloud.example.test").metadata(
        metadata(image.read_bytes(), "arduino", "firmware.hex"), "arduino")
    monkeypatch.setattr(installer, "avrdude", lambda: ("avrdude", "avrdude.conf"))
    job = installer.prepare(image, release, "/dev/ttyACM0")
    real_resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda p: p if str(p).replace("\\", "/") ==
                        "/dev/ttyACM0" else real_resolve(p))
    # Windows represents a rooted POSIX path with backslashes; use a dedicated port double.
    real_path = module.Path
    port = Mock()
    port.resolve.return_value = "/dev/ttyACM0"
    port.__str__ = Mock(return_value="/dev/ttyACM0")
    port.is_char_device.return_value = True
    monkeypatch.setattr(module, "Path", lambda p: port if p == "/dev/ttyACM0" else real_path(p))
    monkeypatch.setattr(module.os, "access", lambda *_: True)
    calls = []

    def run(args, log, *unused):
        calls.append(args)
        if "flash:r:" in args[-1]:
            (Path(job["work"]) / "previous.hex").write_text(firmware_hex())
        elif fail:
            raise RuntimeError("simulated flash failure")

    monkeypatch.setattr(installer, "_run", run)
    if fail:
        with pytest.raises(RuntimeError):
            installer.install(job, lambda _: None)
    else:
        installer.install(job, lambda _: None)
    assert len(calls) == 2 and "flash:r:" in calls[0][-1] and "flash:w:" in calls[1][-1]
    assert all("-V" not in args and "-F" not in args for args in calls)
    assert firmware_recovery(installer.state) == ("flashing" if fail else "reset_required")


def test_unreadable_recovery_record_cannot_enable_treatment(tmp_path):
    assert firmware_recovery(tmp_path) is None
    write_json(tmp_path / "updates/firmware-recovery.json", {"status": "unknown"})
    assert firmware_recovery(tmp_path) == "flashing"
