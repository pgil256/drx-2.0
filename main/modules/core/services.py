"""
Service Registration Module
Configures the dependency injection container for the application
"""
from main.modules.utils.container import Container
from main.modules.hardware.arduino_controller import ArduinoController
from main.modules.hardware.gpio_controller import GPIOController
from main.modules.hardware.actuator_controller import ActuatorController
from main.modules.protocols.protocol_controller import ProtocolController
from main.modules.ui.ui_controller import UIController
from main.modules.utils.email_utils import EmailSender
from main.config.settings import get_settings
from main.modules.data.csv_helper import CSVHelper

def configure_services(container: Container, debug_mode: bool = False) -> Container:
    """
    Configure all services in the container
    
    Args:
        container: The dependency injection container
        debug_mode: Whether to run in debug mode
        
    Returns:
        The configured container
    """
    # Register configuration
    settings = get_settings()
    container.register("config", instance=settings)
    
    # Register hardware components
    container.register_class("gpio_controller", GPIOController, singleton=True)
    container.register_class("arduino_controller", ArduinoController, singleton=True)
    
    # Register actuator controller with dependencies
    def create_actuator_controller():
        config = container.resolve("config")
        arduino = container.resolve("arduino_controller")
        return ActuatorController(arduino, config)
    
    container.register("actuator_controller", factory=create_actuator_controller)
    
    # Register protocol controller with dependencies
    def create_protocol_controller():
        config = container.resolve("config")
        arduino = container.resolve("arduino_controller")
        return ProtocolController(arduino, config)
    
    container.register("protocol_controller", factory=create_protocol_controller)
    
    # Register UI controller (needs parent window which will be injected later)
    container.register_class("ui_controller", UIController, 
                           parent=None, debug_mode=debug_mode, singleton=True)
    
    # Register email sender
    container.register_class("email_sender", EmailSender, singleton=True)
    
    # Register CSV helper
    container.register_class("csv_helper", CSVHelper, singleton=True)
    
    return container

def get_container(debug_mode: bool = False) -> Container:
    """
    Get the configured container with all services registered
    
    Args:
        debug_mode: Whether to run in debug mode
        
    Returns:
        The configured container
    """
    container = Container()
    return configure_services(container, debug_mode)