"""Presentation for Qt's standard dialogs, including static convenience calls.

``QMessageBox.question(...)`` and friends stay in use (tests and controllers
rely on them), so this app-level filter restyles them as they appear: no
window-manager frame, the DSDialog title strip toned by severity, the app's
spacing and a drawn severity badge. DSDialogs style themselves and are skipped.
"""

from typing import Dict

from PyQt5.QtCore import QEvent, QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QDialog, QInputDialog, QLabel, QMessageBox, QProgressDialog,
)

from .qss import resolve

STRIP_HEIGHT = 56
_STRIP_NAME = "DSDialogTitleStrip"
_STANDARD = (QMessageBox, QInputDialog, QProgressDialog)
_TONE = {
    QMessageBox.Critical: "--banner-fault",
    QMessageBox.Warning: "--banner-warning",
}
_SEVERITIES = (QMessageBox.Warning, QMessageBox.Critical, QMessageBox.Question,
               QMessageBox.Information)


class DialogTheme(QObject):
    """Keep native Qt dialog behaviour while using the app's frame, spacing and icons."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._icons: Dict[int, QPixmap] = {}

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        etype = event.type()
        if etype not in (QEvent.Polish, QEvent.Show, QEvent.LayoutRequest, QEvent.Resize,
                         QEvent.WindowTitleChange):
            return False
        if not isinstance(watched, QDialog) or watched.property("dsDialog"):
            return False
        if etype != QEvent.Polish and not watched.testAttribute(Qt.WA_WState_Polished):
            # Title and size events also fire mid-construction, before the
            # message box has an icon; wait until it is being shown.
            return False
        standard = isinstance(watched, _STANDARD)
        if standard and etype == QEvent.Polish:
            self._make_frameless(watched)
        if etype in (QEvent.Polish, QEvent.Show, QEvent.LayoutRequest):
            layout = watched.layout()
            if layout is not None:
                margins = layout.contentsMargins()
                values = (margins.left(), margins.top(), margins.right(), margins.bottom())
                # Standard dialogs leave room for the title strip; other plain
                # dialogs get the app spacing unless they chose their own.
                top = 24 + (STRIP_HEIGHT if standard and watched.windowTitle() else 0)
                wanted = (24, top, 24, 24)
                if (standard or max(values) <= 11) and values != wanted:
                    layout.setContentsMargins(*wanted)
                    layout.setSpacing(max(16, layout.spacing()))
        if standard:
            self._update_strip(watched)
        if isinstance(watched, QMessageBox) and watched.icon() in _SEVERITIES:
            label = watched.findChild(QLabel, "qt_msgboxex_icon_label")
            if label is not None:
                pixmap = self._icon(watched.icon())
                current = label.pixmap()
                if current is None or current.cacheKey() != pixmap.cacheKey():
                    # Updating the label preserves QMessageBox.icon(), including safety
                    # alerts that are upgraded from Warning to Critical while visible.
                    label.setPixmap(pixmap)
        return False

    @staticmethod
    def _make_frameless(dialog: QDialog) -> None:
        """Drop the window-manager frame before the dialog is first mapped."""
        if dialog.windowFlags() & Qt.FramelessWindowHint:
            return
        flags = dialog.windowFlags() | Qt.FramelessWindowHint
        handle = dialog.windowHandle()
        if handle is None:
            dialog.setWindowFlags(flags)
        else:
            # Already created but not yet shown: update the platform window in
            # place (setWindowFlags here would recreate it mid-show).
            dialog.overrideWindowFlags(flags)
            handle.setFlags(handle.flags() | Qt.FramelessWindowHint)

    @staticmethod
    def _update_strip(dialog: QDialog) -> None:
        title = dialog.windowTitle()
        strip = dialog.findChild(QLabel, _STRIP_NAME)
        if not title:
            if strip is not None:
                strip.hide()
            return
        if strip is None:
            strip = QLabel(dialog)
            strip.setObjectName(_STRIP_NAME)
            strip.setTextFormat(Qt.PlainText)
            strip.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        tone = "--surface-dark"
        if isinstance(dialog, QMessageBox):
            tone = _TONE.get(dialog.icon(), tone)
        style = f"background: {resolve(tone)};"
        if strip.styleSheet() != style:
            strip.setStyleSheet(style)
        if strip.text() != title:
            strip.setText(title)
        strip.setGeometry(0, 0, dialog.width(), STRIP_HEIGHT)
        strip.show()
        strip.raise_()

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
