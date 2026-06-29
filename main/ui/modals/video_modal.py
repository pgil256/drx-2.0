"""VideoModal — demo-video frame over a dim scrim.

Mirrors `VideoModal` in `bundle.jsx`: a 720px card with a dark title bar, a 16:9
stage (radial-gradient backdrop, faint knee watermark, big play button) and a
transport bar (play/pause, elapsed/total time, progress track). Phase 4 drops
the existing VLC ``VideoPlayer`` into the stage; here it is the static frame.

Signals:
    play_toggled(bool)  — play button pressed (True = now playing)
    closed              — dismissed
"""

from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH, pause_icon, play_icon
from ui.widgets.ds._common import drop_shadow, image_path, mono_font, resolve, sans_font

from ._overlay import Overlay

_DURATION = 150  # seconds (demo clock)


def _fmt(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


class VideoModal(Overlay):
    play_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, scrim="rgba(15,20,28,0.60)")
        self._playing = False

        card = QFrame()
        card.setObjectName("VideoCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(720)
        card.setStyleSheet(
            f"#VideoCard {{ background: #ffffff; border-radius: {resolve('--radius-lg')}; }}"
        )
        drop_shadow(card, blur=48, dy=8, alpha=51)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._title_bar())
        lay.addWidget(self._stage())
        lay.addWidget(self._transport())

        self.set_card(card)

    def _title_bar(self):
        bar = QFrame()
        bar.setObjectName("VideoHeader")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"#VideoHeader {{ background: {resolve('--surface-dark')};"
            f" border-top-left-radius: {resolve('--radius-lg')};"
            f" border-top-right-radius: {resolve('--radius-lg')}; }}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 12, 18, 12)
        title = QLabel("Demo Video — Getting Started")
        title.setFont(sans_font(size="--text-base", weight=600))
        title.setStyleSheet("color: #ffffff; background: transparent;")
        close = QPushButton(GLYPH["close"])
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(32, 32)
        close.setFont(sans_font(size="--text-base", weight=600))
        close.setStyleSheet(
            "QPushButton { border: none; border-radius: 16px; color: #ffffff;"
            " background: rgba(255,255,255,0.15); }"
            " QPushButton:hover { background: rgba(255,255,255,0.28); }"
        )
        close.clicked.connect(self.close_overlay)
        h.addWidget(title)
        h.addStretch(1)
        h.addWidget(close)
        return bar

    def _stage(self):
        stage = QFrame()
        stage.setObjectName("VideoStage")
        stage.setAttribute(Qt.WA_StyledBackground, True)
        stage.setFixedHeight(int(720 * 9 / 16))  # 16:9
        stage.setStyleSheet(
            "#VideoStage { background: qradialgradient(cx:0.5, cy:0.42, radius:0.75,"
            " fx:0.5, fy:0.42, stop:0 #1b2838, stop:1 #0d141d); }"
        )
        grid = QGridLayout(stage)
        grid.setContentsMargins(0, 0, 0, 0)

        watermark = QLabel()
        watermark.setAlignment(Qt.AlignCenter)
        watermark.setStyleSheet("background: transparent;")
        pix = QPixmap(image_path("logos", "knee.png"))
        if not pix.isNull():
            watermark.setPixmap(
                pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        wm_opacity = QGraphicsOpacityEffect(watermark)
        wm_opacity.setOpacity(0.18)
        watermark.setGraphicsEffect(wm_opacity)
        grid.addWidget(watermark, 0, 0, Qt.AlignCenter)

        self._big_play = QPushButton()
        self._big_play.setCursor(Qt.PointingHandCursor)
        self._big_play.setFixedSize(84, 84)
        self._big_play.setIconSize(QSize(34, 34))
        self._big_play.setIcon(play_icon(resolve("--ink-900"), 34))
        self._big_play.setStyleSheet(
            "QPushButton { border: none; border-radius: 42px;"
            " background: rgba(255,255,255,0.92); }"
            " QPushButton:hover { background: #ffffff; }"
        )
        self._big_play.clicked.connect(self._toggle)
        grid.addWidget(self._big_play, 0, 0, Qt.AlignCenter)  # stacks above watermark
        return stage

    def _transport(self):
        bar = QFrame()
        bar.setObjectName("VideoTransport")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"#VideoTransport {{ background: #ffffff;"
            f" border-bottom-left-radius: {resolve('--radius-lg')};"
            f" border-bottom-right-radius: {resolve('--radius-lg')}; }}"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 14, 18, 14)
        h.setSpacing(14)

        self._small_play = QPushButton()
        self._small_play.setCursor(Qt.PointingHandCursor)
        self._small_play.setFixedSize(40, 40)
        self._small_play.setIconSize(QSize(15, 15))
        self._small_play.setIcon(play_icon("#ffffff", 15))
        self._small_play.setStyleSheet(
            "QPushButton { border: none; border-radius: 8px;"
            f" background: {resolve('--color-primary')}; }}"
            f" QPushButton:hover {{ background: {resolve('--color-primary-hover')}; }}"
        )
        self._small_play.clicked.connect(self._toggle)
        h.addWidget(self._small_play)

        self._elapsed = QLabel(_fmt(0))
        self._elapsed.setFont(mono_font(size="--text-xs"))
        self._elapsed.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        h.addWidget(self._elapsed)

        track = QFrame()
        track.setObjectName("VTrack")
        track.setAttribute(Qt.WA_StyledBackground, True)
        track.setFixedHeight(8)
        track.setStyleSheet(
            f"#VTrack {{ background: {resolve('--gray-300')}; border-radius: 4px; }}"
        )
        tlay = QHBoxLayout(track)
        tlay.setContentsMargins(0, 0, 0, 0)
        self._vfill = QFrame()
        self._vfill.setObjectName("VFill")
        self._vfill.setAttribute(Qt.WA_StyledBackground, True)
        self._vfill.setFixedWidth(0)
        self._vfill.setStyleSheet(
            "#VFill { border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {resolve('--blue-500')}, stop:1 {resolve('--blue-600')}); }}"
        )
        tlay.addWidget(self._vfill)
        tlay.addStretch(1)
        h.addWidget(track, 1)

        total = QLabel(_fmt(_DURATION))
        total.setFont(mono_font(size="--text-xs"))
        total.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        h.addWidget(total)
        return bar

    def _toggle(self):
        self._playing = not self._playing
        icon_dark = play_icon(resolve("--ink-900"), 34) if not self._playing \
            else pause_icon(resolve("--ink-900"), 34)
        icon_white = play_icon("#ffffff", 15) if not self._playing \
            else pause_icon("#ffffff", 15)
        self._big_play.setIcon(icon_dark)
        self._small_play.setIcon(icon_white)
        self.play_toggled.emit(self._playing)
