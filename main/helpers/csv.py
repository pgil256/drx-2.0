import csv
import logging
from utils.logging import setup_logger
from PyQt5.QtWidgets import QMessageBox


class CSVHelper:
    def __init__(self):
        self.logger = setup_logger(component="CSV Helper")
        self.users = {}
        self.patients = {}

    def initialize_data(self):
        """Initialize CSV data by loading both user and patient data."""
        self.users = self.load_csv("/home/pi/drx-2.0/main/data/users/user_pins.csv")
        self.patients = self.load_csv(
            "/home/pi/drx-2.0/main/data/patients/patient_pins.csv"
        )

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

    def save_patient_data(self, current_user, current_pin, table_widget):
        """
        Save patient data to CSV.

        Args:
            current_user (dict): Current user data including status
            current_pin (str): Current patient's PIN
            table_widget (QTableWidget): Table widget containing patient data
        """
        print("Saving patient data to CSV")

        if not current_user or current_user["status"] != "admin":
            QMessageBox.warning(
                None, "Access Denied", "Only admins can save patient data."
            )
            print("Access denied for saving patient data")
            return

        if current_pin not in self.patients:
            QMessageBox.warning(None, "Error", "No patient data to save.")
            print("No patient data to save")
            return

        # Update patient data from table
        for row in range(table_widget.rowCount()):
            key = table_widget.item(row, 0).text().lower().replace(" ", "_")
            value = table_widget.item(row, 1).text()
            self.patients[current_pin][key] = value

        # Save to CSV file
        try:
            with open(
                "/home/pi/drx-2.0/main/data/patients/patient_pins.csv", "w", newline=""
            ) as file:
                writer = csv.DictWriter(
                    file, fieldnames=self.patients[current_pin].keys()
                )
                writer.writeheader()
                for patient in self.patients.values():
                    writer.writerow(patient)

            QMessageBox.information(
                None, "Success", "Patient data updated successfully."
            )
            print("Patient data saved successfully")

        except Exception as e:
            QMessageBox.critical(
                None, "Error", f"Failed to save patient data: {str(e)}"
            )
            print(f"Error saving patient data: {str(e)}")
