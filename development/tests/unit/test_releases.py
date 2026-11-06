"""Release verification and isolated installation tests; never flash the host."""

import hashlib
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
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
        request = client._opener.open.call_args[0][0]
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


# ----- U1: crash-safe software swap and pruning -----
RESTORE = Path(module.__file__).resolve().parents[3] / "restore_update.sh"
HEX = "0123456789abcdef" * 2
posix_shell = pytest.mark.skipif(
    not sys.platform.startswith("linux") or shutil.which("flock") is None,
    reason="runs runtime/restore_update.sh, which needs bash and flock (Linux)")


class Crash(BaseException):
    """A power cut: no except or rollback code runs after it."""


def crash_between_renames(installer, job, monkeypatch):
    original = module.os.replace

    def replace(source, target):
        if Path(source).name.startswith(".software-next-"):
            raise Crash()
        original(source, target)

    monkeypatch.setattr(module.os, "replace", replace)
    with pytest.raises(Crash):
        installer.install(job, lambda _: None)
    monkeypatch.setattr(module.os, "replace", original)


def restore(runtime, *options):
    return subprocess.run(["bash", str(RESTORE), *options, str(runtime)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True, timeout=30)


def test_journal_is_on_disk_before_the_first_rename(prepared, monkeypatch):
    installer, job = prepared
    events = []
    original = module.os.replace

    def replace(source, target):
        journal = installer.runtime / module.SWAP_JOURNAL
        if Path(source).parent == installer.runtime:  # not write_json's renames
            events.append(("rename", Path(source).name,
                           journal.read_text() if journal.exists() else None))
        original(source, target)

    monkeypatch.setattr(module.os, "replace", replace)
    monkeypatch.setattr(module, "fsync_tree", lambda path: events.append(("tree", path.name)))
    monkeypatch.setattr(module, "fsync_directory",
                        lambda path: events.append(("directory", path.name)))
    installer.install(job, lambda _: None)

    renames = [event for event in events if event[0] == "rename"]
    assert len(renames) == 2
    assert renames[0][1] == "raspberry-pi"
    assert renames[1][1].startswith(".software-next-")
    journal = renames[0][2]
    assert journal is not None  # written before the first rename
    lines = dict(line.split("=", 1) for line in journal.splitlines())
    assert set(lines) == {"target", "retired", "candidate"}
    assert Path(lines["retired"]).name.startswith(".software-old-")
    assert Path(lines["candidate"]).name == renames[1][1]
    # The new tree is flushed before the journal; the folder after both renames.
    tree = events.index(("tree", renames[1][1]))
    first = events.index(renames[0])
    assert tree < first
    assert ("directory", "runtime") in events[events.index(renames[1]):]
    assert not (installer.runtime / module.SWAP_JOURNAL).exists()


@posix_shell
def test_crash_between_the_renames_is_restored_before_the_next_start(prepared, monkeypatch):
    installer, job = prepared
    crash_between_renames(installer, job, monkeypatch)
    target = installer.runtime / "raspberry-pi"
    assert not target.exists()
    assert (installer.runtime / module.SWAP_JOURNAL).exists()

    result = restore(installer.runtime)

    assert result.returncode == 0, result.stderr
    assert (target / "main/kneespa.py").read_text() == "OLD = True\n"
    assert not (installer.runtime / module.SWAP_JOURNAL).exists()
    assert not list(installer.runtime.glob(".software-old-*"))
    assert "Restored the previous software" in result.stderr


@posix_shell
def test_restore_leaves_a_present_app_folder_alone(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "raspberry-pi/main").mkdir(parents=True)
    (runtime / (".software-old-" + HEX)).mkdir()
    result = restore(runtime)
    assert result.returncode == 0
    assert (runtime / (".software-old-" + HEX)).is_dir()


@posix_shell
@pytest.mark.parametrize("journal", [None, "retired=/etc\n", "retired=../escape\n"])
def test_restore_without_a_usable_journal_takes_the_newest_retired_folder(tmp_path, journal):
    runtime = tmp_path / "runtime"
    older, newer = runtime / (".software-old-" + "a" * 32), runtime / (".software-old-" + HEX)
    for folder, mark in ((older, "older"), (newer, "newer")):
        (folder / "main").mkdir(parents=True)
        (folder / "main/kneespa.py").write_text(mark)
    os.utime(str(older), (1000, 1000))
    os.utime(str(newer), (2000, 2000))
    if journal:
        (runtime / module.SWAP_JOURNAL).write_text(journal)
    result = restore(runtime)
    assert result.returncode == 0, result.stderr
    assert (runtime / "raspberry-pi/main/kneespa.py").read_text() == "newer"
    assert older.is_dir()


@posix_shell
def test_restore_reports_when_nothing_can_be_restored(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    result = restore(runtime)
    assert result.returncode == 1
    assert "no previous software" in result.stderr


@posix_shell
def test_restore_changes_nothing_while_the_app_holds_the_lock(tmp_path):
    import fcntl

    runtime = tmp_path / "runtime"
    (runtime / (".software-old-" + HEX) / "main").mkdir(parents=True)
    lock = tmp_path / "logs/desktop-launch.lock"
    lock.parent.mkdir()
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = restore(runtime, "--lock", str(lock))
    assert result.returncode == 0
    assert "running" in result.stderr
    assert not (runtime / "raspberry-pi").exists()
    assert restore(runtime, "--lock", str(lock)).returncode == 0
    assert (runtime / "raspberry-pi/main").is_dir()


def prepared_folder(root, name, mtime, release_id=None, extension=".zip"):
    folder = root / name
    folder.mkdir(parents=True)
    if release_id:
        write_json(folder / "job.json",
                   {"release": {"id": release_id, "extension": extension}})
    os.utime(str(folder), (mtime, mtime))
    return folder


def test_install_prunes_old_preparations_but_never_a_backup(prepared):
    installer, job = prepared
    root = installer.root
    old1 = prepared_folder(root, "prepared-old1", 1000, "firmware-id", ".hex")
    old2 = prepared_folder(root, "prepared-old2", 2000, "recovery-id")
    old3 = prepared_folder(root, "prepared-old3", 3000, "stale-id")
    old4 = prepared_folder(root, "prepared-old4", 3500, "stale-id-2")
    failed = prepared_folder(root, "prepared-failed", 4000)
    write_json(root / "installed.json",
               {"arduino": {"id": "firmware-id", "backup": str(old1 / "previous.hex")}})
    write_json(root / "firmware-recovery.json",
               {"status": "reset_required", "backup": str(old2 / "previous.hex")})
    downloads = root / "downloads"
    downloads.mkdir()
    for name in (RELEASE_ID + ".zip", "firmware-id.hex", "recovery-id.zip",
                 "stale-id.zip", "interrupted.part"):
        (downloads / name).write_bytes(b"x")
    leftovers = [installer.runtime / (".software-old-" + HEX),
                 installer.runtime / (".software-next-" + HEX)]
    for leftover in leftovers:
        leftover.mkdir()
    unrelated = installer.runtime / ".software-old-notes"
    unrelated.mkdir()

    installer.install(job, lambda _: None)

    work = Path(job["work"])
    kept = {path.name for path in root.glob("prepared-*")}
    # The two newest (this install and the failed preparation), plus the two a
    # record points to, however old.
    assert kept == {work.name, failed.name, old1.name, old2.name}
    assert not old3.exists() and not old4.exists()
    assert sorted(path.name for path in downloads.iterdir()) == sorted(
        [RELEASE_ID + ".zip", "firmware-id.hex", "recovery-id.zip"])
    assert not any(leftover.exists() for leftover in leftovers)
    assert unrelated.is_dir()
    assert read_json(root / "installed.json")["arduino"]["backup"] == str(old1 / "previous.hex")


def test_an_unreadable_record_stops_all_pruning(prepared):
    installer, job = prepared
    root = installer.root
    old = [prepared_folder(root, "prepared-old%d" % index, 1000 + index, "id-%d" % index)
           for index in range(3)]
    (root / "firmware-recovery.json").write_text("not json")

    installer.install(job, lambda _: None)

    assert all(folder.is_dir() for folder in old)
