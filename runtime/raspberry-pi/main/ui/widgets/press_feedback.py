# ui/widgets/press_feedback.py
"""Pressed-state feedback for QLabel-based touch controls.

Several navigation targets are QLabels with mousePressEvent handlers;
unlike buttons they give no visual response to a touch, so operators
double-tap. This installs a dimming effect on press, cleared on
release/leave, without touching layouts or stylesheets.
"""
from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QGraphicsOpacityEffect


class PressFeedbackFilter(QObject):
    """Event filter that dims a widget while it is pressed."""

    def eventFilter(self, watched, event):
        etype = event.type()
        if etype == QEvent.MouseButtonPress:
            effect = QGraphicsOpacityEffect(watched)
            effect.setOpacity(0.5)
            watched.setGraphicsEffect(effect)
        elif etype in (QEvent.MouseButtonRelease, QEvent.Leave):
            watched.setGraphicsEffect(None)
        return False  # never consume; the real handlers still run


def install_press_feedback(*widgets):
    """Attach press feedback to the given widgets; returns the filter
    (keep a reference so it is not garbage-collected)."""
    feedback = PressFeedbackFilter()
    for widget in widgets:
        if widget is not None:
            widget.installEventFilter(feedback)
    return feedback
