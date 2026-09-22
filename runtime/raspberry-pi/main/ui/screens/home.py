"""Home — a device home rather than a website splash.

Brand line, three launch tiles (Set up patient → Setup, Start treatment →
Treatment, Watch videos) and a device status card (status pill, controller,
treatment records, last sync, calibration, last treatment). Logged out, the
gated tiles dim and a prominent Sign in tile leads the row; videos stay open.

View + signal surface only. The shell routes tile taps through the same
gating as the rail and feeds the status card from the existing screen setters.

Signals:
    login_requested          — Sign in tile
    navigate_requested(str)  — 'setup' | 'protocols'
    video_requested          — Watch videos tile
"""

from datetime import datetime
from typing import Dict, Optional

from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.presentation import device_status_tone
from ui.theme import control_icon, nav_icon
from ui.widgets.common import image_label
from ui.widgets.ds import DSBadge, DSCard, DSKeyValueList
from ui.widgets.ds._common import image_path, resolve, sans_font

TILE_HEIGHT = 200
_OUTCOMES = {"completed": "Completed", "stopped": "Stopped by operator",
             "fault": "Ended with a fault"}


class _LaunchTile(QPushButton):
    """A large, flat launch target: tinted icon disc, title and one-line hint."""

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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 22)
        lay.setSpacing(6)
        self._disc = QLabel(self)
        self._disc.setFixedSize(56, 56)
        self._disc.setAlignment(Qt.AlignCenter)
        self._disc.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._disc)
        lay.addStretch(1)
        self._title = QLabel(title, self)
        self._title.setFont(sans_font(size="--text-lg", weight=600))
        self._title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._title)
        self._hint = QLabel(hint, self)
        self._hint.setWordWrap(True)
        self._hint.setFont(sans_font(size="--text-sm"))
        self._hint.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self._hint)
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
            bg, border = resolve("--surface-card"), resolve("--border-divider")
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

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(24)

        brand = QHBoxLayout()
        brand.setSpacing(16)
        brand.addWidget(image_label(image_path("logos", "knee.png"), 48, 48))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        # The top bar already carries the wordmark; the page title greets.
        self._title = QLabel()
        self._title.setTextFormat(Qt.PlainText)
        self._title.setFont(sans_font(size="--text-xl", weight=600, tracking=-0.01))
        self._title.setStyleSheet(f"color: {resolve('--text-strong')};")
        titles.addWidget(self._title)
        self._greeting = QLabel()
        self._greeting.setFont(sans_font(size="--text-base"))
        self._greeting.setStyleSheet(f"color: {resolve('--text-muted')};")
        titles.addWidget(self._greeting)
        brand.addLayout(titles, 1)
        root.addLayout(brand)

        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self._sign_in_tile = _LaunchTile(
            "Sign in", "Scan with your phone or use a staff PIN.",
            lambda color, size: control_icon("lock", color, size), primary=True)
        self._sign_in_tile.clicked.connect(self.login_requested)
        self._setup_tile = _LaunchTile(
            "Set up patient", "Position the actuators and save defaults.",
            lambda color, size: nav_icon("setup", color, size))
        self._setup_tile.clicked.connect(lambda: self.navigate_requested.emit("setup"))
        self._treatment_tile = _LaunchTile(
            "Start treatment", "Choose a protocol, review settings and start.",
            lambda color, size: nav_icon("protocols", color, size))
        self._treatment_tile.clicked.connect(lambda: self.navigate_requested.emit("protocols"))
        self._video_tile = _LaunchTile(
            "Watch videos", "Patient education and device demonstrations.",
            lambda color, size: nav_icon("play", color, size))
        self._video_tile.clicked.connect(self.video_requested)
        for tile in (self._sign_in_tile, self._setup_tile, self._treatment_tile,
                     self._video_tile):
            tiles.addWidget(tile, 1)
        root.addLayout(tiles)

        self._status_pill = DSBadge("Connecting", tone="neutral", dot=True, size="md")
        card = DSCard("Device status", header_right=self._status_pill)
        body = card.body_layout
        body.setContentsMargins(24, 12, 24, 12)
        body.setSpacing(4)
        self._detail = QLabel("Waiting for device readiness.")
        self._detail.setWordWrap(True)
        self._detail.setFont(sans_font(size="--text-base"))
        body.addWidget(self._detail)
        columns = QGridLayout()
        columns.setHorizontalSpacing(40)
        self.status_rows = DSKeyValueList()
        self.status_rows.add_row("controller", "Controller", "Not checked",
                                 strip=("Arduino",), status=True)
        self.status_rows.add_row("calibration", "Calibration", "Required", status=True)
        self.status_rows.add_row("records", "Treatment records", "Not checked", status=True)
        self.status_rows.set_row_visible("calibration", False)
        columns.addWidget(self.status_rows, 0, 0)
        self.history_rows = DSKeyValueList()
        self.history_rows.add_row("last_sync", "Last sync", "Not recorded yet",
                                  strip=("Last successful sync",))
        self.history_rows.add_row("last_treatment", "Last treatment", "None this session")
        columns.addWidget(self.history_rows, 0, 1)
        columns.setColumnStretch(0, 1)
        columns.setColumnStretch(1, 1)
        body.addLayout(columns)
        root.addWidget(card)
        root.addStretch(1)

        self.set_logged_in(False)

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

    # ----- status card (fed by the shell) -----
    def set_device_status(self, label: str, detail: str) -> None:
        self._status_pill.set_text(label)
        self._status_pill.set_tone(device_status_tone(label))
        self._detail.setText(detail)
        offline = label == "Controller offline"
        self.status_rows.set_value("controller", "Offline" if offline else "Connected")
        self.status_rows.set_row_visible("calibration", label == "Calibration required")

    def set_cloud_status(self, message: str) -> None:
        self.status_rows.set_value("records", message)

    def set_details(self, details: Dict[str, str]) -> None:
        if "sync_time" in details:
            self.history_rows.set_value("last_sync", details["sync_time"])
        if "controller" in details:
            self.status_rows.set_value("controller", details["controller"])

    def set_last_treatment(self, outcome: str, duration_seconds: int) -> None:
        seconds = max(0, int(duration_seconds))
        stamp = datetime.now().strftime("%H:%M")
        text = (f"{_OUTCOMES.get(outcome, 'Ended')} · "
                f"{seconds // 60}:{seconds % 60:02d} active · {stamp}")
        self.history_rows.set_value("last_treatment", text)
