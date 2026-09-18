"""Separate technician PIN with salted hashing and persistent attempt limits."""

import json
import math
import os
import tempfile
import time
from typing import Callable, Optional

try:
    from main.config.constants import SERVICE_PIN_PATH
except ModuleNotFoundError:  # Direct execution of main/kneespa.py
    from config.constants import SERVICE_PIN_PATH

from helpers.logging import setup_logger
from helpers.secure_auth import SecureAuthHelper


logger = setup_logger(component="ServiceAccess")


class ServiceAccess:
    """Provision a six-digit service PIN once and verify it independently of login."""

    MAX_FAILURES = 5
    LOCKOUT_SECONDS = 60

    def __init__(
        self, path: Optional[str] = None, clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.path = os.path.abspath(path or SERVICE_PIN_PATH)
        self._clock = time.time if clock is None else clock
        self._environment_hash = os.environ.get("KNEESPA_SERVICE_PIN_HASH", "")
        self._stored_hash = ""
        self._failures = 0
        self._lockout_until = 0.0
        self._load_error = False
        self._file_configured = False
        self._load()

    @property
    def configured(self) -> bool:
        """Whether credentials exist, including an unreadable credential file."""
        return bool(self._environment_hash or self._stored_hash or self._file_configured)

    @property
    def lockout_remaining(self) -> int:
        """Seconds until attempts are accepted again."""
        return max(0, math.ceil(self._lockout_until - self._clock()))

    @staticmethod
    def _valid_pin(pin: str) -> bool:
        return isinstance(pin, str) and len(pin) == 6 and pin.isascii() and pin.isdigit()

    @staticmethod
    def _valid_hash(value: object) -> bool:
        """Accept bounded PBKDF2 records, never legacy unsalted service credentials."""
        try:
            prefix, iterations, salt, digest = value.split("$")
            return (
                prefix == "pbkdf2_sha256" and 100000 <= int(iterations) <= 1000000
                and len(bytes.fromhex(salt)) == 16 and len(bytes.fromhex(digest)) == 32
            )
        except (AttributeError, TypeError, ValueError):
            return False

    def _load(self) -> None:
        """Read rate-limit state on every attempt so reopening cannot reset it."""
        self._load_error = False
        try:
            with open(self.path, "r", encoding="utf-8") as source:
                state = json.load(source)
            self._file_configured = True
            stored_hash = state.get("pin_hash", "")
            failures = state.get("failures", 0)
            lockout = float(state.get("lockout_until", 0))
            if stored_hash and not self._valid_hash(stored_hash):
                raise ValueError("Invalid service credential format")
            if not isinstance(failures, int) or not 0 <= failures <= self.MAX_FAILURES:
                raise ValueError("Invalid service attempt state")
            if not math.isfinite(lockout) or lockout < 0:
                raise ValueError("Invalid service lockout state")
            if not stored_hash and not self._environment_hash:
                raise ValueError("Service credential is missing")
            self._stored_hash = stored_hash
            self._failures = failures
            self._lockout_until = lockout
        except FileNotFoundError:
            self._file_configured = False
            self._stored_hash = ""
            self._failures = 0
            self._lockout_until = 0.0
        except (OSError, ValueError, TypeError, AttributeError):
            # An unreadable existing credential must not become an invitation
            # to silently replace the technician PIN with a new one.
            self._file_configured = True
            self._load_error = True
            logger.error("Service credential state is unreadable; technician access is blocked")

    def _persist(self, pin_hash: str, failures: int, lockout_until: float) -> None:
        """Atomically write credentials and rate limits before changing live state."""
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".service-pin-", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
                json.dump({
                    "version": 1, "pin_hash": pin_hash,
                    "failures": failures, "lockout_until": lockout_until,
                }, destination)
                destination.flush()
                os.fsync(destination.fileno())
            # mkstemp creates mode 0600 on POSIX. chmod also protects existing
            # installations where supported; Windows applies its parent ACL.
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            logger.error("Unable to persist service credential state; access is not granted")
            raise
        self._stored_hash = pin_hash
        self._failures = failures
        self._lockout_until = lockout_until
        self._file_configured = True

    def provision(self, pin: str, confirmation: str, is_admin: bool) -> None:
        """Create the initial service credential only for an authenticated admin."""
        self._load()
        if not is_admin:
            raise PermissionError("An administrator must provision the first service PIN.")
        if self.configured:
            raise ValueError("A service PIN is already configured.")
        if not self._valid_pin(pin):
            raise ValueError("The service PIN must contain exactly six digits.")
        if pin != confirmation:
            raise ValueError("The service PIN confirmation does not match.")
        self._persist(SecureAuthHelper.hash_pin_secure(pin), 0, 0.0)

    def verify(self, pin: str) -> bool:
        """Verify a PIN, locking for 60 seconds after five consecutive failures.

        Failed state writes raise rather than granting access without enforcing
        the rate limit. Credentials and failures survive closing the wizard or
        restarting the app. There is no default or treatment-login fallback PIN.
        """
        self._load()
        if self._load_error:
            raise ValueError(
                "The service PIN file is unreadable; restore it before service access."
            )
        if not self.configured or self.lockout_remaining:
            return False
        stored_hash = self._environment_hash or self._stored_hash
        valid = (
            self._valid_pin(pin) and self._valid_hash(stored_hash)
            and SecureAuthHelper.verify_pin(pin, stored_hash)
        )
        if valid:
            # Access also requires writable rate-limit storage. Otherwise a
            # read-only state file would let unlimited guesses fail to persist
            # and still admit the eventual correct guess.
            self._persist(self._stored_hash, 0, 0.0)
            return True
        failures = 0 if self._lockout_until else self._failures
        failures += 1
        lockout = self._clock() + self.LOCKOUT_SECONDS if failures >= self.MAX_FAILURES else 0.0
        self._persist(self._stored_hash, failures, lockout)
        return False
