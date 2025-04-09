"""
Unit tests for CSV data handling.
"""
import pytest
import os
import tempfile
import csv
from unittest.mock import patch, MagicMock
from typing import Dict, Any, Optional, List

# Add project root to Python path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from main.helpers.csv import CSVHelper
from tests.fixtures.test_logger import capture_logs


class MockQMessageBox:
    """Mock for QMessageBox to avoid GUI dependencies."""
    
    @staticmethod
    def information(*args, **kwargs):
        """Mock information dialog."""
        return 0
        
    @staticmethod
    def warning(*args, **kwargs):
        """Mock warning dialog."""
        return 0
        
    @staticmethod
    def critical(*args, **kwargs):
        """Mock critical dialog."""
        return 0


class MockQTableWidget:
    """Mock for QTableWidget to avoid GUI dependencies."""
    
    def __init__(self, data: Dict[str, str]):
        """Initialize with test data.
        
        Args:
            data: Dictionary of field_name: value pairs
        """
        self.data = data
        self.rows = [(key, value) for key, value in data.items()]
        
    def rowCount(self) -> int:
        """Return number of rows.
        
        Returns:
            Number of rows
        """
        return len(self.rows)
        
    def item(self, row: int, col: int) -> MagicMock:
        """Return mock table item.
        
        Args:
            row: Row index
            col: Column index
            
        Returns:
            Mock item with text method
        """
        item = MagicMock()
        if col == 0:  # Field name
            item.text.return_value = self.rows[row][0]
        else:  # Value
            item.text.return_value = self.rows[row][1]
        return item


@pytest.fixture
def temp_csv_files() -> Dict[str, str]:
    """Create temporary CSV files for testing.
    
    Returns:
        Dictionary of file type to file path
    """
    files = {}
    
    # Create user CSV
    user_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    files['user'] = user_file.name
    with open(user_file.name, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['pin', 'name', 'status'])
        writer.writerow(['1234', 'Admin User', 'admin'])
        writer.writerow(['5678', 'Regular User', 'user'])
    
    # Create patient CSV
    patient_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    files['patient'] = patient_file.name
    with open(patient_file.name, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['pin', 'name', 'age', 'condition'])
        writer.writerow(['2468', 'Test Patient', '45', 'Knee Pain'])
        writer.writerow(['1357', 'Another Patient', '62', 'Osteoarthritis'])
    
    return files


@pytest.mark.unit
class TestCSVHelper:
    """Test suite for CSVHelper class."""
    
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_load_csv(self, temp_csv_files: Dict[str, str]):
        """Test loading CSV data."""
        csv_helper = CSVHelper()
        
        # Test loading user CSV
        user_data = csv_helper.load_csv(temp_csv_files['user'])
        assert len(user_data) == 2
        assert '1234' in user_data
        assert user_data['1234']['name'] == 'Admin User'
        assert user_data['1234']['status'] == 'admin'
        
        # Test loading patient CSV
        patient_data = csv_helper.load_csv(temp_csv_files['patient'])
        assert len(patient_data) == 2
        assert '2468' in patient_data
        assert patient_data['2468']['name'] == 'Test Patient'
        assert patient_data['1357']['condition'] == 'Osteoarthritis'
        
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_load_nonexistent_csv(self):
        """Test loading a non-existent CSV file."""
        with capture_logs("CSV Helper") as logs:
            csv_helper = CSVHelper()
            
            # Load non-existent file
            data = csv_helper.load_csv("/nonexistent/file.csv")
            
            # Verify empty data returned
            assert data == {}
            
            # Check logs for error
            assert logs.contains_message("CSV file not found")
        
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_invalid_csv_format(self, temp_csv_files: Dict[str, str]):
        """Test loading an invalid CSV file."""
        # Create invalid CSV file
        invalid_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        with open(invalid_file.name, 'w') as f:
            f.write('pin,name,status\n')
            f.write('1234,"Unclosed quote\n')  # Invalid format
            
        with capture_logs("CSV Helper") as logs:
            csv_helper = CSVHelper()
            
            # Try to load invalid file - should handle error gracefully
            data = csv_helper.load_csv(invalid_file.name)
            
            # Check logs for error
            assert logs.contains_message("CSV file error")
            
        # Clean up
        os.unlink(invalid_file.name)
        
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_initialize_data(self, temp_csv_files: Dict[str, str]):
        """Test initializing data from CSV files."""
        csv_helper = CSVHelper()
        
        # Patch the path constants for testing
        with patch('main.helpers.csv.CSVHelper.load_csv') as mock_load_csv:
            mock_load_csv.side_effect = lambda path: (
                {'1234': {'pin': '1234', 'name': 'Admin'}} if 'user' in path 
                else {'2468': {'pin': '2468', 'name': 'Patient'}}
            )
            
            # Initialize data
            csv_helper.initialize_data()
            
            # Check data was loaded
            assert '1234' in csv_helper.users
            assert '2468' in csv_helper.patients
            
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_save_patient_data(self, temp_csv_files: Dict[str, str]):
        """Test saving patient data."""
        csv_helper = CSVHelper()
        
        # Load test data
        csv_helper.patients = csv_helper.load_csv(temp_csv_files['patient'])
        
        # Mock table widget with updated data
        table_data = {
            'name': 'Test Patient Updated',
            'age': '46',
            'condition': 'Knee Pain Improved'
        }
        mock_table = MockQTableWidget(table_data)
        
        # Create a temp file for saving
        save_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        
        with patch('main.helpers.csv.open', create=True) as mock_open:
            # Make open return our temp file
            mock_open.return_value.__enter__.return_value = open(save_file.name, 'w')
            
            # Call save with admin user
            current_user = {'status': 'admin'}
            csv_helper.save_patient_data(current_user, '2468', mock_table)
            
            # Check data was updated
            assert csv_helper.patients['2468']['name'] == 'Test Patient Updated'
            assert csv_helper.patients['2468']['age'] == '46'
            assert csv_helper.patients['2468']['condition'] == 'Knee Pain Improved'
            
        # Clean up
        os.unlink(save_file.name)
        
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_save_patient_data_unauthorized(self, temp_csv_files: Dict[str, str]):
        """Test saving patient data with non-admin user."""
        csv_helper = CSVHelper()
        
        # Load test data
        csv_helper.patients = csv_helper.load_csv(temp_csv_files['patient'])
        
        # Original data
        original_name = csv_helper.patients['2468']['name']
        
        # Mock table widget with updated data
        table_data = {
            'name': 'Should Not Update',
            'age': '99',
            'condition': 'Should Not Change'
        }
        mock_table = MockQTableWidget(table_data)
        
        with capture_logs("CSV Helper") as logs:
            # Call save with non-admin user
            current_user = {'status': 'user'}
            csv_helper.save_patient_data(current_user, '2468', mock_table)
            
            # Check data was not updated
            assert csv_helper.patients['2468']['name'] == original_name
            
            # Check logs for error
            assert logs.contains_message("Access denied")
            
    @patch('main.helpers.csv.QMessageBox', MockQMessageBox)
    def test_save_patient_data_invalid_pin(self, temp_csv_files: Dict[str, str]):
        """Test saving patient data with invalid PIN."""
        csv_helper = CSVHelper()
        
        # Load test data
        csv_helper.patients = csv_helper.load_csv(temp_csv_files['patient'])
        
        # Mock table widget with updated data
        table_data = {
            'name': 'Should Not Update',
            'age': '99',
            'condition': 'Should Not Change'
        }
        mock_table = MockQTableWidget(table_data)
        
        with capture_logs("CSV Helper") as logs:
            # Call save with non-existent patient PIN
            current_user = {'status': 'admin'}
            csv_helper.save_patient_data(current_user, '9999', mock_table)
            
            # Check logs for error
            assert logs.contains_message("No patient data to save")