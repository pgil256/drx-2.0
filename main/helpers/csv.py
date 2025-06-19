import csv
import logging
import os
from helpers.logging import setup_logger
from PyQt5.QtWidgets import QMessageBox


class CSVHelper:
    def __init__(self):
        self.logger = setup_logger(component="CSV Helper")
        self.users = {}

    def initialize_data(self):
        """Initialize CSV data by loading user data."""
        # Get the directory of the current file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Navigate to the data/users directory relative to the current file
        users_file = os.path.join(current_dir, "..", "data", "user_pins.csv")
        self.users = self.load_csv(users_file)
        
    def load_csv(self, filename):
        """
        Load CSV data into a dictionary.

        Args:
            filename (str): Path to the CSV file

        Returns:
            dict: Dictionary with PIN as key and row data as value
        """
        print(f"Loading CSV file: {filename}")

        data = {}
        try:
            with open(filename, "r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    data[row["pin"]] = row
            print(f"CSV file {filename} loaded successfully")

        except FileNotFoundError:
            print(f"CSV file not found: {filename}")
            QMessageBox.critical(None, "Error", f"CSV file not found: {filename}")

        except csv.Error as e:
            print(f"CSV file error in {filename}: {e}")
            QMessageBox.critical(None, "Error", f"CSV file error in {filename}: {e}")

        return data
