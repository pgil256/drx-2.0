import csv
import os
from helpers.logging import setup_logger
from helpers.secure_auth import SecureAuthHelper
try:
    from PyQt5.QtWidgets import QMessageBox
except ImportError:
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
            # Get the directory of the current file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Navigate to the data/users directory relative to the current file
            users_file = os.path.join(current_dir, "..", "data", "user_pins.csv")
            print(f"CSVHelper: Loading user data from {users_file}")
            self.users = self.load_csv(users_file)
            print(f"CSVHelper: Loaded {len(self.users)} user records from CSV")
        
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
        try:
            with open(filename, "r", newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    pin_hash = row.get("pin_hash")
                    if not pin_hash and row.get("pin"):
                        # Legacy CSV support: convert plaintext pins in
                        # memory only -- salted, so no reversible digest
                        # is ever held
                        pin_hash = SecureAuthHelper.hash_pin_secure(row["pin"])
                        row.pop("pin", None)
                    if not pin_hash:
                        raise KeyError("pin_hash")
                    row["pin_hash"] = pin_hash
                    data[pin_hash] = row
                    row_count += 1
            print(f"CSVHelper: Successfully loaded {row_count} rows from {filename}")

        except FileNotFoundError:
            print(f"CSVHelper: ERROR - CSV file not found: {filename}")
            QMessageBox.critical(None, "Error", f"CSV file not found: {filename}")

        except csv.Error as e:
            print(f"CSVHelper: ERROR - CSV file error in {filename}: {e}")
            QMessageBox.critical(None, "Error", f"CSV file error in {filename}: {e}")

        except KeyError as e:
            print(f"CSVHelper: ERROR - Missing 'pin_hash' column in CSV file {filename}: {e}")
            QMessageBox.critical(
                None,
                "Error",
                f"CSV format error: Missing 'pin_hash' column in {filename}",
            )

        return data
