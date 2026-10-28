"""Keyboard-only focus rings for the touch kiosk.

Qt gives a tapped button focus, so a plain ``:focus`` rule leaves a ring lit
on whatever the operator touched last. This app-level filter marks a widget's
``keyboardFocus`` property only when focus arrived by Tab, Backtab or a
shortcut; stylesheets draw rings with ``[keyboardFocus="true"]:focus``.
"""

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtWidgets import QApplication, QWidget

_KEYBOARD_REASONS = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)


def _mark(widget: QWidget, keyboard: bool) -> None:
    if bool(widget.property("keyboardFocus")) == keyboard:
        return
    widget.setProperty("keyboardFocus", keyboard)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class KeyboardFocusFilter(QObject):
    """Tag focus changes with how they happened so QSS can ignore touch focus."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype in (QEvent.FocusIn, QEvent.FocusOut) and isinstance(watched, QWidget):
            _mark(watched, etype == QEvent.FocusIn and event.reason() in _KEYBOARD_REASONS)
        return False


def install_keyboard_focus(app: QApplication) -> None:
    """Install once so repeated theme application cannot stack event filters."""
    if getattr(app, "_kneespa_keyboard_focus", None) is None:
        app._kneespa_keyboard_focus = KeyboardFocusFilter(app)
        app.installEventFilter(app._kneespa_keyboard_focus)
