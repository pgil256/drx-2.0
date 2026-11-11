"""Detached-signature checks for downloaded releases, warn first (checklist U2).

Each downloaded release is checked against its detached OpenPGP signature
with ``gpgv`` and the keyring shipped with the app. No Python dependency: a
subprocess with an argument list, never a shell. See
``development/docs/release-signing.md`` for the cloud side.

``KNEESPA_RELEASE_SIGNATURE_MODE`` (device ``.env``) chooses what a missing or
bad signature does:

- ``warn`` (the default): log it, show it on the release screen, and install;
- ``enforce``: refuse the install.

Without ``gpgv`` or the keyring (a Windows dev machine, or before the owner
adds the public key) a release cannot be checked, and counts as unsigned.
"""

import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable, NamedTuple, Optional, Tuple

MODE_SETTING = "KNEESPA_RELEASE_SIGNATURE_MODE"
WARN, ENFORCE = "warn", "enforce"
# Shipped with the app; it is not in the repository until the owner supplies
# the release public key. Releases are always checked against the installed
# keyring, never one inside the download.
KEYRING = Path(__file__).resolve().parents[1] / "config" / "release-keyring.gpg"
GPGV_TIMEOUT_S = 30

VALID, INVALID, MISSING, UNSIGNED = "valid", "invalid", "missing", "unsigned"
DESCRIPTIONS = {
    INVALID: "the release signature is not valid",
    MISSING: "the release has no signature",
    UNSIGNED: "the release signature could not be checked on this device",
}

logger = logging.getLogger(__name__)


class SignatureCheck(NamedTuple):
    status: str  # VALID, INVALID, MISSING or UNSIGNED
    detail: str


def signature_mode(environ=os.environ) -> str:
    """``warn`` unless set. An unrecognised value is treated as ``enforce``:
    a typo must never quietly weaken the check."""
    value = environ.get(MODE_SETTING, "").strip().lower()
    if value in ("", WARN):
        return WARN
    if value != ENFORCE:
        logger.warning("%s=%r is not warn or enforce; enforcing", MODE_SETTING, value)
    return ENFORCE


def verify(archive: Path, signature: Optional[Path], keyring: Path = KEYRING,
           gpgv: Optional[str] = None,
           run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> SignatureCheck:
    """Check ``archive`` against its detached ``signature`` with gpgv."""
    if signature is None:
        return SignatureCheck(MISSING, "No signature was published for this release.")
    executable = gpgv or shutil.which("gpgv")
    if not executable:
        return SignatureCheck(UNSIGNED, "gpgv is not installed.")
    if not keyring.is_file() or keyring.stat().st_size == 0:
        return SignatureCheck(UNSIGNED, f"No release keyring at {keyring}.")
    try:
        # A private, empty home directory: gpgv must trust only the keyring.
        with tempfile.TemporaryDirectory(prefix="kneespa-gpgv-") as home:
            result = run(
                [executable, "--homedir", home, "--keyring", str(keyring.resolve()),
                 str(signature), str(archive)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=GPGV_TIMEOUT_S, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return SignatureCheck(UNSIGNED, f"gpgv could not run ({type(exc).__name__}).")
    if result.returncode == 0:
        return SignatureCheck(VALID, "Signature verified.")
    output = (result.stderr or b"").decode(errors="replace").strip().splitlines()
    return SignatureCheck(INVALID, output[-1] if output else f"gpgv exit {result.returncode}")


def decide(check: SignatureCheck, mode: str) -> Tuple[bool, str]:
    """Whether to install, and what to tell the operator ("" when valid)."""
    if check.status == VALID:
        return True, ""
    problem = DESCRIPTIONS[check.status]
    if mode == WARN:
        return True, (f"Warning: {problem} ({check.detail}) The install will continue "
                      "because signature checking is in warn mode.")
    return False, (f"Install refused: {problem} ({check.detail}) "
                   f"{MODE_SETTING} is enforce.")
