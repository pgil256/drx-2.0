# tests/integration/test_ui_widgets.py
"""Integration tests for misc UI widgets (offscreen, via qtbot).

Covers:
  * ``LoadingSpinner`` -- a transparent overlay wrapping a looping ``QMovie``.
    Its public controls are ``show()`` (starts the animation) and ``hide()``
    (stops it). These tests assert that construction and the show/hide
    lifecycle work without crashing and drive the underlying movie state.
  * ``VideoPlayer`` -- a VLC-backed dialog. ``vlc`` and the multimedia modules
    are mocked by ``conftest.py``, so these tests stay light: construction plus
    no-crash exercising of the public control slots and cleanup.

All tests run under ``QT_QPA_PLATFORM=offscreen`` (set in conftest).
"""
import pytest
from PyQt5.QtGui import QMovie
from PyQt5.QtCore import QSize

from ui.widgets.loading_spinner import LoadingSpinner
from ui.dialogs.video_player import VideoPlayer


@pytest.mark.integration
class TestLoadingSpinnerConstruction:
    """Construction and configuration of LoadingSpinner."""

    def test_construct_default(self, qtbot):
        """A spinner can be constructed with no arguments."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        assert isinstance(spinner, LoadingSpinner)

    def test_hidden_after_construction(self, qtbot):
        """The overlay hides itself at the end of __init__."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        assert spinner.isVisible() is False

    def test_movie_created_and_not_running(self, qtbot):
        """The backing QMovie exists and is idle before show()."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        assert spinner._movie is not None
        assert spinner._movie.state() == QMovie.NotRunning

    def test_construct_with_int_size(self, qtbot):
        """An integer size is accepted (converted to a square QSize)."""
        spinner = LoadingSpinner(size=120)
        qtbot.addWidget(spinner)
        assert isinstance(spinner, LoadingSpinner)

    def test_construct_with_qsize(self, qtbot):
        """An explicit QSize is accepted for non-square spinners."""
        spinner = LoadingSpinner(size=QSize(150, 90), speed_pct=200)
        qtbot.addWidget(spinner)
        assert isinstance(spinner, LoadingSpinner)


@pytest.mark.integration
class TestLoadingSpinnerLifecycle:
    """show()/hide() control the animation without crashing."""

    def test_show_starts_animation(self, qtbot):
        """show() makes the widget visible and starts the movie."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        spinner.show()
        assert spinner.isVisible() is True
        assert spinner._movie.state() == QMovie.Running

    def test_hide_stops_animation(self, qtbot):
        """hide() hides the widget and stops the movie."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        spinner.show()
        spinner.hide()
        assert spinner.isVisible() is False
        assert spinner._movie.state() == QMovie.NotRunning

    def test_show_hide_cycle_repeatable(self, qtbot):
        """The show/hide cycle can be repeated without error."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        for _ in range(3):
            spinner.show()
            assert spinner._movie.state() == QMovie.Running
            spinner.hide()
            assert spinner._movie.state() == QMovie.NotRunning

    def test_double_show_idempotent(self, qtbot):
        """Calling show() twice keeps the movie running (no crash)."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        spinner.show()
        spinner.show()
        assert spinner._movie.state() == QMovie.Running

    def test_hide_without_show_is_safe(self, qtbot):
        """hide() before any show() does not raise and leaves it idle."""
        spinner = LoadingSpinner()
        qtbot.addWidget(spinner)
        spinner.hide()
        assert spinner._movie.state() == QMovie.NotRunning


@pytest.mark.integration
class TestVideoPlayerConstruction:
    """VideoPlayer construction with mocked vlc (light coverage)."""

    def test_construct_no_crash(self, qtbot):
        """The dialog constructs without raising when vlc is mocked."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        assert isinstance(player, VideoPlayer)
        player.safe_cleanup()

    def test_media_player_initialized(self, qtbot):
        """_init_vlc populates a (mocked) media player during construction."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        assert player.resources.get("media_player") is not None
        player.safe_cleanup()

    def test_initial_video_state(self, qtbot):
        """The dialog starts at video index 0 and not playing."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        assert player.video_state["current_video_index"] == 0
        assert player.video_state["is_playing"] is False
        player.safe_cleanup()


@pytest.mark.integration
class TestVideoPlayerControls:
    """Public control slots are callable without crashing (vlc mocked)."""

    def test_play_video_no_crash(self, qtbot):
        """play_video() does not raise with a mocked media player."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.play_video()
        player.safe_cleanup()

    def test_pause_video_no_crash(self, qtbot):
        """pause_video() does not raise with a mocked media player."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.pause_video()
        player.safe_cleanup()

    def test_next_previous_no_crash(self, qtbot):
        """show_next_video()/show_previous_video() do not raise."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        # These slots accept a (mouse) event argument; None is fine here.
        player.show_next_video(None)
        player.show_previous_video(None)
        player.safe_cleanup()

    def test_safe_cleanup_idempotent(self, qtbot):
        """safe_cleanup() can be called repeatedly without crashing."""
        player = VideoPlayer()
        qtbot.addWidget(player)
        player.safe_cleanup()
        player.safe_cleanup()
        assert player.resources.get("media_player") is None
