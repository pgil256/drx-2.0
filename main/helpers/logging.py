import logging
import logging.handlers
import os
import sys
import traceback
import time
from datetime import datetime
from typing import Optional, Dict, Any
from config.constants import APP_NAME, APP_BASE_DIR, LOG_LEVEL


class LoggerSetup:
    """
    Configure and manage application logging.
    Implements a Singleton pattern to ensure only one logger instance is created.
    """

    _instance = None  # Singleton instance

    # Add Qt warning filter class
    class QtWarningFilter(logging.Filter):
        def filter(self, record):
            return not record.getMessage().startswith('QFont::setPointSize')


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

        # Add Qt warning filter
        qt_logger = logging.getLogger('PyQt5')
        qt_logger.addFilter(self.QtWarningFilter())

        # Set up handlers only if they have not been set up already.
        # Checked via .handlers (this logger's own), NOT hasHandlers():
        # hasHandlers() walks up to the root logger, so a stray
        # logging.basicConfig() anywhere would return True and silently
        # skip the rotating file handlers.
        if not self.logger.handlers:
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

# Create global logger instance
logger = setup_logger()


# =============================================================================
# ENHANCED DEBUG FUNCTIONS FOR REAL-TIME VISIBILITY
# =============================================================================

def debug(message: str, component: str = "", level: str = "DEBUG", **kwargs):
    """
    Universal debug function that prints AND logs.
    Used for general debugging information.

    Args:
        message: Debug message to output
        component: Component name for context (e.g., "Arduino", "Protocol")
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        **kwargs: Additional context (e.g., values={'pressure': 50, 'position': 100})
    """
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

    # Build formatted message with optional context
    context_str = ""
    if kwargs:
        context_items = []
        for key, value in kwargs.items():
            if key == 'values' and isinstance(value, dict):
                # Special handling for values dict
                context_items.extend([f"{k}={v}" for k, v in value.items()])
            else:
                context_items.append(f"{key}={value}")
        if context_items:
            context_str = f" [{', '.join(context_items)}]"

    comp_str = f"[{component}] " if component else ""
    formatted_msg = f"[{timestamp}] {comp_str}{message}{context_str}"

    # Always print for real-time visibility
    print(formatted_msg)

    # Also log for persistence
    try:
        comp_logger = setup_logger(component=component)
        level_method = getattr(comp_logger, level.lower(), comp_logger.info)
        level_method(f"{message}{context_str}")
    except Exception as e:
        print(f"[{timestamp}] [LOGGING ERROR] Failed to log: {e}")


def debug_serial(message: str, data: str = None, **kwargs):
    """
    Specialized debug for serial communication.

    Args:
        message: Description of serial event
        data: Raw serial data (will be safely formatted)
        **kwargs: Additional context
    """
    if data is not None:
        # Safely format serial data (handle non-printable chars)
        safe_data = repr(data) if data else "EMPTY"
        debug(f"SERIAL: {message} | Data: {safe_data}", component="Arduino", **kwargs)
    else:
        debug(f"SERIAL: {message}", component="Arduino", **kwargs)


def debug_protocol(message: str, state: dict = None, **kwargs):
    """
    Specialized debug for protocol execution.

    Args:
        message: Protocol event description
        state: Current protocol state dictionary
        **kwargs: Additional context
    """
    if state:
        state_str = ', '.join([f"{k}={v}" for k, v in state.items()])
        debug(f"PROTOCOL: {message} | State: [{state_str}]", component="Protocol", **kwargs)
    else:
        debug(f"PROTOCOL: {message}", component="Protocol", **kwargs)


def debug_safety(message: str, limits: dict = None, current: dict = None, **kwargs):
    """
    Specialized debug for safety-critical operations.

    Args:
        message: Safety event description
        limits: Dictionary of safety limits
        current: Dictionary of current values
        **kwargs: Additional context
    """
    level = kwargs.pop('level', 'WARNING')  # Default to WARNING for safety

    info_parts = [f"SAFETY: {message}"]
    if current:
        info_parts.append(f"Current: {current}")
    if limits:
        info_parts.append(f"Limits: {limits}")

    debug(' | '.join(info_parts), component="Safety", level=level, **kwargs)


def debug_thread(message: str, thread_name: str = None, state: str = None, **kwargs):
    """
    Specialized debug for threading operations.

    Args:
        message: Thread event description
        thread_name: Name of the thread
        state: Thread state (STARTING, RUNNING, STOPPING, etc.)
        **kwargs: Additional context
    """
    import threading
    current = threading.current_thread().name

    parts = [f"THREAD: {message}"]
    if thread_name:
        parts.append(f"Thread: {thread_name}")
    if state:
        parts.append(f"State: {state}")
    parts.append(f"Current: {current}")

    debug(' | '.join(parts), component="Threading", **kwargs)


def debug_state_change(component: str, old_state: Any, new_state: Any, reason: str = ""):
    """
    Log state transitions with before/after values.

    Args:
        component: Component experiencing state change
        old_state: Previous state value
        new_state: New state value
        reason: Optional reason for change
    """
    reason_str = f" | Reason: {reason}" if reason else ""
    debug(f"STATE CHANGE: {old_state} -> {new_state}{reason_str}",
          component=component, level="INFO")


def debug_timing(message: str, start_time: float = None, component: str = "", **kwargs):
    """
    Log timing information for performance analysis.

    Args:
        message: Timing event description
        start_time: Start time from time.time() to calculate elapsed
        component: Component being timed
        **kwargs: Additional context
    """
    import time

    if start_time:
        elapsed = time.time() - start_time
        debug(f"TIMING: {message} | Elapsed: {elapsed:.3f}s",
              component=component, **kwargs)
    else:
        debug(f"TIMING: {message}", component=component, **kwargs)


def debug_gpio(message: str, pin: int = None, state: Any = None, **kwargs):
    """
    Debug GPIO operations.

    Args:
        message: GPIO event description
        pin: GPIO pin number
        state: Pin state (HIGH/LOW, 1/0, etc.)
        **kwargs: Additional context
    """
    parts = [f"GPIO: {message}"]
    if pin is not None:
        parts.append(f"Pin: {pin}")
    if state is not None:
        parts.append(f"State: {state}")

    debug(' | '.join(parts), component="GPIO", **kwargs)


def debug_signal(message: str, signal_name: str = None, data: Any = None, **kwargs):
    """
    Debug PyQt signal emissions and connections.

    Args:
        message: Signal event description
        signal_name: Name of the signal
        data: Data being emitted
        **kwargs: Additional context
    """
    parts = [f"SIGNAL: {message}"]
    if signal_name:
        parts.append(f"Signal: {signal_name}")
    if data is not None:
        parts.append(f"Data: {data}")

    debug(' | '.join(parts), component="Qt", **kwargs)


def debug_error(message: str, exception: Exception = None, component: str = "", **kwargs):
    """
    Log errors with full traceback.

    Args:
        message: Error description
        exception: Exception object
        component: Component where error occurred
        **kwargs: Additional context
    """
    import traceback

    if exception:
        tb_str = ''.join(traceback.format_tb(exception.__traceback__))
        full_msg = f"ERROR: {message} | Exception: {str(exception)}\nTraceback:\n{tb_str}"
    else:
        full_msg = f"ERROR: {message}"

    debug(full_msg, component=component, level="ERROR", **kwargs)


def debug_lock(message: str, lock_name: str = None, acquired: bool = None, wait_time: float = None, **kwargs):
    """
    Debug lock operations for thread safety analysis.

    Args:
        message: Lock event description
        lock_name: Name/ID of the lock
        acquired: Whether lock was successfully acquired
        wait_time: Time spent waiting for lock
        **kwargs: Additional context
    """
    parts = [f"LOCK: {message}"]
    if lock_name:
        parts.append(f"Lock: {lock_name}")
    if acquired is not None:
        parts.append(f"Acquired: {acquired}")
    if wait_time is not None:
        parts.append(f"Wait: {wait_time:.3f}s")

    debug(' | '.join(parts), component="Threading", **kwargs)
