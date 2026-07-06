import csv
import os
import shutil
from config.constants import DATA_PATHS
from helpers.logging import setup_logger
from helpers.secure_auth import SecureAuthHelper
try:
    from PyQt5.QtWidgets import QApplication, QMessageBox
except ImportError:
    QApplication = None

    class QMessageBox:
        @staticmethod
        def critical(parent, title, message):
            print(f"{title}: {message}")


class CSVHelper:
    def __init__(self):
        print("CSVHelper: Initializing CSV helper")
        self.logger = setup_logger(component="CSV Helper")
        self.users = {}

    def initialize_data(self):
        """Initialize CSV data by loading user data."""
        print("CSVHelper: Initializing user data")

        # Try to load from secure authentication first
        secure_auth = SecureAuthHelper()
        if secure_auth.users:
            print("CSVHelper: Using secure authentication from environment variables")
            self.users = secure_auth.users
            print(f"CSVHelper: Loaded {len(self.users)} user records from secure auth")
        else:
            print("CSVHelper: Falling back to hashed CSV file")
            # KNEESPA_USER_PINS_PATH overrides the default in-repo location;
            # the file itself is runtime state and is not tracked in git.
            users_file = DATA_PATHS["USER_PINS"]
            self._seed_users_file(users_file)
            print(f"CSVHelper: Loading user data from {users_file}")
            self.users = self.load_csv(users_file)
            print(f"CSVHelper: Loaded {len(self.users)} user records from CSV")
            if not self.users:
                self.logger.warning(
                    "No users provisioned. Add rows to %s (pin_hash via "
                    "SecureAuthHelper.hash_pin_secure) or set ADMIN_PIN_HASH/"
                    "USER_PIN_HASH in the environment. See README 'User "
                    "provisioning'.",
                    users_file,
                )

    def _seed_users_file(self, users_file):
        """Create the runtime users file from the tracked template if absent.

        The real user_pins.csv holds credentials and lives outside git; a
        fresh checkout has only user_pins.csv.example (header, no rows).
        Seeding the header file keeps first boot on the normal load path —
        zero users and a provisioning warning instead of a missing-file
        error dialog.
        """
        if os.path.exists(users_file):
            return
        example = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "data", "user_pins.csv.example",
        )
        if os.path.exists(example):
            try:
                os.makedirs(os.path.dirname(users_file) or ".", exist_ok=True)
                shutil.copyfile(example, users_file)
                self.logger.info(
                    "Seeded empty users file at %s from template", users_file
                )
            except OSError as e:
                self.logger.error(
                    "Could not seed users file at %s: %s", users_file, e
                )

    def _report_load_error(self, message):
        """Report a CSV load failure without crashing in headless contexts.

        The error is always logged so the failure leaves an audit trail. A
        modal QMessageBox is shown only when a QApplication event loop exists:
        constructing a dialog without one (e.g. at startup before the event
        loop is running, or in a headless/test context) aborts the process. On
        a patient-facing device that would turn a recoverable data error -- a
        missing or malformed user_pins.csv -- into a hard crash.

        Args:
            message (str): Human-readable description of the load failure.
        """
        self.logger.error(message)
        if QApplication is not None and QApplication.instance() is not None:
            QMessageBox.critical(None, "Error", message)

    def load_csv(self, filename):
        """
        Load CSV data into a dictionary.

        Args:
            filename (str): Path to the CSV file

        Returns:
            dict: Dictionary with PIN hash as key and row data as value
        """
        print(f"CSVHelper: Loading CSV file from {filename}")

        data = {}
        row_count = 0
        skipped = 0
        try:
            # utf-8-sig strips a leading BOM: an editor that saved the file
            # UTF-8-with-BOM turned the first header into "﻿pin_hash",
            # so DictReader keyed nothing on "pin_hash" and locked everyone
            # out. utf-8-sig reads BOM and BOM-less files identically.
            with open(filename, "r", newline="", encoding="utf-8-sig") as file:
                reader = csv.DictReader(file)
                for line_no, row in enumerate(reader, start=2):  # row 1 = header
                    pin_hash = row.get("pin_hash")
                    if not pin_hash and row.get("pin"):
                        # Legacy CSV support: convert plaintext pins in
                        # memory only -- salted, so no reversible digest
                        # is ever held
                        pin_hash = SecureAuthHelper.hash_pin_secure(row["pin"])
                        row.pop("pin", None)
                    if not pin_hash:
                        # Skip and log this one row rather than aborting the
                        # whole load: one malformed line used to raise and
                        # discard every user defined after it, silently
                        # locking out valid operators.
                        skipped += 1
                        self.logger.warning(
                            "Skipping malformed row %d in %s (no pin_hash/pin)",
                            line_no, filename,
                        )
                        continue
                    row["pin_hash"] = pin_hash
                    data[pin_hash] = row
                    row_count += 1
            print(f"CSVHelper: Successfully loaded {row_count} rows from {filename}")
            if skipped:
                self._report_load_error(
                    f"Skipped {skipped} malformed row(s) in {filename}; "
                    f"loaded {row_count} valid user(s)"
                )

        except FileNotFoundError:
            print(f"CSVHelper: ERROR - CSV file not found: {filename}")
            self._report_load_error(f"CSV file not found: {filename}")

        except csv.Error as e:
            print(f"CSVHelper: ERROR - CSV file error in {filename}: {e}")
            self._report_load_error(f"CSV file error in {filename}: {e}")

        except (OSError, UnicodeDecodeError) as e:
            # A permission error, a mid-read I/O failure, or a binary/
            # corrupt file must not crash startup on a patient-facing
            # kiosk -- degrade to whatever rows loaded and surface it.
            print(f"CSVHelper: ERROR - Could not read {filename}: {e}")
            self._report_load_error(f"Could not read {filename}: {e}")

        return data
