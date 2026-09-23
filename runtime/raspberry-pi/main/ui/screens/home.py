"""Home — a device home over the full KneeSpa logo.

The full kneespa.com logo is the page's backdrop, like a desktop wallpaper: it
is drawn large and centred in the open area above the dock, at a reduced
opacity so it reads as the brand without competing with the controls. A
greeting sits in the top-left corner. The dock along the bottom holds three
launch tiles (Set up patient → Setup, Start treatment → Treatment, Watch
videos) above a slim device status bar (status pill, controller, treatment
records, last sync, calibration, last treatment), all on frosted surfaces.
Logged out, the gated tiles dim and a prominent Sign in tile leads the row;
videos stay open.

View + signal surface only. The shell routes tile taps through the same
gating as the rail and feeds the status bar from the existing screen setters.

Signals:
    login_requested          — Sign in tile
    navigate_requested(str)  — 'setup' | 'protocols'
    video_requested          — Watch videos tile
"""

from datetime import datetime
from typing import Dict, Iterable, Optional

from PyQt5.QtCore import QRect, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.presentation import device_status_tone
from ui.theme import control_icon, nav_icon
from ui.widgets.ds import DSBadge
from ui.widgets.ds._common import image_path, mark_caption, resolve, sans_font
from ui.widgets.ds.key_value_list import _DOT_TOKENS, _ValueLabel, status_tone

TILE_HEIGHT = 112
STATUS_BAR_HEIGHT = 76
LOGO_OPACITY = 0.5
_MARGIN_X, _MARGIN_Y = 32, 24
_OUTCOMES = {"completed": "Completed", "stopped": "Stopped by operator",
             "fault": "Ended with a fault"}


class _LaunchTile(QPushButton):
    """A large, flat launch target: tinted icon disc beside a title and hint."""

    def __init__(self, title: str, hint: str, icon_factory, primary: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("LaunchTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAccessibleName(title)
        self.setFixedHeight(TILE_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._primary = primary
        self._icon_factory = icon_factory

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(16)
        self._disc = QLabel(self)
        self._disc.setFixedSize(56, 56)
        self._disc.setAlignment(Qt.AlignCenter)
        self._disc.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._disc, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addStretch(1)
        self._title = QLabel(title, self)
        self._title.setFont(sans_font(size="--text-lg", weight=600))
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text.addWidget(self._title)
        self._hint = QLabel(hint, self)
        self._hint.setWordWrap(True)
        self._hint.setFont(sans_font(size="--text-sm"))
        self._hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        text.addWidget(self._hint)
        text.addStretch(1)
        lay.addLayout(text, 1)
        self._render()

    def sizeHint(self) -> QSize:
        return QSize(240, TILE_HEIGHT)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.EnabledChange:
            self._render()

    def _render(self) -> None:
        enabled = self.isEnabled()
        if self._primary:
            bg, border = resolve("--color-primary"), resolve("--color-primary")
            title, hint = resolve("--white"), resolve("--text-on-dark-muted")
            disc_bg, icon = resolve("--on-dark-subtle"), resolve("--white")
            hover, pressed = resolve("--color-primary-hover"), resolve("--color-primary-active")
        else:
            bg, border = resolve("--surface-frost"), resolve("--border-divider")
            title = resolve("--text-strong") if enabled else resolve("--gray-600")
            hint = resolve("--text-muted")
            disc_bg = resolve("--blue-100") if enabled else resolve("--gray-200")
            icon = resolve("--color-primary") if enabled else resolve("--gray-600")
            hover, pressed = resolve("--gray-050"), resolve("--gray-200")
        if not enabled:
            bg = resolve("--gray-100")
        self._disc.setPixmap(self._icon_factory(icon, 30).pixmap(30, 30))
        self._disc.setStyleSheet(f"background: {disc_bg}; border-radius: 28px;")
        self._title.setStyleSheet(f"color: {title}; background: transparent;")
        self._hint.setStyleSheet(f"color: {hint}; background: transparent;")
        self.setStyleSheet(
            f"#LaunchTile {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: {resolve('--radius-lg')}; padding: 0;"
            # QSS min/max-height replace setFixedHeight's bounds; restate them.
            f" min-height: {TILE_HEIGHT - 2}px; max-height: {TILE_HEIGHT - 2}px; }}"
            f"#LaunchTile:hover {{ background: {hover}; }}"
            f"#LaunchTile:pressed {{ background: {pressed}; }}"
            f"#LaunchTile:disabled {{ background: {resolve('--gray-100')};"
            f" border-color: {resolve('--border-divider')}; }}"
            f"#LaunchTile[keyboardFocus=\"true\"]:focus {{"
            f" border: 2px solid {resolve('--ink-900')}; }}"
        )


class _StatusItem(QWidget):
    """One status-bar fact: a small caption over a strong value (optional dot).

    The value strips its own ``"<caption>: "`` prefix (and any ``strip``
    prefixes), so controllers can keep sending sentence-style updates.
    """

    def __init__(self, caption: str, value: str = "", strip: Iterable[str] = (),
                 status: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addStretch(1)
        title = QLabel(caption, self)
        title.setFont(sans_font(size="--text-xs", weight=600))
        title.setStyleSheet(f"color: {resolve('--text-muted')}; background: transparent;")
        mark_caption(title)
        column.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(8)
        self._dot = QFrame(self)
        self._dot.setFixedSize(10, 10)
        self._dot.setVisible(status)
        row.addWidget(self._dot, 0, Qt.AlignVCenter)
        self.value = _ValueLabel([caption] + list(strip),
                                 self._retone if status else None, self)
        self.value.setTextFormat(Qt.PlainText)
        self.value.setFont(sans_font(size="--text-base", weight=600))
        self.value.setStyleSheet(f"color: {resolve('--text-strong')}; background: transparent;")
        row.addWidget(self.value, 1)
        column.addLayout(row)
        column.addStretch(1)
        self.value.setText(value)

    def _retone(self, text: str) -> None:
        color = resolve(_DOT_TOKENS[status_tone(text)])
        self._dot.setStyleSheet(f"background: {color}; border-radius: 5px;")

    def text(self) -> str:
        return self.value.text()


class _StatusBar(QFrame):
    """The slim device status bar: pill and detail, then the key facts."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeStatusBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(STATUS_BAR_HEIGHT)
        self.setAccessibleName("Device status")
        self.setStyleSheet(
            f"#HomeStatusBar {{ background: {resolve('--surface-frost')};"
            f" border: 1px solid {resolve('--border-divider')};"
            f" border-radius: {resolve('--radius-lg')}; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 8, 24, 8)
        row.setSpacing(28)
        lead = QVBoxLayout()
        lead.setSpacing(2)
        lead.addStretch(1)
        heading = QLabel("Device status", self)
        heading.setFont(sans_font(size="--text-xs", weight=600))
        heading.setStyleSheet(f"color: {resolve('--text-muted')}; background: transparent;")
        mark_caption(heading)
        lead.addWidget(heading)
        pill_row = QHBoxLayout()
        pill_row.setSpacing(12)
        self.pill = DSBadge("Connecting", tone="neutral", dot=True, size="md")
        pill_row.addWidget(self.pill)
        self.detail = QLabel("Waiting for device readiness.", self)
        self.detail.setFont(sans_font(size="--text-sm"))
        self.detail.setStyleSheet(f"color: {resolve('--text-body')}; background: transparent;")
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pill_row.addWidget(self.detail, 1)
        lead.addLayout(pill_row)
        lead.addStretch(1)
        row.addLayout(lead, 1)
        self.items: Dict[str, _StatusItem] = {}
        for key, caption, value, strip, status in (
            ("controller", "Controller", "Not checked", ("Arduino",), True),
            ("calibration", "Calibration", "Required", (), True),
            ("records", "Treatment records", "Not checked", (), True),
            ("last_sync", "Last sync", "Not recorded yet", ("Last successful sync",), False),
            ("last_treatment", "Last treatment", "None this session", (), False),
        ):
            item = _StatusItem(caption, value, strip, status, self)
            self.items[key] = item
            row.addWidget(item)
        self.items["calibration"].hide()


class HomeScreen(QWidget):
    login_requested = pyqtSignal()
    navigate_requested = pyqtSignal(str)
    video_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("HomeScreen")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#HomeScreen {{ background: {resolve('--surface-page')}; }}")
        self._logged_in = False
        self._username = ""
        self._logo = QPixmap(image_path("logos", "kneespa-logo-full.png"))
        self._logo_scaled = QPixmap()

        root = QVBoxLayout(self)
        root.setContentsMargins(_MARGIN_X, _MARGIN_Y, _MARGIN_X, _MARGIN_Y)
        root.setSpacing(12)

        # The top bar already carries the wordmark; the page title greets.
        self._titles = QWidget()
        titles = QVBoxLayout(self._titles)
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(2)
        self._title = QLabel()
        self._title.setTextFormat(Qt.PlainText)
        self._title.setFont(sans_font(size="--text-xl", weight=600, tracking=-0.01))
        self._title.setStyleSheet(f"color: {resolve('--text-strong')}; background: transparent;")
        titles.addWidget(self._title)
        self._greeting = QLabel()
        self._greeting.setFont(sans_font(size="--text-base"))
        self._greeting.setStyleSheet(f"color: {resolve('--text-muted')}; background: transparent;")
        titles.addWidget(self._greeting)
        root.addWidget(self._titles)
        root.addStretch(1)  # the logo shows through here

        self._dock = QWidget()
        dock = QVBoxLayout(self._dock)
        dock.setContentsMargins(0, 0, 0, 0)
        dock.setSpacing(12)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._sign_in_tile = _LaunchTile(
            "Sign in", "Staff PIN or QR code.",
            lambda color, size: control_icon("lock", color, size), primary=True)
        self._sign_in_tile.clicked.connect(self.login_requested)
        self._setup_tile = _LaunchTile(
            "Set up patient", "Position the actuators and save defaults.",
            lambda color, size: nav_icon("setup", color, size))
        self._setup_tile.clicked.connect(lambda: self.navigate_requested.emit("setup"))
        self._treatment_tile = _LaunchTile(
            "Start treatment", "Choose a protocol and start.",
            lambda color, size: nav_icon("protocols", color, size))
        self._treatment_tile.clicked.connect(lambda: self.navigate_requested.emit("protocols"))
        self._video_tile = _LaunchTile(
            "Watch videos", "Patient education and demos.",
            lambda color, size: nav_icon("play", color, size))
        self._video_tile.clicked.connect(self.video_requested)
        for tile in (self._sign_in_tile, self._setup_tile, self._treatment_tile,
                     self._video_tile):
            tiles.addWidget(tile, 1)
        dock.addLayout(tiles)
        self._status = _StatusBar()
        dock.addWidget(self._status)
        root.addWidget(self._dock)

        self.set_logged_in(False)

    # ----- logo backdrop -----
    def _logo_rect(self) -> QRect:
        """The largest centred logo rectangle between the greeting and the dock."""
        top = self._titles.geometry().bottom() + 12
        bottom = self._dock.geometry().top() - 16
        area = QRect(_MARGIN_X, top, self.width() - 2 * _MARGIN_X, max(1, bottom - top))
        size = self._logo.size().scaled(area.size(), Qt.KeepAspectRatio)
        rect = QRect(0, 0, size.width(), size.height())
        rect.moveCenter(area.center())
        return rect

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # the page colour from the stylesheet
        if self._logo.isNull():
            return
        rect = self._logo_rect()
        if rect.width() < 2 or rect.height() < 2:
            return
        if self._logo_scaled.size() != rect.size():
            self._logo_scaled = self._logo.scaled(
                rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(self)
        painter.setOpacity(LOGO_OPACITY)
        painter.drawPixmap(rect.topLeft(), self._logo_scaled)
        painter.end()

    # ----- session -----
    def set_logged_in(self, logged_in: bool, username: str = "") -> None:
        """Dim gated tiles and lead with Sign in when there is no clinician session."""
        self._logged_in = logged_in
        self._username = username if logged_in else ""
        self._sign_in_tile.setVisible(not logged_in)
        for tile in (self._setup_tile, self._treatment_tile):
            tile.setEnabled(logged_in)
        today = datetime.now().strftime("%A %d %B")
        if logged_in:
            name = f", {self._username}" if self._username else ""
            self._title.setText(f"Welcome{name}")
            self._greeting.setText(f"{today} · Choose where to start.")
        else:
            self._title.setText("Welcome to KneeSpa DRx")
            self._greeting.setText(f"{today} · Sign in to set up and run treatments.")

    # ----- status bar (fed by the shell) -----
    def status_value(self, key: str) -> str:
        """The shown value for a status-bar item (tests and diagnostics)."""
        return self._status.items[key].text()

    def set_device_status(self, label: str, detail: str) -> None:
        self._status.pill.set_text(label)
        self._status.pill.set_tone(device_status_tone(label))
        self._status.detail.setText(detail)
        self._status.detail.setToolTip(detail)
        offline = label == "Controller offline"
        self._status.items["controller"].value.setText("Offline" if offline else "Connected")
        self._status.items["calibration"].setVisible(label == "Calibration required")

    def set_cloud_status(self, message: str) -> None:
        self._status.items["records"].value.setText(message)

    def set_details(self, details: Dict[str, str]) -> None:
        if "sync_time" in details:
            self._status.items["last_sync"].value.setText(details["sync_time"])
        if "controller" in details:
            self._status.items["controller"].value.setText(details["controller"])

    def set_last_treatment(self, outcome: str, duration_seconds: int) -> None:
        seconds = max(0, int(duration_seconds))
        stamp = datetime.now().strftime("%H:%M")
        text = (f"{_OUTCOMES.get(outcome, 'Ended')} · "
                f"{seconds // 60}:{seconds % 60:02d} active · {stamp}")
        self._status.items["last_treatment"].value.setText(text)
