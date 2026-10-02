# development/tests/unit/test_logging.py
"""Unit tests for the application logging helpers.

Covers main/helpers/logging.py:
  * setup_logger(...) factory
  * LoggerAdapter.process(...)
  * LoggerSetup.QtWarningFilter.filter(...)

These tests assert CURRENT behavior only (tests-only policy for a medical
device). Where the coordinator spec and the actual implementation disagree,
the test documents the real behavior and notes the discrepancy in a comment.
"""
import logging
from pathlib import Path

import pytest

# Imported via the helpers package path (conftest puts main/ on sys.path).
# NOTE: helpers/logging.py shadows the stdlib logging module *within* the
# package, so it must be imported through the helpers namespace.
from helpers.logging import (
    LoggerAdapter,
    LoggerSetup,
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
    silently skipped the file logs in that case."""

    def test_root_handler_does_not_suppress_file_handlers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("helpers.logging.LOG_DIR", str(tmp_path))
        app_logger = logging.getLogger(_LOGGER_NAME)
        serial_logger = logging.getLogger(f"{_LOGGER_NAME}.serial")
        root = logging.getLogger()

        saved_instance = LoggerSetup._instance
        saved_handlers = list(app_logger.handlers)
        saved_serial_handlers = list(serial_logger.handlers)
        qt_logger = logging.getLogger("PyQt5")
        saved_filters = list(qt_logger.filters)
        stray = logging.StreamHandler()
        try:
            # Simulate a fresh process where basicConfig ran first.
            LoggerSetup._instance = None
            app_logger.handlers.clear()
            serial_logger.handlers.clear()
            root.addHandler(stray)

            setup = LoggerSetup()

            handlers = [h for h in setup.logger.handlers if isinstance(h, logging.FileHandler)]
            assert len(handlers) == 1
            setup.logger.error("test record reaches disk")
            setup.trace_serial("RX", "test serial record reaches disk")
            for handler in handlers:
                handler.flush()
            assert "test record reaches disk" in Path(setup.main_log_file).read_text()
            assert "test serial record reaches disk" in Path(setup.serial_log_file).read_text()
            assert len(list(tmp_path.glob("*.log"))) == 2
        finally:
            root.removeHandler(stray)
            for handler in list(app_logger.handlers):
                if handler not in saved_handlers:
                    app_logger.removeHandler(handler)
                    handler.close()
            app_logger.handlers[:] = saved_handlers
            for handler in list(serial_logger.handlers):
                if handler not in saved_serial_handlers:
                    serial_logger.removeHandler(handler)
                    handler.close()
            serial_logger.handlers[:] = saved_serial_handlers
            LoggerSetup._instance = saved_instance
            qt_logger.filters[:] = saved_filters


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
