"""Overlay — a dim-backdrop modal base that centers a card over the app shell.

Mirrors the design's absolute-positioned modals: a translucent scrim fills the
shell, a card sits centered, and clicking the scrim (or pressing Esc) closes.
LoginModal / VideoModal supply the card via :meth:`set_card`.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QVBoxLayout, QWidget


class Overlay(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent=None, scrim="rgba(15,20,28,0.55)"):
        super().__init__(parent)
        self.setObjectName("Overlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#Overlay {{ background: {scrim}; }}")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setAlignment(Qt.AlignCenter)
        self._card = None
        self.hide()

    def set_card(self, card):
        self._card = card
        self._lay.addWidget(card, 0, Qt.AlignCenter)

    def open_over(self, parent=None):
        """Show the overlay covering its parent (or the given parent)."""
        if parent is not None and parent is not self.parent():
            self.setParent(parent)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.setFocus()

    def update_geometry(self):
        if self.parent() is not None and self.isVisible():
            self.setGeometry(self.parent().rect())

    def close_overlay(self):
        self.hide()
        self.closed.emit()

    # Clicking the scrim (a release reaching the overlay, not the card) closes.
    def mouseReleaseEvent(self, event):
        if self._card is None or not self._card.geometry().contains(event.pos()):
            self.close_overlay()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_overlay()
        else:
            super().keyPressEvent(event)
