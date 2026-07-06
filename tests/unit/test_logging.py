# tests/unit/test_logging.py
"""Unit tests for the application logging helpers.

Covers main/helpers/logging.py:
  * setup_logger(...) factory
  * the debug_* family of helper functions
  * LoggerSetup.format_exception(...)
  * LoggerAdapter.process(...)
  * LoggerSetup.QtWarningFilter.filter(...)

These tests assert CURRENT behavior only (tests-only policy for a medical
device). Where the coordinator spec and the actual implementation disagree,
the test documents the real behavior and notes the discrepancy in a comment.
"""
import logging

import pytest

# Imported via the helpers package path (conftest puts main/ on sys.path).
# NOTE: helpers/logging.py shadows the stdlib logging module *within* the
# package, so it must be imported through the helpers namespace.
from helpers.logging import (
    LoggerAdapter,
    LoggerSetup,
    debug,
    debug_error,
    debug_safety,
    debug_state_change,
    debug_timing,
    setup_logger,
)
from config.constants import APP_NAME


# Logger name the implementation logs under (logging.getLogger(APP_NAME)).
_LOGGER_NAME = APP_NAME


@pytest.mark.unit
class TestSetupLogger:
    """Tests for the setup_logger() factory function."""

    def test_returns_logger_adapter(self):
        """setup_logger returns a LoggerAdapter wrapping the app logger.

        NOTE: the coordinator brief describes this as returning a
        logging.Logger; the implementation actually returns a
        logging.LoggerAdapter (which is NOT a Logger subclass). We assert
        the real, current behavior.
        """
        result = setup_logger()
        assert isinstance(result, LoggerAdapter)
        assert isinstance(result, logging.LoggerAdapter)

    def test_underlying_logger_is_app_logger(self):
        """The adapter wraps the named application logger."""
        adapter = setup_logger()
        assert adapter.logger is logging.getLogger(_LOGGER_NAME)

    def test_stores_component_and_user_context(self):
        """component and user args are stored in the adapter's extra dict."""
        adapter = setup_logger(component="Arduino", user="alice")
        assert adapter.extra["component"] == "Arduino"
        assert adapter.extra["user"] == "alice"

    def test_default_context_is_empty(self):
        """With no args, component and user default to empty strings."""
        adapter = setup_logger()
        assert adapter.extra["component"] == ""
        assert adapter.extra["user"] == ""

    def test_singleton_shares_underlying_logger(self):
        """LoggerSetup is a singleton, so adapters share one base logger."""
        a = setup_logger(component="A")
        b = setup_logger(component="B")
        assert a.logger is b.logger


@pytest.mark.unit
class TestHandlerGuard:
    """LoggerSetup must attach its file handlers even when the ROOT logger
    already has handlers (e.g. a stray logging.basicConfig() in a
    dependency). The old hasHandlers() guard walked up to the root and
    silently skipped the rotating file logs in that case."""

    def test_root_handler_does_not_suppress_file_handlers(self):
        app_logger = logging.getLogger(_LOGGER_NAME)
        root = logging.getLogger()

        saved_instance = LoggerSetup._instance
        saved_handlers = list(app_logger.handlers)
        stray = logging.StreamHandler()
        try:
            # Simulate a fresh process where basicConfig ran first.
            LoggerSetup._instance = None
            app_logger.handlers.clear()
            root.addHandler(stray)

            setup = LoggerSetup()

            assert setup.logger.handlers, (
                "own-logger handlers were skipped because the root logger "
                "had a handler"
            )
        finally:
            root.removeHandler(stray)
            for handler in list(app_logger.handlers):
                if handler not in saved_handlers:
                    app_logger.removeHandler(handler)
                    handler.close()
            app_logger.handlers[:] = saved_handlers
            LoggerSetup._instance = saved_instance


@pytest.mark.unit
class TestDebugHelpers:
    """Tests for the debug_* family of helper functions.

    Each helper must run without crashing and emit a log record on the
    application logger. caplog captures records; the component name (when
    given) is prepended to the message by LoggerAdapter.process.
    """

    def test_debug_runs_and_emits(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug("plain message")
        messages = [r.getMessage() for r in caplog.records]
        assert any("plain message" in m for m in messages)

    def test_debug_respects_component(self, caplog):
        """The component arg is reflected in the emitted record."""
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug("hello", component="Arduino")
        messages = [r.getMessage() for r in caplog.records]
        assert any("[Arduino]" in m and "hello" in m for m in messages)

    def test_debug_with_values_kwarg(self, caplog):
        """A values=dict kwarg is flattened into the message context."""
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug("readings", component="Sensors", values={"pressure": 50})
        messages = [r.getMessage() for r in caplog.records]
        assert any("pressure=50" in m for m in messages)

    def test_debug_level_info(self, caplog):
        """An explicit level is honored (record emitted at INFO)."""
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug("info msg", level="INFO")
        assert any(
            r.levelno == logging.INFO and "info msg" in r.getMessage()
            for r in caplog.records
        )

    def test_debug_state_change_runs_and_emits(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_state_change("Pump", "OFF", "ON", reason="start")
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            "[Pump]" in m and "OFF -> ON" in m and "start" in m for m in messages
        )

    def test_debug_state_change_logs_at_info(self, caplog):
        """State changes are logged at INFO level."""
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_state_change("Pump", 0, 1)
        assert any(
            r.levelno == logging.INFO and "0 -> 1" in r.getMessage()
            for r in caplog.records
        )

    def test_debug_timing_with_start_time(self, caplog):
        """With a start_time, an elapsed value is reported."""
        import time

        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_timing("op done", start_time=time.time(), component="Perf")
        messages = [r.getMessage() for r in caplog.records]
        assert any("[Perf]" in m and "Elapsed" in m for m in messages)

    def test_debug_timing_without_start_time(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_timing("just a mark", component="Perf")
        messages = [r.getMessage() for r in caplog.records]
        assert any("[Perf]" in m and "just a mark" in m for m in messages)

    def test_debug_error_with_exception(self, caplog):
        """debug_error includes the exception text and logs at ERROR."""
        try:
            raise ValueError("kaboom")
        except ValueError as exc:
            with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
                debug_error("operation failed", exception=exc, component="Core")
        assert any(
            r.levelno == logging.ERROR
            and "kaboom" in r.getMessage()
            and "[Core]" in r.getMessage()
            for r in caplog.records
        )

    def test_debug_error_without_exception(self, caplog):
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_error("simple error", component="Core")
        assert any(
            r.levelno == logging.ERROR and "simple error" in r.getMessage()
            for r in caplog.records
        )

    def test_debug_safety_runs_and_emits(self, caplog):
        """Safety messages default to WARNING and carry the Safety component."""
        with caplog.at_level(logging.DEBUG, logger=_LOGGER_NAME):
            debug_safety(
                "pressure check",
                limits={"max": 80},
                current={"pressure": 50},
            )
        records = [
            r
            for r in caplog.records
            if "SAFETY" in r.getMessage() and "[Safety]" in r.getMessage()
        ]
        assert records
        assert records[0].levelno == logging.WARNING


@pytest.mark.unit
class TestFormatException:
    """Tests for LoggerSetup.format_exception()."""

    def test_returns_string_with_exception_text(self):
        try:
            raise RuntimeError("unique-error-text")
        except RuntimeError as exc:
            result = LoggerSetup.format_exception(exc)
        assert isinstance(result, str)
        assert "unique-error-text" in result

    def test_includes_traceback_header(self):
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            result = LoggerSetup.format_exception(exc)
        assert "Traceback:" in result

    def test_handles_exception_without_traceback(self):
        """An exception never raised has no __traceback__; should still work."""
        result = LoggerSetup.format_exception(ValueError("no-tb"))
        assert isinstance(result, str)
        assert "no-tb" in result


@pytest.mark.unit
class TestLoggerAdapterProcess:
    """Tests for LoggerAdapter.process()."""

    def _adapter(self, extra):
        return LoggerAdapter(logging.getLogger(_LOGGER_NAME), extra)

    def test_returns_msg_kwargs_tuple(self):
        adapter = self._adapter({})
        result = adapter.process("hello", {})
        assert isinstance(result, tuple)
        assert len(result) == 2
        msg, kwargs = result
        assert isinstance(kwargs, dict)

    def test_no_context_leaves_message_unchanged(self):
        adapter = self._adapter({"component": "", "user": ""})
        msg, _ = adapter.process("plain", {})
        assert msg == "plain"

    def test_prepends_component(self):
        adapter = self._adapter({"component": "Arduino", "user": ""})
        msg, _ = adapter.process("hello", {})
        assert msg == "[Arduino] hello"

    def test_prepends_user(self):
        adapter = self._adapter({"component": "", "user": "bob"})
        msg, _ = adapter.process("hello", {})
        assert msg == "[User: bob] hello"

    def test_component_and_user_order(self):
        """Component wraps the user-prefixed message (component is outermost)."""
        adapter = self._adapter({"component": "Arduino", "user": "bob"})
        msg, _ = adapter.process("hello", {})
        assert msg == "[Arduino] [User: bob] hello"

    def test_kwargs_passed_through_unchanged(self):
        adapter = self._adapter({})
        passed = {"exc_info": True}
        _, kwargs = adapter.process("hello", passed)
        assert kwargs is passed


@pytest.mark.unit
class TestQtWarningFilter:
    """Tests for LoggerSetup.QtWarningFilter.filter()."""

    def _record(self, message):
        return logging.LogRecord(
            name="PyQt5",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg=message,
            args=None,
            exc_info=None,
        )

    def test_blocks_qfont_setpointsize_warning(self):
        """Records starting with QFont::setPointSize are filtered out (False)."""
        f = LoggerSetup.QtWarningFilter()
        record = self._record("QFont::setPointSize: Point size <= 0")
        assert f.filter(record) is False

    def test_allows_other_messages(self):
        f = LoggerSetup.QtWarningFilter()
        record = self._record("some unrelated Qt warning")
        assert f.filter(record) is True

    def test_only_filters_prefix_not_substring(self):
        """The check is a prefix match; the token mid-string is not filtered."""
        f = LoggerSetup.QtWarningFilter()
        record = self._record("note: QFont::setPointSize appeared here")
        assert f.filter(record) is True
