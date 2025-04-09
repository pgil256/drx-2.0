"""
UI test fixtures for KneeSpa application.

This module provides utilities and fixtures for testing UI components.
"""
import sys
import os
import pytest
import time
from typing import Optional, Dict, Any, List, Tuple
from unittest.mock import MagicMock, patch

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Conditionally import PyQt5 to allow tests to run in environments without UI
try:
    from PyQt5.QtWidgets import QApplication, QWidget, QDialog
    from PyQt5.QtTest import QTest
    from PyQt5.QtCore import Qt, QTimer
    PyQt5_AVAILABLE = True
except ImportError:
    PyQt5_AVAILABLE = False
    
# Import conditionally to avoid immediate errors
if PyQt5_AVAILABLE:
    # Import UI modules if PyQt5 is available
    from main.ui.dialogs.timer_dialog import TimerDialog
    from main.ui.dialogs.pressure_dialog import PressureDialog
    from main.ui.dialogs.video_player import VideoPlayer
    

class UITestingNotSupportedError(Exception):
    """Exception raised when UI testing is not supported."""
    pass


class MockQApplication:
    """Mock QApplication for environments without UI support."""
    
    @staticmethod
    def instance():
        """Return None to indicate no application instance."""
        return None
        
    @classmethod
    def create(cls):
        """Create a mock application instance."""
        app = cls()
        return app
        
    def exec_(self):
        """Mock application execution."""
        pass
        
    def processEvents(self):
        """Mock event processing."""
        pass


class UITestFixture:
    """Test fixture for UI components.
    
    This class provides utilities for testing UI components without
    requiring a graphical environment.
    """
    
    def __init__(self):
        """Initialize the UI test fixture."""
        self.app = None
        self.widgets = {}
        self.event_loop_running = False
        
    def setup(self) -> bool:
        """Set up the UI test environment.
        
        Returns:
            True if setup successful, False otherwise
        """
        if not PyQt5_AVAILABLE:
            return False
            
        # Get or create QApplication instance
        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
            
        return True
        
    def teardown(self):
        """Clean up UI test environment."""
        # Close any open widgets
        for widget in self.widgets.values():
            if hasattr(widget, 'close'):
                widget.close()
                
        self.widgets = {}
        
        # Don't quit the application to avoid affecting other tests
        
    def process_events(self, msecs: int = 100):
        """Process UI events for the specified time.
        
        Args:
            msecs: Time to process events in milliseconds
        """
        if self.app is None:
            return
            
        # Process events for a short period
        self.app.processEvents()
        time.sleep(msecs / 1000)
        self.app.processEvents()
        
    def register_widget(self, name: str, widget: QWidget):
        """Register a widget for tracking.
        
        Args:
            name: Name to associate with the widget
            widget: QWidget instance
        """
        self.widgets[name] = widget
        
    def get_widget(self, name: str) -> Optional[QWidget]:
        """Get a registered widget by name.
        
        Args:
            name: Widget name
            
        Returns:
            QWidget if found, None otherwise
        """
        return self.widgets.get(name)


class MockDialog(MagicMock):
    """Mock dialog for testing without UI."""
    
    def __init__(self, *args, **kwargs):
        """Initialize mock dialog."""
        super().__init__(*args, **kwargs)
        self.accepted = False
        self.rejected = False
        self.shown = False
        self.closed = False
        
    def exec_(self):
        """Simulate dialog execution."""
        self.shown = True
        return 1 if self.accepted else 0
        
    def accept(self):
        """Simulate dialog acceptance."""
        self.accepted = True
        self.closed = True
        
    def reject(self):
        """Simulate dialog rejection."""
        self.rejected = True
        self.closed = True
        
    def close(self):
        """Simulate dialog close."""
        self.closed = True
        
    def show(self):
        """Simulate dialog show."""
        self.shown = True


@pytest.fixture
def ui_fixture() -> UITestFixture:
    """Fixture to provide a UITestFixture.
    
    Returns:
        UITestFixture instance
    """
    fixture = UITestFixture()
    if not fixture.setup():
        pytest.skip("UI testing not supported in this environment")
        
    yield fixture
    
    fixture.teardown()


@pytest.fixture
def mock_dialog():
    """Fixture to provide a mock dialog.
    
    Returns:
        MockDialog instance
    """
    return MockDialog()


@pytest.fixture
def mock_timer_dialog():
    """Fixture to provide a mock TimerDialog.
    
    Returns:
        MockDialog configured as a TimerDialog
    """
    dialog = MockDialog(spec=TimerDialog if PyQt5_AVAILABLE else object)
    dialog.get_minutes.return_value = 5
    return dialog


@pytest.fixture
def mock_pressure_dialog():
    """Fixture to provide a mock PressureDialog.
    
    Returns:
        MockDialog configured as a PressureDialog
    """
    dialog = MockDialog(spec=PressureDialog if PyQt5_AVAILABLE else object)
    dialog.get_pressure.return_value = 30
    return dialog


@pytest.fixture
def mock_video_player():
    """Fixture to provide a mock VideoPlayer.
    
    Returns:
        MockDialog configured as a VideoPlayer
    """
    dialog = MockDialog(spec=VideoPlayer if PyQt5_AVAILABLE else object)
    return dialog