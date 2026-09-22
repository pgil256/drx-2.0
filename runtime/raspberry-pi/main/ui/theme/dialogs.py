"""Presentation for Qt's standard dialogs, including static convenience calls."""

from typing import Dict

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QDialog, QInputDialog, QLabel, QMessageBox

from .qss import resolve


class DialogTheme(QObject):
    """Keep native Qt dialog behaviour while using the app's spacing and icons."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._icons: Dict[int, QPixmap] = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() not in (QEvent.Polish, QEvent.Show, QEvent.LayoutRequest):
            return False
        if isinstance(watched, QDialog):
            layout = watched.layout()
            if layout is not None:
                margins = layout.contentsMargins()
                values = (margins.left(), margins.top(), margins.right(), margins.bottom())
                standard = isinstance(watched, (QMessageBox, QInputDialog))
                # Preserve deliberate layouts such as the treatment editor and keyboard.
                if (standard or max(values) <= 11) and values != (24, 24, 24, 24):
                    layout.setContentsMargins(24, 24, 24, 24)
                    layout.setSpacing(max(16, layout.spacing()))
        if isinstance(watched, QMessageBox) and watched.icon() != QMessageBox.NoIcon:
            label = watched.findChild(QLabel, "qt_msgboxex_icon_label")
            if label is not None:
                pixmap = self._icon(watched.icon())
                current = label.pixmap()
                if current is None or current.cacheKey() != pixmap.cacheKey():
                    # Updating the label preserves QMessageBox.icon(), including safety
                    # alerts that are upgraded from Warning to Critical while visible.
                    label.setPixmap(pixmap)
        return False

    def _icon(self, severity: int) -> QPixmap:
        """Draw a crisp severity badge without platform-specific stock artwork."""
        if severity not in self._icons:
            symbol, foreground, background = {
                QMessageBox.Warning: ("!", "--color-warning", "--amber-100"),
                QMessageBox.Critical: ("!", "--color-danger", "--red-100"),
                QMessageBox.Question: ("?", "--color-primary", "--blue-100"),
                QMessageBox.Information: ("i", "--color-primary", "--blue-100"),
            }[severity]
            pixmap = QPixmap(104, 104)
            pixmap.setDevicePixelRatio(2)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(resolve(background)))
            painter.drawEllipse(QRectF(1, 1, 50, 50))
            painter.setPen(QColor(resolve(foreground)))
            font = QFont(QApplication.font())
            font.setPixelSize(30)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(0, 0, 52, 52), Qt.AlignCenter, symbol)
            painter.end()
            self._icons[severity] = pixmap
        return self._icons[severity]


def install_dialog_theme(app: QApplication) -> None:
    """Install once so repeated theme application cannot stack event filters."""
    if getattr(app, "_kneespa_dialog_theme", None) is None:
        app._kneespa_dialog_theme = DialogTheme(app)
        app.installEventFilter(app._kneespa_dialog_theme)
