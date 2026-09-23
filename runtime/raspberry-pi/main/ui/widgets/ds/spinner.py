"""DSSpinner — a small inline busy indicator for "Looking up…" style waits.

Replaces greying out a whole control while a request is pending: the control
stays readable, a spinner beside the status line shows work in progress. It
only animates while visible, so a hidden spinner costs nothing on the Pi.
"""

from typing import Optional

from PyQt5.QtCore import QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

from ._common import resolve


class DSSpinner(QWidget):
    def __init__(self, size: int = 20, color_token: str = "--color-primary",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor(resolve(color_token))
        self._track = QColor(resolve("--gray-300"))
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._advance)

    def _advance(self) -> None:
        self._angle = (self._angle + 30) % 360
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = max(2.0, self.width() / 8.0)
        rect = QRectF(width / 2, width / 2, self.width() - width, self.height() - width)
        pen = QPen(self._track, width)
        painter.setPen(pen)
        painter.drawEllipse(rect)
        pen.setColor(self._color)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, -self._angle * 16, 100 * 16)
        painter.end()
