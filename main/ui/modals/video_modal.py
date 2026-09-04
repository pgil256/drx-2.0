"""VideoModal — the demo-video player over a dim scrim.

Mirrors `VideoModal` in `bundle.jsx`: an 800px card with a dark title bar, a 16:9
stage (radial-gradient backdrop, faint knee watermark, big play button) and a
transport bar (play/pause, elapsed/total time, progress track).

The stage embeds a VLC media player (``_VlcEngine``) that plays every ``.mp4``
in the videos directory in sorted filename order — advancing to the next clip
automatically when one ends — with prev/next transport buttons to skip between
clips. VLC and the bundled clips are both optional — if either is missing the
modal degrades to the static frame (the play button still toggles its icon and
emits ``play_toggled`` so the UI stays consistent), so it can never block the
app on a machine without VLC.

Signals:
    play_toggled(bool)  — play button pressed (True = now playing)
    closed              — dismissed
"""

import os
import shutil
import subprocess
import sys
from numbers import Real
from typing import List, Optional

from PyQt5.QtCore import QEvent, QObject, QPointF, Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
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
_DEFAULT_VOLUME = 100
_VIDEO_CARD_WIDTH = 800
_TOUCH_CONTROL_SIZE = 48


def _fmt(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _real_number(value: object) -> Optional[float]:
    """Return a VLC numeric result as a float, or ``None`` when unavailable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return float(value)
    # Some older python-vlc/ctypes combinations expose c_long values instead
    # of plain Python ints. Do not broadly call float(value): MagicMock and
    # other sentinel objects can misleadingly coerce to a number.
    raw = getattr(value, "value", None)
    if isinstance(raw, Real) and not isinstance(raw, bool):
        return float(raw)
    return None


def _audio_config_dir() -> str:
    configured = os.environ.get("KNEESPA_AUDIO_CONFIG_DIR")
    if configured:
        return os.path.expanduser(configured)
    root = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(root, "kneespa")


def _read_audio_preference(name: str) -> str:
    try:
        with open(os.path.join(_audio_config_dir(), name), "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _write_audio_preference(name: str, value: object) -> None:
    try:
        folder = _audio_config_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
        os.replace(temporary, path)
    except OSError as exc:
        print(f"VideoModal: unable to save audio preference {name}: {exc!r}")


def _discover_alsa_devices() -> List[str]:
    """Return the direct ALSA devices used by the successful Pi sound test."""
    if not sys.platform.startswith("linux") or shutil.which("aplay") is None:
        return []
    try:
        result = subprocess.run(
            ["aplay", "-L"],
            capture_output=True,
            check=False,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return list(dict.fromkeys(
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("sysdefault:")
    ))


def _friendly_audio_device(device: str) -> str:
    lowered = device.lower()
    if "headphone" in lowered:
        return "Headphones / Speakers"
    if "vc4hdmi0" in lowered:
        return "HDMI 1"
    if "vc4hdmi1" in lowered:
        return "HDMI 2"
    if "vc4hdmi" in lowered or "hdmi" in lowered:
        return "HDMI"
    card = device.split("CARD=", 1)[-1]
    return card.replace("_", " ")


def _expand_icon(color="#ffffff", size=16):
    """Four outward corner brackets — standard fullscreen icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    o = size * 0.12
    a = size * 0.32
    e = size - o
    for cx, cy, sx, sy in [(o, o, 1, 1), (e, o, -1, 1), (o, e, 1, -1), (e, e, -1, -1)]:
        p.drawLine(QPointF(cx, cy), QPointF(cx + sx * a, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * a))
    p.end()
    return QIcon(pm)


def _compress_icon(color="#ffffff", size=16):
    """Four inward corner brackets — exit fullscreen icon."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    c = size * 0.40
    a = size * 0.28
    ic = size - c
    for cx, cy, sx, sy in [(c, c, -1, -1), (ic, c, 1, -1), (c, ic, -1, 1), (ic, ic, 1, 1)]:
        p.drawLine(QPointF(cx, cy), QPointF(cx + sx * a, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * a))
    p.end()
    return QIcon(pm)


class _VlcEngine:
    """Thin VLC wrapper that renders into a host surface widget.

    Every public method is a no-op when VLC or the clip is unavailable, so the
    modal degrades gracefully instead of raising. All VLC calls are guarded —
    in tests ``vlc`` is a MagicMock, so ``position()`` returns ``None`` (the
    mock's getters are not real numbers) and play/pause are harmless.
    """

    def __init__(
        self,
        surface: QWidget,
        audio_device: str = "",
        volume: int = _DEFAULT_VOLUME,
    ) -> None:
        self._surface = surface
        self._instance = None
        self._player = None
        self._playlist = self._discover_playlist()
        self._index = 0
        self._audio_device = audio_device
        self._volume = max(0, min(100, int(volume)))
        self._muted = self._volume == 0
        self._audio_attempts = 0
        self._audio_ready = False
        self.available = vlc is not None and bool(self._playlist)

    @staticmethod
    def _discover_playlist():
        """All .mp4 paths in the videos directory, in sorted filename order.

        ``UI_PATHS["VIDEOS"]`` is the directory; a single-file path (the
        pre-playlist config shape) still works via the dirname fallback.
        """
        try:
            configured = UI_PATHS.get("VIDEOS")
            if not configured:
                return []
            folder = configured if os.path.isdir(configured) else os.path.dirname(configured)
            if os.path.isdir(folder):
                return [
                    os.path.join(folder, f)
                    for f in sorted(os.listdir(folder))
                    if f.lower().endswith(".mp4")
                ]
        except Exception:
            pass
        return []

    def count(self):
        return len(self._playlist)

    def index(self):
        return self._index

    def audio_device(self) -> str:
        return self._audio_device

    def _ensure_player(self):
        if self._player is not None or not self.available:
            return self._player
        try:
            options = ["--no-xlib", "--quiet"]
            if sys.platform.startswith("linux") and self._audio_device:
                # Match the successful direct-output diagnostic exactly:
                # bypass PipeWire/Pulse routing and address ALSA by name.
                options.extend([
                    "--aout=alsa",
                    f"--alsa-audio-device={self._audio_device}",
                ])
                print(f"VideoModal: forcing ALSA output {self._audio_device}")
            self._instance = vlc.Instance(options)
            self._player = self._instance.media_player_new()
            self._embed()
            try:
                # Don't let VLC grab mouse/keyboard input for the embedded
                # window — on X11 that grab can leave the surrounding Qt UI
                # (including the close button) unresponsive during playback.
                self._player.video_set_mouse_input(False)
                self._player.video_set_key_input(False)
            except Exception:
                pass
            self._load(self._index)
        except Exception as exc:
            print(f"VideoModal: VLC init failed, degrading to poster: {exc!r}")
            self._player = None
            self.available = False
        return self._player

    def _load(self, index):
        path = self._playlist[index]
        print(f"VideoModal: loading clip {index + 1}/{len(self._playlist)}: {path}")
        media = self._instance.media_new(path)
        self._player.set_media(media)
        media.release()
        self._audio_attempts = 0
        self._audio_ready = False

    def set_track(self, index):
        """Select playlist entry ``index`` (does not start playback).

        Returns True when the track is selected; the caller decides whether
        to ``play()``. If the player already exists the current clip is
        stopped and the new media loaded; otherwise the index simply becomes
        the one ``_ensure_player`` loads on first play.
        """
        if not self.available or not 0 <= index < len(self._playlist):
            return False
        self._index = index
        if self._player is not None:
            try:
                self._player.stop()
                self._load(index)
            except Exception:
                return False
        return True

    def ended(self):
        """True once the current clip has played to the end."""
        return self.playback_state() == "ended"

    def playback_state(self) -> str:
        """Return a stable lowercase VLC state name, or ``unknown``."""
        if self._player is None or vlc is None:
            return "unknown"
        try:
            state = self._player.get_state()
            for name in (
                "Opening",
                "Buffering",
                "Playing",
                "Paused",
                "Stopped",
                "Ended",
                "Error",
            ):
                if state == getattr(vlc.State, name, object()):
                    return name.lower()
        except Exception:
            pass
        return "unknown"

    def _embed(self):
        if os.environ.get("KNEESPA_VIDEO_NO_EMBED") == "1":
            # Diagnostic escape hatch: let VLC open its own top-level window
            # so embedding problems can be separated from playback problems.
            print("VideoModal: KNEESPA_VIDEO_NO_EMBED=1 — VLC opens its own window")
            return
        handle = int(self._surface.winId())
        print(f"VideoModal: embedding VLC into winId=0x{handle:x} ({sys.platform})")
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
            result = player.play()
            if _real_number(result) == -1:
                return False
            # LibVLC may not have an active audio stream until play() is
            # called. Apply now and retry from the poll once state=Playing.
            self.ensure_audio()
            return True
        except Exception as exc:
            print(f"VideoModal: play() failed: {exc!r}")
            return False

    def pause(self):
        if self._player is not None:
            try:
                # Explicit pause avoids libvlc_media_player_pause()'s toggle
                # semantics getting out of sync with the Qt button state.
                self._player.set_pause(1)
            except Exception:
                try:
                    self._player.pause()
                except Exception:
                    pass

    def set_audio_device(self, device: str) -> None:
        """Rebuild VLC so a new direct ALSA output is used on the next play."""
        if device == self._audio_device:
            return
        self.release()
        self._audio_device = device
        self._audio_attempts = 0
        self._audio_ready = False

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        self._audio_ready = False
        if self._player is not None:
            try:
                self._player.audio_set_volume(self._volume)
            except Exception:
                pass

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._audio_ready = False
        if self._player is not None:
            try:
                self._player.audio_set_mute(self._muted)
            except Exception:
                pass

    def ensure_audio(self) -> None:
        """Unmute and restore nominal VLC volume once audio output exists."""
        if self._player is None or self._audio_ready or self._audio_attempts >= 20:
            return
        self._audio_attempts += 1
        try:
            desired_mute = self._muted or self._volume == 0
            self._player.audio_set_mute(desired_mute)
            self._player.audio_set_volume(self._volume)
            muted = _real_number(self._player.audio_get_mute())
            volume = _real_number(self._player.audio_get_volume())
            # Mute can report -1 until the stream is active. Keep retrying in
            # that case; only a confirmed unmuted stream completes setup.
            self._audio_ready = bool(
                volume is not None
                and int(volume) == self._volume
                and muted == float(desired_mute)
            )
            if self._audio_attempts == 20 and not self._audio_ready:
                print(
                    "VideoModal: VLC audio output did not become ready "
                    f"(mute={muted!r}, volume={volume!r})"
                )
        except Exception as exc:
            if self._audio_attempts == 20:
                print(f"VideoModal: unable to enable VLC audio: {exc!r}")

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
            length = _real_number(self._player.get_length())
            current = _real_number(self._player.get_time())

            if length is None or length <= 0:
                media = self._player.get_media()
                if media is not None:
                    length = _real_number(media.get_duration())

            # Some VLC outputs advance relative position while get_time()
            # remains zero. Use whichever clock has made more progress.
            relative = _real_number(self._player.get_position())
            if length is not None and length > 0 and relative is not None:
                if 0.0 <= relative <= 1.0:
                    relative_time = relative * length
                    current = max(current or 0.0, relative_time)

            if length is not None and length > 0 and current is not None and current >= 0:
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
        self._fullscreen = False
        self._progress_fraction = 0.0
        self._audio_devices = _discover_alsa_devices()
        # Device selection is deliberately manual. Do not infer an output
        # from reports, environment, or previous launches: the operator picks
        # the audible route from the dropdown for this app session.
        self._audio_device = ""
        try:
            saved_volume = int(_read_audio_preference("video_volume") or _DEFAULT_VOLUME)
        except ValueError:
            saved_volume = _DEFAULT_VOLUME
        self._volume = max(0, min(100, saved_volume))
        self._last_nonzero_volume = self._volume or _DEFAULT_VOLUME
        self._muted = self._volume == 0

        card = QFrame()
        card.setObjectName("VideoCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setFixedWidth(_VIDEO_CARD_WIDTH)
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

        self._engine = _VlcEngine(
            self._surface,
            audio_device=self._audio_device,
            volume=self._volume,
        )
        self._update_clip_label()
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._on_poll)
        # Consecutive polls where position() returned None. A run only becomes
        # a failure when VLC independently reports the player as stopped.
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
        self._fs_btn = QPushButton()
        self._fs_btn.setCursor(Qt.PointingHandCursor)
        self._fs_btn.setFixedSize(32, 32)
        self._fs_btn.setIconSize(QSize(16, 16))
        self._fs_btn.setIcon(_expand_icon("#ffffff", 16))
        self._fs_btn.setToolTip("Full screen")
        self._fs_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 16px; color: #ffffff;"
            " background: rgba(255,255,255,0.15); }"
            " QPushButton:hover { background: rgba(255,255,255,0.28); }"
        )
        self._fs_btn.clicked.connect(self._toggle_fullscreen)
        h.addWidget(self._fs_btn)
        h.addWidget(close)
        self._header = bar
        return bar

    def _stage(self):
        stage = QFrame()
        stage.setObjectName("VideoStage")
        stage.setAttribute(Qt.WA_StyledBackground, True)
        stage.setFixedHeight(int(_VIDEO_CARD_WIDTH * 9 / 16))  # 16:9
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
        # The surface must be its OWN native window (VLC renders into its
        # handle) and ONLY it: without WA_DontCreateNativeAncestors the first
        # winId() call silently promotes every ancestor (card, overlay, shell)
        # to native X windows too, which on the Pi's bare-X kiosk breaks mouse
        # routing for the whole modal (unclickable buttons) and window
        # stacking (video hidden behind a sibling native window).
        self._surface.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self._surface.setAttribute(Qt.WA_NativeWindow, True)
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
        self._stage_frame = stage
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
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(12)

        transport_row = QWidget(bar)
        h = QHBoxLayout(transport_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)

        self._prev_btn = self._skip_button(GLYPH["jog_rev_fast"])
        self._prev_btn.clicked.connect(lambda: self._skip(-1))
        h.addWidget(self._prev_btn)

        self._small_play = QPushButton()
        self._small_play.setCursor(Qt.PointingHandCursor)
        self._small_play.setFixedSize(_TOUCH_CONTROL_SIZE, _TOUCH_CONTROL_SIZE)
        self._small_play.setIconSize(QSize(19, 19))
        self._small_play.setIcon(play_icon("#ffffff", 19))
        self._small_play.setStyleSheet(
            "QPushButton { border: none; border-radius: 8px;"
            f" background: {resolve('--color-primary')}; }}"
            f" QPushButton:hover {{ background: {resolve('--color-primary-hover')}; }}"
        )
        self._small_play.clicked.connect(self._toggle)
        h.addWidget(self._small_play)

        self._next_btn = self._skip_button(GLYPH["jog_fwd_fast"])
        self._next_btn.clicked.connect(lambda: self._skip(+1))
        h.addWidget(self._next_btn)

        self._clip_label = QLabel()
        self._clip_label.setFont(mono_font(size="--text-sm"))
        self._clip_label.setStyleSheet(
            f"color: {resolve('--gray-600')}; background: transparent;"
        )
        h.addWidget(self._clip_label)

        self._elapsed = QLabel(_fmt(0))
        self._elapsed.setFont(mono_font(size="--text-sm"))
        self._elapsed.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        h.addWidget(self._elapsed)

        self._track = QFrame()
        self._track.setObjectName("VTrack")
        self._track.setAttribute(Qt.WA_StyledBackground, True)
        self._track.setFixedHeight(10)
        self._track.setStyleSheet(
            f"#VTrack {{ background: {resolve('--gray-300')}; border-radius: 5px; }}"
        )
        tlay = QHBoxLayout(self._track)
        tlay.setContentsMargins(0, 0, 0, 0)
        self._vfill = QFrame()
        self._vfill.setObjectName("VFill")
        self._vfill.setAttribute(Qt.WA_StyledBackground, True)
        self._vfill.setFixedWidth(0)
        self._vfill.setStyleSheet(
            "#VFill { border-radius: 5px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            f" stop:0 {resolve('--blue-500')}, stop:1 {resolve('--blue-600')}); }}"
        )
        tlay.addWidget(self._vfill)
        tlay.addStretch(1)
        self._track.installEventFilter(self)
        h.addWidget(self._track, 1)

        self._total = QLabel(_fmt(_FALLBACK_DURATION))
        self._total.setFont(mono_font(size="--text-sm"))
        self._total.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        h.addWidget(self._total)
        outer.addWidget(transport_row)

        audio_row = QWidget(bar)
        audio = QHBoxLayout(audio_row)
        audio.setContentsMargins(0, 0, 0, 0)
        audio.setSpacing(14)

        output_label = QLabel("Sound output")
        output_label.setFont(sans_font(size="--text-sm", weight=600))
        output_label.setStyleSheet(
            f"color: {resolve('--ink-700')}; background: transparent;"
        )
        audio.addWidget(output_label)

        self._output_combo = QComboBox()
        self._output_combo.setMinimumWidth(190)
        self._output_combo.setMaximumWidth(250)
        self._output_combo.setFixedHeight(_TOUCH_CONTROL_SIZE)
        self._output_combo.setFont(sans_font(size="--text-sm"))
        self._output_combo.setStyleSheet(
            "QComboBox { border: 1px solid "
            f"{resolve('--gray-400')}; border-radius: 8px; padding: 8px 12px;"
            " background: #ffffff; }"
            " QComboBox:disabled { color: "
            f"{resolve('--gray-600')}; background: {resolve('--gray-200')}; }}"
            " QComboBox QAbstractItemView::item { min-height: 40px; padding: 6px; }"
        )
        if self._audio_devices:
            selected = 0
            offset = 0
            if not self._audio_device:
                self._output_combo.addItem("Choose output…", "")
                offset = 1
            for device_index, device in enumerate(self._audio_devices):
                index = device_index + offset
                self._output_combo.addItem(_friendly_audio_device(device), device)
                self._output_combo.setItemData(index, device, Qt.ToolTipRole)
                if device == self._audio_device:
                    selected = index
            self._output_combo.setCurrentIndex(selected)
        else:
            self._output_combo.addItem("System default", "")
            self._output_combo.setEnabled(False)
        self._output_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        audio.addWidget(self._output_combo)
        audio.addStretch(1)

        self._mute_btn = QPushButton("Unmute" if self._muted else "Mute")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setChecked(self._muted)
        self._mute_btn.setFixedSize(84, _TOUCH_CONTROL_SIZE)
        self._mute_btn.setFont(sans_font(size="--text-sm", weight=600))
        self._mute_btn.setStyleSheet(
            "QPushButton { border: 1px solid "
            f"{resolve('--gray-400')}; border-radius: 8px; color: {resolve('--ink-700')};"
            " background: #ffffff; padding: 0; }"
            " QPushButton:checked { color: #ffffff; background: "
            f"{resolve('--ink-700')}; }}"
        )
        self._mute_btn.clicked.connect(self._toggle_mute)
        audio.addWidget(self._mute_btn)

        volume_label = QLabel("Volume")
        volume_label.setFont(sans_font(size="--text-sm", weight=600))
        volume_label.setStyleSheet(
            f"color: {resolve('--ink-700')}; background: transparent;"
        )
        audio.addWidget(volume_label)

        self._volume_slider = QSlider(Qt.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(self._volume)
        self._volume_slider.setFixedSize(180, _TOUCH_CONTROL_SIZE)
        self._volume_slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 10px; border-radius: 5px; }"
            " QSlider::handle:horizontal { width: 32px; height: 32px;"
            " margin: -11px 0; border-radius: 16px; border-width: 3px; }"
        )
        self._volume_slider.setAccessibleName("Video volume")
        self._volume_slider.valueChanged.connect(self._on_volume_changed)
        audio.addWidget(self._volume_slider)

        self._volume_value = QLabel(f"{self._volume}%")
        self._volume_value.setFixedWidth(46)
        self._volume_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._volume_value.setFont(mono_font(size="--text-sm"))
        self._volume_value.setStyleSheet(
            f"color: {resolve('--ink-700')}; background: transparent;"
        )
        audio.addWidget(self._volume_value)
        outer.addWidget(audio_row)
        self._transport_bar = bar
        return bar

    @staticmethod
    def _skip_button(glyph):
        """A quiet prev/next transport button (« / » skip glyphs)."""
        btn = QPushButton(glyph)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedSize(_TOUCH_CONTROL_SIZE, _TOUCH_CONTROL_SIZE)
        btn.setFont(sans_font(size="--text-lg", weight=600))
        btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 8px;"
            f" color: {resolve('--ink-700')}; background: {resolve('--gray-300')};"
            " padding: 0; }"
            f" QPushButton:hover {{ background: {resolve('--gray-400')}; }}"
        )
        return btn

    def _on_volume_changed(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))
        if self._volume > 0:
            self._last_nonzero_volume = self._volume
            if self._muted:
                self._muted = False
                self._mute_btn.setChecked(False)
                self._mute_btn.setText("Mute")
                if hasattr(self, "_engine"):
                    self._engine.set_muted(False)
        elif not self._muted:
            self._muted = True
            self._mute_btn.setChecked(True)
            self._mute_btn.setText("Unmute")
            if hasattr(self, "_engine"):
                self._engine.set_muted(True)

        self._volume_value.setText(f"{self._volume}%")
        if hasattr(self, "_engine"):
            self._engine.set_volume(self._volume)
        _write_audio_preference("video_volume", self._volume)

    def _toggle_mute(self, checked: bool) -> None:
        self._muted = bool(checked)
        self._mute_btn.setText("Unmute" if self._muted else "Mute")
        if not self._muted and self._volume == 0:
            self._volume_slider.setValue(self._last_nonzero_volume)
        if hasattr(self, "_engine"):
            self._engine.set_muted(self._muted)

    def _on_audio_device_changed(self, index: int) -> None:
        device = self._output_combo.itemData(index)
        if not isinstance(device, str) or device == self._audio_device:
            return
        was_playing = self._playing
        self._audio_device = device
        if not hasattr(self, "_engine"):
            return

        self._poll.stop()
        self._engine.set_audio_device(device)
        if was_playing:
            if self._engine.play():
                self._none_polls = 0
                self._poll.start()
            else:
                self._on_playback_failed()

    # ----- playback -----
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Keep the custom progress fill correct when the modal is resized."""
        if watched is self._track and event.type() == QEvent.Resize:
            self._update_progress_fill()
        return super().eventFilter(watched, event)

    def _update_progress_fill(self) -> None:
        width = int(self._track.width() * self._progress_fraction)
        self._vfill.setFixedWidth(max(0, width))

    def _set_progress(self, fraction: float) -> None:
        self._progress_fraction = max(0.0, min(1.0, float(fraction)))
        self._update_progress_fill()

    def _set_playing(self, playing: bool, emit: bool = True) -> None:
        """Update the transport button and the logical playback state together."""
        changed = self._playing != playing
        self._playing = playing
        self._small_play.setIcon(
            pause_icon("#ffffff", 19) if playing else play_icon("#ffffff", 19)
        )
        label = "Pause video" if playing else "Play video"
        self._small_play.setToolTip(label)
        self._small_play.setAccessibleName(label)
        self._small_play.update()
        if emit and changed:
            self.play_toggled.emit(playing)

    def _toggle(self):
        target_playing = not self._playing
        if target_playing:
            # Reveal the native surface BEFORE starting VLC so its X window
            # is mapped when the video output binds to it — binding to a
            # still-hidden window is a black-stage race on the Pi. Degrades
            # back to the poster if playback doesn't start.
            if self._engine.available:
                self._surface.setVisible(True)
                self._watermark.setVisible(False)
                self._big_play.setVisible(False)
            if not self._engine.available:
                # Preserve the optional-VLC fallback contract: the button can
                # still be demonstrated even though no playback poll starts.
                self._set_playing(True)
            elif self._engine.play():
                self._none_polls = 0
                self._set_playing(True)
                self._poll.start()
            else:
                self._surface.setVisible(False)
                self._watermark.setVisible(True)
                self._big_play.setVisible(True)
                self._set_playing(False)
        else:
            self._engine.pause()
            self._big_play.setVisible(True)
            self._poll.stop()
            self._set_playing(False)

    def _skip(self, delta):
        """Jump to the previous/next clip (wraps at the ends).

        Keeps the current play/pause state: skipping while playing starts the
        new clip immediately; skipping on the poster just re-arms which clip
        the play button will start.
        """
        count = self._engine.count()
        if count == 0:
            return
        if not self._engine.set_track((self._engine.index() + delta) % count):
            return
        self._update_clip_label()
        self._elapsed.setText(_fmt(0))
        self._set_progress(0)
        if self._playing:
            self._none_polls = 0
            self._engine.play()

    def _update_clip_label(self):
        count = self._engine.count()
        self._clip_label.setText(f"{self._engine.index() + 1} / {count}" if count else "")
        self._clip_label.setVisible(count > 1)
        self._prev_btn.setVisible(count > 1)
        self._next_btn.setVisible(count > 1)

    def _advance(self):
        """Current clip finished — continue with the next, or reset after the
        last so the playlist starts over from clip 1 on the next play."""
        nxt = self._engine.index() + 1
        if nxt < self._engine.count() and self._engine.set_track(nxt) and self._engine.play():
            self._update_clip_label()
            self._none_polls = 0
            self._elapsed.setText(_fmt(0))
            self._set_progress(0)
        else:
            self._reset_playback()
            self.play_toggled.emit(False)

    def _on_poll(self):
        state = self._engine.playback_state()
        if state == "ended":
            self._advance()
            return
        if state == "error":
            self._on_playback_failed()
            return
        if state == "playing":
            self._engine.ensure_audio()
            self._set_playing(True, emit=False)
        elif state == "paused":
            self._set_playing(False)
            self._poll.stop()
            return

        pos = self._engine.position()
        if pos is None:
            # Opening/buffering can legitimately outlast several polls on the
            # Pi. Only treat missing position as failure when VLC also reports
            # that it stopped; otherwise keep polling its independent clocks.
            self._none_polls += 1
            if state == "stopped" and self._none_polls >= self._MAX_NONE_POLLS:
                self._on_playback_failed()
            return
        self._none_polls = 0
        elapsed, total = pos
        self._elapsed.setText(_fmt(elapsed))
        if total > 0:
            self._total.setText(_fmt(total))
            frac = max(0.0, min(1.0, elapsed / total))
            self._set_progress(frac)
            if elapsed >= total - 0.3:  # clip ended → next clip (or reset)
                self._advance()

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
        """Stop playback, rewind to the first clip, and restore the
        paused/static frame — the next play starts the playlist over."""
        self._none_polls = 0
        self._poll.stop()
        self._engine.stop()
        self._engine.set_track(0)
        self._update_clip_label()
        self._set_playing(False, emit=False)
        self._surface.setVisible(False)
        self._watermark.setVisible(True)
        self._big_play.setVisible(True)
        self._elapsed.setText(_fmt(0))
        self._set_progress(0)

    def close_overlay(self):
        self._reset_playback()
        if self._fullscreen:
            self._toggle_fullscreen()
        super().close_overlay()

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        r = resolve('--radius-lg')
        if self._fullscreen:
            self._apply_fullscreen_size()
            self._card.setStyleSheet(
                "#VideoCard { background: #ffffff; border-radius: 0; }"
            )
            self._header.setStyleSheet(
                f"#VideoHeader {{ background: {resolve('--surface-dark')};"
                " border-radius: 0; }"
            )
            self._transport_bar.setStyleSheet(
                "#VideoTransport { background: #ffffff; border-radius: 0; }"
            )
            self._fs_btn.setIcon(_compress_icon("#ffffff", 16))
            self._fs_btn.setToolTip("Exit full screen")
        else:
            self._card.setFixedWidth(_VIDEO_CARD_WIDTH)
            self._stage_frame.setFixedHeight(int(_VIDEO_CARD_WIDTH * 9 / 16))
            self._card.setStyleSheet(
                f"#VideoCard {{ background: #ffffff; border-radius: {r}; }}"
            )
            self._header.setStyleSheet(
                f"#VideoHeader {{ background: {resolve('--surface-dark')};"
                f" border-top-left-radius: {r};"
                f" border-top-right-radius: {r}; }}"
            )
            self._transport_bar.setStyleSheet(
                f"#VideoTransport {{ background: #ffffff;"
                f" border-bottom-left-radius: {r};"
                f" border-bottom-right-radius: {r}; }}"
            )
            self._fs_btn.setIcon(_expand_icon("#ffffff", 16))
            self._fs_btn.setToolTip("Full screen")

    def _apply_fullscreen_size(self):
        parent = self.parent()
        if parent is None:
            return
        pw, ph = parent.width(), parent.height()
        header_h = self._header.sizeHint().height()
        transport_h = self._transport_bar.sizeHint().height()
        stage_h = max(100, ph - header_h - transport_h)
        self._card.setFixedWidth(pw)
        self._stage_frame.setFixedHeight(stage_h)

    def update_geometry(self):
        super().update_geometry()
        if self._fullscreen:
            self._apply_fullscreen_size()

    def cleanup(self):
        """Release VLC resources (call on app shutdown)."""
        self._poll.stop()
        self._engine.release()
