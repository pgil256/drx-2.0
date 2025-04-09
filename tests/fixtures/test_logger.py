"""
Test logging utilities for KneeSpa testing.

This module provides specialized logging functionality for tests.
"""
import os
import sys
import logging
import tempfile
from contextlib import contextmanager
from typing import Dict, List, Optional, Set, Any, Generator, Tuple

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from main.utils.logging import setup_logger


class TestLogCapture:
    """Captures and analyzes logs during tests."""
    
    def __init__(self, component: str = "TestLogger"):
        """Initialize the log capture.
        
        Args:
            component: Component name for the logger
        """
        self.component = component
        self.log_file = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        self.log_filename = self.log_file.name
        self.log_file.close()
        
        # Create a file handler for the test log
        self.file_handler = logging.FileHandler(self.log_filename)
        self.file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.file_handler.setFormatter(formatter)
        
        # Create the logger
        self.logger = setup_logger(component=component)
        self.logger.addHandler(self.file_handler)
        
        # Initialize log analysis variables
        self.captured_logs = []
        self.error_count = 0
        self.warning_count = 0
        
    def __del__(self):
        """Clean up resources."""
        self.cleanup()
        
    def cleanup(self):
        """Remove the temporary log file."""
        try:
            if hasattr(self, 'file_handler') and self.file_handler:
                self.logger.removeHandler(self.file_handler)
                self.file_handler.close()
                
            if hasattr(self, 'log_filename') and os.path.exists(self.log_filename):
                os.unlink(self.log_filename)
        except Exception as e:
            print(f"Error cleaning up test logger: {e}")
            
    def get_logs(self) -> List[str]:
        """Get all captured log lines.
        
        Returns:
            List of log lines
        """
        if not os.path.exists(self.log_filename):
            return []
            
        with open(self.log_filename, 'r') as f:
            logs = f.readlines()
            
        self.captured_logs = logs
        return logs
        
    def analyze_logs(self) -> Dict[str, Any]:
        """Analyze captured logs and return statistics.
        
        Returns:
            Dictionary with log statistics
        """
        logs = self.get_logs()
        
        analysis = {
            'total_lines': len(logs),
            'error_lines': 0,
            'warning_lines': 0,
            'info_lines': 0,
            'debug_lines': 0,
            'errors': [],
            'warnings': []
        }
        
        for line in logs:
            line = line.lower()
            if ' error ' in line or ' exception ' in line:
                analysis['error_lines'] += 1
                analysis['errors'].append(line.strip())
            elif ' warning ' in line or ' warn ' in line:
                analysis['warning_lines'] += 1
                analysis['warnings'].append(line.strip())
            elif ' info ' in line:
                analysis['info_lines'] += 1
            elif ' debug ' in line:
                analysis['debug_lines'] += 1
                
        self.error_count = analysis['error_lines']
        self.warning_count = analysis['warning_lines']
        
        return analysis
        
    def contains_message(self, message: str, level: Optional[str] = None) -> bool:
        """Check if logs contain a specific message.
        
        Args:
            message: Message text to search for
            level: Optional log level to filter by
            
        Returns:
            True if message is found
        """
        logs = self.get_logs()
        
        for line in logs:
            if message in line:
                if level is None:
                    return True
                elif f" {level.upper()} " in line:
                    return True
                    
        return False
        
    def count_message_occurrences(self, message: str) -> int:
        """Count occurrences of a message in logs.
        
        Args:
            message: Message text to search for
            
        Returns:
            Number of occurrences
        """
        logs = self.get_logs()
        return sum(1 for line in logs if message in line)
        
    def assert_no_errors(self):
        """Assert that no errors were logged.
        
        Raises:
            AssertionError: If errors were found in the logs
        """
        analysis = self.analyze_logs()
        if analysis['error_lines'] > 0:
            errors = '\n'.join(analysis['errors'][:5])  # Show first 5 errors
            raise AssertionError(
                f"Found {analysis['error_lines']} errors in logs. First errors:\n{errors}"
            )
            
    def assert_no_warnings(self):
        """Assert that no warnings were logged.
        
        Raises:
            AssertionError: If warnings were found in the logs
        """
        analysis = self.analyze_logs()
        if analysis['warning_lines'] > 0:
            warnings = '\n'.join(analysis['warnings'][:5])  # Show first 5 warnings
            raise AssertionError(
                f"Found {analysis['warning_lines']} warnings in logs. First warnings:\n{warnings}"
            )
            
    def assert_message_occurs(self, message: str, count: int = 1):
        """Assert that a message occurs a specific number of times.
        
        Args:
            message: Message text to search for
            count: Expected occurrence count
            
        Raises:
            AssertionError: If the message doesn't occur the expected number of times
        """
        actual_count = self.count_message_occurrences(message)
        if actual_count != count:
            raise AssertionError(
                f"Expected message '{message}' to occur {count} times, "
                f"but it occurred {actual_count} times"
            )


@contextmanager
def capture_logs(component: str = "TestLogger") -> Generator[TestLogCapture, None, None]:
    """Context manager for capturing logs during a test.
    
    Args:
        component: Component name for the logger
        
    Yields:
        TestLogCapture instance
    """
    capture = TestLogCapture(component)
    try:
        yield capture
    finally:
        capture.cleanup()


@contextmanager
def assert_log_message(message: str, component: str = "TestLogger") -> Generator[TestLogCapture, None, None]:
    """Context manager that asserts a message appears in logs.
    
    Args:
        message: Message that should appear in logs
        component: Component name for the logger
        
    Yields:
        TestLogCapture instance
        
    Raises:
        AssertionError: If the message doesn't appear in logs
    """
    with capture_logs(component) as logs:
        yield logs
        
    if not logs.contains_message(message):
        raise AssertionError(f"Expected log message '{message}' not found")


@contextmanager
def assert_no_errors_logged(component: str = "TestLogger") -> Generator[TestLogCapture, None, None]:
    """Context manager that asserts no errors were logged.
    
    Args:
        component: Component name for the logger
        
    Yields:
        TestLogCapture instance
        
    Raises:
        AssertionError: If any errors were logged
    """
    with capture_logs(component) as logs:
        yield logs
        
    logs.assert_no_errors()