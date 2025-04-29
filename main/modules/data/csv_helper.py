"""
CSV Helper Module
Provides utilities for working with CSV files for user and patient data
"""
import csv
import os
import logging
from typing import Dict, Any, Optional, List

from main.modules.utils.logging_utils import get_logger_with_context

class CSVHelper:
    """
    Helper class for CSV operations
    
    This class provides methods for loading and saving CSV data,
    particularly for user and patient records.
    """
    
    def __init__(self):
        """Initialize the CSV helper"""
        self.logger = get_logger_with_context(component="CSVHelper")
        self.users: Dict[str, Dict[str, str]] = {}
        self.patients: Dict[str, Dict[str, str]] = {}
        
        # Base directories for data files
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        self.user_csv_path = os.path.join(base_dir, 'data', 'users', 'user_pins.csv')
        self.patient_csv_path = os.path.join(base_dir, 'data', 'patients', 'patient_pins.csv')
        
        self.logger.info(
            "CSV helper initialized",
            structured_data={
                "user_csv_path": self.user_csv_path,
                "patient_csv_path": self.patient_csv_path
            }
        )

    def initialize_data(self) -> None:
        """Initialize CSV data by loading both user and patient data."""
        self.logger.info("Initializing CSV data")
        self.users = self.load_csv(self.user_csv_path)
        self.patients = self.load_csv(self.patient_csv_path)

    def load_csv(self, filename: str) -> Dict[str, Dict[str, str]]:
        """
        Load CSV data into a dictionary.

        Args:
            filename: Path to the CSV file

        Returns:
            Dictionary with PIN as key and row data as value
        """
        self.logger.info(f"Loading CSV file: {filename}")
        data: Dict[str, Dict[str, str]] = {}
        
        try:
            with open(filename, "r") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    if "pin" in row:
                        data[row["pin"]] = row
                    else:
                        self.logger.warning(
                            "CSV row missing PIN field", 
                            structured_data={"row": row}
                        )
            
            self.logger.info(
                f"CSV file loaded successfully",
                structured_data={
                    "filename": filename,
                    "record_count": len(data)
                }
            )

        except FileNotFoundError:
            self.logger.error(
                f"CSV file not found",
                structured_data={"path": filename}
            )
            # Create empty file with headers if it doesn't exist
            self._create_empty_csv(filename)

        except csv.Error as e:
            self.logger.error(
                f"CSV parsing error",
                structured_data={
                    "path": filename,
                    "error": str(e)
                }
            )
        
        except Exception as e:
            self.logger.error(
                f"Unexpected error loading CSV",
                structured_data={
                    "path": filename,
                    "error": str(e)
                },
                exc_info=True
            )

        return data

    def _create_empty_csv(self, filename: str) -> None:
        """
        Create an empty CSV file with appropriate headers
        
        Args:
            filename: Path to the CSV file to create
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            # Determine headers based on file type
            if "user" in filename:
                fieldnames = ["pin", "name", "email", "status"]
            else:  # patient file
                fieldnames = ["pin", "name", "email", "doctor", "notes"]
            
            # Create the file with headers
            with open(filename, "w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                
            self.logger.info(
                f"Created empty CSV file",
                structured_data={
                    "path": filename,
                    "fields": fieldnames
                }
            )
        except Exception as e:
            self.logger.error(
                f"Failed to create empty CSV file",
                structured_data={
                    "path": filename,
                    "error": str(e)
                },
                exc_info=True
            )

    def load_users(self) -> Dict[str, Dict[str, str]]:
        """
        Load users from CSV
        
        Returns:
            Dictionary of users (PIN -> user data)
        """
        self.users = self.load_csv(self.user_csv_path)
        return self.users
    
    def load_patients(self) -> Dict[str, Dict[str, str]]:
        """
        Load patients from CSV
        
        Returns:
            Dictionary of patients (PIN -> patient data)
        """
        self.patients = self.load_csv(self.patient_csv_path)
        return self.patients
    
    def save_users(self, users: Dict[str, Dict[str, str]]) -> bool:
        """
        Save users to CSV
        
        Args:
            users: Dictionary of users (PIN -> user data)
            
        Returns:
            True if saved successfully, False otherwise
        """
        return self._save_csv(self.user_csv_path, users)
    
    def save_patients(self, patients: Dict[str, Dict[str, str]]) -> bool:
        """
        Save patients to CSV
        
        Args:
            patients: Dictionary of patients (PIN -> patient data)
            
        Returns:
            True if saved successfully, False otherwise
        """
        return self._save_csv(self.patient_csv_path, patients)
    
    def _save_csv(self, filename: str, data: Dict[str, Dict[str, str]]) -> bool:
        """
        Save dictionary data to a CSV file
        
        Args:
            filename: Path to the CSV file
            data: Dictionary mapping PINs to row data dictionaries
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not data:
            self.logger.warning(
                f"Attempted to save empty data to CSV",
                structured_data={"path": filename}
            )
            return False
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            
            # Get fieldnames from first record
            first_record = next(iter(data.values()))
            fieldnames = list(first_record.keys())
            
            # Make sure 'pin' is the first field
            if 'pin' in fieldnames:
                fieldnames.remove('pin')
                fieldnames.insert(0, 'pin')
                
            with open(filename, "w", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                for row in data.values():
                    writer.writerow(row)
                    
            self.logger.info(
                f"CSV file saved successfully",
                structured_data={
                    "path": filename,
                    "record_count": len(data)
                }
            )
            return True
            
        except Exception as e:
            self.logger.error(
                f"Failed to save CSV file",
                structured_data={
                    "path": filename,
                    "error": str(e)
                },
                exc_info=True
            )
            return False
            
    def get_user(self, pin: str) -> Optional[Dict[str, str]]:
        """
        Get user data by PIN
        
        Args:
            pin: User PIN
            
        Returns:
            User data dictionary or None if not found
        """
        return self.users.get(pin)
        
    def get_patient(self, pin: str) -> Optional[Dict[str, str]]:
        """
        Get patient data by PIN
        
        Args:
            pin: Patient PIN
            
        Returns:
            Patient data dictionary or None if not found
        """
        return self.patients.get(pin)
    
    def add_user(self, user_data: Dict[str, str]) -> bool:
        """
        Add a new user
        
        Args:
            user_data: User data dictionary (must include 'pin')
            
        Returns:
            True if added successfully, False otherwise
        """
        if 'pin' not in user_data:
            self.logger.error("Cannot add user without PIN")
            return False
            
        pin = user_data['pin']
        self.users[pin] = user_data
        return self.save_users(self.users)
        
    def add_patient(self, patient_data: Dict[str, str]) -> bool:
        """
        Add a new patient
        
        Args:
            patient_data: Patient data dictionary (must include 'pin')
            
        Returns:
            True if added successfully, False otherwise
        """
        if 'pin' not in patient_data:
            self.logger.error("Cannot add patient without PIN")
            return False
            
        pin = patient_data['pin']
        self.patients[pin] = patient_data
        return self.save_patients(self.patients)