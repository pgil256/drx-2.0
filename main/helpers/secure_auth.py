"""
Secure Authentication Helper
This module provides secure authentication using environment variables.
For production, this should be replaced with a proper database and password hashing.
"""

import os
import hashlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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

        # Load admin user from environment
        admin_pin = os.getenv("ADMIN_PIN")
        if admin_pin:
            users[admin_pin] = {
                "pin": admin_pin,
                "username": os.getenv("ADMIN_USERNAME", "Administrator"),
                "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
                "status": "admin"
            }
            print("SecureAuthHelper: Loaded admin user from environment")

        # Load regular user from environment
        user_pin = os.getenv("USER_PIN")
        if user_pin:
            users[user_pin] = {
                "pin": user_pin,
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
        if self.users and pin in self.users:
            return self.users[pin]
        return None

    def hash_pin(self, pin):
        """
        Hash a PIN for secure storage.
        Note: In production, use bcrypt or similar with salt.

        Args:
            pin (str): The PIN to hash

        Returns:
            str: Hashed PIN
        """
        return hashlib.sha256(pin.encode()).hexdigest()