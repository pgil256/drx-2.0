# controllers/auth_controller.py
"""Login/PIN handling extracted from the KneeSpa window.

Owns the lockout state (it is security state, not UI state); the login
modal submits the whole PIN to handle_login.

Lockout state is persisted to disk (DATA_PATHS["AUTH_STATE"]) so that
power-cycling the kiosk does not reset the brute-force window, and the
lockout duration doubles on each consecutive lockout. Failed attempts
are logged for audit; the PIN itself is never logged.

The Pi has no real-time clock, so lockouts are timed with a monotonic
clock, never the wall clock. The file stores the seconds that remained at
the last save together with the boot ID and the monotonic reading. After
an app restart in the same boot the elapsed time is subtracted; after a
reboot the whole remainder is served again. An unreadable file starts a
lockout rather than a clean slate.
"""
import json
import math
import os
import time
from pathlib import Path

from config.constants import DATA_PATHS
from helpers.device_records import write_json
from helpers.logging import setup_logger
from helpers.secure_auth import SecureAuthHelper

BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def read_boot_id():
    """This boot's identity, or None where the kernel does not provide one."""
    try:
        with open(BOOT_ID_PATH, "r", encoding="ascii") as f:
            return f.read().strip() or None
    except (OSError, ValueError):
        return None


class AuthStateError(ValueError):
    """The stored lockout state cannot be trusted."""


class AuthController:
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_SECONDS = 60
    LOCKOUT_MAX_SECONDS = 3600

    def __init__(self, window, state_path=None, clock=time.monotonic, boot_id=read_boot_id):
        self.window = window
        self.logger = setup_logger(component="Auth")
        self.state_path = state_path or DATA_PATHS["AUTH_STATE"]
        self._clock = clock
        self._boot_id = boot_id()
        self.failed_logins = 0
        # Deadline on self._clock (monotonic), not wall-clock time.
        self.lockout_until = 0.0
        # Consecutive lockouts served without a successful login in
        # between; drives the exponential backoff.
        self.lockout_count = 0
        self._load_state()

    # -- persistence --------------------------------------------------

    def lockout_remaining(self):
        """Seconds left in the current lockout (0 when not locked)."""
        return max(0.0, self.lockout_until - self._clock())

    def _load_state(self):
        """Restore lockout state. A missing file starts clean; an unreadable
        one starts a lockout, so damaging it cannot reset the attempt count."""
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            failed, count, remaining = self._parse_state(state)
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, AttributeError) as e:
            self.lockout_count = 1
            self.lockout_until = self._clock() + self.LOCKOUT_SECONDS
            self.logger.warning(
                "Auth state file unreadable (%s); starting a %d s lockout",
                e, self.LOCKOUT_SECONDS,
            )
            self._save_state()
            return
        self.failed_logins = failed
        self.lockout_count = count
        self.lockout_until = self._clock() + remaining if remaining > 0 else 0.0

    def _parse_state(self, state):
        """Return (failed_logins, lockout_count, remaining seconds)."""
        failed = int(state.get("failed_logins", 0))
        count = int(state.get("lockout_count", 0))
        if failed < 0 or count < 0:
            raise AuthStateError("negative attempt counts")
        if "lockout_remaining_s" in state:
            remaining = float(state["lockout_remaining_s"])
            saved_at = state.get("monotonic")
            saved_at = None if saved_at is None else float(saved_at)
            if (not math.isfinite(remaining) or remaining < 0
                    or (saved_at is not None and not math.isfinite(saved_at))):
                raise AuthStateError("invalid lockout timing")
            same_boot = self._boot_id is not None and state.get("boot_id") == self._boot_id
            if same_boot and saved_at is not None:
                # The app restarted within this boot: the monotonic clock
                # kept running, so the time since the save has been served.
                elapsed = self._clock() - saved_at
                remaining -= min(max(elapsed, 0.0), remaining)
            # After a reboot (or with no boot ID) the monotonic clock
            # restarted; serve the whole remainder again.
        else:
            # Older files stored a wall-clock deadline. Convert it once.
            until = float(state.get("lockout_until", 0.0))
            if not math.isfinite(until):
                raise AuthStateError("invalid lockout deadline")
            remaining = max(0.0, until - time.time()) if until else 0.0
        return failed, count, min(remaining, float(self.LOCKOUT_MAX_SECONDS))

    def _save_state(self):
        """Persist lockout state atomically (kiosk power cuts are routine)."""
        remaining = self.lockout_remaining()
        state = {
            "failed_logins": self.failed_logins,
            "lockout_count": self.lockout_count,
            "lockout_remaining_s": remaining,
            "monotonic": self._clock(),
            "boot_id": self._boot_id,
            # Wall-clock deadline, read only by app versions before the
            # monotonic format (a rollback must not reset the lockout).
            "lockout_until": time.time() + remaining if remaining else 0.0,
        }
        try:
            write_json(Path(self.state_path), state)
        except (OSError, ValueError) as e:
            # Never let bookkeeping failure block the login path; the
            # in-memory lockout still protects the running session.
            self.logger.error("Could not persist auth state: %s", e)

    def _lockout_duration(self):
        """Exponential backoff: 60 s, 120 s, 240 s, ... capped at 1 h."""
        return min(
            self.LOCKOUT_SECONDS * (2 ** self.lockout_count),
            self.LOCKOUT_MAX_SECONDS,
        )

    def _upgrade_legacy_hash(self, stored_hash, pin, user):
        """Replace a proven unsalted SHA-256 hash with PBKDF2 where it is stored.

        Legacy hashes keep working. Only user_pins.csv rows can be rewritten;
        an *_PIN_HASH value from the environment is only reported.
        """
        if not SecureAuthHelper.is_legacy_hash(stored_hash):
            return
        username = user.get("username")
        try:
            if stored_hash in (os.getenv("ADMIN_PIN_HASH"), os.getenv("USER_PIN_HASH")):
                self.logger.warning(
                    "User %r signed in with a legacy unsalted PIN hash from the "
                    "environment; replace it with SecureAuthHelper.hash_pin_secure",
                    username)
                return
            csv_helper = getattr(self.window, "csv", None)
            new_hash = SecureAuthHelper.hash_pin_secure(pin)
            if csv_helper is None or not csv_helper.replace_pin_hash(
                    DATA_PATHS["USER_PINS"], stored_hash, new_hash):
                self.logger.warning(
                    "User %r signed in with a legacy unsalted PIN hash that could "
                    "not be upgraded", username)
                return
            users = self.window.users
            users.pop(stored_hash, None)
            user["pin_hash"] = new_hash
            users[new_hash] = user
            self.logger.warning("Upgraded a legacy unsalted PIN hash to PBKDF2 for user %r",
                                username)
        except Exception:
            # Bookkeeping must never undo a successful login.
            self.logger.exception("Legacy PIN hash upgrade failed")

    # -- login --------------------------------------------------------

    def handle_login(self, pin: str):
        """Validate a submitted PIN with persistent lockout protection."""
        window = self.window
        self.logger.info("Handling login")

        # Lockout: a kiosk with a short numeric PIN and unlimited instant
        # retries is brute-forceable in minutes
        remaining = self.lockout_remaining()
        if remaining > 0:
            wait_s = int(remaining) + 1
            self.logger.warning(
                "Login attempt during lockout (%d s remaining)", wait_s
            )
            window._show_timed_error(
                f"Too many failed attempts. Try again in {wait_s} seconds."
            )
            return

        matched_user = None
        matched_hash = None
        for stored_hash, user in window.users.items():
            if SecureAuthHelper.verify_pin(pin, stored_hash):
                matched_user = user
                matched_hash = stored_hash
                break

        if matched_user:
            self.logger.info(
                "Login successful for user %r", matched_user.get("username")
            )
            self.failed_logins = 0
            self.lockout_count = 0
            self._save_state()
            window.current_user = matched_user
            window.update_ui_after_login()
            self._upgrade_legacy_hash(matched_hash, pin, matched_user)
        else:
            self.failed_logins += 1
            self.logger.warning(
                "Failed login attempt %d of %d",
                self.failed_logins, self.LOCKOUT_THRESHOLD,
            )
            if self.failed_logins >= self.LOCKOUT_THRESHOLD:
                duration = self._lockout_duration()
                self.lockout_until = self._clock() + duration
                self.lockout_count += 1
                self.failed_logins = 0
                self.logger.warning(
                    "Login locked for %d s (consecutive lockout #%d)",
                    duration, self.lockout_count,
                )
                window._show_timed_error(
                    f"Too many failed attempts. Login locked for "
                    f"{duration} seconds."
                )
            else:
                window._show_timed_error("Invalid PIN. Please try again.")
            self._save_state()
