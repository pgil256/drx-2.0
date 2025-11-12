import csv
import logging
import os
from helpers.logging import setup_logger
from PyQt5.QtWidgets import QMessageBox


class CSVHelper:
    def __init__(self):
        print("CSVHelper: Initializing CSV helper")
        self.logger = setup_logger(component="CSV Helper")
        self.users = {}

    def initialize_data(self):
        """Initialize CSV data by loading user data."""
        print("CSVHelper: Initializing user data")
        # Get the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate to the data/users directory relative to the current file
        users_file = os.path.join(current_dir, "..", "data", "user_pins.csv")
        print(f"CSVHelper: Loading user data from {users_file}")
        self.users = self.load_csv(users_file)
        print(f"CSVHelper: Loaded {len(self.users)} user records")
        
    def load_csv(self, filename):
        """
        Load CSV data into a dictionary.

        Args:
            filename (str): Path to the CSV file

        Returns:
            dict: Dictionary with PIN as key and row data as value
        """
        print(f"CSVHelper: Loading CSV file from {filename}")

        data = {}
        row_count = 0
        try:
            with open(filename, "r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data[row["pin"]] = row
                    row_count += 1
            print(f"CSVHelper: Successfully loaded {row_count} rows from {filename}")

        except FileNotFoundError:
            print(f"CSVHelper: ERROR - CSV file not found: {filename}")
            QMessageBox.critical(None, "Error", f"CSV file not found: {filename}")

        except csv.Error as e:
            print(f"CSVHelper: ERROR - CSV file error in {filename}: {e}")
            QMessageBox.critical(None, "Error", f"CSV file error in {filename}: {e}")

        except KeyError as e:
            print(f"CSVHelper: ERROR - Missing 'pin' column in CSV file {filename}: {e}")
            QMessageBox.critical(None, "Error", f"CSV format error: Missing 'pin' column in {filename}")

        return data
