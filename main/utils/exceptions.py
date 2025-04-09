# utils/exceptions.py

"""
Custom exceptions for KneeSpa application.
Defines hierarchy of application-specific exceptions for better error handling and debugging.
"""

from typing import Optional, Dict, Any

class KneeSpaException(Exception):
    """Base exception class for all KneeSpa exceptions."""
    
    def __init__(self, message: str, code: Optional[int] = None, **kwargs: Any):
        """
        Initialize base exception.
        
        Args:
            message: Error message
            code: Optional error code
            kwargs: Additional context parameters
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = kwargs
        
    def __str__(self) -> str:
        """String representation of the exception."""
        base_msg = f"{self.__class__.__name__}: {self.message}"
        if self.code:
            base_msg = f"{base_msg} (Error Code: {self.code})"
        if self.context:
            base_msg = f"{base_msg} | Context: {self.context}"
        return base_msg

# Hardware Exceptions
class HardwareException(KneeSpaException):
    """Base class for hardware-related exceptions."""
    pass

class ArduinoException(HardwareException):
    """Arduino communication and control exceptions."""
    pass

class ArduinoConnectionError(ArduinoException):
    """Arduino connection failures."""
    pass

class ArduinoTimeoutError(ArduinoException):
    """Arduino communication timeout."""
    pass

class ArduinoCommandError(ArduinoException):
    """Arduino command execution failures."""
    pass

class GPIOException(HardwareException):
    """GPIO operation exceptions."""
    pass

class ActuatorException(HardwareException):
    """Actuator operation exceptions."""
    pass

class EmergencyStopException(HardwareException):
    """Emergency stop related exceptions."""
    def __init__(self, message: str, triggered_by: str, **kwargs: Any):
        super().__init__(message, triggered_by=triggered_by, **kwargs)

# Protocol Exceptions
class ProtocolException(KneeSpaException):
    """Base class for protocol-related exceptions."""
    pass

class ProtocolValidationError(ProtocolException):
    """Protocol validation failures."""
    pass

class ProtocolExecutionError(ProtocolException):
    """Protocol execution failures."""
    pass

class ProtocolInterruptedError(ProtocolException):
    """Protocol interruption exceptions."""
    pass

class ProtocolSafetyError(ProtocolException):
    """Protocol safety limit violations."""
    pass

# User and Authentication Exceptions
class AuthenticationException(KneeSpaException):
    """Base class for authentication-related exceptions."""
    pass

class InvalidPINError(AuthenticationException):
    """Invalid PIN exceptions."""
    pass

class AccessDeniedError(AuthenticationException):
    """Access permission exceptions."""
    pass

class SessionExpiredError(AuthenticationException):
    """Session expiration exceptions."""
    pass

# Data Management Exceptions
class DataException(KneeSpaException):
    """Base class for data-related exceptions."""
    pass

class CSVError(DataException):
    """CSV file operation exceptions."""
    pass

class DataValidationError(DataException):
    """Data validation failures."""
    pass

class DataSaveError(DataException):
    """Data saving failures."""
    pass

class DataLoadError(DataException):
    """Data loading failures."""
    pass

# Configuration Exceptions
class ConfigurationException(KneeSpaException):
    """Base class for configuration-related exceptions."""
    
    def __init__(self, message: str, path: str = None, code: Optional[int] = None, **kwargs: Any):
        """
        Initialize configuration exception.
        
        Args:
            message: Error message
            path: Path to configuration file
            code: Error code
            kwargs: Additional context
        """
        super().__init__(message, code=code, path=path, **kwargs)
        self.path = path
    
    def __str__(self) -> str:
        """String representation with path information."""
        base_msg = super().__str__()
        if self.path:
            return f"{base_msg} (File: {self.path})"
        return base_msg

class ConfigurationLoadError(ConfigurationException):
    """Configuration loading failures."""
    pass

class ConfigurationSaveError(ConfigurationException):
    """Configuration saving failures."""
    pass

class InvalidConfigurationError(ConfigurationException):
    """Invalid configuration exceptions."""
    pass

# UI Exceptions
class UIException(KneeSpaException):
    """Base class for UI-related exceptions."""
    pass

class DialogError(UIException):
    """Dialog operation exceptions."""
    pass

class WidgetError(UIException):
    """Widget operation exceptions."""
    pass

# Safety System Exceptions
class SafetyException(KneeSpaException):
    """Base class for safety-related exceptions."""
    
    def __init__(
        self,
        message: str,
        severity: str = "HIGH",
        requires_reset: bool = True,
        **kwargs: Any
    ):
        """
        Initialize safety exception.
        
        Args:
            message: Error message
            severity: Error severity level
            requires_reset: Whether system reset is required
            kwargs: Additional context parameters
        """
        super().__init__(
            message,
            severity=severity,
            requires_reset=requires_reset,
            **kwargs
        )
        self.severity = severity
        self.requires_reset = requires_reset

class SafetyLimitException(SafetyException):
    """Safety limit violations."""
    pass

class EmergencyStopTriggered(SafetyException):
    """Emergency stop trigger events."""
    pass

class MotorOverloadException(SafetyException):
    """Motor overload events."""
    pass

# Utility Functions
def handle_exception(e: Exception) -> Dict[str, Any]:
    """
    Convert exception to dictionary format.
    
    Args:
        e: Exception to convert
        
    Returns:
        Dict containing exception details
    """
    error_info = {
        'type': e.__class__.__name__,
        'message': str(e),
        'module': e.__class__.__module__
    }
    
    if isinstance(e, KneeSpaException):
        error_info.update({
            'code': getattr(e, 'code', None),
            'context': getattr(e, 'context', {})
        })
        
    if isinstance(e, SafetyException):
        error_info.update({
            'severity': e.severity,
            'requires_reset': e.requires_reset
        })
        
    return error_info

def is_safety_critical(e: Exception) -> bool:
    """
    Check if exception is safety-critical.
    
    Args:
        e: Exception to check
        
    Returns:
        bool: True if safety-critical
    """
    return isinstance(e, SafetyException) and e.severity == "HIGH"

def requires_system_reset(e: Exception) -> bool:
    """
    Check if exception requires system reset.
    
    Args:
        e: Exception to check
        
    Returns:
        bool: True if reset required
    """
    return (
        isinstance(e, SafetyException) and
        e.requires_reset
    )

# Usage example:
"""
try:
    # Attempt some operation
    if safety_violation_detected:
        raise SafetyLimitException(
            "Safety limit exceeded",
            severity="HIGH",
            requires_reset=True,
            limit_type="pressure",
            current_value=current_pressure,
            limit_value=MAX_PRESSURE
        )
except SafetyLimitException as e:
    if is_safety_critical(e):
        trigger_emergency_stop()
    if requires_system_reset(e):
        initiate_system_reset()
    
    error_details = handle_exception(e)
    log_error(error_details)
    notify_operator(error_details)
"""