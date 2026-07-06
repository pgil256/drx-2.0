"""VideoModal — the demo-video player over a dim scrim.

Mirrors `VideoModal` in `bundle.jsx`: a 720px card with a dark title bar, a 16:9
stage (radial-gradient backdrop, faint knee watermark, big play button) and a
transport bar (play/pause, elapsed/total time, progress track).

The stage embeds a VLC media player (``_VlcEngine``) that renders into a native
surface widget. VLC and the bundled clip are both optional — if either is
missing the modal degrades to the static frame (the play button still toggles
its icon and emits ``play_toggled`` so the UI stays consistent), so it can never
block the app on a machine without VLC.

Signals:
    play_toggled(bool)  — play button pressed (True = now playing)
    closed              — dismissed
"""

import os
import sys

from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config.constants import UI_PATHS
from ui.theme import GLYPH, pause_icon, play_icon
from ui.widgets.ds._common import drop_shadow, image_path, mono_font, resolve, sans_font

from ._overlay import Overlay

try:  # VLC is optional — absent on dev boxes / headless CI (mocked in tests).
    import vlc
except Exception:  # pragma: no cover - exercised only where vlc is missing
    vlc = None

_FALLBACK_DURATION = 150  # seconds; used for the static clock when VLC is absent


def _fmt(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class _VlcEngine:
    """Thin VLC wrapper that renders into a host surface widget.

    Every public method is a no-op when VLC or the clip is unavailable, so the
    modal degrades gracefully instead of raising. All VLC calls are guarded —
    in tests ``vlc`` is a MagicMock, so ``position()`` returns ``None`` (the
    mock's getters are not real numbers) and play/pause are harmless.
    """

    def __init__(self, surface):
        self._surface = surface
        self._instance = None
        self._player = None
        self._video_path = self._first_video()
        self.available = vlc is not None and self._video_path is not None

    @staticmethod
    def _first_video():
        try:
            video = UI_PATHS.get("VIDEOS")
            if video and os.path.exists(video):
                return video
            folder = os.path.dirname(video) if video else None
            if folder and os.path.isdir(folder):
                clips = sorted(
                    f for f in os.listdir(folder) if f.lower().endswith(".mp4")
                )
                if clips:
                    return os.path.join(folder, clips[0])
        except Exception:
            pass
        return None

    def _ensure_player(self):
        if self._player is not None or not self.available:
            return self._player
        try:
            self._instance = vlc.Instance(["--no-xlib", "--quiet", "--no-audio"])
            self._player = self._instance.media_player_new()
            self._embed()
            media = self._instance.media_new(self._video_path)
            self._player.set_media(media)
            media.release()
        except Exception:
            self._player = None
            self.available = False
        return self._player

    def _embed(self):
        handle = int(self._surface.winId())
        if sys.platform.startswith("linux"):
            self._player.set_xwindow(handle)
        elif sys.platform == "win32":
            self._player.set_hwnd(handle)
        elif sys.platform == "darwin":
            self._player.set_nsobject(handle)

    def play(self):
        player = self._ensure_player()
        if player is None:
            return False
        try:
            player.play()
            return True
        except Exception:
            return False

    def pause(self):
        if self._player is not None:
            try:
                self._player.pause()  # VLC pause() toggles play/pause
            except Exception:
                pass

    def stop(self):
        # Unconditional — a paused player is not "playing" but still holds media.
        if self._player is not None:
            try:
                self._player.stop()
            except Exception:
                pass

    def position(self):
        """Return ``(elapsed_s, total_s)`` floats, or ``None`` when unknown."""
        if self._player is None:
            return None
        try:
            length = self._player.get_length()
            current = self._player.get_time()
            if (isinstance(length, (int, float)) and isinstance(current, (int, float))
                    and length > 0):
                return current / 1000.0, length / 1000.0
        except Exception:
            pass
        return None

    def release(self):
        try:
            self.stop()
            if self._player is not None:
                media = self._player.get_media()
                if media:
                    media.release()
                self._player.release()
            if self._instance is not None:
                self._instance.release()
        except Exception:
            pass
        finally:
            self._player = None
            self._instance = None


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

        self._engine = _VlcEngine(self._surface)
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._on_poll)
        self.closed.connect(self._on_closed)
        # Consecutive polls where position() returned None. VLC returns None
        # for a poll or two while opening media, so we tolerate a short run;
        # a sustained run means the player died mid-playback.
        self._none_polls = 0
        self._MAX_NONE_POLLS = 3

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

        # Native surface the VLC player renders into — fills the stage, hidden
        # until playback starts so the gradient + watermark show underneath.
        self._surface = QFrame()
        self._surface.setObjectName("VideoSurface")
        self._surface.setAttribute(Qt.WA_StyledBackground, True)
        self._surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._surface.setStyleSheet("#VideoSurface { background: #000000; }")
        self._surface.setVisible(False)
        grid.addWidget(self._surface, 0, 0)

        self._watermark = QLabel()
        self._watermark.setAlignment(Qt.AlignCenter)
        self._watermark.setStyleSheet("background: transparent;")
        pix = QPixmap(image_path("logos", "knee.png"))
        if not pix.isNull():
            self._watermark.setPixmap(
                pix.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        wm_opacity = QGraphicsOpacityEffect(self._watermark)
        wm_opacity.setOpacity(0.18)
        self._watermark.setGraphicsEffect(wm_opacity)
        grid.addWidget(self._watermark, 0, 0, Qt.AlignCenter)

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
        self._watermark.raise_()
        self._big_play.raise_()
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

        self._track = QFrame()
        self._track.setObjectName("VTrack")
        self._track.setAttribute(Qt.WA_StyledBackground, True)
        self._track.setFixedHeight(8)
        self._track.setStyleSheet(
            f"#VTrack {{ background: {resolve('--gray-300')}; border-radius: 4px; }}"
        )
        tlay = QHBoxLayout(self._track)
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
        h.addWidget(self._track, 1)

        self._total = QLabel(_fmt(_FALLBACK_DURATION))
        self._total.setFont(mono_font(size="--text-xs"))
        self._total.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        h.addWidget(self._total)
        return bar

    # ----- playback -----
    def _toggle(self):
        self._playing = not self._playing
        if self._playing:
            # Only reveal the video surface / start polling if VLC actually began
            # playing; otherwise keep the static poster frame (graceful degrade).
            if self._engine.play():
                self._none_polls = 0
                self._surface.setVisible(True)
                self._watermark.setVisible(False)
                self._big_play.setVisible(False)
                self._poll.start()
        else:
            self._engine.pause()
            self._big_play.setVisible(True)
            self._poll.stop()
        self._small_play.setIcon(
            pause_icon("#ffffff", 15) if self._playing else play_icon("#ffffff", 15)
        )
        self.play_toggled.emit(self._playing)

    def _on_poll(self):
        pos = self._engine.position()
        if pos is None:
            # A sustained run of None while we believe we're playing means
            # VLC crashed or the media handle went away; recover instead of
            # polling a dead player forever.
            self._none_polls += 1
            if self._none_polls >= self._MAX_NONE_POLLS:
                self._on_playback_failed()
            return
        self._none_polls = 0
        elapsed, total = pos
        self._elapsed.setText(_fmt(elapsed))
        if total > 0:
            self._total.setText(_fmt(total))
            frac = max(0.0, min(1.0, elapsed / total))
            self._vfill.setFixedWidth(int(self._track.width() * frac))
            if elapsed >= total - 0.3:  # clip ended → return to the paused frame
                self._reset_playback()

    def _on_playback_failed(self):
        """VLC stopped producing a position mid-playback: recover to the
        static poster frame so the modal never hangs on a dead player.

        The instructional video is non-critical, so degrading to the poster
        (with the play button back) is the right surface: the operator sees
        it stopped and can retry. Logged for diagnostics.
        """
        print("VideoModal: playback position stalled; resetting to poster")
        self._reset_playback()
        self.play_toggled.emit(False)

    def _reset_playback(self):
        """Stop playback and restore the paused/static frame."""
        self._none_polls = 0
        self._poll.stop()
        self._engine.stop()
        self._playing = False
        self._surface.setVisible(False)
        self._watermark.setVisible(True)
        self._big_play.setVisible(True)
        self._small_play.setIcon(play_icon("#ffffff", 15))
        self._elapsed.setText(_fmt(0))
        self._vfill.setFixedWidth(0)

    def _on_closed(self):
        # Always stop playback + restore the static frame when dismissed —
        # including the paused→close case (where _playing is already False and
        # the poll is stopped, but VLC still holds media and the surface shows).
        self._reset_playback()

    def cleanup(self):
        """Release VLC resources (call on app shutdown)."""
        self._poll.stop()
        self._engine.release()
