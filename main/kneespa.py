"""
KneeSpa Application with Dependency Injection
Main application module using the IoC container for dependency management
"""
import os
import sys
import logging
import argparse
from datetime import datetime

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt

# Set Qt environment variables before imports
os.environ["QT_LOGGING_RULES"] = "qt.qpa.xcb.fontdatabase=false"
os.environ["QT_DEBUG_PLUGINS"] = "0"
os.environ["QT_FONT_DPI"] = "96"

# Fix negative font size issue
import PyQt5.QtGui
originalSetPointSize = PyQt5.QtGui.QFont.setPointSize

def fixed_setPointSize(self, size):
    """Override QFont.setPointSize to prevent negative values"""
    if size <= 0:
        size = 10  # Use a reasonable default size
    return originalSetPointSize(self, size)

PyQt5.QtGui.QFont.setPointSize = fixed_setPointSize

# Import services setup
from main.modules.core.services import get_container
from main.modules.utils.logging_utils import setup_logger
from main.modules.utils.error_handling import handle_exception

class KneeSpaApp(QtWidgets.QMainWindow):
    """
    Main KneeSpa application class with dependency injection
    
    This class uses the IoC container to manage dependencies between
    components, making the system more maintainable and testable.
    """
    
    def __init__(self, debug_mode=False):
        """
        Initialize the KneeSpa application
        
        Args:
            debug_mode: Whether to run in debug mode
        """
        super().__init__()
        
        # Setup logger
        self.logger = setup_logger(component="KneeSpaApp")
        self.logger.info(f"Initializing KneeSpa application in {'debug' if debug_mode else 'production'} mode")
        
        # Application state
        self.debug_mode = debug_mode
        self.current_user = None
        
        # Initialize dependency container
        self.container = get_container(debug_mode)
        
        # Initialize application components
        self.initialize_components()
        
        # Connect signals and slots
        self.connect_signals()
        
        # Initialize CSV data
        self.initialize_data()
        
        self.logger.info("KneeSpa application initialized successfully")
        
    def initialize_components(self):
        """Initialize all application components using the container"""
        try:
            self.logger.info("Initializing application components")
            
            # Get config from container
            self.config = self.container.resolve("config")
            self.config.get_config()
            
            # Get controllers from container
            self.gpio_controller = self.container.resolve("gpio_controller")
            self.gpio_controller.initialize()
            
            self.arduino_controller = self.container.resolve("arduino_controller")
            self.arduino_controller.start()
            
            self.actuator_controller = self.container.resolve("actuator_controller")
            self.protocol_controller = self.container.resolve("protocol_controller")
            
            # Initialize UI controller with parent window
            ui_controller = self.container.resolve("ui_controller")
            ui_controller.parent = self  # Set parent window
            self.ui_controller = ui_controller
            
            # Initialize email sender
            self.email_sender = self.container.resolve("email_sender")
            self.email_sender.configure("ksdrxsmtp@gmail.com", "nujyxfajvgouwvux")
            
            self.logger.info("All components initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize components: {str(e)}")
            raise
            
    def connect_signals(self):
        """Connect signals between components"""
        try:
            self.logger.info("Connecting signals between components")
            
            # Connect UI controller signals
            self.ui_controller.login_success.connect(self.handle_login)
            self.ui_controller.logout_requested.connect(self.handle_logout)
            self.ui_controller.protocol_start_requested.connect(self.start_protocol)
            self.ui_controller.protocol_stop_requested.connect(self.stop_protocol)
            self.ui_controller.assistance_requested.connect(self.handle_assistance_request)
            
            # Connect actuator control signals
            self.ui_controller.actuator_position_changed.connect(self.handle_position_change)
            self.ui_controller.actuator_pressure_changed.connect(self.handle_pressure_change)
            self.ui_controller.actuator_reset_requested.connect(self.handle_actuator_reset)
            self.ui_controller.actuator_stop_requested.connect(self.handle_actuator_stop)
            self.ui_controller.actuator_move_requested.connect(self.handle_actuator_move)
            self.ui_controller.arduino_reset_requested.connect(self.handle_arduino_reset)
            self.ui_controller.emergency_stop_requested.connect(self.handle_emergency_stop)
            
            # Connect protocol controller signals
            self.protocol_controller.protocol_started.connect(self.handle_protocol_started)
            self.protocol_controller.protocol_stopped.connect(self.handle_protocol_stopped)
            self.protocol_controller.protocol_status_updated.connect(self.handle_protocol_status)
            self.protocol_controller.protocol_pressure_updated.connect(self.handle_protocol_pressure)
            
            # Connect actuator controller signals
            self.actuator_controller.position_changed.connect(self.handle_position_update)
            self.actuator_controller.pressure_changed.connect(self.handle_pressure_update)
            self.actuator_controller.operation_completed.connect(self.handle_operation_completed)
            
            # Connect Arduino controller signals
            self.arduino_controller.connection_status_changed.connect(self.handle_connection_status)
            
            self.logger.info("Signals connected successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to connect signals: {str(e)}")
            raise
            
    def initialize_data(self):
        """Initialize application data from CSV files"""
        try:
            self.logger.info("Initializing application data")
            
            # Initialize the CSV helper from container
            self.csv = self.container.resolve("csv_helper")
            self.csv.initialize_data()
            self.users = self.csv.users
            self.patients = self.csv.patients
            
            self.logger.info("Application data initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize data: {str(e)}")
            handle_exception(e, self, self.logger)
            
    # Signal handlers
    
    def handle_login(self, login_pin):
        """
        Handle login attempt
        
        Args:
            login_pin: Login PIN entered by the user
        """
        self.logger.info(f"Login attempt with PIN: {'*' * len(login_pin)}")
        
        try:
            if login_pin in self.users:
                self.current_user = self.users[login_pin]
                self.logger.info(f"Login successful for user: {self.current_user['username']}")
                
                # Update UI with user information
                self.ui_controller.update_ui_after_login(self.current_user)
                
                return True
            else:
                self.logger.warning("Login failed: Invalid PIN")
                QtWidgets.QMessageBox.warning(self, "Login Failed", "Invalid PIN. Please try again.")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during login: {str(e)}")
            handle_exception(e, self, self.logger)
            return False
            
    def handle_logout(self):
        """Handle logout request"""
        self.logger.info("User logged out")
        self.current_user = None
        
    # ... [rest of the handler methods remain the same] ...
    
    def shutdown(self):
        """Clean up resources and shutdown the application"""
        self.logger.info("Shutting down KneeSpa application")
        
        try:
            # Stop any running protocol
            if hasattr(self, 'protocol_controller') and self.protocol_controller.is_running:
                self.protocol_controller.stop_protocol()
                
            # Disconnect Arduino
            if hasattr(self, 'arduino_controller'):
                self.arduino_controller.disconnect()
                
            # Clean up GPIO
            if hasattr(self, 'gpio_controller'):
                self.gpio_controller.cleanup()
                
            self.logger.info("KneeSpa application shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}")
            
    def closeEvent(self, event):
        """Handle window close event"""
        self.logger.info("Window close event received")
        
        # Show confirmation dialog
        reply = QtWidgets.QMessageBox.question(
            self, 
            "Exit Application", 
            "Are you sure you want to exit?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, 
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Shutdown application
            self.shutdown()
            event.accept()
        else:
            event.ignore()
            
    def exit_app(self):
        """Exit the application"""
        self.logger.info("Exit application requested")
        self.close()
        
    def shutdown_app(self):
        """Shutdown the system"""
        self.logger.info("System shutdown requested")
        
        # Show confirmation dialog
        reply = QtWidgets.QMessageBox.question(
            self, 
            "Shutdown System", 
            "Are you sure you want to shutdown the system?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, 
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Shutdown application
            self.shutdown()
            
            # Shutdown system
            if not self.debug_mode:
                os.system("sudo shutdown -h now")
            else:
                self.logger.info("Debug mode: System shutdown skipped")
                
            # Exit application
            QtWidgets.QApplication.quit()


def main():
    """Main function to start the application"""
    parser = argparse.ArgumentParser(description="KneeSpa Application")
    parser.add_argument("--debug", action="store_true", help="Run in debug mode (windowed)")
    args = parser.parse_args()
    
    print(f"Application started at {datetime.now()}")
    print(f"Debug mode: {'enabled' if args.debug else 'disabled'}")
    
    app = QtWidgets.QApplication(sys.argv)
    window = KneeSpaApp(debug_mode=args.debug)
    window.show()
    
    sys.exit(app.exec_())
    
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Exception occurred: {str(e)}")
        print("Full traceback:")
        import traceback
        traceback.print_exc()
    finally:
        import RPi.GPIO as GPIO
        GPIO.cleanup()