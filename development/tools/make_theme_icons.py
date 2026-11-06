"""Regenerate the PNG icons that app.qss references through ``url(theme:/...)``.

Qt style sheets can only place an image (not a drawn shape) in sub-controls
such as ``QComboBox::down-arrow`` and ``QCheckBox::indicator``. The shapes are
drawn here with QPainter from the theme tokens so they stay font-independent
and match the drawn icons in ``ui/theme/icons.py``.

    QT_QPA_PLATFORM=offscreen python development/tools/make_theme_icons.py
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "runtime", "raspberry-pi", "main",
))

from PyQt5.QtCore import QPointF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPolygonF  # noqa: E402

from ui.theme import resolve  # noqa: E402
from ui.theme.qss import ICON_DIR  # noqa: E402


def _image(size):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    return image


def _pen(color, width):
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def chevron_down(color, size=20):
    """An open "v" the same weight as the nav-rail line icons."""
    image = _image(size)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(_pen(color, size * 0.11))
    painter.drawPolyline(QPolygonF([
        QPointF(size * 0.25, size * 0.38),
        QPointF(size * 0.50, size * 0.63),
        QPointF(size * 0.75, size * 0.38),
    ]))
    painter.end()
    return image


def check(color, size=16):
    """A tick for the checked QCheckBox indicator."""
    image = _image(size)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(_pen(color, size * 0.14))
    painter.drawPolyline(QPolygonF([
        QPointF(size * 0.20, size * 0.52),
        QPointF(size * 0.42, size * 0.74),
        QPointF(size * 0.80, size * 0.30),
    ]))
    painter.end()
    return image


ICONS = {
    "chevron-down.png": lambda: chevron_down(resolve("--ink-700")),
    "chevron-down-disabled.png": lambda: chevron_down(resolve("--gray-600")),
    "check.png": lambda: check(resolve("--white")),
}


def main():
    QGuiApplication(sys.argv)
    os.makedirs(ICON_DIR, exist_ok=True)
    for name, draw in ICONS.items():
        path = os.path.join(ICON_DIR, name)
        if not draw().save(path, "PNG"):
            raise SystemExit(f"could not write {path}")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
