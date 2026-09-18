"""Small shared view helpers for the modern KneeSpa DRx screens.

Thin, generic widgets used across chrome / screens / modals: a label that emits
``clicked`` (the design wires several plain elements as buttons), an image label,
an uppercase eyebrow caption, and a hairline divider. Anything component-shaped
lives in ``ui/widgets/ds`` instead.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QFrame, QLabel

from .ds._common import resolve, sans_font


class ClickableLabel(QLabel):
    """A QLabel that emits ``clicked`` on a left mouse release."""

    clicked = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def image_label(path, width, height, parent=None, clickable=False):
    """A (optionally clickable) label showing a smoothly scaled image."""
    lbl = ClickableLabel(parent) if clickable else QLabel(parent)
    pix = QPixmap(path)
    if not pix.isNull():
        lbl.setPixmap(pix.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    lbl.setFixedSize(width, height)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet("background: transparent;")
    return lbl


def eyebrow(text, parent=None):
    """Uppercase, letter-spaced, muted section caption (the DS T_EYEBROW)."""
    lbl = QLabel(text.upper(), parent)
    lbl.setFont(sans_font(size="--text-xs", weight=600, tracking=0.06))
    lbl.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
    return lbl


def hline(color_token="--gray-300", parent=None):
    """A 1px horizontal divider."""
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {resolve(color_token)}; border: none;")
    return line
