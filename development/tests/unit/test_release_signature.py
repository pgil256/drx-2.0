"""Release signatures with gpgv, warn first (checklist U2).

gpgv is mocked except in the last test, which runs the real tools on Linux.
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError

import pytest

from controllers.release_controller import ReleaseController
from helpers import release_signature as sig
from helpers.release_client import MAX_SIGNATURE_BYTES, ReleaseClient

pytestmark = pytest.mark.unit
RELEASE_ID = "e9984c77-9bea-41b3-9d3d-ebaf5dd8b660"


@pytest.fixture
def files(tmp_path):
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"release bytes")
    signature = tmp_path / "release.zip.sig"
    signature.write_bytes(b"signature bytes")
    keyring = tmp_path / "release-keyring.gpg"
    keyring.write_bytes(b"public key")
    return SimpleNamespace(archive=archive, signature=signature, keyring=keyring)


def gpgv_exit(code, stderr=b""):
    return Mock(return_value=subprocess.CompletedProcess([], code, b"", stderr))


# ----- the mode -----

@pytest.mark.parametrize("value,mode", [
    (None, "warn"), ("", "warn"), ("warn", "warn"), (" WARN ", "warn"),
    ("enforce", "enforce"), ("Enforce", "enforce"),
    ("enforced", "enforce"), ("off", "enforce"),  # a typo never weakens the check
])
def test_signature_mode_defaults_to_warn_and_never_weakens_on_a_typo(value, mode):
    environ = {} if value is None else {sig.MODE_SETTING: value}
    assert sig.signature_mode(environ) == mode


# ----- checking one release -----

def test_a_good_signature_is_valid_and_gpgv_gets_an_argument_list(files):
    run = gpgv_exit(0)
    check = sig.verify(files.archive, files.signature, files.keyring, gpgv="/usr/bin/gpgv",
                       run=run)
    assert check.status == sig.VALID
    args, kwargs = run.call_args
    command = args[0]
    assert command[0] == "/usr/bin/gpgv"
    assert command[1] == "--homedir"  # a private, empty home: only the keyring counts
    assert command[3:] == ["--keyring", str(files.keyring.resolve()),
                           str(files.signature), str(files.archive)]
    assert "shell" not in kwargs
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_a_bad_signature_is_invalid_with_gpgv_s_reason(files):
    run = gpgv_exit(1, b"gpgv: Signature made today\ngpgv: BAD signature from \"x\"\n")
    check = sig.verify(files.archive, files.signature, files.keyring, gpgv="gpgv", run=run)
    assert check == sig.SignatureCheck(sig.INVALID, 'gpgv: BAD signature from "x"')


def test_no_signature_is_missing(files):
    run = gpgv_exit(0)
    assert sig.verify(files.archive, None, files.keyring, gpgv="gpgv", run=run).status \
        == sig.MISSING
    run.assert_not_called()


def test_no_gpgv_is_unsigned(files, monkeypatch):
    monkeypatch.setattr(sig.shutil, "which", lambda name: None)
    run = gpgv_exit(0)
    assert sig.verify(files.archive, files.signature, files.keyring, run=run).status \
        == sig.UNSIGNED
    run.assert_not_called()


@pytest.mark.parametrize("keyring", ["absent", "empty"])
def test_no_keyring_is_unsigned(files, keyring):
    if keyring == "absent":
        files.keyring.unlink()
    else:
        files.keyring.write_bytes(b"")
    run = gpgv_exit(0)
    check = sig.verify(files.archive, files.signature, files.keyring, gpgv="gpgv", run=run)
    assert check.status == sig.UNSIGNED
    run.assert_not_called()


@pytest.mark.parametrize("error", [OSError("exec failed"),
                                   subprocess.TimeoutExpired("gpgv", 30)])
def test_gpgv_that_cannot_run_is_unsigned(files, error):
    run = Mock(side_effect=error)
    check = sig.verify(files.archive, files.signature, files.keyring, gpgv="gpgv", run=run)
    assert check.status == sig.UNSIGNED


# ----- what each result means in each mode -----

@pytest.mark.parametrize("status", [sig.VALID, sig.INVALID, sig.MISSING, sig.UNSIGNED])
@pytest.mark.parametrize("mode", [sig.WARN, sig.ENFORCE])
def test_only_a_valid_signature_installs_silently(status, mode):
    allowed, message = sig.decide(sig.SignatureCheck(status, "detail"), mode)
    if status == sig.VALID:
        assert (allowed, message) == (True, "")
    elif mode == sig.WARN:
        assert allowed is True
        assert message.startswith("Warning:") and "detail" in message
    else:
        assert allowed is False
        assert message.startswith("Install refused:") and sig.MODE_SETTING in message


# ----- fetching the signature -----

def metadata():
    data = b"release"
    return dict(id=RELEASE_ID, platform="raspberry-pi", filename="software.zip", version="2.1",
                size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                download_url=f"/api/v1/admin/releases/{RELEASE_ID}/download")


class Response(io.BytesIO):
    def __init__(self, data, content_type="application/pgp-signature", status=200):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Type": content_type}


def client_returning(response):
    client = ReleaseClient("https://cloud.example.test")
    client.check_context = Mock()
    client._opener = Mock()
    if isinstance(response, Exception):
        client._opener.open.side_effect = response
    else:
        client._opener.open.return_value = response
    return client


def test_the_signature_is_fetched_next_to_the_release(tmp_path):
    client = client_returning(Response(b"detached signature"))
    path, reason = client.download_signature(metadata(), tmp_path)
    assert reason == ""
    assert path == tmp_path / (RELEASE_ID + ".zip.sig")
    assert path.read_bytes() == b"detached signature"
    request = client._opener.open.call_args[0][0]
    assert request.full_url == (
        f"https://cloud.example.test/api/v1/admin/releases/{RELEASE_ID}/signature")
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


@pytest.mark.parametrize("response,reason", [
    (HTTPError("", 404, "missing", {}, io.BytesIO()), "No signature was published"),
    (HTTPError("", 500, "error", {}, io.BytesIO()), "HTTP 500"),
    (OSError("https://user:secret@host"), "OSError"),
    (Response(b"<html>", content_type="text/html"), "did not return a signature"),
    (Response(b""), "empty or too large"),
    (Response(b"x" * (MAX_SIGNATURE_BYTES + 1)), "empty or too large"),
])
def test_a_signature_that_cannot_be_fetched_counts_as_missing(tmp_path, response, reason):
    path, why = client_returning(response).download_signature(metadata(), tmp_path)
    assert path is None
    assert reason in why
    assert "secret" not in why  # remote error text is never repeated
    assert list(tmp_path.iterdir()) == []


# ----- the controller step between download and preparation -----

def check_with(client, mode, monkeypatch, tmp_path, check=None):
    monkeypatch.setenv(sig.MODE_SETTING, mode)
    if check is not None:
        monkeypatch.setattr(sig, "verify", Mock(return_value=check))
    host = SimpleNamespace(window=SimpleNamespace(logger=MagicMock()))
    archive = tmp_path / "release.zip"
    return ReleaseController._check_signature(host, client, {"version": "2.1"}, archive)


def test_a_valid_signature_adds_no_note(monkeypatch, tmp_path):
    client = Mock(download_signature=Mock(return_value=(tmp_path / "x.sig", "")))
    note = check_with(client, "enforce", monkeypatch, tmp_path,
                      sig.SignatureCheck(sig.VALID, "Signature verified."))
    assert note == ""


def test_warn_mode_installs_with_a_note(monkeypatch, tmp_path):
    client = Mock(download_signature=Mock(return_value=(None, "No signature was published.")))
    note = check_with(client, "warn", monkeypatch, tmp_path)
    assert note.startswith("Warning:") and "No signature was published." in note


def test_enforce_mode_refuses_before_anything_is_prepared(monkeypatch, tmp_path):
    client = Mock(download_signature=Mock(return_value=(tmp_path / "x.sig", "")))
    with pytest.raises(ValueError, match="Install refused"):
        check_with(client, "enforce", monkeypatch, tmp_path,
                   sig.SignatureCheck(sig.INVALID, "BAD signature"))


# ----- the real tools -----

@pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("gpg")
                    or not shutil.which("gpgv"), reason="needs gpg and gpgv (Linux)")
def test_real_gpgv_accepts_a_good_signature_and_rejects_a_changed_file(tmp_path):
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    env = dict(os.environ, GNUPGHOME=str(home))

    def gpg(*args, **kwargs):
        return subprocess.run(["gpg", "--batch", "--pinentry-mode", "loopback",
                               "--passphrase", "", *args],
                              env=env, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60, **kwargs)

    gpg("--quick-generate-key", "KneeSpa test release <test@example.invalid>",
        "ed25519", "sign", "never")
    keyring = tmp_path / "release-keyring.gpg"
    keyring.write_bytes(gpg("--export").stdout)  # binary, as gpgv needs
    archive = tmp_path / "release.zip"
    archive.write_bytes(b"release bytes")
    signature = tmp_path / "release.zip.sig"
    gpg("--detach-sign", "--output", str(signature), str(archive))

    assert sig.verify(archive, signature, keyring).status == sig.VALID
    archive.write_bytes(b"release bytes, changed")
    assert sig.verify(archive, signature, keyring).status == sig.INVALID
