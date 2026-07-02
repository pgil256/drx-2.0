# tests/integration/conftest.py
"""Qt lifecycle fixtures for the integration suite.

Two rules keep headless Qt testing stable and bounded in memory:

1. Exactly ONE ``QApplication`` for the whole process, kept alive by a strong
   module-level reference. PyQt5 does not keep the application alive for you:
   with only fixture-local references the C++ object is garbage-collected
   between tests, silently dropping registered application fonts (the app
   *stylesheet* survives destruction — Qt stores it in a static — so a
   recreated app looks themed while its Plex fonts are gone). Recreating
   QApplication mid-process is also a classic PyQt5 segfault source.

2. No widget outlives its test. The earlier module-scoped ``app`` fixtures let
   every test's top-level widgets (full ``AppShell`` trees per test)
   accumulate for a whole module, which compounds into OOM/SIGKILL on the
   memory-capped CI runner. The autouse janitor below closes and deletes all
   top-level widgets after each test and drains the deferred-delete queue.
"""
import pytest

_QAPP_REF = None   # strong session-long reference (see rule 1)
_THEMED = False    # apply_theme() ran on this process's QApplication


def _cleanup_top_level_widgets():
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication

    application = QApplication.instance()
    if application is None:
        return
    for widget in QApplication.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass  # underlying C++ object already gone
    # Deliver the DeferredDelete events posted above.
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    application.processEvents()


@pytest.fixture(autouse=True)
def qt_widget_janitor():
    """Delete all top-level widgets after every integration test.

    Runs after qtbot's own teardown (autouse fixtures finalize last), so it
    only sweeps up widgets no other fixture manages.
    """
    yield
    _cleanup_top_level_widgets()


@pytest.fixture
def qt_app(qt_widget_janitor):
    """Function-scoped handle to the process-wide ``QApplication``.

    Function-scoped so every consumer is tied to the janitor's per-test widget
    cleanup; the application object itself is created once and pinned for the
    session.
    """
    global _QAPP_REF
    from PyQt5.QtWidgets import QApplication

    _QAPP_REF = QApplication.instance() or QApplication([])
    return _QAPP_REF


@pytest.fixture
def themed_app(qt_app):
    """``qt_app`` with the KneeSpa theme (fonts + stylesheet) applied once."""
    global _THEMED
    if not _THEMED:
        from ui.theme import apply_theme

        apply_theme(qt_app)
        _THEMED = True
    return qt_app
