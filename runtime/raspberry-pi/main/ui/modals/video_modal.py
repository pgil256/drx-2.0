"""VideoModal — a video library and playlist player over a dim scrim.

Mirrors `VideoModal` in `bundle.jsx`: an 800px card with a dark title bar, a 16:9
stage (radial-gradient backdrop, faint knee watermark, big play button) and a
transport bar (play/pause, elapsed/total time, progress track).

Opening the modal shows every clip in a selectable list. Choosing one starts
the playlist at that clip; All videos stops playback and returns to the list.
The stage embeds a VLC media player (``_VlcEngine`` from ``vlc_engine``) that
plays every ``.mp4`` in the videos directory in sorted filename order —
advancing to the next clip automatically when one ends — with prev/next
transport buttons to skip between clips. VLC and the bundled clips are both
optional — if either is missing the modal shows a static frame with an
unavailable message, so it can never block the app or claim to be playing on a
machine without VLC.

Signals:
    play_toggled(bool)  — play button pressed (True = now playing)
    closed              — dismissed
"""

from typing import Optional

from PyQt5.QtCore import QEvent, QObject, Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme import GLYPH, compress_icon, expand_icon, pause_icon, play_icon
from ui.widgets.ds._common import image_path, mono_font, resolve, sans_font

from ._overlay import Overlay
from .vlc_engine import (
    _DEFAULT_VOLUME,
    _VlcEngine,
    _discover_alsa_devices,
    _friendly_audio_device,
    _read_audio_preference,
    _write_audio_preference,
)

_VIDEO_CARD_WIDTH = 800
_TOUCH_CONTROL_SIZE = 48


def _fmt(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


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
        # No drop_shadow() here, on purpose. A QGraphicsEffect makes Qt
        # composite the whole card through a cached source pixmap; with the
        # native VLC surface (WA_NativeWindow) inside that card, the Pi's
        # X11 backend stopped repainting the transport bar while a clip
        # played: the volume slider and its "NN%" label responded to touch
        # (VLC's volume changed) but the on-screen widgets went stale.
        # The dim scrim already separates the card from the page.

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._title_bar())
        self._pages = QStackedWidget()
        self._player_page = QWidget()
        player_layout = QVBoxLayout(self._player_page)
        player_layout.setContentsMargins(0, 0, 0, 0)
        player_layout.setSpacing(0)
        player_layout.addWidget(self._stage())
        player_layout.addWidget(self._transport())
        self._pages.addWidget(self._player_page)
        lay.addWidget(self._pages)

        self.set_card(card)
        self._apply_frame_style(rounded=True)

        self._engine = _VlcEngine(
            self._surface,
            audio_device=self._audio_device,
            volume=self._volume,
        )
        self._update_clip_label()
        self._set_playing(False, emit=False)
        if not self._engine.available:
            self._show_playback_error()
        self._poll = QTimer(self)
        self._poll.setInterval(250)
        self._poll.timeout.connect(self._on_poll)
        # Consecutive polls where position() returned None. A run only becomes
        # a failure when VLC independently reports the player as stopped.
        self._none_polls = 0
        self._MAX_NONE_POLLS = 3
        self._library_page = self._library()
        self._pages.addWidget(self._library_page)
        self._show_library()

    def _library(self) -> QWidget:
        """Build a scrollable, touch-sized list of all playable clips."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(14)
        intro = QLabel(
            f"{self._engine.count()} videos · Choose where to start\n"
            "The following videos will play automatically in the order shown."
        )
        intro.setWordWrap(True)
        intro.setFont(sans_font(size="--text-base"))
        intro.setStyleSheet(f"color: {resolve('--ink-700')}; background: transparent;")
        layout.addWidget(intro)
        self._video_list = QListWidget()
        self._video_list.setAccessibleName("Video playlist")
        self._video_list.setWordWrap(True)
        self._video_list.setFont(sans_font(size="--text-base"))
        self._video_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._video_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._video_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._video_list.verticalScrollBar().setAccessibleName("Scroll video playlist")
        # Override the theme's handle border too, so the touch-sized thumb stays visible.
        self._video_list.setStyleSheet(
            "QListWidget { background: #ffffff; color: #172b3b; border: none; }"
            "QListWidget::item { padding: 10px 14px; border: 1px solid #d9e2e8;"
            " border-radius: 8px; margin-bottom: 6px; }"
            "QListWidget::item:hover { background: #f0f7fb; }"
            "QListWidget::item:selected { background: #e4f3fb; color: #123a52;"
            " border-color: #1678a5; }"
            f"QScrollBar:vertical {{ width: {_TOUCH_CONTROL_SIZE}px;"
            " background: #f0f7fb; border: none; border-radius: 12px; margin: 0; }"
            "QScrollBar::handle:vertical { background: #1678a5;"
            " border: 4px solid #f0f7fb; border-radius: 12px; min-height: 64px; }"
            "QScrollBar::handle:vertical:hover, QScrollBar::handle:vertical:pressed"
            " { background: #123a52; }"
            "QScrollBar::handle:vertical:disabled { background: #d9e2e8; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
            " { height: 0; background: none; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical"
            " { background: none; }"
        )
        for index, title in enumerate(self._engine.titles()):
            item = QListWidgetItem(f"{index + 1:02d}   {title}")
            item.setSizeHint(QSize(0, 76))
            item.setToolTip(title)
            self._video_list.addItem(item)
        self._video_list.itemClicked.connect(self._select_video)
        self._video_list.itemActivated.connect(self._select_video)
        layout.addWidget(self._video_list, 1)
        self._library_message = QLabel()
        self._library_message.setWordWrap(True)
        self._library_message.setFont(sans_font(size="--text-base"))
        self._library_message.setStyleSheet("color: #714600; background: #fff4d9; padding: 12px;")
        self._library_message.setVisible(not self._engine.available)
        self._library_message.setText(self._playback_message.text())
        layout.addWidget(self._library_message)
        return page

    def open_over(self, parent: Optional[QWidget] = None) -> None:
        """Always start at the library when the operator opens Video."""
        self._show_library()
        super().open_over(parent)
        self._video_list.setFocus()

    def _show_library(self) -> None:
        """Stop playback and return to the list without dismissing the modal."""
        was_playing = self._playing
        self._reset_playback()
        if was_playing:
            self.play_toggled.emit(False)
        if self._fullscreen:
            self._toggle_fullscreen()
        self._pages.setCurrentWidget(self._library_page)
        self._header_title.setText("Videos")
        self._library_btn.hide()
        self._fs_btn.hide()
        self._video_list.clearSelection()
        self._video_list.scrollToTop()
        self._library_message.setVisible(not self._engine.available)
        self._library_message.setText(self._playback_message.text())

    def _select_video(self, item: QListWidgetItem) -> None:
        """Start the selected clip, then continue through the remaining playlist."""
        if self._pages.currentWidget() is not self._library_page:
            return
        index = self._video_list.row(item)
        if not self._engine.set_track(index):
            self._show_playback_error()
            self._library_message.setText(self._playback_message.text())
            self._library_message.show()
            return
        self._update_clip_label()
        self._toggle()

    def _title_bar(self):
        bar = QFrame()
        bar.setObjectName("VideoHeader")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(18, 12, 18, 12)
        title = QLabel("Videos")
        title.setFont(sans_font(size="--text-base", weight=600))
        title.setStyleSheet("color: #ffffff; background: transparent;")
        self._header_title = title
        close = QPushButton(GLYPH["close"])
        close.setCursor(Qt.PointingHandCursor)
        close.setFixedSize(48, 48)
        close.setAccessibleName("Close video")
        close.setFont(sans_font(size="--text-base", weight=600))
        close.setStyleSheet(
            "QPushButton { border: none; border-radius: 16px; padding: 0; color: #ffffff;"
            " background: rgba(255,255,255,0.15); }"
            " QPushButton:hover { background: rgba(255,255,255,0.28); }"
        )
        close.clicked.connect(self.close_overlay)
        h.addWidget(title)
        h.addStretch(1)
        self._library_btn = QPushButton("All videos")
        self._library_btn.setAccessibleName("Back to video list")
        self._library_btn.setMinimumSize(116, 48)
        self._library_btn.setCursor(Qt.PointingHandCursor)
        self._library_btn.setFont(sans_font(size="--text-base", weight=600))
        self._library_btn.setStyleSheet(
            "QPushButton { color: #ffffff; background: #38424b;"
            " border: none; border-radius: 10px; padding: 0 14px; }"
            "QPushButton:hover { background: #46535e; }"
        )
        self._library_btn.clicked.connect(self._show_library)
        h.addWidget(self._library_btn)
        self._fs_btn = QPushButton()
        self._fs_btn.setCursor(Qt.PointingHandCursor)
        self._fs_btn.setFixedSize(48, 48)
        self._fs_btn.setAccessibleName("Toggle video fullscreen")
        self._fs_btn.setIconSize(QSize(16, 16))
        self._fs_btn.setIcon(expand_icon("#ffffff", 16))
        self._fs_btn.setToolTip("Full screen")
        self._fs_btn.setStyleSheet(
            "QPushButton { border: none; border-radius: 16px; padding: 0; color: #ffffff;"
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
        self._playback_message = QLabel()
        self._playback_message.setWordWrap(True)
        self._playback_message.setAlignment(Qt.AlignCenter)
        self._playback_message.setMaximumWidth(560)
        self._playback_message.setStyleSheet(
            "color: #ffffff; background: #1b2838; padding: 16px; border-radius: 8px;"
        )
        self._playback_message.hide()
        grid.addWidget(self._playback_message, 0, 0, Qt.AlignHCenter | Qt.AlignBottom)
        self._watermark.raise_()
        self._big_play.raise_()
        self._stage_frame = stage
        return stage

    def _transport(self):
        bar = QFrame()
        bar.setObjectName("VideoTransport")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(20, 14, 20, 16)
        self._current_title = QLabel()
        self._current_title.setWordWrap(True)
        self._current_title.setFont(sans_font(size="--text-base", weight=600))
        self._current_title.setStyleSheet(
            f"color: {resolve('--ink-900')}; background: transparent;"
        )
        outer.addWidget(self._current_title)
        outer.setSpacing(12)
        outer.addWidget(self._transport_row(bar))
        outer.addWidget(self._audio_row(bar))
        self._transport_bar = bar
        return bar

    def _transport_row(self, parent):
        """Prev / play / next, the clip counter and the elapsed/total progress track."""
        transport_row = QWidget(parent)
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

        self._total = QLabel("--:--")
        self._total.setFont(mono_font(size="--text-sm"))
        self._total.setStyleSheet(f"color: {resolve('--gray-600')}; background: transparent;")
        h.addWidget(self._total)
        return transport_row

    def _audio_row(self, parent):
        """Sound output picker, mute toggle and volume slider with its readout."""
        audio_row = QWidget(parent)
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
        return audio_row

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
        # Force a synchronous repaint of the audio row: with VLC rendering
        # into its own X window next to these widgets, a queued update()
        # could be starved on the Pi and leave the label showing the old
        # value even though the volume had changed.
        self._volume_value.repaint()
        self._volume_slider.repaint()
        self._mute_btn.repaint()
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
            self._pages.setCurrentWidget(self._player_page)
            self._header_title.setText("Video playlist")
            self._library_btn.show()
            self._fs_btn.show()
            self._playback_message.hide()
            # Reveal the native surface BEFORE starting VLC so its X window
            # is mapped when the video output binds to it — binding to a
            # still-hidden window is a black-stage race on the Pi. Degrades
            # back to the poster if playback doesn't start.
            if self._engine.available:
                self._surface.setVisible(True)
                self._watermark.setVisible(False)
                self._big_play.setVisible(False)
            if not self._engine.available:
                self._show_playback_error()
            elif self._engine.play():
                self._none_polls = 0
                self._set_playing(True)
                self._poll.start()
            else:
                self._surface.setVisible(False)
                self._watermark.setVisible(True)
                self._big_play.setVisible(True)
                self._set_playing(False)
                self._show_playback_error()
        else:
            self._engine.pause()
            self._big_play.setVisible(True)
            self._poll.stop()
            self._set_playing(False)

    def _show_playback_error(self) -> None:
        """Explain unavailable playback without changing the transport to playing."""
        if not self._engine.count():
            message = "No demo videos are available on this device."
        elif not self._engine.available:
            message = "Video playback is unavailable. Please contact support."
        else:
            message = "The video could not play. Please try again."
        self._playback_message.setText(message)
        self._playback_message.show()
        self._playback_message.raise_()

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
        self._total.setText("--:--")
        self._set_progress(0)
        if self._playing:
            self._none_polls = 0
            if not self._engine.play():
                self._on_playback_failed()

    def _update_clip_label(self):
        count = self._engine.count()
        self._clip_label.setText(f"{self._engine.index() + 1} / {count}" if count else "")
        titles = self._engine.titles()
        self._current_title.setText(titles[self._engine.index()] if titles else "")
        self._clip_label.setVisible(count > 1)
        self._prev_btn.setVisible(count > 1)
        self._next_btn.setVisible(count > 1)

    def _advance(self):
        """Continue with the next clip, or return to the list after the last."""
        nxt = self._engine.index() + 1
        if nxt < self._engine.count() and self._engine.set_track(nxt) and self._engine.play():
            self._update_clip_label()
            self._none_polls = 0
            self._elapsed.setText(_fmt(0))
            self._total.setText("--:--")
            self._set_progress(0)
        else:
            self._show_library()

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
        self._show_playback_error()
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
        self._total.setText("--:--")
        self._set_progress(0)

    def close_overlay(self):
        self._reset_playback()
        if self._fullscreen:
            self._toggle_fullscreen()
        super().close_overlay()

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._apply_fullscreen_size()
            self._apply_frame_style(rounded=False)
            self._fs_btn.setIcon(compress_icon("#ffffff", 16))
            self._fs_btn.setToolTip("Exit full screen")
        else:
            self._card.setFixedWidth(_VIDEO_CARD_WIDTH)
            self._stage_frame.setFixedHeight(int(_VIDEO_CARD_WIDTH * 9 / 16))
            self._apply_frame_style(rounded=True)
            self._fs_btn.setIcon(expand_icon("#ffffff", 16))
            self._fs_btn.setToolTip("Full screen")

    def _apply_frame_style(self, rounded):
        """Style the card, title bar and transport bar as one frame: rounded
        outer corners for the centered card, square ones in full screen."""
        if rounded:
            r = resolve('--radius-lg')
            card = f"border-radius: {r};"
            header = f"border-top-left-radius: {r}; border-top-right-radius: {r};"
            transport = f"border-bottom-left-radius: {r}; border-bottom-right-radius: {r};"
        else:
            card = header = transport = "border-radius: 0;"
        self._card.setStyleSheet(f"#VideoCard {{ background: #ffffff; {card} }}")
        self._header.setStyleSheet(
            f"#VideoHeader {{ background: {resolve('--surface-dark')}; {header} }}"
        )
        self._transport_bar.setStyleSheet(
            f"#VideoTransport {{ background: #ffffff; {transport} }}"
        )

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
