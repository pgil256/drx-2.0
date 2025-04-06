import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime
from typing import Optional, Dict, Any
from config.constants import APP_NAME, APP_BASE_DIR, LOG_LEVEL


class LoggerSetup:
    """
    Configure and manage application logging.
    Implements a Singleton pattern to ensure only one logger instance is created.
    """

    _instance = None  # Singleton instance

    def __new__(cls, *args, **kwargs):
        # Implement Singleton pattern to ensure only one instance of LoggerSetup
        if cls._instance is None:
            cls._instance = super(LoggerSetup, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize logging configuration."""
        if hasattr(self, "_initialized") and self._initialized:
            return

        self.log_dir = os.path.join(APP_BASE_DIR, "logs")
        self.main_log_file = os.path.join(self.log_dir, "kneespa.log")
        self.error_log_file = os.path.join(self.log_dir, "error.log")
        self.debug_log_file = os.path.join(self.log_dir, "debug.log")

        # Create log directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)

        # Initialize logger
        self.logger = logging.getLogger(APP_NAME)
        self.logger.setLevel(getattr(logging, LOG_LEVEL))

        # Set up handlers only if they have not been set up already
        if not self.logger.hasHandlers():
            self.setup_handlers()

        # Mark as initialized to prevent redundant initializations
        self._initialized = True

        # Log initialization
        print(f"Logging initialized at {datetime.now()}")

    def setup_handlers(self) -> None:
        """Configure logging handlers with appropriate formats."""
        # Common format for all logs
        verbose_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"
        )

        simple_formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        )

        # Main file handler (all logs)
        main_handler = logging.handlers.RotatingFileHandler(
            self.main_log_file, maxBytes=10 * 1024 * 1024, backupCount=5  # 10MB
        )
        main_handler.setFormatter(verbose_formatter)
        main_handler.setLevel(logging.INFO)
        self.logger.addHandler(main_handler)

        # Error file handler (errors only)
        error_handler = logging.handlers.RotatingFileHandler(
            self.error_log_file, maxBytes=5 * 1024 * 1024, backupCount=3  # 5MB
        )
        error_handler.setFormatter(verbose_formatter)
        error_handler.setLevel(logging.ERROR)
        self.logger.addHandler(error_handler)

        # Debug file handler (debug and above)
        debug_handler = logging.handlers.RotatingFileHandler(
            self.debug_log_file, maxBytes=20 * 1024 * 1024, backupCount=2  # 20MB
        )
        debug_handler.setFormatter(verbose_formatter)
        debug_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(debug_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(simple_formatter)
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

    def get_logger(self) -> logging.Logger:
        """Get configured logger instance."""
        return self.logger

    @staticmethod
    def format_exception(e: Exception) -> str:
        """
        Format exception with traceback.

        Args:
            e: Exception to format

        Returns:
            str: Formatted exception with traceback
        """
        return f"{str(e)}\nTraceback:\n{''.join(traceback.format_tb(e.__traceback__))}"


class LoggerAdapter(logging.LoggerAdapter):
    """Custom logger adapter for adding context to log messages."""

    def __init__(self, logger: logging.Logger, extra: Optional[Dict[str, Any]] = None):
        """
        Initialize adapter with optional context.

        Args:
            logger: Base logger instance
            extra: Additional context dictionary
        """
        super().__init__(logger, extra or {})

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """
        Process log message with context.

        Args:
            msg: Log message
            kwargs: Additional arguments

        Returns:
            tuple: Processed message and kwargs
        """
        # Add user context if available
        user_context = self.extra.get("user", "")
        if user_context:
            msg = f"[User: {user_context}] {msg}"

        # Add component context if available
        component = self.extra.get("component", "")
        if component:
            msg = f"[{component}] {msg}"

        return msg, kwargs


def setup_logger(
    component: str = "", user: str = "", level: str = LOG_LEVEL
) -> LoggerAdapter:
    """
    Create configured logger for component.

    Args:
        component: Component name for context
        user: User name for context
        level: Logging level

    Returns:
        LoggerAdapter: Configured logger adapter
    """
    logger_setup = LoggerSetup()
    logger = logger_setup.get_logger()

    return LoggerAdapter(logger, {"component": component, "user": user})


# Example usage in other modules:
"""
from utils.logging import setup_logger

# Create logger for component
logger = setup_logger(component='Arduino')

# Log messages with component context
logger.info('Arduino initialized')
logger.error('Communication error')

# Create logger with user context
user_logger = setup_logger(component='UserInterface', user='admin')
user_logger.info('User action performed')

# Log with exception formatting
try:
    # Some operation
    pass
except Exception as e:
    logger.error(f"Operation failed: {LoggerSetup.format_exception(e)}")
"""


class ErrorLogging:
    """Error logging utility functions."""

    @staticmethod
    def log_system_error(
        logger: LoggerAdapter, error: Exception, context: str = ""
    ) -> None:
        """
        Log system error with full context.

        Args:
            logger: Logger instance
            error: Exception to log
            context: Additional context information
        """
        error_msg = f"System Error: {str(error)}"
        if context:
            error_msg = f"{error_msg} | Context: {context}"

        logger.error(error_msg, exc_info=True)

    @staticmethod
    def log_user_error(logger: LoggerAdapter, error: str, user: str = "") -> None:
        """
        Log user-related error.

        Args:
            logger: Logger instance
            error: Error message
            user: Username for context
        """
        error_msg = f"User Error: {error}"
        if user:
            error_msg = f"{error_msg} | User: {user}"

        logger.warning(error_msg)

    @staticmethod
    def log_hardware_error(
        logger: LoggerAdapter,
        component: str,
        error: Exception,
        status: Dict[str, Any] = None,
    ) -> None:
        """
        Log hardware-related error.

        Args:
            logger: Logger instance
            component: Hardware component name
            error: Exception to log
            status: Optional status dictionary
        """
        error_msg = f"Hardware Error in {component}: {str(error)}"
        if status:
            error_msg = f"{error_msg} | Status: {status}"

        logger.error(error_msg, exc_info=True)


# Create global logger instance
logger = setup_logger()
