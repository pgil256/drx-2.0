"""
Secure Authentication Helper
This module provides secure authentication using environment variables.
"""

import os
import hashlib
import hmac
import secrets

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

# Load environment variables
load_dotenv()

PBKDF2_ITERATIONS = 200_000
PBKDF2_PREFIX = "pbkdf2_sha256"


class SecureAuthHelper:
    def __init__(self):
        """Initialize secure authentication helper."""
        print("SecureAuthHelper: Initializing secure authentication")
        self.users = self._load_secure_users()

    def _load_secure_users(self):
        """
        Load users from environment variables.
        In production, this should query a secure database with hashed passwords.
        """
        users = {}

        admin_pin_hash = os.getenv("ADMIN_PIN_HASH")
        admin_pin = os.getenv("ADMIN_PIN")
        if not admin_pin_hash and admin_pin:
            admin_pin_hash = self.hash_pin_secure(admin_pin)
        if admin_pin_hash:
            users[admin_pin_hash] = {
                "pin_hash": admin_pin_hash,
                "username": os.getenv("ADMIN_USERNAME", "Administrator"),
                "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
                "status": "admin"
            }
            print("SecureAuthHelper: Loaded admin user from environment")

        user_pin_hash = os.getenv("USER_PIN_HASH")
        user_pin = os.getenv("USER_PIN")
        if not user_pin_hash and user_pin:
            user_pin_hash = self.hash_pin_secure(user_pin)
        if user_pin_hash:
            users[user_pin_hash] = {
                "pin_hash": user_pin_hash,
                "username": os.getenv("USER_USERNAME", "User"),
                "email": os.getenv("USER_EMAIL", "user@example.com"),
                "status": "user"
            }
            print("SecureAuthHelper: Loaded regular user from environment")

        # If no environment users are defined, fall back to CSV (for backwards compatibility)
        if not users:
            print("SecureAuthHelper: WARNING - No users in environment, falling back to CSV")
            print("SecureAuthHelper: For production, configure users in environment variables")
            return None  # Signal to use CSV fallback

        return users

    def validate_pin(self, pin):
        """
        Validate a PIN against stored users.

        Args:
            pin (str): The PIN to validate

        Returns:
            dict: User data if valid, None otherwise
        """
        if not self.users:
            return None
        for stored_hash, user in self.users.items():
            if self.verify_pin(pin, stored_hash):
                return user
        return None

    @staticmethod
    def hash_pin_secure(pin):
        """Hash a PIN with PBKDF2-HMAC-SHA256 and a random per-user salt.

        Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
        """
        salt = secrets.token_bytes(16)
        derived = hashlib.pbkdf2_hmac(
            "sha256", str(pin).encode(), salt, PBKDF2_ITERATIONS
        )
        return (
            f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}"
            f"${salt.hex()}${derived.hex()}"
        )

    @staticmethod
    def verify_pin(pin, stored_hash):
        """Verify a PIN against either hash format.

        Supports the salted PBKDF2 format for all new hashes and the
        legacy unsalted SHA-256 hex digests already present in deployed
        user files (those keep working but should be re-provisioned).
        """
        if not stored_hash:
            return False
        stored_hash = str(stored_hash)  # tolerate a non-str cell from the CSV
        if stored_hash.startswith(PBKDF2_PREFIX + "$"):
            try:
                _, iterations, salt_hex, hash_hex = stored_hash.split("$")
                derived = hashlib.pbkdf2_hmac(
                    "sha256",
                    str(pin).encode(),
                    bytes.fromhex(salt_hex),
                    int(iterations),
                )
                return hmac.compare_digest(derived.hex(), hash_hex)
            except (ValueError, TypeError):
                return False
        # Legacy unsalted SHA-256
        legacy = hashlib.sha256(str(pin).encode()).hexdigest()
        try:
            return hmac.compare_digest(legacy, str(stored_hash))
        except (TypeError, ValueError):
            # compare_digest raises on non-ASCII str input; one mis-columned
            # CSV row must not abort the login loop for every later user
            return False

    @staticmethod
    def hash_pin(pin):
        """
        Legacy unsalted SHA-256 hash (kept only so existing stored hashes
        remain verifiable). Use hash_pin_secure for anything new: a bare
        digest of a short numeric PIN is reversible instantly.

        Args:
            pin (str): The PIN to hash

        Returns:
            str: Hashed PIN
        """
        return hashlib.sha256(str(pin).encode()).hexdigest()
