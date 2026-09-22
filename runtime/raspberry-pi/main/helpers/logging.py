import logging
import os
import re
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, TextIO

from config.constants import (
    APP_NAME,
    LOG_CLEANUP_INTERVAL_S,
    LOG_DIR,
    LOG_LEVEL,
    LOG_MAX_FILE_BYTES,
    LOG_TOTAL_BUDGET_BYTES,
)


_RUN_LOG_NAME = re.compile(
    r"(?:python|arduino)_\d{8}-\d{6}-\d{6}_(?P<pid>[1-9]\d*)\.log"
    r"(?:\.(?P<part>[1-9]\d*))?"
)


def _diagnostic_warning(message: str) -> None:
    """Report a logging failure without reentering captured stderr or logging."""
    try:
        if sys.__stderr__ is not None:
            sys.__stderr__.write(message + "\n")
            sys.__stderr__.flush()
    except Exception:
        pass


def _process_exists(pid: int) -> bool:
    """Conservatively protect base logs whose owner may still be running."""
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # os.kill(pid, 0) terminates processes on Windows. Query a handle instead.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such PID
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # Permission denied or an unknown error: preserve the file.
    return True


class LogRetention:
    """Share a disk budget across run logs without deleting active base files."""

    def __init__(
        self, directory: str, budget_bytes: int = LOG_TOTAL_BUDGET_BYTES,
        interval_s: float = LOG_CLEANUP_INTERVAL_S,
    ) -> None:
        self.directory = os.path.abspath(directory)
        self.budget_bytes = budget_bytes
        self.interval_s = interval_s
        self._next_cleanup = 0.0
        self._lock = threading.Lock()
        self._warned = False

    def cleanup(self, force: bool = False) -> None:
        """Prune oldest closed files at startup, rollover, and periodically on writes."""
        if not self._lock.acquire(blocking=False):
            return
        try:
            now = time.monotonic()
            if not force and now < self._next_cleanup:
                return
            self._next_cleanup = now + self.interval_s
            files = []
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    match = _RUN_LOG_NAME.fullmatch(entry.name)
                    if match is None or not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        # Windows directory entries can cache stale sizes for open files.
                        # Count bytes from a fresh stat, including both active logs.
                        stat = os.stat(entry.path, follow_symlinks=False)
                    except FileNotFoundError:
                        continue  # Another process already pruned this file.
                    files.append((stat.st_mtime_ns, entry.path, stat.st_size, match))
            total = sum(item[2] for item in files)
            live_pids = {}
            for _, path, size, match in sorted(files):
                if total <= self.budget_bytes:
                    break
                if match["part"] is None:
                    pid = int(match["pid"])
                    if pid not in live_pids:
                        live_pids[pid] = _process_exists(pid)
                    if live_pids[pid]:
                        continue
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    self._warn(exc)
                    continue
                total -= size
        except Exception as exc:
            self._warn(exc)
        finally:
            self._lock.release()

    def _warn(self, error: Exception) -> None:
        """Keep cleanup failures advisory and avoid flooding diagnostics."""
        if not self._warned:
            self._warned = True
            _diagnostic_warning(f"Log cleanup failed: {error}")


class DiagnosticFileHandler(logging.FileHandler):
    """Rotate into ascending numbered segments and isolate diagnostic failures."""

    def __init__(
        self, filename: str, encoding: str = "utf-8",
        max_bytes: int = LOG_MAX_FILE_BYTES, retention: Optional[LogRetention] = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.retention = retention
        self._part = 0
        self._encoding_errors = "backslashreplace"
        # FileHandler only accepts errors= on Python 3.9 and later.
        super().__init__(filename, encoding=encoding)

    def _open(self) -> TextIO:
        """Preserve encoding error handling on older Pi Python versions and rollover."""
        return open(
            self.baseFilename, self.mode, encoding=self.encoding, errors=self._encoding_errors,
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Keep records intact; only a single oversized record can exceed the target."""
        try:
            if self._closed:
                return
            message = self.format(record) + self.terminator
            size = len(
                message.replace("\n", os.linesep).encode(self.encoding, self._encoding_errors)
            )
            current_size = self.stream.tell()
            rotated = current_size > 0 and current_size + size > self.max_bytes
            if rotated:
                self.stream.close()
                self.stream = None
                self._part += 1
                destination = f"{self.baseFilename}.{self._part}"
                # A unique run normally starts empty; never overwrite an existing segment.
                while os.path.lexists(destination):
                    self._part += 1
                    destination = f"{self.baseFilename}.{self._part}"
                os.rename(self.baseFilename, destination)
                self.stream = self._open()
            self.stream.write(message)
            self.flush()
            if self.retention is not None:
                self.retention.cleanup(force=rotated)
        except Exception:
            self.handleError(record)

    def handleError(self, record: logging.LogRecord) -> None:
        """Disable a failed file and report directly to the original stderr once."""
        self.setLevel(logging.CRITICAL + 1)
        _diagnostic_warning(f"Log file disabled after write failure: {self.baseFilename}")


def read_recent_log_lines(path: str, lines: int = 200) -> List[str]:
    """Read a bounded line tail, including preceding numbered segments if needed."""
    if lines <= 0:
        return []
    directory, filename = os.path.split(os.path.abspath(path))
    pattern = re.compile(re.escape(filename) + r"\.([1-9]\d*)")
    segments = []
    with os.scandir(directory) as entries:
        for entry in entries:
            match = pattern.fullmatch(entry.name)
            if match is not None and entry.is_file(follow_symlinks=False):
                segments.append((int(match[1]), entry.path))
    recent = []
    paths = [path] + [part for _, part in sorted(segments, reverse=True)]
    for part in paths:
        try:
            with open(part, "r", encoding="utf-8", errors="replace") as log_file:
                tail = deque(log_file, maxlen=lines - len(recent))
        except FileNotFoundError:
            continue  # A concurrent cleanup can remove a segment while we read.
        recent = list(tail) + recent
        if len(recent) >= lines:
            break
    return recent


class ConsoleCapture:
    """Keep console output visible and persist complete lines in the app log."""

    def __init__(self, stream: Any, logger: logging.Logger, level: int) -> None:
        self.stream = stream
        self.logger = logger
        self.level = level
        self._pending = ""
        self._lock = threading.RLock()

    def write(self, text: str) -> int:
        """Tee text without routing the log record back through the console."""
        with self._lock:
            self.stream.write(text)
            self._pending += text
            while "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                if line:
                    self.logger.log(self.level, line, extra={"console_output": True})
        return len(text)

    def flush(self) -> None:
        """Persist a final partial line and flush the original console."""
        with self._lock:
            if self._pending:
                self.logger.log(self.level, self._pending, extra={"console_output": True})
                self._pending = ""
            self.stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)


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

        self.log_dir = LOG_DIR
        self.run_id = f"{datetime.now():%Y%m%d-%H%M%S-%f}_{os.getpid()}"
        self.main_log_file = os.path.join(self.log_dir, f"python_{self.run_id}.log")
        self.serial_log_file = os.path.join(self.log_dir, f"arduino_{self.run_id}.log")
        self._console_capture = None

        # Create log directory if it doesn't exist
        os.makedirs(self.log_dir, exist_ok=True)
        self.retention = LogRetention(self.log_dir)
        self.retention.cleanup(force=True)

        # Initialize logger
        self.logger = logging.getLogger(APP_NAME)
        self.logger.setLevel(getattr(logging, LOG_LEVEL))
        self.serial_logger = logging.getLogger(f"{APP_NAME}.serial")
        self.serial_logger.setLevel(logging.INFO)
        self.serial_logger.propagate = False

        # Add Qt warning filter
        qt_logger = logging.getLogger('PyQt5')
        qt_logger.addFilter(self.QtWarningFilter())

        # Set up handlers only if they have not been set up already.
        # Checked via .handlers (this logger's own), NOT hasHandlers():
        # hasHandlers() walks up to the root logger, so a stray
        # logging.basicConfig() anywhere would return True and silently
        # skip the file handlers.
        if not self.logger.handlers:
            self.setup_handlers()

        # Mark as initialized to prevent redundant initializations
        self._initialized = True

        # Log initialization
        self.logger.info("Application log: %s", self.main_log_file)
        self.logger.info("Arduino serial log: %s", self.serial_log_file)
        self.serial_logger.info("Serial monitor started; waiting for Arduino traffic")

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
        main_handler = DiagnosticFileHandler(self.main_log_file, retention=self.retention)
        main_handler.setFormatter(verbose_formatter)
        main_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(main_handler)

        # A separate transcript uses the existing serial connection's TX/RX hooks.
        serial_handler = DiagnosticFileHandler(self.serial_log_file, retention=self.retention)
        serial_handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s"))
        self.serial_logger.addHandler(serial_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(simple_formatter)
        console_handler.setLevel(logging.INFO)
        console_handler.addFilter(lambda record: not getattr(record, "console_output", False))
        self.logger.addHandler(console_handler)

    def start_console_capture(self) -> None:
        """Capture legacy print calls and Python stderr for the application run."""
        if self._console_capture is None:
            stdout = ConsoleCapture(sys.stdout, self.logger, logging.INFO)
            stderr = ConsoleCapture(sys.stderr, self.logger, logging.ERROR)
            self._console_capture = (stdout, stderr)
            sys.stdout, sys.stderr = stdout, stderr

    def stop_console_capture(self) -> None:
        """Flush captured output and restore the console before printing log files."""
        if self._console_capture is not None:
            stdout, stderr = self._console_capture
            stdout.flush()
            stderr.flush()
            sys.stdout, sys.stderr = stdout.stream, stderr.stream
            self._console_capture = None

    def trace_serial(self, direction: str, data: str) -> None:
        """Record serial traffic without allowing diagnostics to interrupt control."""
        safe_data = str(data).replace("\r", "\\r").replace("\n", "\\n")
        try:
            self.serial_logger.info("%s %s", direction, safe_data)
        except Exception:
            # Diagnostics must not prevent a command from being sent or parsed.
            pass

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
