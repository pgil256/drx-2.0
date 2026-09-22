"""DSDialog — one dialog frame for every popup on the kiosk.

A title strip (title + optional close), a body (``body_layout``) and a footer
action row (``add_action``) on a 12px-radius card. The card stays a real
``QDialog`` so ``exec_()``, ``open()``, ``accept()`` / ``reject()``, modality
and the QObject parent tree behave exactly as before; it is frameless, so the
window manager never adds its own title bar.

The in-shell look comes from a companion backdrop that lives *inside* the host
window (the main window, or the shell in tests): a live, translucent scrim
over the app plus the card's soft shadow. Child-widget translucency needs no
compositor, so the scrim renders on the Pi's bare X server; the card's
rounded corners use a window mask for the same reason.

Non-modal alerts (``scrim=False``) get the shadow only and never block the
app, so STOP stays reachable while they are open. A tap on the scrim does
nothing unless the dialog opts in with ``dismiss_on_scrim`` (then it rejects).

Tones colour the title strip: ``default`` (slate), ``danger`` (red),
``warning`` (amber), ``info`` (blue).
"""

from typing import Optional

from PyQt5.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QRegion
from PyQt5.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ui.theme import control_icon

from ._common import px, resolve, sans_font

STRIP_HEIGHT = 60
HOST_MARGIN = 20
_TONES = {
    "default": "--surface-dark",
    "danger": "--banner-fault",
    "warning": "--banner-warning",
    "info": "--color-primary",
}


def _rgba(token: str) -> QColor:
    """Parse a colour token that may be ``#rrggbb`` or ``rgba(r, g, b, a)``."""
    value = resolve(token).strip()
    if value.startswith("rgba("):
        r, g, b, a = (part.strip() for part in value[5:-1].split(","))
        color = QColor(int(r), int(g), int(b))
        color.setAlphaF(float(a))
        return color
    return QColor(value)


class _Backdrop(QWidget):
    """Scrim + card shadow painted inside the host window."""

    def __init__(self, host: QWidget, dim: bool, on_tap=None) -> None:
        super().__init__(host)
        self.setObjectName("DSDialogBackdrop")
        self._dim = dim
        self._on_tap = on_tap
        self._card = QRect()
        self._radius = px("--radius-lg")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not dim)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.hide()

    def track(self, card_global: QRect) -> None:
        host = self.parentWidget()
        top_left = host.mapFromGlobal(card_global.topLeft())
        self._card = QRect(top_left, card_global.size())
        if self._dim:
            self.setGeometry(host.rect())
        else:
            self.setGeometry(self._card.adjusted(-24, -16, 24, 32))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._dim:
            painter.fillRect(self.rect(), _rgba("--overlay-scrim"))
        card = QRectF(self._card.translated(-self.pos())) if not self._dim else QRectF(self._card)
        # A cheap blur: stacked, expanding rounded rects under the card.
        painter.setPen(Qt.NoPen)
        for step in range(12, 0, -1):
            shade = QColor(0, 0, 0, 5 if self._dim else 7)
            painter.setBrush(shade)
            grow = step * 1.5
            painter.drawRoundedRect(card.adjusted(-grow, -grow + 6, grow, grow + 6),
                                    self._radius + grow, self._radius + grow)
        painter.end()

    # A dimmed backdrop swallows taps; only dialogs that opt in are dismissed.
    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()
        if self._on_tap is not None and not self._card.contains(event.pos()):
            self._on_tap()


class DSDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, title: str = "",
                 tone: str = "default", closable: bool = True, scrim: bool = True,
                 width: Optional[int] = None, dismiss_on_scrim: bool = False) -> None:
        super().__init__(parent)
        self.setProperty("dsDialog", True)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setObjectName("DSDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._scrim = scrim
        self._dismiss_on_scrim = dismiss_on_scrim
        self._backdrop: Optional[_Backdrop] = None
        self._host: Optional[QWidget] = None
        self._radius = px("--radius-lg")
        self._tone = "default"
        # Style before any child exists: with a styled parent, Qt does not
        # repolish children of an unpolished widget when its sheet changes.
        self._apply_style(tone)
        if width:
            self.setFixedWidth(width)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._strip = QFrame(self)
        self._strip.setObjectName("DSDialogStrip")
        self._strip.setAttribute(Qt.WA_StyledBackground, True)
        self._strip.setFixedHeight(STRIP_HEIGHT)
        strip = QHBoxLayout(self._strip)
        strip.setContentsMargins(24, 0, 8, 0)
        strip.setSpacing(12)
        self._title = QLabel(title, self._strip)
        self._title.setTextFormat(Qt.PlainText)
        self._title.setFont(sans_font(size="--text-md", weight=600))
        strip.addWidget(self._title, 1)
        self.close_button = QPushButton(self._strip)
        self.close_button.setObjectName("DSDialogClose")
        self.close_button.setAccessibleName("Close")
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.TabFocus)
        self.close_button.setAutoDefault(False)
        self.close_button.setFixedSize(48, 48)
        self.close_button.setIcon(control_icon("close", resolve("--white"), 22))
        self.close_button.setIconSize(QSize(22, 22))
        self.close_button.clicked.connect(self.reject)
        self.close_button.setVisible(closable)
        strip.addWidget(self.close_button)
        outer.addWidget(self._strip)

        self.body = QWidget(self)
        self.body.setObjectName("DSDialogBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(24, 20, 24, 20)
        self.body_layout.setSpacing(16)
        outer.addWidget(self.body, 1)

        self.footer = QFrame(self)
        self.footer.setObjectName("DSDialogFooter")
        self.footer.setAttribute(Qt.WA_StyledBackground, True)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(24, 16, 24, 16)
        self.footer_layout.setSpacing(12)
        self.footer.hide()
        outer.addWidget(self.footer)

        self.set_title(title)

    # ----- content API -----
    def set_title(self, title: str) -> None:
        self._title.setText(title)
        self.setWindowTitle(title)
        self._strip.setVisible(bool(title) or self.close_button.isVisibleTo(self))

    def title(self) -> str:
        return self._title.text()

    def set_tone(self, tone: str) -> None:
        self._apply_style(tone)
        for widget in [self] + self.findChildren(QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()

    def _apply_style(self, tone: str) -> None:
        self._tone = tone if tone in _TONES else "default"
        strip = resolve(_TONES[self._tone])
        radius = f"{self._radius}px"
        self.setStyleSheet(
            f"#DSDialog {{ background: {resolve('--surface-card')}; }}"
            f"#DSDialogStrip {{ background: {strip}; border: none;"
            f" border-top-left-radius: {radius}; border-top-right-radius: {radius}; }}"
            f"#DSDialogStrip QLabel {{ color: {resolve('--white')}; background: transparent; }}"
            f"#DSDialogClose {{ border: none; border-radius: 12px; padding: 0; min-height: 0;"
            f" background: {resolve('--on-dark-subtle')}; }}"
            f"#DSDialogClose:hover, #DSDialogClose:pressed {{"
            f" background: {resolve('--on-dark-subtle-hover')}; }}"
            f"#DSDialogBody {{ background: transparent; }}"
            f"#DSDialogFooter {{ background: {resolve('--surface-page')};"
            f" border-top: 1px solid {resolve('--border-divider')};"
            f" border-bottom-left-radius: {radius}; border-bottom-right-radius: {radius}; }}"
        )

    def tone(self) -> str:
        return self._tone

    def set_closable(self, closable: bool) -> None:
        self.close_button.setVisible(closable)

    def add_action(self, widget: QWidget, stretch: int = 0) -> QWidget:
        """Append a footer action (primary last, per platform convention)."""
        self.footer_layout.addWidget(widget, stretch)
        self.footer.show()
        return widget

    def add_action_stretch(self, stretch: int = 1) -> None:
        self.footer_layout.addStretch(stretch)
        self.footer.show()

    # ----- hosting -----
    def _resolve_host(self) -> Optional[QWidget]:
        widget = self.parentWidget()
        while widget is not None:
            window = widget.window()
            if isinstance(window, DSDialog):
                widget = window.parentWidget()
                continue
            return window
        return None

    def host(self) -> Optional[QWidget]:
        return self._host

    def _ensure_backdrop(self) -> Optional[_Backdrop]:
        host = self._resolve_host()
        if host is not self._host:
            if self._host is not None:
                self._host.removeEventFilter(self)
            if self._backdrop is not None:
                self._backdrop.deleteLater()
                self._backdrop = None
            self._host = host
            if host is not None:
                host.installEventFilter(self)
                self._backdrop = _Backdrop(
                    host, self._scrim, self.reject if self._dismiss_on_scrim else None)
                self.destroyed.connect(self._backdrop.deleteLater)
        return self._backdrop

    def _place(self) -> None:
        """Fit inside the host with a margin and centre over it."""
        host = self._host
        if host is None:
            return
        bounds = QRect(host.mapToGlobal(QPoint(0, 0)), host.size())
        limit = bounds.adjusted(HOST_MARGIN, HOST_MARGIN, -HOST_MARGIN, -HOST_MARGIN)
        size = self.size().boundedTo(limit.size())
        if size != self.size():
            self.resize(size)
        rect = QRect(QPoint(0, 0), size)
        rect.moveCenter(bounds.center())
        self.move(rect.topLeft())
        self._sync_backdrop()

    def _sync_backdrop(self) -> None:
        if self._backdrop is None or not self.isVisible():
            return
        self._backdrop.track(QRect(self.pos(), self.size()))
        self._backdrop.show()
        self._backdrop.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._ensure_backdrop()
        self._place()

    def hideEvent(self, event) -> None:
        if self._backdrop is not None:
            self._backdrop.hide()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # A shaped window gives rounded corners without a compositor. Headless
        # platforms cannot shape windows (and would log a warning per resize).
        if QGuiApplication.platformName() not in ("offscreen", "minimal"):
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        if self.isVisible():
            self._place()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._sync_backdrop()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._host and event.type() in (QEvent.Resize, QEvent.Move):
            if self.isVisible():
                self._place()
        return super().eventFilter(watched, event)
